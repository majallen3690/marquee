"""Inventory-aware market maker (M3): quoting under inventory risk.

Quoting model (ADR-012): quotes anchor on best_bid/best_ask directly (never a
halved mid — ADR-004), skewed against inventory and widened by a realized-
volatility proxy. Inventory control has three regimes:

  |inv| < soft_limit          symmetric quotes, linear skew
  soft <= |inv| < hard_limit  steeper skew, reduced size on the risk side
  |inv| >= hard_limit         risk-increasing side pulled entirely; excess
                              over hard_limit unwound with a market order

The hard-limit regime is the flash-crash lever for M5: tightening hard_limit
mid-run forces makers one-sided or out, and the cascade follows from
interaction, not scripting.

Bookkeeping: inventory tracks signed fills (maker legs via on_fill, taker legs
via ack fills). Quotes are cancel-and-replace each wake. Under latency jitter a
new quote can arrive before the old one's cancel — transiently two quotes a
side, exactly the race real makers manage; both ids stay tracked until their
cancel acks come back.
"""

from marquee.engine.types import (
    CancelResult,
    ExecutionReport,
    Fill,
    ReportStatus,
    Side,
)
from marquee.sim.protocols import (
    AgentContext,
    CancelIntent,
    Intent,
    SubmitLimit,
    SubmitMarket,
)


class InventoryMarketMaker:
    def __init__(
        self,
        agent_id: int,
        anchor_price: int = 10_000,
        half_spread: int = 2,
        quote_size: int = 20,
        skew_per_unit: float = 0.02,
        soft_limit: int = 120,
        hard_limit: int = 240,
        vol_window: int = 16,
        vol_widen_factor: float = 0.15,
        fallback_half_spread: int = 6,
    ) -> None:
        self._agent_id = agent_id
        self._anchor = anchor_price
        self._half_spread = half_spread
        self._quote_size = quote_size
        self._skew_per_unit = skew_per_unit
        self._soft_limit = soft_limit
        self._hard_limit = hard_limit
        self._vol_window = vol_window
        self._vol_widen_factor = vol_widen_factor
        self._fallback_half_spread = fallback_half_spread

        self.inventory = 0
        self._open_bids: dict[int, None] = {}  # order_id -> None, insertion-ordered
        self._open_asks: dict[int, None] = {}
        self._mid_x2_samples: list[int] = []  # bounded ring, comparison-only values
        self._last_ref: int | None = None  # last known reference price (ticks)

    @property
    def agent_id(self) -> int:
        return self._agent_id

    def apply_perturbation(self, param: str, value: int) -> None:
        """ADR-010 lever. Tightening hard_limit mid-run is the flash-crash
        trigger: makers over the new limit pull a side and unwind at market."""
        if param == "hard_limit":
            self._hard_limit = value
        elif param == "soft_limit":
            self._soft_limit = value
        elif param == "half_spread":
            self._half_spread = value
        elif param == "quote_size":
            self._quote_size = value
        else:
            raise ValueError(f"unknown market-maker perturbation param {param!r}")

    # -- quoting -------------------------------------------------------------

    def _vol_widen(self) -> int:
        samples = self._mid_x2_samples
        if len(samples) < 2:
            return 0
        # Range of mid_x2 over the window, in x2-tick units; factor absorbs the
        # implicit /2 so no halving happens here (ADR-004).
        return int((max(samples) - min(samples)) * self._vol_widen_factor)

    def _skew_ticks(self) -> int:
        skew = self.inventory * self._skew_per_unit
        if abs(self.inventory) >= self._soft_limit:
            skew *= 2.0
        return int(round(skew))

    def _target_quotes(self, ctx: AgentContext) -> list[Intent]:
        book = ctx.book(depth=1)
        best_bid = book.best_bid
        best_ask = book.best_ask

        if best_bid is not None and best_ask is not None:
            mid_x2 = best_bid + best_ask
            samples = self._mid_x2_samples
            samples.append(mid_x2)
            if len(samples) > self._vol_window:
                del samples[0]
            self._last_ref = best_bid  # integer reference, no halving
            bid_anchor, ask_anchor = best_bid, best_ask
            half = self._half_spread
        else:
            # Empty or one-sided book: quote a wide two-sided market around the
            # best available reference so the market can restart.
            ref = best_bid if best_bid is not None else best_ask
            if ref is None:
                ref = self._last_ref if self._last_ref is not None else self._anchor
            self._last_ref = ref
            bid_anchor = ask_anchor = ref
            half = self._fallback_half_spread

        widen = self._vol_widen()
        skew = self._skew_ticks()
        bid_px = bid_anchor + 1 - half - widen - skew
        ask_px = ask_anchor - 1 + half + widen - skew
        bid_px = max(bid_px, 1)
        ask_px = max(ask_px, bid_px + 1)

        intents: list[Intent] = []
        inv = self.inventory
        if inv >= self._hard_limit:
            # Long and at the limit: no bid; unwind the excess aggressively.
            excess = inv - self._hard_limit
            if excess > 0:
                intents.append(SubmitMarket(Side.SELL, excess))
            intents.append(SubmitLimit(Side.SELL, ask_px, self._quote_size))
            return intents
        if inv <= -self._hard_limit:
            excess = -inv - self._hard_limit
            if excess > 0:
                intents.append(SubmitMarket(Side.BUY, excess))
            intents.append(SubmitLimit(Side.BUY, bid_px, self._quote_size))
            return intents

        bid_size = self._quote_size
        ask_size = self._quote_size
        if inv >= self._soft_limit:
            bid_size = max(1, self._quote_size // 2)  # buying adds risk — shrink it
        elif inv <= -self._soft_limit:
            ask_size = max(1, self._quote_size // 2)
        intents.append(SubmitLimit(Side.BUY, bid_px, bid_size))
        intents.append(SubmitLimit(Side.SELL, ask_px, ask_size))
        return intents

    # -- lifecycle -----------------------------------------------------------

    def on_wake(self, ctx: AgentContext) -> list[Intent]:
        intents: list[Intent] = [
            CancelIntent(oid) for oid in (*self._open_bids, *self._open_asks)
        ]
        intents.extend(self._target_quotes(ctx))
        return intents

    def on_order_ack(self, ctx: AgentContext, report: ExecutionReport) -> list[Intent]:
        if report.status is ReportStatus.REJECTED:
            return []
        # Taker legs (marketable quotes / unwind orders) adjust inventory.
        for fill in report.fills:
            self.inventory += fill.qty if report.side is Side.BUY else -fill.qty
        if report.resting_qty > 0:
            if report.side is Side.BUY:
                self._open_bids[report.order_id] = None
            else:
                self._open_asks[report.order_id] = None
        return []

    def on_fill(self, ctx: AgentContext, fill: Fill) -> list[Intent]:
        # Maker leg: taker bought means we sold.
        self.inventory += -fill.qty if fill.taker_side is Side.BUY else fill.qty
        return []

    def on_cancel_ack(self, ctx: AgentContext, result: CancelResult) -> list[Intent]:
        self._open_bids.pop(result.order_id, None)
        self._open_asks.pop(result.order_id, None)
        return []
