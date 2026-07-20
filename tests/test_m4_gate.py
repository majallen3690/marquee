"""M4 gate: the committed calibration scenario reproduces the stylized facts of
real markets from its seed — thresholds per ADR-013, market quality per ADR-012."""

from pathlib import Path

import yaml

from marquee.analysis import check_bounds, compute_run_stats
from marquee.analysis.stylized_facts import check_facts, compute_stylized_facts
from marquee.sim import run_scenario
from marquee.sim.scenario import load_scenario

SCENARIO = Path(__file__).parents[1] / "scenarios" / "m4-calibrated.yaml"


def test_calibrated_scenario_reproduces_stylized_facts(tmp_path) -> None:
    config, raw = load_scenario(SCENARIO)
    doc = yaml.safe_load(raw)

    out = run_scenario(SCENARIO, tmp_path / "run")

    facts = compute_stylized_facts(out, config.self_trade_policy, config.horizon_ns)
    fact_violations = check_facts(facts, doc["stylized_facts_thresholds"])
    assert fact_violations == [], (
        f"stylized-facts thresholds violated: {fact_violations}\nfull facts: {facts}"
    )

    # The long-horizon run must also still be a healthy market (M3 bounds).
    stats = compute_run_stats(out, config.self_trade_policy, config.horizon_ns)
    quality_violations = check_bounds(stats, doc["analysis_bounds"])
    assert quality_violations == [], (
        f"market-quality bounds violated on the M4 run: {quality_violations}"
    )
