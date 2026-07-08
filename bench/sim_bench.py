"""M2 full-loop throughput gate (ADR-005): kernel + agents + recorder.

    uv run python bench/sim_bench.py

Measures kernel-processed events per wall second over a real scenario run with
a real JsonlRecorder writing to disk, so the calibration-run-time claim is
gated directly. Gate: median >= 30,000 events/sec over RUNS runs.
"""

import statistics
import sys
import tempfile
import time
from pathlib import Path

from marquee.agents import RandomPoster
from marquee.engine import MatchingEngine
from marquee.sim import JsonlRecorder, SimKernel

RUNS = 5
HORIZON_NS = 5_000_000_000  # 5 sim-seconds
N_AGENTS = 12
MEAN_WAKE_NS = 2_000_000  # ~500 wakes/agent/sim-sec -> ~30k wakes + arrivals + deliveries
TARGET_EVENTS_PER_SEC = 30_000


def run_once(out_dir: Path) -> tuple[float, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    recorder = JsonlRecorder(out_dir / "events.jsonl", out_dir / "trades.jsonl")
    kernel = SimKernel(
        master_seed=99,
        engine=MatchingEngine(),
        recorder=recorder,
        horizon_ns=HORIZON_NS,
        agent_to_exchange_ns=1_000_000,
        exchange_to_agent_ns=1_000_000,
        latency_jitter_ns=200_000,
    )
    for aid in range(1, N_AGENTS + 1):
        kernel.register_agent(
            RandomPoster(aid, anchor_price=10_000, band_ticks=5, max_qty=50, cancel_pct=20),
            mean_wake_interval_ns=MEAN_WAKE_NS,
        )
    start = time.perf_counter_ns()
    kernel.run()
    elapsed_ns = time.perf_counter_ns() - start
    recorder.close()
    return kernel.events_processed / (elapsed_ns / 1e9), kernel.events_processed


def check_power() -> None:
    """On battery, boost clocks decay run-to-run and medians sag 30-50%."""
    if sys.platform != "win32":
        return
    import ctypes

    class PowerStatus(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_ubyte),
            ("BatteryFlag", ctypes.c_ubyte),
            ("BatteryLifePercent", ctypes.c_ubyte),
            ("SystemStatusFlag", ctypes.c_ubyte),
            ("BatteryLifeTime", ctypes.c_ulong),
            ("BatteryFullLifeTime", ctypes.c_ulong),
        ]

    status = PowerStatus()
    on_battery = (
        ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))
        and status.ACLineStatus == 0
    )
    if on_battery:
        print("WARNING: running on BATTERY — sustained clocks are capped and")
        print("  run-to-run variance is large. Plug in for gate-quality numbers.\n")


def main() -> None:
    if sys.gettrace() is not None:
        sys.exit("FATAL: trace hook active — numbers would be garbage.")
    check_power()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        run_once(tmp_path / "warmup")  # warm-up run, discarded
        rates = []
        for i in range(RUNS):
            rate, n_events = run_once(tmp_path / f"run{i}")
            rates.append(rate)
            print(f"run {i + 1}/{RUNS}: {rate:,.0f} events/sec ({n_events:,} events)")

    median = statistics.median(rates)
    print(f"\nmedian: {median:,.0f} events/sec  (target {TARGET_EVENTS_PER_SEC:,})")
    if median >= TARGET_EVENTS_PER_SEC:
        print("GATE: PASS")
    else:
        print("GATE: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
