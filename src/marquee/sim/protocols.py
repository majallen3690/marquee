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


@runtime_checkable
class Agent(Protocol):
    """Wake/act/observe lifecycle. All methods return intents; [] means no action.

    on_order_ack closes the id loop: the kernel assigns order ids, and the ack
    (delivered under the same latency model as fills) is how an agent learns the
    id of its own resting order — without it, cancelling a stale quote is
    impossible (ADR-007).
    """

    @property
    def agent_id(self) -> AgentId: ...

    def on_wake(self, ctx: AgentContext) -> list[Intent]: ...

    def on_order_ack(self, ctx: AgentContext, report: ExecutionReport) -> list[Intent]: ...

    def on_fill(self, ctx: AgentContext, fill: Fill) -> list[Intent]: ...


@runtime_checkable
class Recorder(Protocol):
    """Sink for the kernel's typed event stream. JSONL writer in M2; the same
    stream fans out to the WebSocket bridge in M5 (one producer, two sinks).
    Serialization contract (exact bytes) is pinned in ADR-006."""

    def record(self, event: dict) -> None: ...

    def close(self) -> None: ...
