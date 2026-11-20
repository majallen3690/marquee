"""Bridge tests (M5): paced session, live perturbation path, REST surface."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from marquee.server.app import create_app
from marquee.server.session import LiveSession

SCENARIO = Path(__file__).parents[1] / "scenarios" / "m5-flash-crash.yaml"


def test_session_steps_and_frames(tmp_path) -> None:
    session = LiveSession(SCENARIO, tmp_path / "live")
    session.set_speed(20.0)  # 20 sim-seconds per wall-second
    frame = session.step(0.25)  # 5 sim-seconds advanced
    assert frame["type"] == "frame"
    assert frame["status"] == "live"
    assert frame["t"] > 0
    assert frame["bids"] and frame["asks"]  # market formed
    assert frame["trades"]
    assert {m["id"] for m in frame["makers"]} == {1, 2}
    assert all(type(px) is int and type(q) is int for px, q in frame["bids"])


def test_session_pause_freezes_sim_time(tmp_path) -> None:
    session = LiveSession(SCENARIO, tmp_path / "live")
    session.set_speed(10.0)
    t1 = session.step(0.1)["t"]
    session.set_paused(True)
    t2 = session.step(0.5)["t"]
    assert t2 == t1
    session.set_paused(False)
    assert session.step(0.1)["t"] > t1


def test_live_perturbation_lands_and_is_recorded(tmp_path) -> None:
    session = LiveSession(SCENARIO, tmp_path / "live")
    session.set_speed(50.0)
    session.step(0.1)  # 5 sim-seconds in
    effective = session.perturb(1, "quote_size", 7)
    assert effective > session.kernel.now
    frame = session.step(0.1)
    assert any(p["param"] == "quote_size" for p in frame["perturbations"])
    maker_1 = next(m for m in frame["makers"] if m["id"] == 1)
    assert maker_1["size"] == 7  # actually applied to the live agent
    # And it reached the log with a heap key (replayable, ADR-010).
    session.set_paused(True)
    events_path = tmp_path / "live" / "events.jsonl"
    session._recorder._inner._events.flush()
    logged = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if '"k":"prt"' in line
    ]
    assert any(ev["prm"] == "quote_size" and ev["v"] == 7 for ev in logged)


def test_session_completes_and_writes_manifest(tmp_path) -> None:
    session = LiveSession(SCENARIO, tmp_path / "live")
    session.set_speed(50.0)
    for _ in range(30):  # 30 * 0.1 wall-sec * 50x = 150 sim-sec >= 60s horizon
        frame = session.step(0.1)
        if frame["status"] == "done":
            break
    assert frame["status"] == "done"
    assert (tmp_path / "live" / "manifest.json").exists()
    with pytest.raises(RuntimeError, match="run complete"):
        session.perturb(1, "quote_size", 5)


def test_rest_surface(tmp_path) -> None:
    app = create_app(SCENARIO, tmp_path / "live")
    with TestClient(app) as client:
        meta = client.get("/api/meta").json()
        assert meta["scenario"] == "m5-flash-crash"
        assert len(meta["agents"]) == 11

        response = client.post("/api/control", json={"action": "pause"})
        assert response.json()["status"] == "paused"
        response = client.post("/api/control", json={"action": "speed", "value": 4.0})
        assert app.state.session.speed == 4.0

        response = client.post(
            "/api/perturb", json={"agent_id": 1, "param": "hard_limit", "value": 10}
        )
        assert response.json()["effective_ns"] > 0


def test_frame_carries_agent_ledger_and_run_stats(tmp_path) -> None:
    """Frame v2 (ADR-019): per-agent ledger + run totals. Trading is zero-sum, so
    inventory and cash must each net to exactly zero across all agents."""
    session = LiveSession(SCENARIO, tmp_path / "live")
    session.set_speed(50.0)
    session.step(0.4)  # 20 sim-seconds
    frame = session.step(0.1)  # 25 sim-seconds, before the 30 s lever
    assert len(frame["agents"]) == 11
    assert {a["cls"] for a in frame["agents"]} == {"market_maker", "momentum", "noise"}
    assert sum(a["inv"] for a in frame["agents"]) == 0
    assert sum(a["cash"] for a in frame["agents"]) == 0
    assert all(a["sold_after"] == 0 for a in frame["agents"])  # no lever yet
    makers = {m["id"]: m["inv"] for m in frame["makers"]}
    assert all(a["inv"] == makers[a["id"]] for a in frame["agents"] if a["id"] in makers)
    stats = frame["stats"]
    assert stats["trades"] > 0 and stats["vwap"] is not None
    assert all("tka" in tr for tr in frame["trades"])


def test_meta_exposes_the_scheduled_lever(tmp_path) -> None:
    meta = LiveSession(SCENARIO, tmp_path / "live").meta()
    assert {p["t"] for p in meta["scheduled"]} == {30_000_000_000}
    assert len(meta["scheduled"]) == 8


def test_ui_mid_series_is_the_gate_series(tmp_path) -> None:
    """The live session samples the mid on the same 100 ms grid the committed crash
    gate uses, so the headline the UI computes (move, amplification) is the number
    the gate asserts, at any playback speed."""
    from marquee.analysis.stylized_facts import sample_mid_series

    session = LiveSession(SCENARIO, tmp_path / "live")
    session.set_speed(50.0)
    for _ in range(40):
        frame = session.step(0.1)
        if frame["status"] == "done":
            break
    assert frame["status"] == "done"
    assert frame["mids"] and all(t % 100_000_000 == 0 for t, _ in frame["mids"])
    gate = sample_mid_series(
        tmp_path / "live", session.config.self_trade_policy, session.config.horizon_ns, 100_000_000
    )
    assert [m for _, m in session.mid_series] == gate


def test_history_backfills_and_matches_the_live_ledger(tmp_path) -> None:
    session = LiveSession(SCENARIO, tmp_path / "live")
    session.set_speed(50.0)
    for _ in range(14):  # ~35 sim-seconds: past the 30 s lever
        frame = session.step(0.05)
    history = session.history()
    assert len(history["mids"]) == len(session.mid_series) > 300
    times = [f["t"] for f in history["frames"]]
    assert times == sorted(times) and len(times) >= 60  # a slim frame every 500 ms
    assert all(f["mids"] == [] for f in history["frames"])
    # Volume buckets add up to the run total, so a late page's volume pane is complete.
    bucketed = sum(up + dn for _, up, dn in history["vol"])
    assert bucketed == sum(a["vol"] for a in frame["agents"]) // 2  # each trade has two sides
    # The server found the biggest sweep after the lever, so the marker survives a reload.
    assert frame["stats"]["burst"] is not None and frame["stats"]["burst"]["qty"] > 0
    assert history["last_tid"] >= max(tr["tid"] for tr in frame["trades"])


def test_history_endpoint(tmp_path) -> None:
    app = create_app(SCENARIO, tmp_path / "live")
    with TestClient(app) as client:
        body = client.get("/api/history").json()
        assert set(body) == {"mids", "frames", "vol", "last_tid"}
