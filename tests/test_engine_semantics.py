"""Example-based tests pinning each ADR-009 rule to a concrete scenario."""

import pytest

from marquee.engine import (
    CancelStatus,
    MatchingEngine,
    Order,
    OrderType,
    ReportStatus,
    SelfTradePolicy,
    Side,
    StpCancel,
)

_id_counter = 0


def order(
    side: Side,
    qty: int,
    price: int = 0,
    order_type: OrderType = OrderType.LIMIT,
    agent: int = 1,
    oid: int | None = None,
) -> Order:
    global _id_counter
    _id_counter += 1
    return Order(
        order_id=oid if oid is not None else _id_counter,
        agent_id=agent,
        side=side,
        order_type=order_type,
        price=price,
        qty=qty,
        ts=_id_counter,
    )


@pytest.fixture(autouse=True)
def _reset_ids() -> None:
    global _id_counter
    _id_counter = 0


def test_maker_price_rule_crossed_limit() -> None:
    """A limit buy at 105 hitting a resting ask at 100 prints at 100."""
    eng = MatchingEngine()
    eng.submit(order(Side.SELL, qty=10, price=100, agent=1))
    report = eng.submit(order(Side.BUY, qty=10, price=105, agent=2))
    assert len(report.fills) == 1
    assert report.fills[0].price == 100


def test_marketable_limit_walks_levels_and_rests_remainder_at_own_price() -> None:
    eng = MatchingEngine()
    eng.submit(order(Side.SELL, qty=5, price=100, agent=1))
    eng.submit(order(Side.SELL, qty=5, price=101, agent=1))
    eng.submit(order(Side.SELL, qty=5, price=106, agent=1))  # beyond taker limit
    report = eng.submit(order(Side.BUY, qty=20, price=105, agent=2))
    assert [f.price for f in report.fills] == [100, 101]
    assert sum(f.qty for f in report.fills) == 10
    assert report.resting_qty == 10
    assert eng.best_bid == 105  # remainder rests at the taker's own limit
    assert eng.best_ask == 106


def test_market_order_is_ioc_partial() -> None:
    eng = MatchingEngine()
    eng.submit(order(Side.SELL, qty=30, price=100, agent=1))
    report = eng.submit(order(Side.BUY, qty=100, order_type=OrderType.MARKET, agent=2))
    assert sum(f.qty for f in report.fills) == 30
    assert report.resting_qty == 0
    assert report.cancelled_qty == 70
    assert eng.best_ask is None  # book swept, nothing rested


def test_market_order_into_empty_book_cancels_in_full() -> None:
    eng = MatchingEngine()
    report = eng.submit(order(Side.BUY, qty=50, order_type=OrderType.MARKET))
    assert report.status is ReportStatus.ACCEPTED  # defined outcome, not an error
    assert report.fills == ()
    assert report.cancelled_qty == 50


def test_validation_rejects_bad_qty_and_price() -> None:
    eng = MatchingEngine()
    r1 = eng.submit(order(Side.BUY, qty=0, price=100))
    r2 = eng.submit(order(Side.BUY, qty=-5, price=100))
    r3 = eng.submit(order(Side.BUY, qty=10, price=0))
    for r in (r1, r2, r3):
        assert r.status is ReportStatus.REJECTED
        assert r.fills == ()
        assert r.resting_qty == 0
    snap = eng.snapshot(ts=0)
    assert snap.bids == () and snap.asks == ()  # book untouched


def test_fifo_within_level() -> None:
    eng = MatchingEngine()
    first = order(Side.SELL, qty=10, price=100, agent=1)
    second = order(Side.SELL, qty=10, price=100, agent=2)
    eng.submit(first)
    eng.submit(second)
    report = eng.submit(order(Side.BUY, qty=15, price=100, agent=3))
    assert [f.maker_order_id for f in report.fills] == [first.order_id, second.order_id]
    assert [f.qty for f in report.fills] == [10, 5]


def test_cancelled_order_never_fills_and_cancel_statuses() -> None:
    eng = MatchingEngine()
    resting = order(Side.SELL, qty=10, price=100)
    eng.submit(resting)
    result = eng.cancel(resting.order_id)
    assert result.status is CancelStatus.CANCELLED
    assert result.removed_qty == 10

    again = eng.cancel(resting.order_id)
    assert again.status is CancelStatus.ALREADY_TERMINAL

    unknown = eng.cancel(99_999)
    assert unknown.status is CancelStatus.UNKNOWN

    report = eng.submit(order(Side.BUY, qty=10, price=100, agent=2))
    assert report.fills == ()  # nothing to match — the cancel really removed it
    assert report.resting_qty == 10


