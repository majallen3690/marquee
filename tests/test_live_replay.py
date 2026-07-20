"""Replay mode (c), live-insertion variant (ADR-010): a perturbation inserted
MID-RUN — the UI/bridge path — must re-simulate byte-identically from the
schedule extracted out of the log.

This is the test that catches the global-seq trap: if perturbations consumed
the kernel's global insertion counter, live insertion would shift the seq of
every subsequent event relative to pre-scheduled re-simulation and the logs
would diverge from the insertion point onward.
"""

from pathlib import Path

from marquee.engine import SelfTradePolicy
from marquee.sim.replay import extract_perturbations
from marquee.sim.scenario import AgentSpec, ScenarioConfig, build_session

HORIZON = 12_000_000_000


def make_config(perturbations=()) -> ScenarioConfig:
    return ScenarioConfig(
        name="live-replay-test",
        master_seed=90210,
        horizon_ns=HORIZON,
        self_trade_policy=SelfTradePolicy.ALLOW,
        agent_to_exchange_ns=1_000_000,
        exchange_to_agent_ns=1_000_000,
        latency_jitter_ns=200_000,
        agents=(
            AgentSpec("market_maker", 1, 10_000_000, {"anchor_price": 10_000, "quote_size": 40}),
            AgentSpec("momentum", 11, 50_000_000, {"threshold_ticks": 3, "order_size": 10}),
            AgentSpec("noise", 21, 20_000_000, {"anchor_price": 10_000}),
            AgentSpec("noise", 22, 30_000_000, {"anchor_price": 10_000}),
        ),
        perturbations=tuple(perturbations),
    )


def output_bytes(out_dir: Path) -> tuple[bytes, bytes]:
    return (
        (out_dir / "events.jsonl").read_bytes(),
        (out_dir / "trades.jsonl").read_bytes(),
    )


def test_live_inserted_perturbation_resimulates_byte_identically(tmp_path) -> None:
    # Live session: run halfway, insert mid-run exactly like the bridge, finish.
    kernel, recorder, _ = build_session(make_config(), tmp_path / "live")
    kernel.run_until(6_000_000_000)
    assert kernel.now > 0  # the strictly-later live rule is actually exercised
    kernel.schedule_perturbation(kernel.now + 1, 1, "hard_limit", 10)
    kernel.schedule_perturbation(kernel.now + 1, 1, "quote_size", 5)
    kernel.run()
    recorder.close()

    schedule = extract_perturbations(tmp_path / "live" / "events.jsonl")
    assert [(p.param, p.value) for p in schedule] == [("hard_limit", 10), ("quote_size", 5)]

    # Re-simulation: same config, extracted schedule pre-scheduled before start.
    kernel2, recorder2, _ = build_session(make_config(schedule), tmp_path / "resim")
    kernel2.run()
    recorder2.close()

    assert output_bytes(tmp_path / "live") == output_bytes(tmp_path / "resim")


def test_paced_stepping_equals_straight_run(tmp_path) -> None:
    """run_until in small increments (the bridge's pacing loop) must be
    byte-invisible next to a single run()."""
    kernel, recorder, _ = build_session(make_config(), tmp_path / "stepped")
    t = 0
    while t < HORIZON:
        t += 250_000_000  # 4 steps per sim-second
        kernel.run_until(t)
    recorder.close()

    kernel2, recorder2, _ = build_session(make_config(), tmp_path / "straight")
    kernel2.run()
    recorder2.close()

    assert output_bytes(tmp_path / "stepped") == output_bytes(tmp_path / "straight")
