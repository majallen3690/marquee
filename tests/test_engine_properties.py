"""Hypothesis property suite for the matching engine (M1 gate).

Written against ADR-005/ADR-009 before the engine implementation. The core
device is a *shadow book*: the test rebuilds the expected book state purely
from ExecutionReports/CancelResults (never peeking at engine internals) and
asserts the engine's snapshot matches it exactly after every operation. On top
of that, targeted properties pin price-time priority, the maker price rule,
the conservation identity, and cancel semantics.
"""

from collections import defaultdict
from dataclasses import dataclass

from hypothesis import given, settings
from hypothesis import strategies as st

from marquee.engine import (
    CancelStatus,
    MatchingEngine,
    Order,
    OrderType,
    ReportStatus,
    SelfTradePolicy,
    Side,
)

PRICE_LO, PRICE_HI = 1, 60  # narrow band → heavy level reuse, matching, tombstones
QTY_HI = 50
AGENTS = 4


@dataclass(frozen=True)
class LimitOp:
    side: Side
    price: int
    qty: int
    agent: int


@dataclass(frozen=True)
class MarketOp:
    side: Side
    qty: int
    agent: int


@dataclass(frozen=True)
class CancelOp:
    target_index: int  # index into submitted-so-far order ids; may exceed → unknown id


sides = st.sampled_from([Side.BUY, Side.SELL])

limit_ops = st.builds(
    LimitOp,
    side=sides,
    price=st.integers(PRICE_LO, PRICE_HI),
    qty=st.integers(-2, QTY_HI),  # includes invalid qty <= 0 → REJECTED path
    agent=st.integers(0, AGENTS - 1),
)
market_ops = st.builds(
    MarketOp,
    side=sides,
    qty=st.integers(1, QTY_HI * 4),  # oversized → sweeps + IOC cancellation
    agent=st.integers(0, AGENTS - 1),
)
cancel_ops = st.builds(CancelOp, target_index=st.integers(0, 400))

op_sequences = st.lists(
    st.one_of(limit_ops, limit_ops, market_ops, cancel_ops),
    min_size=1,
    max_size=200,
)


class ShadowBook:
    """Expected state, reconstructed only from engine outputs."""

    def __init__(self) -> None:
        self.remaining: dict[int, int] = {}
        self.price: dict[int, int] = {}
        self.side: dict[int, Side] = {}

    def levels(self, side: Side) -> dict[int, int]:
        agg: dict[int, int] = defaultdict(int)
        for oid, rem in self.remaining.items():
            if self.side[oid] is side:
                agg[self.price[oid]] += rem
        return dict(agg)


def apply_and_check(engine: MatchingEngine, shadow: ShadowBook, order: Order) -> None:
    pre_best_opposite = engine.best_ask if order.side is Side.BUY else engine.best_bid
    report = engine.submit(order)

    # The report echoes the submitted order (agents interpret acks without
    # positional correlation).
    assert report.side is order.side
    assert report.price == order.price
    assert report.qty == order.qty

    # Conservation identity — universal, including rejections (ADR-009 rule 3).
    assert (
        report.qty
        == sum(f.qty for f in report.fills) + report.resting_qty + report.cancelled_qty
    )

    if report.status is ReportStatus.REJECTED:
        assert report.fills == ()
        assert report.resting_qty == 0
        assert report.cancelled_qty == order.qty
        return

    assert order.qty > 0
    assert report.resting_qty >= 0
    assert report.cancelled_qty >= 0
    if order.order_type is OrderType.MARKET:
        assert report.resting_qty == 0  # IOC never rests (ADR-009 rule 2)

    prev_price: int | None = None
    prev_maker_at_price: int = -1
    for fill in report.fills:
        assert fill.qty > 0
        assert fill.taker_order_id == order.order_id
        assert fill.taker_agent_id == order.agent_id
        assert fill.taker_side is order.side
        # Maker price rule (ADR-009 rule 1): fill price is the resting order's price.
        assert fill.price == shadow.price[fill.maker_order_id]
        # Price priority: fills walk away from the touch monotonically...
        if prev_price is not None:
            if order.side is Side.BUY:
                assert fill.price >= prev_price
            else:
                assert fill.price <= prev_price
        # ...and FIFO within a level: kernel ids are monotonic, so maker ids at
        # one price must strictly increase (earlier-submitted matched first).
        if fill.price == prev_price:
            assert fill.maker_order_id > prev_maker_at_price
        prev_maker_at_price = fill.maker_order_id
        prev_price = fill.price
        # Limit taker never trades through its own limit.
        if order.order_type is OrderType.LIMIT:
            if order.side is Side.BUY:
                assert fill.price <= order.price
            else:
                assert fill.price >= order.price
        # Update shadow: maker consumed.
        shadow.remaining[fill.maker_order_id] -= fill.qty
        assert shadow.remaining[fill.maker_order_id] >= 0
        if shadow.remaining[fill.maker_order_id] == 0:
            del shadow.remaining[fill.maker_order_id]

    # First fill must be at the pre-submit best opposite price (price priority).
    # Exception: CANCEL_RESTING may have removed the taker's own order(s) at the
    # touch first, so the first actual fill can be deeper — but never better.
    if report.fills:
        assert pre_best_opposite is not None
        if report.stp_cancelled:
            if order.side is Side.BUY:
                assert report.fills[0].price >= pre_best_opposite
            else:
                assert report.fills[0].price <= pre_best_opposite
        else:
            assert report.fills[0].price == pre_best_opposite

    for sc in report.stp_cancelled:
        assert sc.qty == shadow.remaining[sc.order_id]
        del shadow.remaining[sc.order_id]

    if report.resting_qty:
        shadow.remaining[order.order_id] = report.resting_qty
        shadow.price[order.order_id] = order.price
        shadow.side[order.order_id] = order.side


