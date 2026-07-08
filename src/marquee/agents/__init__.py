"""Agent implementations and the scenario-facing registry."""

from collections.abc import Callable

from marquee.agents.scripted import RandomPoster
from marquee.sim.protocols import Agent

AGENT_REGISTRY: dict[str, Callable[[int, dict], Agent]] = {
    "random_poster": lambda agent_id, params: RandomPoster(agent_id, **params),
}

__all__ = ["AGENT_REGISTRY", "RandomPoster"]
