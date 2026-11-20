"""Record a whole run as UI frames for the zero-install demo (GitHub Pages).

The static build of the front end plays this file back in the browser with no
server: one frame per 100 ms of sim time, in exactly the shape the live bridge
sends, with the gate-grid mids made incremental and the tape trimmed to the rows
the UI shows.

    uv run python -m marquee.server.record --out viz/public/replay/m5-flash-crash.json
"""

import argparse
import json
import tempfile
from pathlib import Path

from marquee.server.session import LiveSession

SCENARIO = Path(__file__).resolve().parents[3] / "scenarios" / "m5-flash-crash.yaml"
STEP_S = 0.1  # one frame per 100 ms of sim time at speed 1
TAPE_ROWS = 40


def record(scenario: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        session = LiveSession(scenario, Path(tmp) / "run")
        frames: list[dict] = []
        last_mid_t = -1
        while True:
            frame = session.step(STEP_S)
            frame["mids"] = [m for m in frame["mids"] if m[0] > last_mid_t]
            if frame["mids"]:
                last_mid_t = frame["mids"][-1][0]
            frame["trades"] = frame["trades"][-TAPE_ROWS:]
            frames.append(frame)
            if frame["status"] == "done":
                break
        return {"meta": session.meta(), "frames": frames}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", type=Path, default=SCENARIO)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = record(args.scenario)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"{len(data['frames'])} frames, {args.out.stat().st_size / 1e6:.1f} MB -> {args.out}")


if __name__ == "__main__":
    main()
