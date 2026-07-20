"""Momentum trader (M3): trend-follows recent mid moves with market orders.

The destabilizer of the population — positive feedback (buys after rises,
sells after falls) is what lets volatility cluster and crashes cascade instead
of damping out. Signal math uses mid_x2 values comparison-only (ADR-004: never
halved)."""

from collections import deque

from marquee.engine.types import CancelResult, ExecutionReport, Fill, Side
from marquee.sim.protocols import AgentContext, Intent, SubmitMarket


class MomentumTrader:
    def __init__(
        self,
        agent_id: int,
        lookback_ns: int = 500_000_000,
        threshold_ticks: int = 3,
        order_size: int = 15,
        act_pct: int = 60,
        cooldown_wakes: int = 2,
        max_samples: int = 64,
    ) -> None:
        self._agent_id = agent_id
        self._lookback_ns = lookback_ns
        self._threshold_x2 = 2 * threshold_ticks  # signal compares mid_x2 values
        self._order_size = order_size
        self._act_pct = act_pct
        self._cooldown_wakes = cooldown_wakes
        self._samples: deque[tuple[int, int]] = deque(maxlen=max_samples)  # (t, mid_x2)
        self._cooldown = 0

    @property
    def agent_id(self) -> int:
        return self._agent_id

    def _signal(self, now: int, mid_x2: int) -> int:
        """+1 up-trend, -1 down-trend, 0 no signal. Compares against the oldest
        sample inside the lookback window."""
        horizon = now - self._lookback_ns
        reference: int | None = None
        for t, m in self._samples:
            if t >= horizon:
                reference = m
                break
        if reference is None:
            return 0
        delta = mid_x2 - reference
        if delta >= self._threshold_x2:
            return 1
        if delta <= -self._threshold_x2:
            return -1
        return 0

    def on_wake(self, ctx: AgentContext) -> list[Intent]:
        book = ctx.book(depth=1)
        if book.best_bid is None or book.best_ask is None:
            return []
        mid_x2 = book.best_bid + book.best_ask
        signal = self._signal(ctx.now, mid_x2)
        self._samples.append((ctx.now, mid_x2))
        if self._cooldown > 0:
            self._cooldown -= 1
            return []
        if signal == 0 or int(ctx.rng.integers(0, 100)) >= self._act_pct:
            return []
        self._cooldown = self._cooldown_wakes
        side = Side.BUY if signal > 0 else Side.SELL
        return [SubmitMarket(side, self._order_size)]

    def on_order_ack(self, ctx: AgentContext, report: ExecutionReport) -> list[Intent]:
        return []

    def on_fill(self, ctx: AgentContext, fill: Fill) -> list[Intent]:
        return []

    def on_cancel_ack(self, ctx: AgentContext, result: CancelResult) -> list[Intent]:
        return []
