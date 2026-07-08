"""M2 gate: a scripted multi-agent scenario replays byte-identically (ADR-006).

Gate (a): two subprocesses, same scenario, different PYTHONHASHSEED → identical
SHA-256 for events.jsonl and trades.jsonl.
Gate (b): the order stream extracted from events.jsonl, re-fed through a fresh
engine with agents disabled, reproduces trades.jsonl byte-for-byte.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from marquee.engine import SelfTradePolicy
from marquee.sim import run_scenario
from marquee.sim.replay import replay_order_stream

SCENARIO = Path(__file__).parents[1] / "scenarios" / "m2-scripted.yaml"
WORKER = Path(__file__).parent / "_scenario_worker.py"


def _run_subprocess(hash_seed: str, out_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = hash_seed
    result = subprocess.run(
        [sys.executable, str(WORKER), str(SCENARIO), str(out_dir)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=600,
    )
    return dict(line.split(":", 1) for line in result.stdout.strip().splitlines())


def test_scenario_replays_byte_identically_across_hash_seeds(tmp_path) -> None:
    hashes_a = _run_subprocess("1", tmp_path / "a")
    hashes_b = _run_subprocess("2", tmp_path / "b")
    assert hashes_a == hashes_b
    assert set(hashes_a) == {"events.jsonl", "trades.jsonl"}
    # Non-vacuous: the runs really produced events and trades.
    assert (tmp_path / "a" / "trades.jsonl").stat().st_size > 0
    assert (tmp_path / "a" / "events.jsonl").stat().st_size > 0


def test_order_stream_replay_reproduces_trades(tmp_path) -> None:
    out = run_scenario(SCENARIO, tmp_path / "run")
    replayed = replay_order_stream(out / "events.jsonl", SelfTradePolicy.ALLOW)
    assert replayed == (out / "trades.jsonl").read_bytes()
    assert replayed  # non-vacuous


def test_manifest_records_reproducibility_context(tmp_path) -> None:
    out = run_scenario(SCENARIO, tmp_path / "run")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for key in (
        "scenario_name",
        "master_seed",
        "config_sha256",
        "config_text",
        "python_version",
        "numpy_version",
        "git_sha",
        "dirty",
        "dirty_diff_sha256",
    ):
        assert key in manifest
    assert manifest["scenario_name"] == "m2-scripted"
