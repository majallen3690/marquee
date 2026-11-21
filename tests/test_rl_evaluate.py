"""The M7 judges are judged too: detectors, statistics and the committed episode sets."""

import math

from marquee.rl.evaluate import (
    HALF_LIFE_MAX_STEPS,
    HELD_OUT,
    HELD_OUT_2,
    HELD_OUT_3,
    HELD_OUT_4,
    TRAIN_EVAL,
    VALIDATION,
    VALIDATION_2,
    detectors,
    inventory_half_life,
    lead_collapse,
    paired,
    risk_adjusted,
)


def row(pnl=100.0, q_path=(0, 10, 5, 2, 1, 0), **kw) -> dict:
    base = {
        "pnl": pnl,
        "spread_capture": pnl,
        "inventory_pnl": 0.0,
        "abs_dW": abs(pnl) + 1,
        "maker_volume": 100,
        "taker_volume": 0,
        "maker_fills": 10,
        "self_trade_volume": 0,
        "two_sided_frac": 1.0,
        "submitted_two_sided_frac": 1.0,
        "median_spread": 4.0,
        "q_path": list(q_path),
    }
    base.update(kw)
    return base


def test_episode_sets_are_fixed_and_disjoint() -> None:
    sets = [TRAIN_EVAL, VALIDATION, HELD_OUT, HELD_OUT_2, HELD_OUT_3, VALIDATION_2, HELD_OUT_4]
    assert [len(s) for s in sets] == [40, 20, 40, 20, 40, 40, 40]
    seeds = [{e.master_seed for e in s} for s in sets]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            assert not seeds[i] & seeds[j]
    assert HELD_OUT[0].master_seed == 2_000_001  # committed, not drawn at runtime
    assert HELD_OUT_3[0].master_seed == 5_000_001


def test_a_clean_market_maker_passes_and_each_degeneracy_trips_its_detector() -> None:
    rule = [row() for _ in range(5)]
    clean = detectors([row() for _ in range(5)], rule, [row() for _ in range(5)])
    assert all(v["passed"] is not False for v in clean.values())

    def tripped(cand, key):
        return detectors(cand, rule)[key]["passed"] is False

    assert tripped([row(maker_fills=1)] * 5, "G1 fill rate vs rule")
    # G2 judges quotes submitted (ADR-024); fills that empty a side mid-step do not trip it
    assert tripped([row(submitted_two_sided_frac=0.9)] * 5, "G2 two-sided steps")
    assert not tripped([row(two_sided_frac=0.9)] * 5, "G2 two-sided steps")
    assert tripped([row(median_spread=20.0)] * 5, "G3 median spread vs rule")
    assert tripped([row(taker_volume=100)] * 5, "G4 maker share of volume")
    assert tripped([row(self_trade_volume=1)] * 5, "G5 self-trade volume")
    assert tripped([row(inventory_pnl=90.0)] * 5, "G6 directional P&L share")
    assert tripped([row(q_path=range(0, 300))] * 5, "G7 inventory half-life (steps)")
    # G10: worse held-out than training by more than a quarter
    g10 = detectors([row(pnl=50.0)] * 5, rule, [row(pnl=100.0)] * 5)
    assert g10["G10 held-out vs training seeds"]["passed"] is False
    # not applicable is reported as None, never as a pass
    assert clean["G8 no forgetting vs Stage-1 population"]["passed"] is None


def test_half_life_and_risk_adjustment() -> None:
    q = [100 * 0.5**k for k in range(40)]  # halves every step
    assert math.isclose(inventory_half_life([{"q_path": q}]), 1.0, rel_tol=1e-9)
    assert inventory_half_life([{"q_path": list(range(300))}]) > HALF_LIFE_MAX_STEPS
    assert risk_adjusted([{"pnl": 1.0}, {"pnl": 3.0}]) == 2.0 / math.sqrt(2)


def test_paired_counts_and_sign_test() -> None:
    a = [{"pnl": 2.0}] * 9 + [{"pnl": 0.0}]
    b = [{"pnl": 1.0}] * 10
    out = paired(a, b)
    assert (out["wins"], out["losses"]) == (9, 1)
    assert math.isclose(out["sign_p"], 22 / 1024)


def test_ablation_collapse_is_losing_the_lead_or_being_hurt_alone() -> None:
    def d(mean, ra):
        return {"mean_pnl": mean, "risk_adjusted": ra}

    main = d(100.0, 2.0)
    base_main = {"rule": d(-50.0, -0.5), "fixed": d(-10.0, -0.1)}
    # the whole market got harder, the policy kept its lead: not a collapse
    harder = {"rule": d(-200.0, -0.9), "fixed": d(-100.0, -0.3)}
    v = lead_collapse(d(40.0, 0.3), main, harder, base_main)
    assert v["below_half"] and not v["lost_lead"] and not v["collapsed"]
    # same ablation, but a baseline now out-scores the policy: collapse
    v = lead_collapse(d(40.0, 0.3), main, {**harder, "fixed": d(20.0, 0.5)}, base_main)
    assert v["lost_lead"] and v["collapsed"]
    # the policy halves while the baselines are untouched: collapse even with the lead
    v = lead_collapse(
        d(40.0, 0.3), main, {"rule": d(-50.0, -0.5), "fixed": d(-10.0, -0.1)}, base_main
    )
    assert not v["lost_lead"] and v["collapsed"]
    # a small dip with the lead kept: fine
    assert not lead_collapse(d(90.0, 1.8), main, base_main, base_main)["collapsed"]
