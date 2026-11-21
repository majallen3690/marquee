"""M8 plumbing (ADR-026): the lever reaches exactly the agents each arm says, the arms
share one market until the lever, and the pre-registered reading is what it says."""

import dataclasses

import numpy as np
import pytest

from marquee.rl.env import ENTRANT_ID, STEP_NS, EnvConfig, MarketMakingEnv
from marquee.rl.m8 import (
    LEVER_NS,
    M8_ENTRY_STEPS,
    M8_SCENARIO,
    M8_SEEDS,
    run_arm,
    verdict,
)

EP = {"master_seed": M8_SEEDS[0], "start_step": 200}


def played(lever: str, controller: str = "rule"):
    cfg = EnvConfig(scenario=M8_SCENARIO, controller=controller, latency_jitter=0.0, lever=lever)
    env = MarketMakingEnv(dataclasses.replace(cfg, record_mid=True))
    env.reset(options=EP)
    while True:
        *_, trunc, _info = env.step(np.array([2, 2, 2]))
        if trunc:
            return env


def test_the_lever_reaches_the_successor_only_in_the_all_arm() -> None:
    levered, holds, none = played("all"), played("others"), played("none")
    assert levered.entrant._hard_limit == 10 and levered.entrant._half_spread == 15
    assert holds.entrant._hard_limit == 360 and holds.entrant._half_spread == 3
    assert none.entrant._hard_limit == 360
    with pytest.raises(ValueError):
        MarketMakingEnv(EnvConfig(scenario=M8_SCENARIO, controller="learned", lever="all"))


def test_arms_share_one_market_until_the_lever() -> None:
    a, b, c = played("all"), played("others"), played("none")

    def before(env):
        return [t for t in env.tape.trades if t[0] < LEVER_NS]

    assert len(before(a)) > 100
    assert before(a) == before(b) == before(c)
    after = [t for t in a.tape.trades if t[0] >= LEVER_NS]
    assert after != [t for t in c.tape.trades if t[0] >= LEVER_NS]


def test_run_arm_measures_the_gate_window_and_the_entrant() -> None:
    r = run_arm(M8_SEEDS[0], 200, "rule, holds", None)
    assert r["lever_step"] == (LEVER_NS - 200 * STEP_NS) // STEP_NS == 100
    assert r["move"] != 0 and r["trade_move"] is not None
    assert r["spread_pre"] is not None and r["entrant_post_volume"] >= 0
    assert ENTRANT_ID == 3


def test_entry_steps_are_committed_and_land_the_lever_mid_episode() -> None:
    assert len(M8_SEEDS) == len(M8_ENTRY_STEPS) == 30
    assert M8_SEEDS[0] == 8_000_001
    lever_steps = [LEVER_NS // STEP_NS - s for s in M8_ENTRY_STEPS]
    assert min(lever_steps) >= 60 and max(lever_steps) <= 180
    assert len(set(lever_steps)) > 10  # not one memorizable step


def test_pre_registered_reading() -> None:
    soft = {"learned smaller": 25, "learned larger": 5, "sign_p": 0.0003, "ratio_ci": (0.4, 0.8)}
    deep = {"learned smaller": 5, "learned larger": 25, "sign_p": 0.0003, "ratio_ci": (1.3, 2.0)}
    mixed = {"learned smaller": 25, "learned larger": 5, "sign_p": 0.0003, "ratio_ci": (0.6, 1.1)}
    assert verdict(soft, "learned") == "softens"
    assert verdict(deep, "learned") == "deepens"
    assert verdict(mixed, "learned") == "no detectable difference"
