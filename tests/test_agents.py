"""Agent-level unit tests (M3): quoting math, signal signs, intent validity."""

import numpy as np

from marquee.agents import InventoryMarketMaker, MomentumTrader, NoiseTrader
from marquee.engine.types import (
    BookSnapshot,
    Fill,
    LevelView,
    Side,
)
from marquee.sim.protocols import CancelIntent, SubmitLimit, SubmitMarket


class StubCtx:
    """Minimal AgentContext stand-in: fixed book, real seeded rng."""

    def __init__(self, best_bid: int | None, best_ask: int | None, seed: int = 7) -> None:
        self.now = 1_000_000_000
        self.rng = np.random.Generator(np.random.PCG64(seed))
        self._best_bid = best_bid
        self._best_ask = best_ask

    def set_book(self, best_bid: int | None, best_ask: int | None) -> None:
        self._best_bid = best_bid
        self._best_ask = best_ask

    def book(self, depth: int = 10) -> BookSnapshot:
        bids = (LevelView(self._best_bid, 50, 3),) if self._best_bid is not None else ()
        asks = (LevelView(self._best_ask, 50, 3),) if self._best_ask is not None else ()
        return BookSnapshot(ts=self.now, bids=bids, asks=asks)


def make_fill(qty: int, taker_side: Side) -> Fill:
    return Fill(
        trade_id=1, price=100, qty=qty, taker_order_id=5, maker_order_id=4,
        taker_agent_id=9, maker_agent_id=1, taker_side=taker_side, ts=0,
    )


def quotes_of(intents: list) -> dict[Side, SubmitLimit]:
    result = {}
    for intent in intents:
        if isinstance(intent, SubmitLimit):
            result[intent.side] = intent
    return result


# -- market maker -------------------------------------------------------------


def test_mm_quotes_two_sided_uncrossed_ints() -> None:
    mm = InventoryMarketMaker(1, half_spread=2)
    intents = mm.on_wake(StubCtx(9_998, 10_002))
    quotes = quotes_of(intents)
    assert set(quotes) == {Side.BUY, Side.SELL}
    bid, ask = quotes[Side.BUY], quotes[Side.SELL]
    assert type(bid.price) is int and type(ask.price) is int
    assert type(bid.qty) is int and type(ask.qty) is int
    assert bid.price < ask.price


def test_mm_inventory_skews_quotes_down_when_long_up_when_short() -> None:
    neutral = quotes_of(InventoryMarketMaker(1).on_wake(StubCtx(9_998, 10_002)))

    long_mm = InventoryMarketMaker(1, skew_per_unit=0.05)
    long_mm.inventory = 100
    long_quotes = quotes_of(long_mm.on_wake(StubCtx(9_998, 10_002)))
    assert long_quotes[Side.BUY].price < neutral[Side.BUY].price
    assert long_quotes[Side.SELL].price < neutral[Side.SELL].price

    short_mm = InventoryMarketMaker(1, skew_per_unit=0.05)
    short_mm.inventory = -100
    short_quotes = quotes_of(short_mm.on_wake(StubCtx(9_998, 10_002)))
    assert short_quotes[Side.BUY].price > neutral[Side.BUY].price
    assert short_quotes[Side.SELL].price > neutral[Side.SELL].price


def test_mm_hard_limit_pulls_risk_side_and_unwinds_excess() -> None:
    mm = InventoryMarketMaker(1, hard_limit=240)
    mm.inventory = 250  # 10 over the hard limit
    intents = mm.on_wake(StubCtx(9_998, 10_002))
    sides = {type(intent) for intent in intents}
    assert SubmitMarket in sides
    market_orders = [i for i in intents if isinstance(i, SubmitMarket)]
    assert market_orders == [SubmitMarket(Side.SELL, 10)]
    limits = [i for i in intents if isinstance(i, SubmitLimit)]
    assert all(limit.side is Side.SELL for limit in limits)  # no bid — no new risk


