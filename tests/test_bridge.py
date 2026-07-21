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
