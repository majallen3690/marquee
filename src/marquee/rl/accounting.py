"""P&L accounting for the seat under test (RL_DESIGN §5).

The ledger is built from the public trade tape, not from the agent's own
bookkeeping, so the learned maker and the rule-based baseline are measured by
exactly the same code. Marking uses the mid of the book *without the seat's own
orders* (rule 1); terminal inventory is valued by walking that book (rule 3).
"""

import json
import math
from dataclasses import dataclass

from marquee.engine import MatchingEngine
from marquee.engine.types import Side

# (t, price, qty, maker agent, taker agent, taker side)
type Trade = tuple[int, int, int, int, int, int]


class TapeRecorder:
    """Recorder for training runs: drops the event log, keeps the public tape."""

    __slots__ = ("trades",)

    def __init__(self) -> None:
        self.trades: list[Trade] = []

    def record_line(self, line: str) -> None:
        pass

    def record_trade_line(self, line: str) -> None:
        d = json.loads(line)
        self.trades.append((d["t"], d["px"], d["qty"], d["mka"], d["tka"], d["tks"]))

    def close(self) -> None:
        pass


@dataclass
class Ledger:
    """Signed inventory, cash (ticks) and an average-cost basis for one agent.
    Wealth W = cash + q·m splits exactly into realized (cash + cost) and
    unrealized (q·m − cost)."""

    agent_id: int
    q: int = 0
    cash: int = 0
    cost: float = 0.0
    maker_volume: int = 0
    taker_volume: int = 0
    maker_fills: int = 0
    self_trade_volume: int = 0  # must stay 0 under CANCEL_RESTING (detector G5)
    cursor: int = 0

    def consume(self, tape: list[Trade]) -> None:
        for _t, px, qty, mka, tka, tks in tape[self.cursor :]:
            if mka == self.agent_id:  # resting order hit: we took the other side
                self._apply(tks == Side.SELL, px, qty)
                self.maker_volume += qty
                self.maker_fills += 1
            if tka == self.agent_id:
                self._apply(tks == Side.BUY, px, qty)
                self.taker_volume += qty
                if mka == self.agent_id:
                    self.self_trade_volume += qty
        self.cursor = len(tape)

    def _apply(self, bought: bool, px: int, qty: int) -> None:
        dq = qty if bought else -qty
        if self.q == 0 or (self.q > 0) == (dq > 0):
            self.cost += px * dq
        else:
            closing = min(abs(dq), abs(self.q))
            self.cost -= (self.cost / self.q) * (closing if self.q > 0 else -closing)
            leftover = abs(dq) - closing
            if leftover:
                self.cost = float(px * (leftover if dq > 0 else -leftover))
        self.q += dq
        self.cash -= px * dq
        if self.q == 0:
            self.cost = 0.0

    def realized(self) -> float:
        return self.cash + self.cost

    def unrealized(self, mid: float) -> float:
        return self.q * mid - self.cost


def mid_excluding(engine: MatchingEngine, agent_id: int) -> float | None:
    """Own-order-excluded mid: the agent cannot move its own mark by quoting."""
    snap = engine.snapshot_excluding(0, 1, agent_id)
    if snap.bids and snap.asks:
        return (snap.bids[0].price + snap.asks[0].price) / 2
    return None


def liquidation_value(
    engine: MatchingEngine, agent_id: int, q: int, fallback: float, depth: int = 50
) -> float:
    """Cash from unwinding q now by walking everyone else's book (signed: selling a
    long brings cash in, buying back a short pays it out). If the book is shallower
    than the position, the remainder is priced one tick past the worst level seen."""
    if q == 0:
        return 0.0
    snap = engine.snapshot_excluding(0, depth, agent_id)
    levels = snap.bids if q > 0 else snap.asks
    remaining = abs(q)
    value = 0.0
    worst = fallback
    for lv in levels:
        take = min(remaining, lv.qty)
        value += lv.price * take
        remaining -= take
        worst = lv.price
        if remaining == 0:
            break
    if remaining:
        value += (worst - 1 if q > 0 else worst + 1) * remaining
    return value if q > 0 else -value


def squash(x: float, scale: float) -> float:
    return math.tanh(x / scale)
