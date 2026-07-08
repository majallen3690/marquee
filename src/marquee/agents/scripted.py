"""Scripted M2 agent: random limit posting with occasional cancels.

Exists to exercise the kernel/agent lifecycle for the M2 gate (multi-agent
scenario, byte-identical replay). It is deliberately dumb — the calibrated M3
population replaces it; this stays as a test fixture.
"""

from marquee.engine.types import CancelResult, ExecutionReport, Fill, Side
from marquee.sim.protocols import AgentContext, CancelIntent, Intent, SubmitLimit


class RandomPoster:
    """Posts limits around the touch (or an anchor price on an empty book);
    sometimes cancels its oldest open order instead. All randomness from ctx.rng,
    all intent fields converted to built-in int at the draw site (ADR-003)."""

    def __init__(
        self,
        agent_id: int,
        anchor_price: int = 10_000,
        band_ticks: int = 5,
        max_qty: int = 50,
        cancel_pct: int = 20,
    ) -> None:
        self._agent_id = agent_id
        self._anchor = anchor_price
        self._band = band_ticks
        self._max_qty = max_qty
        self._cancel_pct = cancel_pct
        self._open: dict[int, None] = {}  # insertion-ordered set of my resting order ids

    @property
    def agent_id(self) -> int:
        return self._agent_id

    def on_wake(self, ctx: AgentContext) -> list[Intent]:
        rng = ctx.rng
        if self._open and int(rng.integers(0, 100)) < self._cancel_pct:
            oldest = next(iter(self._open))
            del self._open[oldest]
            return [CancelIntent(oldest)]
        book = ctx.book(depth=1)
        buy = int(rng.integers(0, 2)) == 0
        if buy:
            base = book.best_bid if book.best_bid is not None else self._anchor
        else:
            base = book.best_ask if book.best_ask is not None else self._anchor
        offset = int(rng.integers(-self._band, self._band + 1))
        price = max(1, base + offset)
        qty = int(rng.integers(1, self._max_qty + 1))
        return [SubmitLimit(Side.BUY if buy else Side.SELL, price, qty)]

    def on_order_ack(self, ctx: AgentContext, report: ExecutionReport) -> list[Intent]:
        if report.resting_qty > 0:
            self._open[report.order_id] = None
        return []

    def on_fill(self, ctx: AgentContext, fill: Fill) -> list[Intent]:
        # Maker side: our resting order traded. If fully gone, a later cancel
        # would come back ALREADY_TERMINAL — benign, but tidy up when we can't
        # know remaining: keep the id; cancel races are part of the lifecycle.
        return []

    def on_cancel_ack(self, ctx: AgentContext, result: CancelResult) -> list[Intent]:
        self._open.pop(result.order_id, None)
        return []
