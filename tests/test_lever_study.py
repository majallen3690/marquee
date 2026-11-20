"""Which part of the lever does the work (ADR-022).

The committed lever changes four maker parameters at once. Taken apart on the
same 30 seeds, the quoting distance (half_spread) carries the whole effect;
shrinking quote size or inventory limits does nothing to the 5 s move, even
though shrinking size removes most of the book's depth. Slow test: 150 runs.
"""

import statistics

import pytest

from marquee.analysis.lever_study import (
    ARMS,
    SCENARIO,
    SPREAD,
    bootstrap_median_ci,
    dosed,
    lever_subset,
    run_jobs,
    sign_test_p,
    summarize,
    trade_moves,
)
from marquee.analysis.seed_sweep import default_seeds
from marquee.sim.scenario import load_scenario

# --- fast: the instruments --------------------------------------------------


def test_dose_one_is_the_committed_lever_and_dose_zero_changes_nothing() -> None:
    config, _ = load_scenario(SCENARIO)
    assert dosed(config, 1.0) == config.perturbations
    base = {(a.agent_id, k): v for a in config.agents for k, v in a.params.items()}
    assert all(p.value == base[(p.agent_id, p.param)] for p in dosed(config, 0.0))
    # intermediate doses sit between the two ends, for every parameter
    for low, mid, high in zip(
        dosed(config, 0.0), dosed(config, 0.5), config.perturbations, strict=True
    ):
        assert min(low.value, high.value) <= mid.value <= max(low.value, high.value)


def test_spread_dose_moves_only_the_quoting_distance() -> None:
    config, _ = load_scenario(SCENARIO)
    assert {p.param for p in dosed(config, 0.5, SPREAD)} == {"half_spread"}
    assert lever_subset(config.perturbations, ARMS["full"]) == config.perturbations


def test_sign_test() -> None:
    assert sign_test_p(15, 15) == 1.0
    assert sign_test_p(30, 0) == pytest.approx(2 / 2**30)
    assert sign_test_p(23, 7) == pytest.approx(0.00522, abs=1e-5)  # the 30-seed headline
    assert sign_test_p(7, 23) == sign_test_p(23, 7)


def test_bootstrap_interval_is_reproducible_and_brackets_the_median() -> None:
    xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 100]
    lo, hi = bootstrap_median_ci(xs)
    assert (lo, hi) == bootstrap_median_ci(xs)
    assert lo <= statistics.median(xs) <= hi


def test_trade_moves_measure_executions_around_the_lever() -> None:
    s = 1_000_000_000
    trades = [
        {"t": 29 * s + 500, "px": 100, "qty": 10},
        {"t": 30 * s, "px": 101, "qty": 10},  # last trade at or before the lever
        {"t": 31 * s, "px": 95, "qty": 5},
        {"t": 32 * s, "px": 104, "qty": 5},
        {"t": 34 * s + 500, "px": 99, "qty": 4},
        {"t": 36 * s, "px": 50, "qty": 99},  # after the window: ignored
    ]
    m = trade_moves(trades)
    assert m["trade_move"] == -6.0  # 95 - 101 beats 104 - 101
    assert m["trade_end"] == pytest.approx(99 - 100.5)
    assert (m["post_volume"], m["post_trades"]) == (14, 3)


# --- slow: the finding ------------------------------------------------------


@pytest.mark.slow
def test_quoting_distance_carries_the_lever_not_depth() -> None:
    config, _ = load_scenario(SCENARIO)
    jobs = {
        "control": ((), True),
        "limits only": (lever_subset(config.perturbations, ARMS["limits only"]), True),
        "size only": (lever_subset(config.perturbations, ARMS["size only"]), True),
        "spread only": (lever_subset(config.perturbations, SPREAD), True),
        "spread dose 0.4": (dosed(config, 0.4, SPREAD), True),
    }
    raw = run_jobs(jobs, default_seeds(30), workers=8)
    control = {r["seed"]: r for r in raw["control"]}
    arm = {k: summarize(v, control) for k, v in raw.items() if k != "control"}

    spread = arm["spread only"]
    assert spread["bigger"] >= 27, spread
    assert spread["trade_bigger"] >= 27, spread  # executions agree, not just quotes
    assert spread["median_ratio"] >= 3.0, spread
    # More distance, more move: the dose is monotone between these two points.
    assert arm["spread dose 0.4"]["median_move"] < spread["median_move"]

    for name in ("limits only", "size only"):
        a = arm[name]
        assert 0.8 <= a["median_ratio"] <= 1.25, (name, a)
        assert a["sign_p"] > 0.05, (name, a)
    # ...even though cutting size removes most of the book near the price.
    assert arm["size only"]["depth_removed"] >= 0.70
