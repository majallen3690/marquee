"""Simulation kernel and agent API.

The kernel owns the clock, the event queue, and RNG stream spawning (ADR-002,
ADR-003, ADR-006). Agents interact only through the typed protocols defined in
marquee.sim.protocols — never with the engine or each other directly (ADR-007).

Implemented in M2; the boundary types live here from M0 so the engine (M1) can
be built against them.
"""

from marquee.sim.protocols import (
    Agent,
    AgentContext,
    CancelIntent,
    Intent,
    Recorder,
    SubmitLimit,
    SubmitMarket,
)

__all__ = [
    "Agent",
    "AgentContext",
    "CancelIntent",
    "Intent",
    "Recorder",
    "SubmitLimit",
    "SubmitMarket",
]
