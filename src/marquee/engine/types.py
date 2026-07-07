"""Core typed vocabulary shared across engine, kernel, agents, and recorder.

Invariants (ADR-004): every price is an integer number of ticks, every quantity
is an integer number of units, every time is an integer number of nanoseconds
since sim epoch 0. No floats cross this boundary. Aliases document intent only;
runtime enforcement happens at the kernel and recorder chokepoints (ADR-003).

Matching semantics these types encode are pinned in ADR-009.
"""

from dataclasses import dataclass
from enum import IntEnum

# Integer-only domain types (ADR-004). Aliases document intent at signatures.
type Ticks = int
type Qty = int
type TimeNs = int
type OrderId = int
type TradeId = int
type AgentId = int


class Side(IntEnum):
    BUY = 0
    SELL = 1

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(IntEnum):
    LIMIT = 0
    MARKET = 1  # IOC: unfilled remainder is cancelled, never rested (ADR-009)


class ReportStatus(IntEnum):
    ACCEPTED = 0
    REJECTED = 1  # qty <= 0, or LIMIT price < 1 tick (ADR-009 rule 4)


class CancelStatus(IntEnum):
    CANCELLED = 0  # was live, now removed from the book
    ALREADY_TERMINAL = 1  # id was issued but order already filled/cancelled (benign race)
    UNKNOWN = 2  # id never issued — caller bug, fail loudly


class SelfTradePolicy(IntEnum):
    """Per-scenario config (ADR-009 rule 5). ALLOW is the Phase 1 default; the
    policy must be flippable without an engine interface change because
    self-trading is a documented RL reward-hacking vector (M6)."""

    ALLOW = 0
    CANCEL_RESTING = 1
    REJECT_TAKER = 2


@dataclass(frozen=True, slots=True)
class Order:
    """An order as submitted to the engine. price is ignored for MARKET orders.

    This is the boundary type only — the engine keeps its own mutable resting
    state internally (ADR-005 implementation note 1).
    """

    order_id: OrderId
    agent_id: AgentId
    side: Side
    order_type: OrderType
    price: Ticks
    qty: Qty
    ts: TimeNs


@dataclass(frozen=True, slots=True)
class Fill:
    """One trade: an aggressing (taker) order matched against a resting (maker)
    order. price is always the maker's resting price (ADR-009 rule 1). Both
    agent ids are carried so analysis can flag self-trade/wash volume."""

    trade_id: TradeId
    price: Ticks
    qty: Qty
    taker_order_id: OrderId
    maker_order_id: OrderId
    taker_agent_id: AgentId
    maker_agent_id: AgentId
    taker_side: Side
    ts: TimeNs


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    """Engine response to a submit.

    Conservation identity (ADR-009 rule 3), universal including rejections:
        order.qty == sum(f.qty for f in fills) + resting_qty + cancelled_qty
    REJECTED implies fills == (), resting_qty == 0, cancelled_qty == order.qty.
    """

    order_id: OrderId
    status: ReportStatus
    fills: tuple[Fill, ...]
    resting_qty: Qty  # remainder now resting on the book (LIMIT only)
    cancelled_qty: Qty  # remainder cancelled (market IOC remainder, or rejection)


@dataclass(frozen=True, slots=True)
class CancelResult:
    order_id: OrderId
    status: CancelStatus
    removed_qty: Qty  # quantity removed from the book (0 unless status is CANCELLED)


@dataclass(frozen=True, slots=True)
class LevelView:
    price: Ticks
    qty: Qty  # aggregate resting quantity at this level
    order_count: int  # live orders only (tombstones excluded)


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    """Read-only depth view. bids sorted best (highest) first, asks best (lowest) first."""

    ts: TimeNs
    bids: tuple[LevelView, ...]
    asks: tuple[LevelView, ...]

    @property
    def best_bid(self) -> Ticks | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Ticks | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid_x2(self) -> Ticks | None:
        """Twice the mid, kept integer (ADR-004). For comparison/logging ONLY.

        Never compute `mid_x2 // 2` in agent code — flooring on odd sums gives a
        systematic half-tick downward bias. Quote off best_bid/best_ask directly;
        the analysis layer halves this in exactly one float-permitted helper.
        """
        if not self.bids or not self.asks:
            return None
        return self.bids[0].price + self.asks[0].price

    @property
    def spread(self) -> Ticks | None:
        if not self.bids or not self.asks:
            return None
        return self.asks[0].price - self.bids[0].price
