"""Engine-level determinism gate (ADR-006 gate a, applied at M1).

Two subprocesses, same seed and workload, *different* PYTHONHASHSEED → the
SHA-256 of the serialized output stream must be identical. Run in-process this
check would share one hash seed and could green-light latent str-hash-order
nondeterminism.
"""

import os
import subprocess
import sys
from pathlib import Path

WORKER = Path(__file__).parent / "_determinism_worker.py"
SEED = "1337"
N_MESSAGES = "30000"


def _run(hash_seed: str) -> str:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = hash_seed
    result = subprocess.run(
        [sys.executable, str(WORKER), SEED, N_MESSAGES],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=120,
    )
    return result.stdout.strip()


def test_same_workload_identical_output_across_hash_seeds() -> None:
    first = _run("1")
    second = _run("2")
    assert first == second
    assert len(first) == 64  # a real sha256, not empty output
