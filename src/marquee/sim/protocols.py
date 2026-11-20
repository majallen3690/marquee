"""Typed boundaries between kernel, agents, and recorder (ADR-007).

Agents return *intents*; the kernel assigns order ids, applies latency, routes
to the engine, and records everything. Agents never hold engine references.

Market data is pull-based: agents call ctx.book(depth) inside their callbacks.
There is no per-event push of snapshots to N agents (ADR-007).
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from marquee.engine.types import (
    AgentId,
    BookSnapshot,
    CancelResult,
    ExecutionReport,
    Fill,
    OrderId,
    Qty,
    Side,
    Ticks,
    TimeNs,
)


@dataclass(frozen=True, slots=True)
class SubmitLimit:
    side: Side
    price: Ticks
    qty: Qty


@dataclass(frozen=True, slots=True)
class SubmitMarket:
    side: Side
    qty: Qty


@dataclass(frozen=True, slots=True)
class CancelIntent:
    order_id: OrderId


type Intent = SubmitLimit | SubmitMarket | CancelIntent


class AgentContext(Protocol):
    """Read-only view handed to an agent on every callback.

    rng is the agent's private seeded stream (ADR-006) — the only sanctioned
    source of randomness in agent code. Draws that feed intents must be
    converted to built-in int at the draw site (ADR-003).
    """

    @property
    def now(self) -> TimeNs: ...

    @property
    def rng(self) -> np.random.Generator: ...

    def book(self, depth: int = 10) -> BookSnapshot: ...

    def book_excluding_self(self, depth: int = 10) -> BookSnapshot:
        """The book without this agent's own resting orders (M7)."""
        ...

    def queue_ahead(self, order_id: OrderId) -> int | None:
        """Quantity ahead of one of this agent's own live orders, else None (M7)."""
        ...


@runtime_checkable
class Agent(Protocol):
    """Wake/act/observe lifecycle. All methods return intents; [] means no action.

    on_order_ack closes the id loop: the kernel assigns order ids, and the ack
    (delivered under the same latency model as fills) is how an agent learns the
    id of its own resting order — without it, cancelling a stale quote is
    impossible (ADR-007).

    on_fill fires for the MAKER side of a trade; the taker sees its fills inside
    its own ExecutionReport ack. In a self-trade under ALLOW both fire for the
    same agent (taker leg + maker leg), so inventory bookkeeping nets to zero
    without special-casing.

    on_cancel_ack delivers the result of the agent's own CancelIntent, and also
    fires when self-trade prevention (CANCEL_RESTING) removes one of the agent's
    resting orders (ADR-011).
    """

    @property
    def agent_id(self) -> AgentId: ...

    def on_wake(self, ctx: AgentContext) -> list[Intent]: ...

    def on_order_ack(self, ctx: AgentContext, report: ExecutionReport) -> list[Intent]: ...

    def on_fill(self, ctx: AgentContext, fill: Fill) -> list[Intent]: ...

    def on_cancel_ack(self, ctx: AgentContext, result: CancelResult) -> list[Intent]: ...


@runtime_checkable
class Perturbable(Protocol):
    """Agents that accept mid-run parameter changes (ADR-010). Unknown params
    must raise ValueError — a perturbation silently ignored would desync the
    demo narrative from reality."""

    def apply_perturbation(self, param: str, value: int) -> None: ...


@runtime_checkable
class Recorder(Protocol):
    """Sink for the kernel's event stream. JSONL writer in M2; the same stream
    fans out to the WebSocket bridge in M5 (one producer, two sinks).

    Lines arrive pre-serialized in the exact ADR-006 canonical form — the
    kernel builds them with the fixed-schema fmt_* helpers in
    marquee.sim.recorder, which enforce the built-in-int contract before any
    byte is produced. Events go to events.jsonl, fills to trades.jsonl."""

    def record_line(self, line: str) -> None: ...

    def record_trade_line(self, line: str) -> None: ...

    def close(self) -> None: ...
