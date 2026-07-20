"""M3 gate: the committed mixed-population scenario sustains a continuously
two-sided market, verified by the automated run-analysis bounds — no eyeballing."""

from pathlib import Path

import yaml

from marquee.analysis import check_bounds, compute_run_stats
from marquee.sim import run_scenario
from marquee.sim.scenario import load_scenario

SCENARIO = Path(__file__).parents[1] / "scenarios" / "m3-mixed.yaml"


def test_mixed_population_market_quality_bounds(tmp_path) -> None:
    config, raw = load_scenario(SCENARIO)
    bounds = yaml.safe_load(raw)["analysis_bounds"]

    out = run_scenario(SCENARIO, tmp_path / "run")
    stats = compute_run_stats(out, config.self_trade_policy, config.horizon_ns)

    violations = check_bounds(stats, bounds)
    assert violations == [], (
        f"market-quality bounds violated: {violations}\nfull stats: {stats}"
    )
    # Sanity floor so a degenerate-but-in-bounds run can't sneak through.
    assert stats.total_trades > 100
    assert stats.samples_total >= 2_900  # ~10ms grid over 30 sim-seconds