def check_book_state(engine: MatchingEngine, shadow: ShadowBook) -> None:
    snap = engine.snapshot(ts=0, depth=PRICE_HI + 8)
    # Never crossed, never negative (M1 gate invariants).
    if snap.best_bid is not None and snap.best_ask is not None:
        assert snap.best_bid < snap.best_ask
    for level in snap.bids + snap.asks:
        assert level.qty > 0
        assert level.order_count > 0
    # Exact match against the shadow book, both sides, all levels.
    assert {lv.price: lv.qty for lv in snap.bids} == shadow.levels(Side.BUY)
    assert {lv.price: lv.qty for lv in snap.asks} == shadow.levels(Side.SELL)


@settings(max_examples=200, deadline=None)
@given(ops=op_sequences, policy=st.sampled_from(list(SelfTradePolicy)))
def test_engine_invariants_hold_over_arbitrary_op_sequences(
    ops: list, policy: SelfTradePolicy
) -> None:
    engine = MatchingEngine(self_trade_policy=policy)
    shadow = ShadowBook()
    next_id = 1
    issued: list[int] = []

    for op in ops:
        if isinstance(op, LimitOp):
            order = Order(
                order_id=next_id,
                agent_id=op.agent,
                side=op.side,
                order_type=OrderType.LIMIT,
                price=op.price,
                qty=op.qty,
                ts=next_id,
            )
            issued.append(next_id)
            next_id += 1
            apply_and_check(engine, shadow, order)
        elif isinstance(op, MarketOp):
            order = Order(
                order_id=next_id,
                agent_id=op.agent,
                side=op.side,
                order_type=OrderType.MARKET,
                price=0,
                qty=op.qty,
                ts=next_id,
            )
            issued.append(next_id)
            next_id += 1
            apply_and_check(engine, shadow, order)
        else:
            if op.target_index < len(issued):
                target = issued[op.target_index]
                result = engine.cancel(target)
                if target in shadow.remaining:
                    # Live per our model → engine must agree, exactly.
                    assert result.status is CancelStatus.CANCELLED
                    assert result.removed_qty == shadow.remaining.pop(target)
                else:
                    assert result.status is CancelStatus.ALREADY_TERMINAL
                    assert result.removed_qty == 0
            else:
                bogus = next_id + 1000 + op.target_index
                result = engine.cancel(bogus)
                assert result.status is CancelStatus.UNKNOWN
                assert result.removed_qty == 0
        check_book_state(engine, shadow)

    # A cancelled/filled order must never fill later: exercised implicitly —
    # shadow deletes terminal orders, and any later fill naming them would
    # KeyError in shadow.price lookup above.


@settings(max_examples=100, deadline=None)
@given(ops=op_sequences)
def test_engine_is_a_pure_function_of_its_input_sequence(ops: list) -> None:
    """Two fresh engines fed the identical sequence produce identical outputs."""

    def run() -> list[str]:
        engine = MatchingEngine()
        out: list[str] = []
        next_id = 1
        issued: list[int] = []
        for op in ops:
            if isinstance(op, LimitOp | MarketOp):
                is_limit = isinstance(op, LimitOp)
                order = Order(
                    order_id=next_id,
                    agent_id=op.agent,
                    side=op.side,
                    order_type=OrderType.LIMIT if is_limit else OrderType.MARKET,
                    price=op.price if is_limit else 0,
                    qty=op.qty,
                    ts=next_id,
                )
                issued.append(next_id)
                next_id += 1
                out.append(repr(engine.submit(order)))
            elif op.target_index < len(issued):
                out.append(repr(engine.cancel(issued[op.target_index])))
        return out

    assert run() == run()
