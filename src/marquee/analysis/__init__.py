"""Offline run analysis (M3) and stylized-facts calibration (M4).

Float math is permitted here (ADR-004) — this layer never feeds the sim.
"""

from marquee.analysis.run_stats import RunStats, check_bounds, compute_run_stats

__all__ = ["RunStats", "check_bounds", "compute_run_stats"]