def test_mm_inventory_bookkeeping_maker_and_taker_legs() -> None:
    mm = InventoryMarketMaker(1)
    ctx = StubCtx(9_998, 10_002)
    # Maker leg: taker bought from us -> we are short 10.
    mm.on_fill(ctx, make_fill(10, Side.BUY))
    assert mm.inventory == -10
    # Maker leg: taker sold to us -> we gain 4.
    mm.on_fill(ctx, make_fill(4, Side.SELL))
    assert mm.inventory == -6


def test_mm_quotes_wide_around_anchor_on_empty_book() -> None:
    mm = InventoryMarketMaker(1, anchor_price=10_000, fallback_half_spread=6)
    quotes = quotes_of(mm.on_wake(StubCtx(None, None)))
    assert set(quotes) == {Side.BUY, Side.SELL}
    assert quotes[Side.BUY].price < 10_000 < quotes[Side.SELL].price


def test_mm_cancels_stale_quotes_on_wake() -> None:
    mm = InventoryMarketMaker(1)
    ctx = StubCtx(9_998, 10_002)
    mm._open_bids[77] = None
    mm._open_asks[78] = None
    intents = mm.on_wake(ctx)
    cancels = [i for i in intents if isinstance(i, CancelIntent)]
    assert {c.order_id for c in cancels} == {77, 78}


# -- momentum -----------------------------------------------------------------


def build_momentum() -> tuple[MomentumTrader, StubCtx]:
    trader = MomentumTrader(
        11, lookback_ns=10_000_000_000, threshold_ticks=2, act_pct=100, cooldown_wakes=0
    )
    return trader, StubCtx(9_998, 10_002)


def test_momentum_buys_uptrend_sells_downtrend() -> None:
    trader, ctx = build_momentum()
    assert trader.on_wake(ctx) == []  # first sample, no reference yet

    ctx.set_book(10_004, 10_008)  # mid up 6 ticks >= threshold
    intents = trader.on_wake(ctx)
    assert intents == [SubmitMarket(Side.BUY, trader._order_size)]

    trader2, ctx2 = build_momentum()
    trader2.on_wake(ctx2)
    ctx2.set_book(9_990, 9_994)  # mid down 8 ticks
    assert trader2.on_wake(ctx2) == [SubmitMarket(Side.SELL, trader2._order_size)]


def test_momentum_flat_no_action() -> None:
    trader, ctx = build_momentum()
    trader.on_wake(ctx)
    ctx.set_book(9_999, 10_001)  # mid moved 0 ticks (mid_x2 unchanged)
    assert trader.on_wake(ctx) == []


# -- noise --------------------------------------------------------------------


def test_noise_intents_always_wellformed() -> None:
    trader = NoiseTrader(21, anchor_price=10_000)
    ctx = StubCtx(9_998, 10_002, seed=3)
    seen_kinds = set()
    for _ in range(300):
        for intent in trader.on_wake(ctx):
            seen_kinds.add(type(intent))
            if isinstance(intent, SubmitLimit):
                assert type(intent.price) is int and intent.price >= 1
                assert type(intent.qty) is int and intent.qty >= 1
            elif isinstance(intent, SubmitMarket):
                assert type(intent.qty) is int and intent.qty >= 1
            else:
                assert isinstance(intent, CancelIntent)
    assert SubmitLimit in seen_kinds and SubmitMarket in seen_kinds
    assert len(trader._open) <= trader._max_open


def test_noise_improving_orders_stay_inside_spread() -> None:
    trader = NoiseTrader(21, improve_pct=100, market_pct=0, cancel_pct=0)
    ctx = StubCtx(9_990, 10_010, seed=5)
    for _ in range(100):
        for intent in trader.on_wake(ctx):
            assert isinstance(intent, SubmitLimit)
            assert 9_990 < intent.price < 10_010
