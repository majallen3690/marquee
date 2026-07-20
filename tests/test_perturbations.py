"""Perturbation-path unit tests (ADR-010 wiring, M5 core)."""

import numpy as np
import pytest

from marquee.agents import InventoryMarketMaker, MomentumTrader, NoiseTrader
from marquee.engine import MatchingEngine, Side
from marquee.engine.types import ExecutionReport, Fill, ReportStatus
from marquee.sim import ListRecorder, SimKernel, SubmitLimit, SubmitMarket
from tests.test_agents import StubCtx


def make_kernel(recorder: ListRecorder) -> SimKernel:
    return SimKernel(
        master_seed=5,
        engine=MatchingEngine(),
        recorder=recorder,
        horizon_ns=100_000_000,
        agent_to_exchange_ns=1_000,
        exchange_to_agent_ns=1_000,
    )


def test_schedule_validation_rules() -> None:
    rec = ListRecorder()
    kernel = make_kernel(rec)
    mm = InventoryMarketMaker(1)
    noise = NoiseTrader(2)
    kernel.register_agent(mm, 10_000_000)
    kernel.register_agent(noise, 10_000_000)

    with pytest.raises(ValueError, match="unknown agent_id"):
        kernel.schedule_perturbation(50, 99, "hard_limit", 10)
    with pytest.raises(TypeError, match="does not implement"):
        kernel.schedule_perturbation(50, 2, "hard_limit", 10)  # noise: not Perturbable
    with pytest.raises(TypeError, match="built-in int"):
        kernel.schedule_perturbation(50, 1, "hard_limit", 10.0)

    # Pre-run scheduling at any future time is fine.
    kernel.schedule_perturbation(50, 1, "hard_limit", 10)
    kernel.run()
    assert any(e["k"] == "prt" for e in rec.events)
    assert mm._hard_limit == 10  # actually applied

    # Once the clock has advanced, effective time must be strictly later.
    with pytest.raises(ValueError, match="strictly after"):
        kernel.schedule_perturbation(kernel.now, 1, "soft_limit", 5)


def test_mm_unknown_param_is_loud() -> None:
    mm = InventoryMarketMaker(1)
    with pytest.raises(ValueError, match="unknown market-maker perturbation"):
        mm.apply_perturbation("banana", 3)


def test_mm_perturbed_hard_limit_forces_unwind_next_wake() -> None:
    mm = InventoryMarketMaker(1, hard_limit=300)
    mm.inventory = 80  # comfortably inside the original limit
    mm.apply_perturbation("hard_limit", 10)
    intents = mm.on_wake(StubCtx(9_998, 10_002))
    markets = [i for i in intents if isinstance(i, SubmitMarket)]
    assert markets == [SubmitMarket(Side.SELL, 70)]  # excess over the new limit
    limits = [i for i in intents if isinstance(i, SubmitLimit)]
    assert all(quote.side is Side.SELL for quote in limits)  # bid pulled


def test_momentum_position_cap_blocks_one_direction() -> None:
    trader = MomentumTrader(
        11, lookback_ns=10_000_000_000, threshold_ticks=2,
        act_pct=100, cooldown_wakes=0, max_position=50,
    )
    ctx = StubCtx(9_998, 10_002)
    trader.on_wake(ctx)  # first sample
    trader.position = 50  # at the cap
    ctx.set_book(10_010, 10_014)  # strong up signal
    assert trader.on_wake(ctx) == []  # long side blocked
    ctx.set_book(9_980, 9_984)  # strong down signal
    assert trader.on_wake(ctx) != []  # short side still allowed


def test_momentum_tracks_position_from_ack_fills() -> None:
    trader = MomentumTrader(11)
    fill = Fill(
        trade_id=1, price=100, qty=30, taker_order_id=9, maker_order_id=8,
        taker_agent_id=11, maker_agent_id=1, taker_side=Side.BUY, ts=0,
    )
    report = ExecutionReport(
        order_id=9, status=ReportStatus.ACCEPTED, side=Side.BUY, price=0, qty=30,
        fills=(fill,), resting_qty=0, cancelled_qty=0,
    )
    trader.on_order_ack(StubCtx(99, 101), report)
    assert trader.position == 30


def test_noise_anchoring_biases_flow_toward_anchor() -> None:
    # Mid 400 ticks above anchor; weight 0.0005 * 800 (x2) = 0.4 -> clamped
    # to +0.25 sell bias: expect ~75% sells.
    trader = NoiseTrader(
        21, anchor_price=10_000, anchor_weight=0.0005,
        cancel_pct=0, market_pct=100, improve_pct=0,
    )
    ctx = StubCtx(10_398, 10_402, seed=11)
    sells = 0
    n = 400
    for _ in range(n):
        (intent,) = trader.on_wake(ctx)
        assert isinstance(intent, SubmitMarket)
        if intent.side is Side.SELL:
            sells += 1
    assert sells / n > 0.65  # decisively sell-biased, not a coin flip
