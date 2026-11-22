"""The M7 gate report (RL_DESIGN §9, ADR-023): one command, one verdict.

    uv run --group train python -m marquee.rl.report --model models/m7-stage1.zip
        --gate amended --held-out 3 --out docs/m7-results-heldout3.json

--gate original --held-out 1 reproduces the first run (docs/m7-results.json, ADR-024).

Steps, in order, nothing tuned on the held-out set:
1. The best fixed quoting rule, chosen on TRAIN_EVAL (cached in docs/m7-fixed-grid.json).
2. HELD_OUT for the candidate and every baseline (rule-based, best fixed, do-nothing,
   random); risk-adjusted P&L and paired sign tests.
3. Detectors G1–G10 (G10 also plays the candidate on TRAIN_EVAL).
4. Ablations A1–A6 (amended gate: baselines run under every ablation too).
Writes docs/m7-results.json and prints the verdict.
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
from pathlib import Path  # noqa: E402

from marquee.rl.evaluate import (  # noqa: E402
    DO_NOTHING,
    FIXED_GRID,
    HELD_OUT,
    HELD_OUT_3,
    HELD_OUT_4,
    TRAIN_EVAL,
    ablations,
    ablations_vs_baselines,
    best_fixed,
    describe,
    detectors,
    export_actor,
    paired,
    run_eval,
)

REPO = Path(__file__).resolve().parents[3]
GRID_CACHE = REPO / "docs" / "m7-fixed-grid.json"


def fixed_grid(workers: int) -> tuple[tuple[int, int, int], dict]:
    if GRID_CACHE.exists():
        data = json.loads(GRID_CACHE.read_text(encoding="utf-8"))
        if len(data["table"]) == len(FIXED_GRID):
            return tuple(data["best"]), {tuple(json.loads(k)): v for k, v in data["table"].items()}
    best, table = best_fixed(workers)
    GRID_CACHE.write_text(
        json.dumps(
            {"best": best, "table": {json.dumps(list(k)): v for k, v in table.items()}}, indent=1
        ),
        encoding="utf-8",
    )
    return best, table


def _clean(x):
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return str(x)
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", type=Path)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "m7-results.json")
    ap.add_argument("--grid-only", action="store_true")
    ap.add_argument("--gate", choices=("original", "amended"), default="amended")
    ap.add_argument("--held-out", type=int, choices=(1, 3, 4), default=3)
    args = ap.parse_args()

    best, grid = fixed_grid(args.workers)
    print("best fixed rule on training seeds:", best, grid[best], flush=True)
    if args.grid_only:
        return

    cand_spec = ("np", export_actor(str(args.model)))  # same actions as SB3, no torch
    specs = {
        "learned": cand_spec,
        "rule-based maker": ("rule",),
        "best fixed rule": ("fixed", best),
        "do-nothing": DO_NOTHING,
        "random": ("random", 0),
    }
    held_out = {1: HELD_OUT, 3: HELD_OUT_3, 4: HELD_OUT_4}[args.held_out]
    rows = {name: run_eval(spec, held_out, workers=args.workers) for name, spec in specs.items()}
    table = {name: describe(r) for name, r in rows.items()}
    for name, d in table.items():
        print(f"{name:18s} {d}", flush=True)

    cand_train = run_eval(cand_spec, TRAIN_EVAL, workers=args.workers)
    det = detectors(rows["learned"], rows["rule-based maker"], cand_train)
    det_fixed = detectors(rows["best fixed rule"], rows["rule-based maker"])
    if args.gate == "original":
        abl = ablations(cand_spec, table["learned"]["mean_pnl"], workers=args.workers)
    else:
        gate_specs = {k: specs[k] for k in ("learned", "rule-based maker", "best fixed rule")}
        abl = ablations_vs_baselines(gate_specs, table, held_out, workers=args.workers)

    ra = {k: v["risk_adjusted"] for k, v in table.items()}
    beats_rule = ra["learned"] > ra["rule-based maker"]
    beats_fixed = ra["learned"] > ra["best fixed rule"]
    det_ok = all(v["passed"] is not False for v in det.values())
    abl_ok = not any(v["collapsed"] for v in abl.values())
    verdict = {
        "beats_rule_based": beats_rule,
        "beats_best_fixed": beats_fixed,
        "detectors_clean": det_ok,
        "no_ablation_collapse": abl_ok,
        "GATE_PASSED": beats_rule and beats_fixed and det_ok and abl_ok,
    }
    result = {
        "model": str(args.model),
        "gate": args.gate,
        "held_out_set": f"HELD_OUT_{args.held_out}" if args.held_out != 1 else "HELD_OUT",
        "best_fixed_rule": best,
        "held_out": table,
        "paired_vs_rule": paired(rows["learned"], rows["rule-based maker"]),
        "paired_vs_best_fixed": paired(rows["learned"], rows["best fixed rule"]),
        "train_eval": describe(cand_train),
        "detectors": det,
        "detectors_best_fixed": det_fixed,
        "ablations": abl,
        "verdict": verdict,
        "episodes": {
            k: [{kk: vv for kk, vv in r.items() if kk != "q_path"} for r in v]
            for k, v in rows.items()
        },
    }
    args.out.write_text(json.dumps(_clean(result), indent=1), encoding="utf-8")
    print(
        json.dumps(_clean({k: result[k] for k in ("detectors", "ablations", "verdict")}), indent=1)
    )


if __name__ == "__main__":
    main()
