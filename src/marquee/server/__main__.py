"""One-command demo entry point: `uv run marquee-demo` (M5 gate)."""

import argparse
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from marquee.server.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    parser = argparse.ArgumentParser(description="marquee live demo")
    parser.add_argument(
        "--scenario",
        default=str(REPO_ROOT / "scenarios" / "m5-flash-crash.yaml"),
    )
    parser.add_argument("--out", default=str(REPO_ROOT / "runs" / "live"))
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not args.no_browser:
        def open_browser() -> None:
            time.sleep(1.0)
            webbrowser.open(f"http://127.0.0.1:{args.port}/")

        threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(
        create_app(args.scenario, args.out),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
