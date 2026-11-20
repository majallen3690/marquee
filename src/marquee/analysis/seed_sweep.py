"""Seed sweep for the M5 lever (ADR-020): the crash-gate metrics over many seeds,
each run twice, with and without the scripted lever.

One seed is an anecdote. This measures what the lever does in general, and the
no-lever twin of each seed is the control (same seed, same flow up to 30 s).

    uv run python -m marquee.analysis.seed_sweep --seeds 30 --out docs/seed-sweep.json
"""

import argparse
import dataclasses
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from marquee.analysis.stylized_facts import sample_mid_series
from marquee.sim.scenario import build_session, load_scenario

SCENARIO = Path(__file__).resolve().parents[3] / "scenarios" / "m5-flash-crash.yaml"
COMMITTED_SEED = 777002
GRID_NS = 100_000_000
LEVER_INDEX = 300  # 30 s on the 100 ms grid; mids[0] is the 0.1 s sample
PRE_LEN, POST_LEN = 150, 50  # 15 s before the lever, 5 s after (crash_criteria)


@dataclass(frozen=True, slots=True)
class GateMove:
    seed: int
    lever: bool
    move: float  # signed extreme of mid - mid_at_lever over the 5 s after it
    pre_worst: float  # worst max-min over 5 s windows in the 15 s before
    amp: float  # |move| / pre_worst, exactly as tests/test_m5_crash.py computes it


def gate_move(mids: list[float]) -> tuple[float, float]:
    """The committed gate's two numbers from a 100 ms mid series."""
    pre = mids[LEVER_INDEX - PRE_LEN : LEVER_INDEX]
    post = mids[LEVER_INDEX : LEVER_INDEX + POST_LEN]
    at_lever = mids[LEVER_INDEX - 1]
    move = max((m - at_lever for m in post), key=abs)
    worst = max(
        max(pre[i : i + POST_LEN]) - min(pre[i : i + POST_LEN])
        for i in range(0, len(pre) - POST_LEN, POST_LEN // 5)
    )
    return move, worst


def run_one(seed: int, lever: bool, work: Path, momentum: bool = True) -> GateMove:
    """The committed scenario with its seed replaced; optionally without the lever
    (the control) or without the three momentum traders (the ablation)."""
    config, _ = load_scenario(SCENARIO)
    agents = config.agents if momentum else tuple(
        a for a in config.agents if a.agent_class != "momentum"
    )
    config = dataclasses.replace(config, master_seed=seed, agents=agents)
    out = work / f"run_{seed}_{int(lever)}_{int(momentum)}"
    kernel, recorder, _ = build_session(config, out, include_config_perturbations=lever)
    try:
        kernel.run()
    finally:
        recorder.close()
    mids = sample_mid_series(out, config.self_trade_policy, config.horizon_ns, GRID_NS)
    move, worst = gate_move(mids)
    return GateMove(seed, lever, move, worst, abs(move) / worst)


def sweep(seeds: list[int]) -> list[GateMove]:
    with tempfile.TemporaryDirectory() as tmp:
        return [run_one(s, lever, Path(tmp)) for s in seeds for lever in (True, False)]


def default_seeds(n: int) -> list[int]:
    """The committed seed plus n-1 fixed others, so the sweep is itself reproducible."""
    return [COMMITTED_SEED, *range(1001, 1000 + n)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rows = sweep(default_seeds(args.seeds))
    for row in rows:
        print(json.dumps(asdict(row)))
    if args.out:
        args.out.write_text(json.dumps([asdict(r) for r in rows], indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
