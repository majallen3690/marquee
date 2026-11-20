"""The control run: the same scenario and seed with no perturbation at all.

Up to the moment a lever is pulled the two runs are identical event for event,
so the difference between them after it is the lever's effect, not chance. This
is the dotted "no lever" line on the chart (ADR-021) and the control in the seed
sweep (ADR-020).
"""

import tempfile
from pathlib import Path

from marquee.analysis.stylized_facts import sample_mid_series
from marquee.sim.scenario import build_session, load_scenario

GRID_NS = 100_000_000  # the crash gate's grid


def control_mids(scenario_path: str | Path, grid_ns: int = GRID_NS) -> list[tuple[int, float]]:
    """(t, mid) on the gate grid for the scenario run with its perturbations removed."""
    config, _ = load_scenario(scenario_path)
    with tempfile.TemporaryDirectory() as tmp:
        kernel, recorder, _ = build_session(config, tmp, include_config_perturbations=False)
        try:
            kernel.run()
        finally:
            recorder.close()
        mids = sample_mid_series(tmp, config.self_trade_policy, config.horizon_ns, grid_ns)
    # sample_mid_series skips leading samples before the first two-sided book, so
    # align from the end: the last sample is at the horizon.
    last = (config.horizon_ns // grid_ns) * grid_ns
    return [(last - (len(mids) - 1 - i) * grid_ns, m) for i, m in enumerate(mids)]
