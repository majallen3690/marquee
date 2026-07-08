"""Price-time priority matching engine (ADR-005 structures, ADR-009 semantics).

Pure library: a deterministic function of its input sequence. No clock, no I/O,
no randomness. The kernel assigns order ids (dense, monotonic); the engine
validates strict increase and raises on violation.

Internal representation notes (binding, from the M0 adversarial review):
- Liveness is orders-dict membership. Cancels delete the dict entry in O(1);
  the id left behind in its level's deque is a tombstone, skipped (and popped)
  when it surfaces during matching.
- Levels compact their deques when tombstones outnumber live orders, so a
  market maker re-quoting behind the touch cannot accumulate unbounded dead
  entries on levels that never trade.
- Each side's best-price heap holds at most one entry per tick (in_heap set,
  used for O(1) membership only — never iterated), and rebuilds itself when
  stale entries outnumber live levels. All maintenance is a pure function of
  book contents, so replay is unaffected.
"""

import heapq
from collections import deque

from marquee.engine.types import (
    BookSnapshot,
    CancelResult,
    CancelStatus,
    ExecutionReport,
    Fill,
    LevelView,
    Order,
    OrderId,
    OrderType,
    ReportStatus,
    SelfTradePolicy,
    Side,
    StpCancel,
    Ticks,
    TimeNs,
)

# A level's deque is rebuilt when dead > live and dead > this floor; below the
# floor, rebuild bookkeeping costs more than the tombstones it would reclaim.
_COMPACT_FLOOR = 16


class _Resting:
    """Engine-internal mutable resting-order state (never crosses the boundary)."""

    __slots__ = ("order_id", "agent_id", "side", "price", "remaining")

    def __init__(self, order_id: int, agent_id: int, side: Side, price: int, remaining: int):
        self.order_id = order_id
        self.agent_id = agent_id
        self.side = side
        self.price = price
        self.remaining = remaining


class _Level:
    __slots__ = ("price", "queue", "qty", "live", "dead")

    def __init__(self, price: int) -> None:
        self.price = price
        self.queue: deque[int] = deque()
        self.qty = 0  # aggregate live resting quantity
        self.live = 0  # live order count
        self.dead = 0  # tombstone count (cancelled ids still in queue)


class _BookSide:
    """One side: levels dict + lazy min-heap of ticks (bids stored negated)."""

    __slots__ = ("levels", "heap", "in_heap", "stale", "is_bid")

    def __init__(self, is_bid: bool) -> None:
        self.levels: dict[int, _Level] = {}
        self.heap: list[int] = []
        self.in_heap: set[int] = set()  # ticks with an entry in heap; membership only
        self.stale = 0  # heap entries whose level no longer exists
        self.is_bid = is_bid

    def best(self) -> int | None:
        """Best tick, cleaning stale heap entries lazily. Amortized O(1)."""
        heap = self.heap
        levels = self.levels
        while heap:
            tick = -heap[0] if self.is_bid else heap[0]
            if tick in levels:
                return tick
            heapq.heappop(heap)
            self.in_heap.discard(tick)
            if self.stale:
                self.stale -= 1
        return None

    def get_or_create(self, tick: int) -> _Level:
        level = self.levels.get(tick)
        if level is None:
            level = _Level(tick)
            self.levels[tick] = level
            if tick in self.in_heap:
                # A stale entry for this tick just became valid again.
                if self.stale:
                    self.stale -= 1
            else:
                heapq.heappush(self.heap, -tick if self.is_bid else tick)
                self.in_heap.add(tick)
        return level

    def drop_level(self, tick: int) -> None:
        del self.levels[tick]
        if tick in self.in_heap:
            self.stale += 1
            if self.stale > len(self.levels):
                self._rebuild()

    def _rebuild(self) -> None:
        ticks = list(self.levels.keys())  # dict order: insertion — deterministic
        self.heap = [-t for t in ticks] if self.is_bid else ticks.copy()
        heapq.heapify(self.heap)
        self.in_heap = set(ticks)
        self.stale = 0


