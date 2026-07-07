"""M1 throughput gate benchmark (protocol pinned in ADR-005).

Standalone script — never run under pytest or coverage. Usage:

    uv run python bench/lob_bench.py

Workload: seeded, committed, mixed — ~55% limit orders around a drifting mid,
~25% cancels, ~20% market orders of which a slice is sweep-sized (multi-level).
Orders are pre-constructed outside the timed section: object construction of
inbound messages belongs to the kernel's budget (the separate 30k events/sec
full-loop target at M2); this gate times engine operations.

Gate: median >= 100,000 messages/sec over RUNS timed runs.
"""

import statistics
import subprocess
import sys
import time

import numpy as np

from marquee.engine import MatchingEngine, Order, OrderType, Side

SEED = 7
N_MESSAGES = 1_000_000
WARMUP_MESSAGES = 100_000
RUNS = 5
TARGET_MSGS_PER_SEC = 100_000

SUBMIT, CANCEL = 0, 1


def build_workload(seed: int, n: int) -> list[tuple[int, object]]:
    """Deterministic op list: (SUBMIT, Order) or (CANCEL, order_id)."""
    rng = np.random.Generator(np.random.PCG64(seed))
    ops: list[tuple[int, object]] = []
    next_id = 1
    issued: list[int] = []
    mid = 10_000

    for _ in range(n):
        roll = int(rng.integers(0, 100))
        if roll < 55 or not issued:
            mid = max(mid + int(rng.integers(-3, 4)), 10)
            side = Side.BUY if int(rng.integers(0, 2)) == 0 else Side.SELL
            offset = int(rng.integers(0, 12))
            price = max(mid - offset if side is Side.BUY else mid + offset, 1)
            ops.append(
                (
                    SUBMIT,
                    Order(
                        order_id=next_id,
                        agent_id=int(rng.integers(0, 32)),
                        side=side,
                        order_type=OrderType.LIMIT,
                        price=price,
                        qty=int(rng.integers(1, 200)),
                        ts=next_id,
                    ),
                )
            )
            issued.append(next_id)
            next_id += 1
        elif roll < 80:
            ops.append((CANCEL, issued[int(rng.integers(0, len(issued)))]))
        else:
            # Sweep-heavy segment: ~20% of volume as multi-level market orders
            # (ADR-005 requires the gate workload to include sweeps).
            sweep = 10 if roll >= 96 else 1
            side = Side.BUY if int(rng.integers(0, 2)) == 0 else Side.SELL
            ops.append(
                (
                    SUBMIT,
                    Order(
                        order_id=next_id,
                        agent_id=int(rng.integers(0, 32)),
                        side=side,
                        order_type=OrderType.MARKET,
                        price=0,
                        qty=int(rng.integers(1, 200)) * sweep,
                        ts=next_id,
                    ),
                )
            )
            issued.append(next_id)
            next_id += 1
    return ops


def run_once(ops: list[tuple[int, object]]) -> float:
    engine = MatchingEngine()
    submit = engine.submit
    cancel = engine.cancel
    start = time.perf_counter_ns()
    for kind, payload in ops:
        if kind == SUBMIT:
            submit(payload)
        else:
            cancel(payload)
    elapsed_ns = time.perf_counter_ns() - start
    return len(ops) / (elapsed_ns / 1e9)


def check_environment() -> None:
    if sys.gettrace() is not None:
        sys.exit("FATAL: trace hook active (debugger/coverage?) — numbers would be garbage.")
    active_monitor_ids = [
        i for i in range(6) if sys.monitoring.get_tool(i) is not None
    ]
    if active_monitor_ids:
        sys.exit(f"FATAL: sys.monitoring tools active: {active_monitor_ids}")
    if sys.platform == "win32":
        try:
            scheme = subprocess.run(
                ["powercfg", "/getactivescheme"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            if "High performance" not in scheme and "Ultimate" not in scheme:
                print(f"WARNING: power plan is not High Performance:\n  {scheme.strip()}")
                print("  Run-to-run variance may be +/-30-50%. Gate uses median of runs.\n")
        except OSError:
            pass


def main() -> None:
    check_environment()

    print(f"building workload: seed={SEED}, n={N_MESSAGES + WARMUP_MESSAGES}")
    ops = build_workload(SEED, N_MESSAGES + WARMUP_MESSAGES)
    warmup, timed = ops[:WARMUP_MESSAGES], ops[WARMUP_MESSAGES:]

    # Warm-up: allocator/caches, on a throwaway engine. Timed runs need ids to
    # start fresh, so rebuild the timed ops' engine each run instead.
    throwaway = MatchingEngine()
    for kind, payload in warmup:
        if kind == SUBMIT:
            throwaway.submit(payload)
        else:
            throwaway.cancel(payload)

    # Timed ops must be self-consistent (ids strictly increasing from a fresh
    # engine) — regenerate a clean workload for timing.
    timed = build_workload(SEED + 1, N_MESSAGES)

    rates = []
    for i in range(RUNS):
        rate = run_once(timed)
        rates.append(rate)
        print(f"run {i + 1}/{RUNS}: {rate:,.0f} msgs/sec")

    median = statistics.median(rates)
    print(f"\nmedian: {median:,.0f} msgs/sec  (target {TARGET_MSGS_PER_SEC:,})")
    if median >= TARGET_MSGS_PER_SEC:
        print("GATE: PASS")
    else:
        print("GATE: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
