"use client";

/** Trade tape: newest first, price colored by aggressor side. */

import { Glyph, Num, VoidState } from "./primitives";
import { fmtPx, fmtQty, fmtSimTime } from "@/lib/format";
import type { Frame } from "@/lib/types";

export function TradeTape({ frame }: { frame: Frame | null }) {
  if (!frame) return <VoidState>AWAITING FEED</VoidState>;
  if (frame.trades.length === 0) return <VoidState>NO PRINTS YET</VoidState>;

  const rows = [...frame.trades].reverse();
  return (
    <div className="h-full overflow-hidden px-3 py-1">
      <div className="grid grid-cols-[88px_1fr_64px_16px] gap-2 text-axis uppercase tracking-[0.08em] text-ink-2">
        <span>Time</span>
        <span className="text-right">Price</span>
        <span className="text-right">Qty</span>
        <span />
      </div>
      {rows.map((trade, index) => (
        <div
          key={trade.tid}
          className="grid h-[18px] grid-cols-[88px_1fr_64px_16px] items-center gap-2 text-dense"
        >
          <span className="text-ink-2">{fmtSimTime(trade.t)}</span>
          <span className="text-right">
            <Num
              value={fmtPx(trade.px)}
              tone={trade.side === 0 ? "bid" : "ask"}
              flash={index === 0}
            />
          </span>
          <span className="text-right text-ink-1">{fmtQty(trade.qty)}</span>
          <Glyph dir={trade.side === 0 ? "up" : "down"} />
        </div>
      ))}
    </div>
  );
}