class MatchingEngine:
    """Limit order book with price-time priority matching.

    submit / cancel / snapshot per ADR-007. Self-trade handling per ADR-009
    rule 5; the policy is fixed per engine instance (scenario config).
    """

    def __init__(self, self_trade_policy: SelfTradePolicy = SelfTradePolicy.ALLOW) -> None:
        self._policy = self_trade_policy
        self._orders: dict[int, _Resting] = {}  # live orders only: membership == liveness
        self._bids = _BookSide(is_bid=True)
        self._asks = _BookSide(is_bid=False)
        self._max_order_id = 0
        self._next_trade_id = 1

    @property
    def best_bid(self) -> Ticks | None:
        return self._bids.best()

    @property
    def best_ask(self) -> Ticks | None:
        return self._asks.best()

    def submit(self, order: Order) -> ExecutionReport:
        oid = order.order_id
        if oid <= self._max_order_id:
            raise ValueError(
                f"order ids must be strictly increasing: got {oid}, "
                f"already saw {self._max_order_id}"
            )
        self._max_order_id = oid  # even rejected ids count as issued (ADR-009 rule 6)

        qty = order.qty
        is_limit = order.order_type is OrderType.LIMIT
        if qty <= 0 or (is_limit and order.price < 1):
            return ExecutionReport(
                order_id=oid,
                status=ReportStatus.REJECTED,
                fills=(),
                resting_qty=0,
                cancelled_qty=qty,
            )

        is_buy = order.side is Side.BUY
        opposite = self._asks if is_buy else self._bids
        orders = self._orders
        policy = self._policy
        taker_agent = order.agent_id
        limit = order.price
        remaining = qty
        fills: list[Fill] = []
        stp_cancelled: list[StpCancel] = []
        stop_taker = False  # REJECT_TAKER tripped: cancel the unfilled remainder

        while remaining > 0 and not stop_taker:
            best_tick = opposite.best()
            if best_tick is None:
                break
            if is_limit and (best_tick > limit if is_buy else best_tick < limit):
                break
            level = opposite.levels[best_tick]
            queue = level.queue
            while remaining > 0 and queue:
                maker_id = queue[0]
                maker = orders.get(maker_id)
                if maker is None:  # tombstone
                    queue.popleft()
                    level.dead -= 1
                    continue
                if maker.agent_id == taker_agent and policy is not SelfTradePolicy.ALLOW:
                    if policy is SelfTradePolicy.REJECT_TAKER:
                        stop_taker = True
                        break
                    # CANCEL_RESTING: remove own resting order, keep matching.
                    queue.popleft()
                    del orders[maker_id]
                    level.qty -= maker.remaining
                    level.live -= 1
                    stp_cancelled.append(StpCancel(maker_id, maker.agent_id, maker.remaining))
                    continue
                traded = maker.remaining if maker.remaining < remaining else remaining
                fills.append(
                    Fill(
                        trade_id=self._next_trade_id,
                        price=best_tick,  # maker price rule (ADR-009 rule 1)
                        qty=traded,
                        taker_order_id=oid,
                        maker_order_id=maker_id,
                        taker_agent_id=taker_agent,
                        maker_agent_id=maker.agent_id,
                        taker_side=order.side,
                        ts=order.ts,
                    )
                )
                self._next_trade_id += 1
                remaining -= traded
                maker.remaining -= traded
                level.qty -= traded
                if maker.remaining == 0:
                    queue.popleft()
                    del orders[maker_id]
                    level.live -= 1
            if level.live == 0:
                # Only tombstones (if anything) left; drop the whole level.
                opposite.drop_level(best_tick)

        resting = 0
        cancelled = 0
        if remaining > 0:
            if is_limit and not stop_taker:
                book = self._bids if is_buy else self._asks
                level = book.get_or_create(limit)
                level.queue.append(oid)
                level.qty += remaining
                level.live += 1
                orders[oid] = _Resting(oid, taker_agent, order.side, limit, remaining)
                resting = remaining
            else:
                cancelled = remaining  # market IOC remainder, or REJECT_TAKER stop

        return ExecutionReport(
            order_id=oid,
            status=ReportStatus.ACCEPTED,
            fills=tuple(fills),
            resting_qty=resting,
            cancelled_qty=cancelled,
            stp_cancelled=tuple(stp_cancelled),
        )

    def cancel(self, order_id: OrderId) -> CancelResult:
        resting = self._orders.get(order_id)
        if resting is None:
            if 0 < order_id <= self._max_order_id:
                return CancelResult(order_id, CancelStatus.ALREADY_TERMINAL, 0)
            return CancelResult(order_id, CancelStatus.UNKNOWN, 0)

        del self._orders[order_id]
        side = self._bids if resting.side is Side.BUY else self._asks
        level = side.levels[resting.price]
        level.qty -= resting.remaining
        level.live -= 1
        level.dead += 1
        if level.live == 0:
            side.drop_level(resting.price)
        elif level.dead > level.live and level.dead > _COMPACT_FLOOR:
            orders = self._orders
            level.queue = deque(x for x in level.queue if x in orders)
            level.dead = 0
        return CancelResult(order_id, CancelStatus.CANCELLED, resting.remaining)

    def snapshot(self, ts: TimeNs, depth: int = 10) -> BookSnapshot:
        if depth == 1:
            # O(1) amortized L1 fast path (ADR-005): agents poll this on every
            # wake; nlargest/nsmallest below scan all levels.
            best_bid = self._bids.best()
            best_ask = self._asks.best()
            bids = ()
            asks = ()
            if best_bid is not None:
                level = self._bids.levels[best_bid]
                bids = (LevelView(price=best_bid, qty=level.qty, order_count=level.live),)
            if best_ask is not None:
                level = self._asks.levels[best_ask]
                asks = (LevelView(price=best_ask, qty=level.qty, order_count=level.live),)
            return BookSnapshot(ts=ts, bids=bids, asks=asks)
        bid_levels = self._bids.levels
        ask_levels = self._asks.levels
        bids = tuple(
            LevelView(price=t, qty=bid_levels[t].qty, order_count=bid_levels[t].live)
            for t in heapq.nlargest(depth, bid_levels)
        )
        asks = tuple(
            LevelView(price=t, qty=ask_levels[t].qty, order_count=ask_levels[t].live)
            for t in heapq.nsmallest(depth, ask_levels)
        )
        return BookSnapshot(ts=ts, bids=bids, asks=asks)
