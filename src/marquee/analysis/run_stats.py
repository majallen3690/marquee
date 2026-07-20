"""Automated run analysis: market-quality metrics + configured bounds (M3 gate).

Reconstructs book state by replaying the recorded order stream through a fresh
engine (same code path as replay mode b), sampling L1 on a fixed sim-time grid.
The M3 gate is `check_bounds(stats, bounds)` against `analysis_bounds` in the
committed scenario file — a script verdict, not an eyeball.

Usage:
    uv run python -m marquee.analysis.run_stats scenarios/m3-mixed.yaml runs/out
"""

import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from marquee.engine import MatchingEngine, Order, OrderType, SelfTradePolicy, Side


@dataclass(frozen=True, slots=True)
class RunStats:
    horizon_ns: int
    samples_total: int
    two_sided_pct: float
    median_spread: float  # ticks, two-sided samples only
    p95_spread: float
    max_spread: int
    mean_l1_bid_depth: float  # units at best bid
    mean_l1_ask_depth: float
    longest_one_sided_ns: int
    total_trades: int
    trades_per_sim_sec: float
    total_traded_qty: int


def _percentile(sorted_values: list, pct: float) -> float:
    if not sorted_values:
        return float("nan")
    index = min(len(sorted_values) - 1, int(round(pct * (len(sorted_values) - 1))))
    return float(sorted_values[index])


def compute_run_stats(
    run_dir: str | Path,
    self_trade_policy: SelfTradePolicy,
    horizon_ns: int,
    sample_interval_ns: int = 10_000_000,  # 10 sim-ms
) -> RunStats:
    run_path = Path(run_dir)
    engine = MatchingEngine(self_trade_policy=self_trade_policy)

    spreads: list[int] = []
    bid_depths: list[int] = []
    ask_depths: list[int] = []
    samples_total = 0
    two_sided = 0
    longest_one_sided = 0
    current_one_sided_start: int | None = None
    next_sample = 0

    def take_sample(sample_t: int) -> None:
        nonlocal samples_total, two_sided, longest_one_sided, current_one_sided_start
        samples_total += 1
        snap = engine.snapshot(ts=sample_t, depth=1)
        if snap.bids and snap.asks:
            two_sided += 1
            spreads.append(snap.asks[0].price - snap.bids[0].price)
            bid_depths.append(snap.bids[0].qty)
            ask_depths.append(snap.asks[0].qty)
            if current_one_sided_start is not None:
                longest_one_sided = max(longest_one_sided, sample_t - current_one_sided_start)
                current_one_sided_start = None
        elif current_one_sided_start is None:
            current_one_sided_start = sample_t

    with open(run_path / "events.jsonl", encoding="utf-8", newline="\n") as f:
        for raw in f:
            ev = json.loads(raw)
            t = ev["t"]
            while next_sample <= t and next_sample <= horizon_ns:
                take_sample(next_sample)
                next_sample += sample_interval_ns
            kind = ev["k"]
            if kind == "ord":
                engine.submit(
                    Order(
                        order_id=ev["oid"],
                        agent_id=ev["aid"],
                        side=Side(ev["side"]),
                        order_type=OrderType(ev["ot"]),
                        price=ev["px"],
                        qty=ev["qty"],
                        ts=t,
                    )
                )
            elif kind == "cxl" and ev["cs"] == 0:
                engine.cancel(ev["oid"])
    while next_sample <= horizon_ns:
        take_sample(next_sample)
        next_sample += sample_interval_ns
    if current_one_sided_start is not None:
        longest_one_sided = max(longest_one_sided, horizon_ns - current_one_sided_start)

    total_trades = 0
    total_qty = 0
    with open(run_path / "trades.jsonl", encoding="utf-8", newline="\n") as f:
        for raw in f:
            trade = json.loads(raw)
            total_trades += 1
            total_qty += trade["qty"]

    spreads.sort()
    sim_seconds = horizon_ns / 1e9
    return RunStats(
        horizon_ns=horizon_ns,
        samples_total=samples_total,
        two_sided_pct=100.0 * two_sided / samples_total if samples_total else 0.0,
        median_spread=float(statistics.median(spreads)) if spreads else float("nan"),
        p95_spread=_percentile(spreads, 0.95),
        max_spread=spreads[-1] if spreads else 0,
        mean_l1_bid_depth=float(statistics.fmean(bid_depths)) if bid_depths else 0.0,
        mean_l1_ask_depth=float(statistics.fmean(ask_depths)) if ask_depths else 0.0,
        longest_one_sided_ns=longest_one_sided,
        total_trades=total_trades,
        trades_per_sim_sec=total_trades / sim_seconds if sim_seconds else 0.0,
        total_traded_qty=total_qty,
    )


def check_bounds(stats: RunStats, bounds: dict) -> list[str]:
    """Returns a list of violations; empty list == gate pass."""
    violations: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            violations.append(message)

    require(
        stats.two_sided_pct >= bounds["min_two_sided_pct"],
        f"two_sided_pct {stats.two_sided_pct:.2f} < {bounds['min_two_sided_pct']}",
    )
    require(
        stats.median_spread <= bounds["max_median_spread"],
        f"median_spread {stats.median_spread:.1f} > {bounds['max_median_spread']}",
    )
    require(
        stats.p95_spread <= bounds["max_p95_spread"],
        f"p95_spread {stats.p95_spread:.1f} > {bounds['max_p95_spread']}",
    )
    require(
        stats.mean_l1_bid_depth >= bounds["min_mean_l1_depth"],
        f"mean_l1_bid_depth {stats.mean_l1_bid_depth:.1f} < {bounds['min_mean_l1_depth']}",
    )
    require(
        stats.mean_l1_ask_depth >= bounds["min_mean_l1_depth"],
        f"mean_l1_ask_depth {stats.mean_l1_ask_depth:.1f} < {bounds['min_mean_l1_depth']}",
    )
    require(
        stats.longest_one_sided_ns <= bounds["max_one_sided_ns"],
        f"longest_one_sided_ns {stats.longest_one_sided_ns} > {bounds['max_one_sided_ns']}",
    )
    require(
        bounds["min_trades_per_sec"] <= stats.trades_per_sim_sec <= bounds["max_trades_per_sec"],
        f"trades_per_sim_sec {stats.trades_per_sim_sec:.1f} outside "
        f"[{bounds['min_trades_per_sec']}, {bounds['max_trades_per_sec']}]",
    )
    return violations


def main() -> None:
    import yaml

    from marquee.engine import SelfTradePolicy as Policy
    from marquee.sim.scenario import load_scenario

    scenario_path, run_dir = sys.argv[1], sys.argv[2]
    config, _ = load_scenario(scenario_path)
    doc = yaml.safe_load(Path(scenario_path).read_bytes())
    bounds = doc.get("analysis_bounds")
    if bounds is None:
        sys.exit(f"{scenario_path} has no analysis_bounds section")

    stats = compute_run_stats(run_dir, Policy(config.self_trade_policy), config.horizon_ns)
    for field in stats.__dataclass_fields__:
        print(f"{field:24} {getattr(stats, field)}")
    violations = check_bounds(stats, bounds)
    if violations:
        print("\nGATE: FAIL")
        for violation in violations:
            print(f"  - {violation}")
        sys.exit(1)
    print("\nGATE: PASS")


if __name__ == "__main__":
    main()
