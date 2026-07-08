"""Limit order book and matching engine.

Pure library: deterministic function of its input event sequence. Knows nothing
of simulation time, agents, or I/O — timestamps are passed in by the caller.
See DECISIONS.md ADR-004 (integer prices), ADR-005 (data structures), ADR-007
(boundaries).
"""

from marquee.engine.book import MatchingEngine
from marquee.engine.types import (
    AgentId,
    BookSnapshot,
    CancelResult,
    CancelStatus,
    ExecutionReport,
    Fill,
    LevelView,
    Order,
    OrderId,
    OrderType,
    Qty,
    ReportStatus,
    SelfTradePolicy,
    Side,
    StpCancel,
    Ticks,
    TimeNs,
    TradeId,
)

__all__ = [
    "AgentId",
    "BookSnapshot",
    "CancelResult",
    "CancelStatus",
    "ExecutionReport",
    "Fill",
    "LevelView",
    "MatchingEngine",
    "Order",
    "OrderId",
    "OrderType",
    "Qty",
    "ReportStatus",
    "SelfTradePolicy",
    "Side",
    "StpCancel",
    "Ticks",
    "TimeNs",
    "TradeId",
]
