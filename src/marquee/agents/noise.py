"""Noise / liquidity trader (M3): uninformed background flow.

A mixture per wake — cancel a stale own order, take liquidity with a market
order, or supply liquidity with a limit placed relative to the touch (mostly
behind it, occasionally improving inside the spread, which is how spreads
tighten without any agent knowing the "true" price)."""

from marquee.engine.types import CancelResult, ExecutionReport, Fill, ReportStatus, Side
from marquee.sim.protocols import (
    AgentContext,
    CancelIntent,
    Intent,
    SubmitLimit,
    SubmitMarket,
)


class NoiseTrader:
    def __init__(
        self,
        agent_id: int,
        anchor_price: int = 10_000,
        cancel_pct: int = 20,
        market_pct: int = 12,
        improve_pct: int = 15,
        depth_ticks: int = 8,
        mean_qty: float = 12.0,
        max_open: int = 24,
    ) -> None:
        self._agent_id = agent_id
        self._anchor = anchor_price
        self._cancel_pct = cancel_pct
        self._market_pct = market_pct
        self._improve_pct = improve_pct
        self._depth_ticks = depth_ticks
        self._mean_qty = mean_qty
        self._max_open = max_open
        self._open: dict[int, None] = {}

    @property
    def agent_id(self) -> int:
        return self._agent_id

    def _qty(self, ctx: AgentContext) -> int:
        return 1 + int(ctx.rng.exponential(self._mean_qty))

    def on_wake(self, ctx: AgentContext) -> list[Intent]:
        rng = ctx.rng
        roll = int(rng.integers(0, 100))
        force_cancel = len(self._open) >= self._max_open
        if self._open and (force_cancel or roll < self._cancel_pct):
            oldest = next(iter(self._open))
            del self._open[oldest]
            return [CancelIntent(oldest)]

        buy = int(rng.integers(0, 2)) == 0
        side = Side.BUY if buy else Side.SELL
        if roll < self._cancel_pct + self._market_pct:
            return [SubmitMarket(side, self._qty(ctx))]

        book = ctx.book(depth=1)
        best_bid = book.best_bid
        best_ask = book.best_ask
        if buy:
            anchor = best_bid if best_bid is not None else (
                best_ask - 1 if best_ask is not None else self._anchor
            )
        else:
            anchor = best_ask if best_ask is not None else (
                best_bid + 1 if best_bid is not None else self._anchor
            )

        improving = int(rng.integers(0, 100)) < self._improve_pct
        if improving and best_bid is not None and best_ask is not None:
            spread = best_ask - best_bid
            if spread > 1:
                step = 1 + int(rng.integers(0, spread - 1))
                price = best_bid + step if buy else best_ask - step
            else:
                price = anchor
        else:
            offset = int(rng.integers(0, self._depth_ticks + 1))
            price = anchor - offset if buy else anchor + offset
        return [SubmitLimit(side, max(price, 1), self._qty(ctx))]

    def on_order_ack(self, ctx: AgentContext, report: ExecutionReport) -> list[Intent]:
        if report.status is not ReportStatus.REJECTED and report.resting_qty > 0:
            self._open[report.order_id] = None
        return []

    def on_fill(self, ctx: AgentContext, fill: Fill) -> list[Intent]:
        return []

    def on_cancel_ack(self, ctx: AgentContext, result: CancelResult) -> list[Intent]:
        self._open.pop(result.order_id, None)
        return []
