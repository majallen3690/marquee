"""M7b model choice (ADR-025): every checkpoint of every run, played deterministically on
VALIDATION + VALIDATION_2 (60 episodes); the highest risk-adjusted P&L is the model.
Nothing on any held-out set is consulted.

    uv run --group train python -m marquee.rl.select runs/m7b-g0.1 runs/m7b-g0.3 runs/m7b-g1.0
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

from marquee.rl.evaluate import VALIDATION, VALIDATION_2, describe, run_eval  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
CHOICE_SET = VALIDATION + VALIDATION_2


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "m7b-selection.json")
    ap.add_argument("--model-out", type=Path, default=REPO / "models" / "m7b.zip")
    args = ap.parse_args()

    # Scores are deterministic, so each is saved as it lands and an interrupted choice
    # resumes where it stopped instead of starting over.
    partial = args.out.with_suffix(".partial.jsonl")
    table = {}
    if partial.exists():
        for line in partial.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            table[rec["ckpt"]] = rec["describe"]
    for run in args.runs:
        for ckpt in sorted(run.glob("ckpt_*.zip")):
            if str(ckpt) in table:
                continue
            d = describe(run_eval(("ppo", str(ckpt)), CHOICE_SET, workers=args.workers))
            table[str(ckpt)] = d
            with open(partial, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ckpt": str(ckpt), "describe": d}) + "\n")
            print(f"{ckpt}  RA {d['risk_adjusted']:.3f}  mean {d['mean_pnl']:.0f}", flush=True)
    best = max(table, key=lambda k: table[k]["risk_adjusted"])
    shutil.copyfile(best, args.model_out)
    args.out.write_text(
        json.dumps({"chosen": best, "episodes": len(CHOICE_SET), "table": table}, indent=1),
        encoding="utf-8",
    )
    print("chosen:", best, table[best])


if __name__ == "__main__":
    main()
