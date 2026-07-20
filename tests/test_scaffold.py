"""M0 smoke tests: package wiring and boundary-type invariants."""

from marquee.engine import (
    BookSnapshot,
    CancelResult,
    CancelStatus,
    ExecutionReport,
    Fill,
    LevelView,
    Order,
    OrderType,
    ReportStatus,
    Side,
)
from marquee.sim import CancelIntent, SubmitLimit, SubmitMarket


def test_side_opposite() -> None:
    assert Side.BUY.opposite is Side.SELL
    assert Side.SELL.opposite is Side.BUY


def test_order_is_integer_domain() -> None:
    order = Order(
        order_id=1,
        agent_id=7,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=10_000,
        qty=100,
        ts=0,
    )
    assert isinstance(order.price, int)
    assert isinstance(order.qty, int)
    assert isinstance(order.ts, int)


def test_snapshot_spread_and_mid() -> None:
    snap = BookSnapshot(
        ts=0,
        bids=(LevelView(price=9_999, qty=500, order_count=3),),
        asks=(LevelView(price=10_001, qty=200, order_count=1),),
    )
    assert snap.best_bid == 9_999
    assert snap.best_ask == 10_001
    assert snap.spread == 2
    assert snap.mid_x2 == 20_000  # integer 2x-mid, no float mid (ADR-004)


def test_empty_book_snapshot() -> None:
    snap = BookSnapshot(ts=0, bids=(), asks=())
    assert snap.best_bid is None
    assert snap.best_ask is None
    assert snap.spread is None
    assert snap.mid_x2 is None


def test_intents_construct() -> None:
    assert SubmitLimit(side=Side.BUY, price=100, qty=10).qty == 10
    assert SubmitMarket(side=Side.SELL, qty=5).side is Side.SELL
    assert CancelIntent(order_id=42).order_id == 42


def test_execution_report_conservation_shape() -> None:
    """ADR-009 rule 3: qty == filled + resting + cancelled, universal incl. rejection."""
    fill = Fill(
        trade_id=1,
        price=10_000,
        qty=30,
        taker_order_id=2,
        maker_order_id=1,
        taker_agent_id=9,
        maker_agent_id=4,
        taker_side=Side.BUY,
        ts=1_000,
    )
    # Market IOC partially filled: 30 filled, 70 cancelled, nothing rests.
    report = ExecutionReport(
        order_id=2,
        status=ReportStatus.ACCEPTED,
        side=Side.BUY,
        price=0,
        qty=100,
        fills=(fill,),
        resting_qty=0,
        cancelled_qty=70,
    )
    submitted = report.qty
    assert submitted == sum(f.qty for f in report.fills) + report.resting_qty + report.cancelled_qty

    rejected = ExecutionReport(
        order_id=3,
        status=ReportStatus.REJECTED,
        side=Side.SELL,
        price=10,
        qty=50,
        fills=(),
        resting_qty=0,
        cancelled_qty=50,
    )
    total = sum(f.qty for f in rejected.fills) + rejected.resting_qty + rejected.cancelled_qty
    assert total == 50


def test_cancel_result_three_way_status() -> None:
    ok = CancelResult(order_id=1, status=CancelStatus.CANCELLED, removed_qty=25)
    race = CancelResult(order_id=1, status=CancelStatus.ALREADY_TERMINAL, removed_qty=0)
    bug = CancelResult(order_id=999, status=CancelStatus.UNKNOWN, removed_qty=0)
    assert ok.removed_qty == 25
    assert race.status is not bug.status  # benign race and caller bug are distinguishable


def test_fill_carries_both_parties() -> None:
    fill = Fill(
        trade_id=1,
        price=10_000,
        qty=50,
        taker_order_id=2,
        maker_order_id=1,
        taker_agent_id=9,
        maker_agent_id=4,
        taker_side=Side.BUY,
        ts=1_000,
    )
    assert fill.maker_agent_id != fill.taker_agent_id
