"""M7 engine and kernel plumbing (RL_DESIGN §3, §5): queue position, the book without
one agent's orders, and a periodic decision clock. All read-only or additive; the
matching path and every existing seed's replay are unchanged (the determinism and
replay suites cover that)."""

from collections import defaultdict

from hypothesis import given, settings
from hypothesis import strategies as st

from marquee.engine import MatchingEngine, Order, OrderType
from marquee.engine.types import SelfTradePolicy, Side
from marquee.sim.kernel import SimKernel
from marquee.sim.protocols import SubmitLimit
from marquee.sim.recorder import ListRecorder


class Shadow:
    """Live orders reconstructed only from engine outputs. Priority is arrival
    order, and ids are strictly increasing, so 'ahead' = same level, smaller id."""

    def __init__(self) -> None:
        self.live: dict[int, tuple[int, Side, int, int]] = {}  # oid -> agent, side, px, rem

    def apply(self, order: Order, report) -> None:
        for f in report.fills:
            agent, side, px, rem = self.live[f.maker_order_id]
            if rem == f.qty:
                del self.live[f.maker_order_id]
            else:
                self.live[f.maker_order_id] = (agent, side, px, rem - f.qty)
        for sc in report.stp_cancelled:
            del self.live[sc.order_id]
        if report.resting_qty:
            self.live[order.order_id] = (
                order.agent_id,
                order.side,
                order.price,
                report.resting_qty,
            )

    def ahead(self, oid: int) -> int:
        _agent, side, px, _rem = self.live[oid]
        return sum(
            rem for o, (_a, s, p, rem) in self.live.items() if s is side and p == px and o < oid
        )

    def levels_without(self, agent: int, side: Side) -> dict[int, int]:
        out: dict[int, int] = defaultdict(int)
        for a, s, p, rem in self.live.values():
            if s is side and a != agent:
                out[p] += rem
        return dict(out)


ops = st.lists(
    st.tuples(
        st.sampled_from(["limit", "limit", "limit", "market", "cancel"]),
        st.integers(1, 3),  # agent
        st.sampled_from([Side.BUY, Side.SELL]),
        st.integers(95, 105),  # price
        st.integers(1, 20),  # qty
    ),
    min_size=1,
    max_size=120,
)


@settings(max_examples=150, deadline=None)
@given(ops=ops, policy=st.sampled_from([SelfTradePolicy.ALLOW, SelfTradePolicy.CANCEL_RESTING]))
def test_queue_ahead_and_book_without_an_agent_match_a_shadow(ops, policy) -> None:
    engine = MatchingEngine(self_trade_policy=policy)
    shadow = Shadow()
    oid = 0
    for kind, agent, side, price, qty in ops:
        if kind == "cancel":
            if shadow.live:
                victim = sorted(shadow.live)[price % len(shadow.live)]
                engine.cancel(victim)
                del shadow.live[victim]
        else:
            oid += 1
            order = Order(
                order_id=oid,
                agent_id=agent,
                side=side,
                order_type=OrderType.LIMIT if kind == "limit" else OrderType.MARKET,
                price=price if kind == "limit" else 0,
                qty=qty,
                ts=oid,
            )
            shadow.apply(order, engine.submit(order))

        for live_id in shadow.live:
            assert engine.queue_ahead(live_id) == shadow.ahead(live_id)
        for excluded in (1, 2, 3):
            snap = engine.snapshot_excluding(0, 5, excluded)
            for side_, levels in ((Side.BUY, snap.bids), (Side.SELL, snap.asks)):
                expect = shadow.levels_without(excluded, side_)
                best = sorted(expect, reverse=side_ is Side.BUY)[:5]
                assert [lv.price for lv in levels] == best
                assert [lv.qty for lv in levels] == [expect[p] for p in best]


def test_queue_ahead_is_what_must_trade_first() -> None:
    """Behavioural meaning, not just bookkeeping: a market order of exactly
    queue_ahead + 1 fills our order by one share."""
    engine = MatchingEngine()
    for i, (agent, qty) in enumerate([(1, 10), (2, 7), (3, 5)], start=1):
        engine.submit(Order(i, agent, Side.BUY, OrderType.LIMIT, 100, qty, i))
    assert engine.queue_ahead(3) == 17
    engine.cancel(2)
    assert engine.queue_ahead(3) == 10
    report = engine.submit(Order(4, 9, Side.SELL, OrderType.MARKET, 0, 11, 4))
    assert [(f.maker_order_id, f.qty) for f in report.fills] == [(1, 10), (3, 1)]
    assert engine.queue_ahead(3) == 0
    assert engine.queue_ahead(1) is None  # filled: not live
    assert engine.queue_ahead(999) is None


class _Probe:
    """Quotes once per wake and records what its context shows it."""

    def __init__(self, agent_id: int) -> None:
        self.agent_id = agent_id
        self.wakes: list[int] = []
        self.seen: list[tuple] = []
        self.oids: list[int] = []

    def on_wake(self, ctx):
        self.wakes.append(ctx.now)
        if self.oids:
            self.seen.append(
                (ctx.queue_ahead(self.oids[-1]), ctx.queue_ahead(1), ctx.book_excluding_self(3))
            )
        return [SubmitLimit(Side.BUY, 100, 5)]

    def on_order_ack(self, ctx, report):
        self.oids.append(report.order_id)
        return []

    def on_fill(self, ctx, fill):
        return []

    def on_cancel_ack(self, ctx, result):
        return []


def test_periodic_wakes_and_the_context_hide_other_agents_queues() -> None:
    kernel = SimKernel(
        master_seed=1, engine=MatchingEngine(), recorder=ListRecorder(), horizon_ns=1_000_000_000
    )
    other, me = _Probe(1), _Probe(2)
    kernel.register_agent(other, 7_000_000)  # Poisson wakes
    kernel.register_agent(me, 100_000_000, periodic=True)
    kernel.run()
    assert me.wakes == [100_000_000 * k for k in range(1, 11)]
    for own_ahead, foreign_ahead, ex_book in me.seen:
        assert own_ahead is not None and own_ahead >= 0
        assert foreign_ahead is None  # order 1 belongs to the other agent
        # without my own orders, the level holds only the other agent's shares
        assert all(lv.qty % 5 == 0 for lv in ex_book.bids)
