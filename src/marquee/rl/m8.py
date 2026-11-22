"""M8: does a learned market maker soften or deepen the lever's effect? (ADR-026)

Maker 2's seat is taken over before the lever (retire and replace, as in M7) by one
of three successors, on the same seed and entry time, while maker 1 is always the
rule-based maker and always takes the lever:

    rule, levered   a rule-based successor that takes the lever too (the M5 lever)
    rule, holds     a rule-based successor that keeps its normal parameters
    learned         the learned maker, which decides for itself

plus the no-lever twins (rule, learned) for each seed's own baseline. The learned maker
never saw a perturbation in training, and the lever lands at a different step of its
episode on every seed (entry 12-24 s, lever at 30 s), so it cannot have memorized it.

The move is the committed crash gate's: the signed largest deviation of the public mid
over the 5 s after the lever, on the 100 ms grid, from the mid at the lever
(`seed_sweep.gate_move`), and the same on executed prices (`lever_study.trade_moves`).

    uv run --group train python -m marquee.rl.m8 --model <model.zip> --out docs/m8-results.json
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402
import json  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

from marquee.analysis.lever_study import bootstrap_median_ci, sign_test_p, trade_moves  # noqa: E402
from marquee.rl.env import ENTRANT_ID, STEP_NS, EnvConfig, MarketMakingEnv  # noqa: E402
from marquee.rl.evaluate import _act, export_actor  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
M8_SCENARIO = REPO / "scenarios" / "m8-lever.yaml"
LEVER_NS = 30_000_000_000
POST_STEPS = 50  # 5 s on the 100 ms grid
PRE_STEPS = 50

# Committed before any M8 run (ADR-026): 30 seeds outside the training pool and every
# M7/M7b episode set, and one entry step per seed (12.0-24.0 s).
M8_SEEDS = tuple(range(8_000_001, 8_000_031))
M8_ENTRY_STEPS = tuple(
    int(x) for x in np.random.default_rng(18).integers(120, 241, size=len(M8_SEEDS))
)

ARMS = {
    "rule, no lever": ("rule", "none"),
    "learned, no lever": ("learned", "none"),
    "rule, levered": ("rule", "all"),
    "rule, holds": ("rule", "others"),
    "learned": ("learned", "others"),
}


def _median(xs):
    xs = [x for x in xs if x is not None]
    return float(np.median(xs)) if xs else None


def run_arm(seed: int, start_step: int, arm: str, model: str | None) -> dict:
    controller, lever = ARMS[arm]
    cfg = EnvConfig(
        scenario=M8_SCENARIO,
        controller=controller,
        latency_jitter=0.0,
        lever=lever,
        record_mid=True,
    )
    env = MarketMakingEnv(cfg)
    obs, _ = env.reset(options={"master_seed": seed, "start_step": start_step})
    spec = ("rule",) if controller == "rule" else ("np", model)  # model: an actor .npz
    rng = np.random.default_rng(seed)
    while True:
        obs, _r, _t, trunc, info = env.step(_act(spec, obs, rng))
        if trunc:
            ep = info["episode"]
            break

    k = (LEVER_NS - env.t0) // STEP_NS  # mid_path[i] is the mid at t0 + (i + 1) * 100 ms
    mids = ep["mid_path"]
    at_lever = next(m for m in reversed(mids[:k]) if m is not None)  # carry, as the gate does
    post = [m for m in mids[k : k + POST_STEPS] if m is not None]
    move = max((m - at_lever for m in post), key=abs)
    trades = [{"t": t, "px": px, "qty": q} for t, px, q, *_ in env.tape.trades]
    own_post = [
        q
        for t, _px, q, mka, tka, _ in env.tape.trades
        if LEVER_NS < t <= LEVER_NS + POST_STEPS * STEP_NS and ENTRANT_ID in (mka, tka)
    ]
    spreads = ep["own_spread_path"]
    q = ep["q_path"]
    return {
        "seed": seed,
        "arm": arm,
        "start_step": start_step,
        "lever_step": int(k),
        "move": float(move),
        **trade_moves(trades),
        # what the entrant did around the lever
        "spread_pre": _median(spreads[k - PRE_STEPS : k]),
        "spread_post": _median(spreads[k : k + POST_STEPS]),
        "two_sided_post": float(np.mean([s is not None for s in spreads[k : k + POST_STEPS]])),
        "q_at_lever": q[k - 1],
        "q_post": q[k + POST_STEPS - 1],
        "entrant_post_volume": int(sum(own_post)),
        "entrant_pnl": ep["pnl"],
    }


def _job(args):
    return run_arm(*args)


def run_all(model: str, workers: int = 6) -> list[dict]:
    jobs = [
        (seed, start, arm, model)
        for seed, start in zip(M8_SEEDS, M8_ENTRY_STEPS, strict=True)
        for arm in ARMS
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_job, jobs))


def paired(rows: list[dict], a: str, b: str, key: str = "move") -> dict:
    """Is |key| smaller under arm a than arm b, seed by seed? Ties drop out."""
    by = {(r["seed"], r["arm"]): r for r in rows}
    da, db = [], []
    for s in M8_SEEDS:
        x, y = by[(s, a)][key], by[(s, b)][key]
        if x is not None and y is not None:
            da.append(abs(x))
            db.append(abs(y))
    smaller = sum(x < y for x, y in zip(da, db, strict=True))
    larger = sum(x > y for x, y in zip(da, db, strict=True))
    ratios = [x / y for x, y in zip(da, db, strict=True) if y > 0]
    return {
        "n": len(da),
        f"{a} smaller": smaller,
        f"{a} larger": larger,
        "sign_p": sign_test_p(smaller, larger),
        "median_ratio": float(np.median(ratios)) if ratios else None,
        "ratio_ci": bootstrap_median_ci(ratios) if ratios else None,
    }


def verdict(p: dict, a: str) -> str:
    """ADR-026's pre-registered reading of the primary comparison."""
    lo, hi = p["ratio_ci"]
    if p["sign_p"] < 0.05 and p[f"{a} smaller"] > p[f"{a} larger"] and hi < 1:
        return "softens"
    if p["sign_p"] < 0.05 and p[f"{a} larger"] > p[f"{a} smaller"] and lo > 1:
        return "deepens"
    return "no detectable difference"


