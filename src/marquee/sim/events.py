"""Kernel event taxonomy (ADR-003 ordering, ADR-011 taxonomy).

Heap key is (time_ns, priority_class, seq). Priority classes order
same-timestamp event kinds; seq (global insertion counter) totalizes the order.
"""

from dataclasses import dataclass
from enum import IntEnum

from marquee.engine.types import AgentId, CancelResult, ExecutionReport, Fill
from marquee.sim.protocols import Intent


class PriorityClass(IntEnum):
    """ADR-003: engine-side processing < deliveries < wakeups < perturbations."""

    INTENT_ARRIVAL = 0
    DELIVERY = 1
    WAKE = 2
    PERTURBATION = 3


@dataclass(frozen=True, slots=True)
class IntentArrival:
    """An agent's intent arriving at the exchange after upstream latency."""

    agent_id: AgentId
    intent: Intent


@dataclass(frozen=True, slots=True)
class Delivery:
    """An exchange message arriving back at an agent after downstream latency."""

    agent_id: AgentId
    payload: ExecutionReport | Fill | CancelResult


@dataclass(frozen=True, slots=True)
class Wake:
    agent_id: AgentId


@dataclass(frozen=True, slots=True)
class Perturbation:
    """Reserved for M5 (ADR-010). Scheduling one before the application registry
    exists is a loud error in the kernel, not a silent no-op."""

    payload: dict
