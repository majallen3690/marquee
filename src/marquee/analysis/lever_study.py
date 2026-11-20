"""Which part of the M5 lever does the work, and how much of it is needed (ADR-022).

The committed lever changes four maker parameters at once (inventory limits,
quote size, quoting distance). Two controlled experiments on the same 30 seeds,
each run paired against its own no-lever twin:

* **Ablation.** Each component alone, and the full lever minus each component.
* **Dose-response.** All four components, or the half-spread alone, moved part
  of the way from their normal values to the lever's, geometrically:
  value = base * (lever/base)**s, for intensity s in (0, 1]. s = 1 is the lever.
* **Mechanism.** Distance alone with the three momentum traders removed.

Every effect is also measured on executed prices, so a quote-only artifact would
show up as disagreement. Results and reading: docs/LEVER_STUDY.md.

Metrics are the committed crash gate's (``seed_sweep.gate_move``), plus the
top-5 book depth on the 100 ms grid: the mean over the 15 s before the lever
and the median over the 5 s after, so each dose can be read as "how much of the
book was removed".

    uv run python -m marquee.analysis.lever_study --out docs/lever-study.json
"""

import os

# One BLAS thread per worker: 20 processes x 24 OpenBLAS threads exhausts memory.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402
import dataclasses  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import tempfile  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

from marquee.analysis.seed_sweep import (  # noqa: E402
    GRID_NS,
    LEVER_INDEX,
    POST_LEN,
    SCENARIO,
    default_seeds,
    gate_move,
)
from marquee.analysis.stylized_facts import sample_mid_series  # noqa: E402
from marquee.sim.scenario import PerturbationSpec, build_session, load_scenario  # noqa: E402

LEVER_NS = 30_000_000_000
PRE_DEPTH_FROM_NS = 15_000_000_000
POST_DEPTH_TO_NS = 35_000_000_000
POST_WINDOW_NS = 5_000_000_000

LIMITS = ("soft_limit", "hard_limit")
SIZE = ("quote_size",)
SPREAD = ("half_spread",)
ARMS: dict[str, tuple[str, ...]] = {
    "full": LIMITS + SIZE + SPREAD,
    "limits only": LIMITS,
    "size only": SIZE,
    "spread only": SPREAD,
    "all but limits": SIZE + SPREAD,
    "all but size": LIMITS + SPREAD,
    "all but spread": LIMITS + SIZE,
}
DOSES = (0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0)


def lever_subset(perturbations: tuple[PerturbationSpec, ...], params: tuple[str, ...]):
    return tuple(p for p in perturbations if p.param in params)


def dosed(config, s: float, params: tuple[str, ...] = ARMS["full"]) -> tuple[PerturbationSpec, ...]:
    """The committed lever (or its ``params`` part) moved a fraction s of the way, in
    log space, from each maker's normal parameter value to the lever's; never below 1."""
    base = {(a.agent_id, k): v for a in config.agents for k, v in a.params.items()}
    out = []
    for p in lever_subset(config.perturbations, params):
        b = base[(p.agent_id, p.param)]
        value = max(1, round(b * (p.value / b) ** s))
        out.append(dataclasses.replace(p, value=value))
    return tuple(out)


def _top5(snapshot) -> int:
    return sum(level.qty for level in snapshot.bids[:5]) + sum(
        level.qty for level in snapshot.asks[:5]
    )


