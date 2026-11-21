"""The M7 environment's guarantees (RL_DESIGN §4–5, ADR-023). Fast: short episodes."""

import dataclasses

import numpy as np
from gymnasium.utils.env_checker import check_env

from marquee.rl.accounting import liquidation_value
from marquee.rl.env import ENTRANT_ID, STEP_NS, EnvConfig, MarketMakingEnv

SHORT = EnvConfig(episode_steps=40, latency_jitter=0.0)
EP = {"master_seed": 4242, "start_step": 300, "latency_scale": 1.0}


def play(cfg: EnvConfig, actions, options=EP):
    env = MarketMakingEnv(cfg)
    env.reset(options=options)
    infos = []
    for a in actions:
        _obs, _r, _t, trunc, info = env.step(np.asarray(a))
        infos.append(info)
        if trunc:
            break
    return env, infos


def test_gymnasium_conformance() -> None:
    check_env(MarketMakingEnv(SHORT), skip_render_check=True)


def test_same_episode_replays_exactly() -> None:
    rng = np.random.default_rng(0)
    actions = [rng.integers([9, 9, 3]) for _ in range(SHORT.episode_steps)]
    _, a = play(SHORT, actions)
    _, b = play(SHORT, actions)
    assert a[-1]["episode"] == b[-1]["episode"]


def test_learned_and_rule_entrants_meet_the_same_market() -> None:
    """Paired by construction: identical public tape until the entrant arrives."""
    learned, _ = play(SHORT, [(2, 2, 2)])
    rule, _ = play(dataclasses.replace(SHORT, controller="rule"), [(0, 0, 0)])
    t0 = EP["start_step"] * STEP_NS

    def before(env):
        return [tr for tr in env.tape.trades if tr[0] < t0]

    assert len(before(learned)) > 100
    assert before(learned) == before(rule)


def test_pnl_is_wealth_change_with_terminal_inventory_walked_off() -> None:
    """Σ(S + I) telescopes to W_T − W_0: cash plus what the position fetches when
    sold into everyone else's book. The agent's own inventory agrees with the tape."""
    rng = np.random.default_rng(1)
    actions = [rng.integers([9, 9, 3]) for _ in range(SHORT.episode_steps)]
    env, infos = play(SHORT, actions)
    ep = infos[-1]["episode"]
    led = env.ledger
    wealth = led.cash + liquidation_value(env.engine, ENTRANT_ID, led.q, fallback=env.m)
    assert abs(ep["pnl"] - wealth) < 1e-6
    assert env.entrant.inventory == led.q
    assert ep["maker_volume"] > 0


def test_no_self_trades_and_quotes_never_cross_the_market() -> None:
    """Aggressive improving quotes on both sides: still no self-trade volume (G5),
    and the agent never takes liquidity except through the hard-limit rule."""
    _, infos = play(SHORT, [(0, 0, 2)] * SHORT.episode_steps)
    ep = infos[-1]["episode"]
    assert ep["self_trade_volume"] == 0
    assert ep["taker_volume"] == 0 or abs(ep["final_q"]) >= 360 - 80


def test_the_original_maker_leaves_the_seat() -> None:
    env, _ = play(SHORT, [(2, 2, 2)])
    assert env.engine.own_orders(EnvConfig().seat) == []
    assert env.engine.own_orders(ENTRANT_ID) != []


def test_ablation_switches_build() -> None:
    from marquee.engine.types import SelfTradePolicy

    for cfg in (
        dataclasses.replace(SHORT, stp=SelfTradePolicy.REJECT_TAKER),
        dataclasses.replace(SHORT, momentum_delta=-1),
        dataclasses.replace(SHORT, momentum_delta=1),
        dataclasses.replace(SHORT, mark="last_trade"),
        dataclasses.replace(SHORT, size_scale=0.5),
    ):
        _, infos = play(cfg, [(2, 2, 2)] * cfg.episode_steps)
        assert "episode" in infos[-1]


def test_submitted_two_sided_counts_decisions_not_resting_quotes() -> None:
    """ADR-024: the learned maker must submit both sides every step away from its
    limit; the rule-based controller does not expose decisions and reports None."""
    _, infos = play(SHORT, [(0, 0, 2)] * SHORT.episode_steps)
    ep = infos[-1]["episode"]
    assert ep["submitted_two_sided_frac"] == 1.0 or abs(ep["final_q"]) >= 360 - 80
    assert ep["submitted_two_sided_frac"] >= ep["two_sided_frac"]
    rule = dataclasses.replace(SHORT, controller="rule")
    _, infos = play(rule, [(0, 0, 0)] * rule.episode_steps)
    assert infos[-1]["episode"]["submitted_two_sided_frac"] is None
