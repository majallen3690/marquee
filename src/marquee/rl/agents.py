"""The learning seat and the helpers that make the comparison fair.

``LearnedMarketMaker`` turns one MultiDiscrete action into one quote update per
decision step (RL_DESIGN §4). There is no "don't quote" action and no taker action:
two-sided quoting is mandatory and inventory is managed only through where and how
large it quotes. At |q| ≥ q_max the agent stops quoting the side that adds risk and
unwinds the excess at market, the exact rule the rule-based maker plays under
(ADR-012), so both compete under the same risk limit.

Quotes are placed relative to the book *without its own orders*. A maker that
anchors on the current best price can end up anchoring on its own previous quote and
walk the market away (ADR-022); this one cannot.

``Window`` runs an agent only inside a time window, so the original rule-based maker
can leave its seat at the episode start and a fresh entrant (learned, or rule-based
for the baseline) can take it flat. Same seed and start time give an identical market
up to the entrant's arrival, which makes the learned-vs-baseline comparison paired.
"""

from marquee.engine.types import CancelResult, ExecutionReport, Fill, ReportStatus, Side
from marquee.sim.protocols import (
    Agent,
    AgentContext,
    CancelIntent,
    Intent,
    SubmitLimit,
    SubmitMarket,
)

OFFSETS = (-2, -1, 0, 1, 2, 3, 4, 6, 8)  # ticks behind the touch; negative improves
SIZE_FRACTIONS = (0.25, 0.5, 1.0)  # of base quote size, both sides


class LearnedMarketMaker:
    def __init__(
        self,
        agent_id: int,
        base_size: int,
        q_max: int,
        fallback_half_spread: int = 6,
        anchor_price: int = 10_000,
    ) -> None:
        self._agent_id = agent_id
        self.base_size = base_size
        self.q_max = q_max
        self._fallback = fallback_half_spread
        self._last_ref = anchor_price
        self.active = False
        self.action: tuple[int, int, int] | None = None
        self.inventory = 0
        self.live: dict[int, list] = {}  # oid -> [side, price, remaining]
        self.last_quote: tuple[int | None, int | None] = (None, None)

    @property
    def agent_id(self) -> int:
        return self._agent_id

    def on_wake(self, ctx: AgentContext) -> list[Intent]:
        intents: list[Intent] = [CancelIntent(oid) for oid in self.live]
        if not self.active or self.action is None:
            self.last_quote = (None, None)
            return intents
        book = ctx.book_excluding_self(1)
        rb = book.bids[0].price if book.bids else None
        ra = book.asks[0].price if book.asks else None
        if rb is None and ra is None:
            rb, ra = self._last_ref - 1, self._last_ref + 1
        elif rb is None:
            rb = ra - 2 * self._fallback
        elif ra is None:
            ra = rb + 2 * self._fallback
        self._last_ref = rb

        a_bid, a_ask, a_size = self.action
        bid = min(rb - OFFSETS[a_bid], ra - 1)  # never cross the rest of the market
        ask = max(ra + OFFSETS[a_ask], rb + 1)
        bid = max(bid, 1)
        ask = max(ask, bid + 1)
        size = max(1, int(round(SIZE_FRACTIONS[a_size] * self.base_size)))

        q = self.inventory
        if q > self.q_max:
            intents.append(SubmitMarket(Side.SELL, q - self.q_max))
        elif q < -self.q_max:
            intents.append(SubmitMarket(Side.BUY, -q - self.q_max))
        quote_bid = q < self.q_max
        quote_ask = q > -self.q_max
        if quote_bid:
            intents.append(SubmitLimit(Side.BUY, bid, size))
        if quote_ask:
            intents.append(SubmitLimit(Side.SELL, ask, size))
        self.last_quote = (bid if quote_bid else None, ask if quote_ask else None)
        return intents

    def on_order_ack(self, ctx: AgentContext, report: ExecutionReport) -> list[Intent]:
        if report.status is ReportStatus.ACCEPTED:
            for f in report.fills:
                self.inventory += f.qty if report.side is Side.BUY else -f.qty
            if report.resting_qty > 0:
                self.live[report.order_id] = [report.side, report.price, report.resting_qty]
        return []

    def on_fill(self, ctx: AgentContext, fill: Fill) -> list[Intent]:
        bought = fill.taker_side is Side.SELL
        self.inventory += fill.qty if bought else -fill.qty
        entry = self.live.get(fill.maker_order_id)
        if entry is not None:
            entry[2] -= fill.qty
            if entry[2] <= 0:
                del self.live[fill.maker_order_id]
        return []

    def on_cancel_ack(self, ctx: AgentContext, result: CancelResult) -> list[Intent]:
        self.live.pop(result.order_id, None)
        return []


class Window:
    """Run ``inner`` only for start_ns <= now < end_ns. Before the window it is never
    woken; after it, it cancels whatever it still has resting and goes quiet.
    Callbacks always reach ``inner`` so its bookkeeping stays true; its intents are
    passed on only inside the window."""

    def __init__(self, inner: Agent, start_ns: int = 0, end_ns: int | None = None) -> None:
        self.inner = inner
        self._start = start_ns
        self._end = end_ns
        self._live: dict[int, int] = {}  # oid -> remaining
        self._cancel_sent: set[int] = set()

    @property
    def agent_id(self) -> int:
        return self.inner.agent_id

    def _open(self, now: int) -> bool:
        return now >= self._start and (self._end is None or now < self._end)

    def _pass(self, ctx: AgentContext, intents: list[Intent]) -> list[Intent]:
        return intents if self._open(ctx.now) else []

    def on_wake(self, ctx: AgentContext) -> list[Intent]:
        if self._open(ctx.now):
            return self.inner.on_wake(ctx)
        if self._end is not None and ctx.now >= self._end:
            out = [CancelIntent(o) for o in self._live if o not in self._cancel_sent]
            self._cancel_sent.update(self._live)
            return out
        return []

    def on_order_ack(self, ctx: AgentContext, report: ExecutionReport) -> list[Intent]:
        if report.status is ReportStatus.ACCEPTED and report.resting_qty > 0:
            self._live[report.order_id] = report.resting_qty
        return self._pass(ctx, self.inner.on_order_ack(ctx, report))

    def on_fill(self, ctx: AgentContext, fill: Fill) -> list[Intent]:
        rem = self._live.get(fill.maker_order_id)
        if rem is not None:
            if rem <= fill.qty:
                del self._live[fill.maker_order_id]
            else:
                self._live[fill.maker_order_id] = rem - fill.qty
        return self._pass(ctx, self.inner.on_fill(ctx, fill))

    def on_cancel_ack(self, ctx: AgentContext, result: CancelResult) -> list[Intent]:
        self._live.pop(result.order_id, None)
        return self._pass(ctx, self.inner.on_cancel_ack(ctx, result))

    def apply_perturbation(self, param: str, value: int) -> None:
        apply = getattr(self.inner, "apply_perturbation", None)
        if apply is None:
            raise ValueError(f"agent {self.agent_id} does not take perturbations")
        apply(param, value)