def test_cancel_partially_filled_order_removes_remainder_only() -> None:
    eng = MatchingEngine()
    resting = order(Side.SELL, qty=10, price=100, agent=1)
    eng.submit(resting)
    eng.submit(order(Side.BUY, qty=4, price=100, agent=2))
    result = eng.cancel(resting.order_id)
    assert result.status is CancelStatus.CANCELLED
    assert result.removed_qty == 6


def test_self_trade_allow_executes_with_both_ids() -> None:
    eng = MatchingEngine(self_trade_policy=SelfTradePolicy.ALLOW)
    eng.submit(order(Side.SELL, qty=10, price=100, agent=7))
    report = eng.submit(order(Side.BUY, qty=10, price=100, agent=7))
    assert len(report.fills) == 1
    assert report.fills[0].maker_agent_id == report.fills[0].taker_agent_id == 7


def test_self_trade_reject_taker_cancels_remainder_keeps_resting() -> None:
    eng = MatchingEngine(self_trade_policy=SelfTradePolicy.REJECT_TAKER)
    other = order(Side.SELL, qty=5, price=99, agent=1)
    own = order(Side.SELL, qty=10, price=100, agent=7)
    eng.submit(other)
    eng.submit(own)
    report = eng.submit(order(Side.BUY, qty=20, price=105, agent=7))
    # Fills the stranger at 99, then meets its own order and stops.
    assert [f.price for f in report.fills] == [99]
    assert report.cancelled_qty == 15
    assert report.resting_qty == 0
    assert eng.best_ask == 100  # own resting order untouched


def test_self_trade_cancel_resting_removes_own_and_keeps_matching() -> None:
    eng = MatchingEngine(self_trade_policy=SelfTradePolicy.CANCEL_RESTING)
    own = order(Side.SELL, qty=5, price=100, agent=7)
    other = order(Side.SELL, qty=5, price=100, agent=1)
    eng.submit(own)
    eng.submit(other)
    report = eng.submit(order(Side.BUY, qty=5, price=100, agent=7))
    assert report.stp_cancelled == (StpCancel(order_id=own.order_id, agent_id=7, qty=5),)
    assert [f.maker_agent_id for f in report.fills] == [1]  # matched the stranger
    assert eng.cancel(own.order_id).status is CancelStatus.ALREADY_TERMINAL


def test_order_ids_must_strictly_increase() -> None:
    eng = MatchingEngine()
    eng.submit(order(Side.BUY, qty=1, price=10, oid=5))
    with pytest.raises(ValueError):
        eng.submit(order(Side.BUY, qty=1, price=10, oid=5))
    with pytest.raises(ValueError):
        eng.submit(order(Side.BUY, qty=1, price=10, oid=3))


def test_rejected_order_id_is_still_issued_for_cancel_purposes() -> None:
    eng = MatchingEngine()
    rejected = order(Side.BUY, qty=0, price=10)
    eng.submit(rejected)
    assert eng.cancel(rejected.order_id).status is CancelStatus.ALREADY_TERMINAL


def test_snapshot_depth_one_fast_path_matches_general_path() -> None:
    """The O(1) L1 fast path must agree with the nlargest/nsmallest path,
    including empty and one-sided books."""
    eng = MatchingEngine()

    def l1_pair(engine: MatchingEngine) -> tuple:
        fast = engine.snapshot(ts=0, depth=1)
        general = engine.snapshot(ts=0, depth=10)
        return fast, general

    fast, general = l1_pair(eng)  # empty book
    assert fast.bids == () and fast.asks == ()

    eng.submit(order(Side.BUY, qty=10, price=99))  # one-sided
    fast, general = l1_pair(eng)
    assert fast.bids == general.bids[:1]
    assert fast.asks == ()

    eng.submit(order(Side.BUY, qty=5, price=98))
    eng.submit(order(Side.SELL, qty=7, price=101))
    eng.submit(order(Side.SELL, qty=3, price=101))  # two orders, same level
    fast, general = l1_pair(eng)
    assert fast.bids == general.bids[:1]
    assert fast.asks == general.asks[:1]
    assert fast.asks[0].qty == 10 and fast.asks[0].order_count == 2
