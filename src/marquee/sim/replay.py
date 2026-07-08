"""Replay mode (b) per ADR-006: order-stream replay through a fresh engine.

Reads events.jsonl, re-feeds the exact submit/cancel arrival stream into a
fresh MatchingEngine (agents disabled), and re-serializes the resulting fills
with the recorder's canonical byte contract. Byte-identical trades.jsonl is
the pass condition.
"""

import json
from pathlib import Path

from marquee.engine import MatchingEngine, Order, OrderType, SelfTradePolicy, Side
from marquee.sim.recorder import fmt_trade


def replay_order_stream(
    events_path: str | Path, self_trade_policy: SelfTradePolicy
) -> bytes:
    """Returns the replayed trades.jsonl content as bytes."""
    engine = MatchingEngine(self_trade_policy=self_trade_policy)
    lines: list[str] = []
    with open(events_path, encoding="utf-8", newline="\n") as f:
        for raw in f:
            ev = json.loads(raw)
            kind = ev["k"]
            if kind == "ord":
                report = engine.submit(
                    Order(
                        order_id=ev["oid"],
                        agent_id=ev["aid"],
                        side=Side(ev["side"]),
                        order_type=OrderType(ev["ot"]),
                        price=ev["px"],
                        qty=ev["qty"],
                        ts=ev["t"],
                    )
                )
                for fill in report.fills:
                    lines.append(
                        fmt_trade(
                            ev["t"], fill.trade_id, fill.price, fill.qty,
                            fill.taker_order_id, fill.maker_order_id,
                            fill.taker_agent_id, fill.maker_agent_id,
                            int(fill.taker_side),
                        )
                    )
            elif kind == "cxl" and ev["cs"] == 0:  # only CANCELLED ops touched the book
                engine.cancel(ev["oid"])
    return ("".join(line + "\n" for line in lines)).encode("utf-8")
