"use client";

/** The order-book ladder — the centerpiece (DESIGN.md). Center-out layout:
 * asks stack upward above the spread row, bids downward below. Depth bars are
 * the data visualization. */

import { Glyph, Num, VoidState } from "./primitives";
import { fmtMid, fmtPx, fmtQty } from "@/lib/format";
import type { Frame } from "@/lib/types";

const SIDE_ROWS = 12;

function Row({
  price,
  qty,
  cum,
  maxQty,
  tone,
}: {
  price: number | null;
  qty: number;
  cum: number;
  maxQty: number;
  tone: "bid" | "ask";
}) {
  if (price === null) {
    return <div className="h-5" />;
  }
  const barPct = maxQty > 0 ? Math.max(2, (qty / maxQty) * 100) : 0;
  const barColor = tone === "bid" ? "bg-bid/18" : "bg-ask/18";
  return (
    <div className="grid h-5 grid-cols-[1fr_72px_56px] items-center gap-2 px-3 text-dense">
      <div className="relative h-full min-w-0">
        <div
          className={`absolute inset-y-1 right-0 ${barColor}`}
          style={{ width: `${barPct}%` }}
        />
        <div className="absolute inset-0 flex items-center justify-end pr-1">
          <Num value={fmtQty(qty)} tone="plain" flash />
        </div>
      </div>
      <div className="text-right">
        <Num value={fmtPx(price)} tone={tone} flash />
      </div>
      <div className="text-right text-ink-2">{fmtQty(cum)}</div>
    </div>
  );
}

function EmptySide({ label }: { label: string }) {
  return (
    <div className="flex h-5 items-center justify-center text-dense text-ink-2">
      — {label} —
    </div>
  );
}

export function DepthLadder({ frame }: { frame: Frame | null }) {
  if (!frame) return <VoidState>AWAITING FEED</VoidState>;

  const { bids, asks, trades } = frame;
  const maxQty = Math.max(1, ...bids.map(([, q]) => q), ...asks.map(([, q]) => q));

  let askCum = 0;
  const askRows = asks.slice(0, SIDE_ROWS).map(([px, qty]) => {
    askCum += qty;
    return { px, qty, cum: askCum };
  });
  let bidCum = 0;
  const bidRows = bids.slice(0, SIDE_ROWS).map(([px, qty]) => {
    bidCum += qty;
    return { px, qty, cum: bidCum };
  });

  const lastTrade = trades.length > 0 ? trades[trades.length - 1] : null;
  const dir = lastTrade === null ? "flat" : lastTrade.side === 0 ? "up" : "down";
  const spread =
    bids.length > 0 && asks.length > 0 ? asks[0][0] - bids[0][0] : null;

  return (
    <div className="flex h-full flex-col justify-center">
      {/* asks: worst at top, best adjacent to the spread row */}
      <div>
        {Array.from({ length: SIDE_ROWS - askRows.length }).map((_, i) => (
          <div key={`pad-a-${i}`} className="h-5" />
        ))}
        {askRows.length === 0 ? (
          <EmptySide label="NO ASKS" />
        ) : (
          [...askRows].reverse().map((row) => (
            <Row
              key={`a-${row.px}`}
              price={row.px}
              qty={row.qty}
              cum={row.cum}
              maxQty={maxQty}
              tone="ask"
            />
          ))
        )}
      </div>

      {/* spread row */}
      <div className="my-1 flex h-9 items-center justify-between border-y border-hairline px-3">
        <div className="text-mid font-semibold">
          {bids.length > 0 && asks.length > 0 ? (
            <Num value={fmtMid(bids[0][0], asks[0][0])} tone="plain" flash />
          ) : (
            <span className="text-ink-2">—</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-dense text-ink-2">
          <span>{spread !== null ? `SPR ${spread}` : "ONE-SIDED"}</span>
          <Glyph dir={dir} />
        </div>
      </div>

      {/* bids: best adjacent to the spread row, worst at bottom */}
      <div>
        {bidRows.length === 0 ? (
          <EmptySide label="NO BIDS" />
        ) : (
          bidRows.map((row) => (
            <Row
              key={`b-${row.px}`}
              price={row.px}
              qty={row.qty}
              cum={row.cum}
              maxQty={maxQty}
              tone="bid"
            />
          ))
        )}
        {Array.from({ length: SIDE_ROWS - bidRows.length }).map((_, i) => (
          <div key={`pad-b-${i}`} className="h-5" />
        ))}
      </div>
    </div>
  );
}
