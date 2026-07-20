"""Agent implementations and the scenario-facing registry."""

from collections.abc import Callable

from marquee.agents.market_maker import InventoryMarketMaker
from marquee.agents.momentum import MomentumTrader
from marquee.agents.noise import NoiseTrader
from marquee.agents.scripted import RandomPoster
from marquee.sim.protocols import Agent

AGENT_REGISTRY: dict[str, Callable[[int, dict], Agent]] = {
    "random_poster": lambda agent_id, params: RandomPoster(agent_id, **params),
    "market_maker": lambda agent_id, params: InventoryMarketMaker(agent_id, **params),
    "momentum": lambda agent_id, params: MomentumTrader(agent_id, **params),
    "noise": lambda agent_id, params: NoiseTrader(agent_id, **params),
}

__all__ = [
    "AGENT_REGISTRY",
    "InventoryMarketMaker",
    "MomentumTrader",
    "NoiseTrader",
    "RandomPoster",
]