def run_case(seed: int, perturbations: tuple[PerturbationSpec, ...], momentum: bool = True) -> dict:
    """One run of the committed scenario with its seed and lever replaced;
    optionally without the three momentum traders."""
    config, _ = load_scenario(SCENARIO)
    agents = (
        config.agents
        if momentum
        else tuple(a for a in config.agents if a.agent_class != "momentum")
    )
    config = dataclasses.replace(
        config, master_seed=seed, perturbations=perturbations, agents=agents
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "run"
        kernel, recorder, _ = build_session(config, out)
        pre, post = [], []
        try:
            for t in range(PRE_DEPTH_FROM_NS + GRID_NS, POST_DEPTH_TO_NS + 1, GRID_NS):
                kernel.run_until(t)
                d = _top5(kernel.engine.snapshot(ts=t, depth=5))
                (pre if t <= LEVER_NS else post).append(d)
            kernel.run()
        finally:
            recorder.close()
        mids = sample_mid_series(out, config.self_trade_policy, config.horizon_ns, GRID_NS)
        trades = [json.loads(line) for line in (out / "trades.jsonl").open(encoding="utf-8")]
    move, worst = gate_move(mids)
    return {
        "seed": seed,
        "move": move,
        "pre_worst": worst,
        "depth_pre": float(np.mean(pre)),
        "depth_post": float(np.median(post)),
        # where the mid sits at the end of the window, not its extreme
        "end_move": mids[LEVER_INDEX + POST_LEN - 1] - mids[LEVER_INDEX - 1],
        **trade_moves(trades),
    }


def _vwap(trades: list[dict], lo: int, hi: int) -> float | None:
    sel = [t for t in trades if lo < t["t"] <= hi]
    qty = sum(t["qty"] for t in sel)
    return sum(t["px"] * t["qty"] for t in sel) / qty if qty else None


def trade_moves(trades: list[dict]) -> dict:
    """The same window measured on executions instead of quotes. A mid can move
    with almost no trading when quotes walk away from a thin book; traded prices
    cannot. ``trade_move``: signed extreme of trade price minus the last trade at or
    before the lever. ``trade_end``: VWAP of the last second of the window minus
    VWAP of the second before the lever."""
    end = LEVER_NS + POST_WINDOW_NS
    before = [t for t in trades if t["t"] <= LEVER_NS]
    ref = before[-1]["px"] if before else None
    post = [t for t in trades if LEVER_NS < t["t"] <= end]
    trade_move = None
    if ref is not None and post:
        trade_move = float(max((t["px"] - ref for t in post), key=abs))
    v0 = _vwap(trades, LEVER_NS - 1_000_000_000, LEVER_NS)
    v1 = _vwap(trades, end - 1_000_000_000, end)
    return {
        "trade_move": trade_move,
        "trade_end": (v1 - v0) if v0 is not None and v1 is not None else None,
        "post_volume": sum(t["qty"] for t in post),
        "post_trades": len(post),
    }


# --- statistics -------------------------------------------------------------


def sign_test_p(wins: int, losses: int) -> float:
    """Two-sided exact sign test (ties already dropped)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = max(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k, n + 1)) / 2**n
    return min(1.0, 2 * tail)


def bootstrap_median_ci(values, n_boot: int = 10_000, seed: int = 0) -> tuple[float, float]:
    """95% percentile bootstrap interval for the median (fixed seed: reproducible)."""
    x = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    meds = np.median(rng.choice(x, size=(n_boot, len(x)), replace=True), axis=1)
    lo, hi = np.percentile(meds, [2.5, 97.5])
    return float(lo), float(hi)


def summarize(rows: list[dict], control: dict[int, dict]) -> dict:
    """Paired against each seed's own no-lever twin."""
    size = [abs(r["move"]) for r in rows]
    ratio = [abs(r["move"]) / max(abs(control[r["seed"]]["move"]), 0.5) for r in rows]
    wins = sum(abs(r["move"]) > abs(control[r["seed"]]["move"]) for r in rows)
    losses = sum(abs(r["move"]) < abs(control[r["seed"]]["move"]) for r in rows)
    removed = [1 - r["depth_post"] / r["depth_pre"] for r in rows]
    trade = [abs(r["trade_move"]) for r in rows if r["trade_move"] is not None]
    trade_ctl = {s: abs(c["trade_move"]) for s, c in control.items() if c["trade_move"] is not None}
    trade_wins = sum(
        abs(r["trade_move"]) > trade_ctl[r["seed"]]
        for r in rows
        if r["trade_move"] is not None and r["seed"] in trade_ctl
    )
    trade_losses = sum(
        abs(r["trade_move"]) < trade_ctl[r["seed"]]
        for r in rows
        if r["trade_move"] is not None and r["seed"] in trade_ctl
    )
    return {
        "median_trade_move": float(np.median(trade)) if trade else None,
        "median_trade_end": float(
            np.median([abs(r["trade_end"]) for r in rows if r["trade_end"] is not None])
        ),
        "median_end_move": float(np.median([abs(r["end_move"]) for r in rows])),
        "trade_bigger": trade_wins,
        "trade_smaller": trade_losses,
        "trade_sign_p": sign_test_p(trade_wins, trade_losses),
        "median_post_volume": float(np.median([r["post_volume"] for r in rows])),
        "median_move": float(np.median(size)),
        "median_move_ci": bootstrap_median_ci(size),
        "median_ratio": float(np.median(ratio)),
        "median_ratio_ci": bootstrap_median_ci(ratio),
        "bigger": wins,
        "smaller": losses,
        "sign_p": sign_test_p(wins, losses),
        "down": sum(r["move"] < 0 for r in rows),
        "depth_removed": float(np.median(removed)),
        "n": len(rows),
    }


# --- driver -----------------------------------------------------------------


def run_jobs(
    jobs: dict[str, tuple[tuple[PerturbationSpec, ...], bool]], seeds: list[int], workers: int
) -> dict[str, list[dict]]:
    """Every (job, seed) run, in parallel; results ordered by seed."""
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {(k, seed): pool.submit(run_case, seed, *jobs[k]) for k in jobs for seed in seeds}
        return {k: [futures[(k, s)].result() for s in seeds] for k in jobs}


def study(seeds: list[int], workers: int = 12) -> dict:
    config, _ = load_scenario(SCENARIO)
    # name -> (lever, momentum traders present)
    jobs: dict[str, tuple[tuple[PerturbationSpec, ...], bool]] = {"control": ((), True)}
    for name, params in ARMS.items():
        jobs[f"arm:{name}"] = (lever_subset(config.perturbations, params), True)
    for s in DOSES:
        jobs[f"dose:{s}"] = (dosed(config, s), True)
        jobs[f"spread dose:{s}"] = (dosed(config, s, SPREAD), True)
    # mechanism: is the spread effect carried by the trend-followers?
    jobs["control, no momentum"] = ((), False)
    jobs["spread only, no momentum"] = (lever_subset(config.perturbations, SPREAD), False)
    # each dose 1.0 is an ablation arm by construction; run it once
    assert jobs["dose:1.0"] == jobs["arm:full"]
    assert jobs["spread dose:1.0"] == jobs["arm:spread only"]
    same = {"dose:1.0": "arm:full", "spread dose:1.0": "arm:spread only"}
    raw = run_jobs({k: v for k, v in jobs.items() if k not in same}, seeds, workers)
    for k, v in same.items():
        raw[k] = raw[v]
    control = {r["seed"]: r for r in raw["control"]}
    control_nm = {r["seed"]: r for r in raw["control, no momentum"]}
    return {
        "seeds": seeds,
        "control": summarize(raw["control"], control),
        "control, no momentum": summarize(raw["control, no momentum"], control_nm),
        "spread only, no momentum": summarize(raw["spread only, no momentum"], control_nm),
        "arms": {name: summarize(raw[f"arm:{name}"], control) for name in ARMS},
        "doses": {
            str(s): {
                "params": {f"{p.agent_id}.{p.param}": p.value for p in jobs[f"dose:{s}"][0]},
                **summarize(raw[f"dose:{s}"], control),
            }
            for s in DOSES
        },
        "spread_doses": {
            str(s): {
                "params": {f"{p.agent_id}.{p.param}": p.value for p in jobs[f"spread dose:{s}"][0]},
                **summarize(raw[f"spread dose:{s}"], control),
            }
            for s in DOSES
        },
        "runs": raw,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = study(default_seeds(args.seeds), args.workers)
    summary = {k: v for k, v in result.items() if k != "runs"}
    print(json.dumps(summary, indent=1))
    if args.out:
        args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
