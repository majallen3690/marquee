"""Simulation kernel and agent API.

The kernel owns the clock, the event queue, and RNG stream spawning (ADR-002,
ADR-003, ADR-006). Agents interact only through the typed protocols defined in
marquee.sim.protocols — never with the engine or each other directly (ADR-007).
"""

from marquee.sim.kernel import SimKernel
from marquee.sim.protocols import (
    Agent,
    AgentContext,
    CancelIntent,
    Intent,
    Recorder,
    SubmitLimit,
    SubmitMarket,
)
from marquee.sim.recorder import JsonlRecorder, ListRecorder
from marquee.sim.scenario import ScenarioConfig, load_scenario, run_scenario

__all__ = [
    "Agent",
    "AgentContext",
    "CancelIntent",
    "Intent",
    "JsonlRecorder",
    "ListRecorder",
    "Recorder",
    "ScenarioConfig",
    "SimKernel",
    "SubmitLimit",
    "SubmitMarket",
    "load_scenario",
    "run_scenario",
]
