"""Subprocess worker: run the committed M2 scenario, print output-file hashes."""

import hashlib
import sys
from pathlib import Path

from marquee.sim import run_scenario


def main(config_path: str, out_dir: str) -> None:
    out = run_scenario(config_path, out_dir)
    for name in ("events.jsonl", "trades.jsonl"):
        digest = hashlib.sha256((Path(out) / name).read_bytes()).hexdigest()
        print(f"{name}:{digest}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