def summarize(rows: list[dict]) -> dict:
    arms = {}
    for arm in ARMS:
        rs = [r for r in rows if r["arm"] == arm]
        size = [abs(r["move"]) for r in rs]
        arms[arm] = {
            "median_move_size": float(np.median(size)),
            "move_size_ci": bootstrap_median_ci(size),
            "down": sum(r["move"] < 0 for r in rs),
            "median_trade_move_size": _median(
                [abs(r["trade_move"]) for r in rs if r["trade_move"] is not None]
            ),
            "entrant_spread_pre": _median([r["spread_pre"] for r in rs]),
            "entrant_spread_post": _median([r["spread_post"] for r in rs]),
            "entrant_two_sided_post": float(np.mean([r["two_sided_post"] for r in rs])),
            "entrant_median_abs_q_post": float(np.median([abs(r["q_post"]) for r in rs])),
            "entrant_median_post_volume": float(np.median([r["entrant_post_volume"] for r in rs])),
            "entrant_mean_pnl": float(np.mean([r["entrant_pnl"] for r in rs])),
        }
    primary = paired(rows, "learned", "rule, holds")
    return {
        "arms": arms,
        "primary: learned vs rule, holds": primary,
        "primary, on executed prices": paired(rows, "learned", "rule, holds", "trade_move"),
        "learned vs rule, levered": paired(rows, "learned", "rule, levered"),
        "lever check: rule, levered vs its twin": paired(rows, "rule, levered", "rule, no lever"),
        "learned vs its own twin": paired(rows, "learned", "learned, no lever"),
        "rule, holds vs its twin": paired(rows, "rule, holds", "rule, no lever"),
        "verdict": verdict(primary, "learned"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "m8-results.json")
    args = ap.parse_args()
    rows = run_all(export_actor(args.model), args.workers)
    out = {"model": args.model, "summary": summarize(rows), "runs": rows}
    args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out["summary"], indent=1))


if __name__ == "__main__":
    main()
