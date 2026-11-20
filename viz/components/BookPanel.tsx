"use client";

/** The order book: price, size, running total, 5 s traded volume. Cumulative
 * depth tints each row; empty ticks stay visible (a run of more than three
 * collapses to one dashed row); the spread is a split-flap readout; a
 * cumulative-depth curve closes the panel. */

import { Lb, Num, Panel, Tiles, VoidState } from "./primitives";
import { fmtPx, fmtSigned } from "@/lib/format";
import type { History } from "@/lib/history";
import type { Derived } from "@/lib/derive";
import type { Frame, Level } from "@/lib/types";

const COLS = "70px 1fr 1fr 50px";

type Row =
  | { k: "lvl"; p: number; q: number; cum: number }
  | { k: "empty"; p: number }
  | { k: "gap"; lo: number; hi: number; n: number };

/** levels are best→worst; dir is +1 for asks (ascending), −1 for bids */
function ladder(levels: Level[], dir: 1 | -1): Row[] {
  const rows: Row[] = [];
  let cum = 0;
  let prev: number | null = null;
  for (const [p, q] of levels) {
    if (prev !== null) {
      const gap = Math.abs(p - prev) - 1;
      if (gap > 3) rows.push({ k: "gap", lo: Math.min(p, prev) + 1, hi: Math.max(p, prev) - 1, n: gap });
      else for (let i = 1; i <= gap; i++) rows.push({ k: "empty", p: prev + dir * i });
    }
    cum += q;
    rows.push({ k: "lvl", p, q, cum });
    prev = p;
  }
  return rows;
}

function BookRow({
  row,
  side,
  cumMax,
  vap,
  best,
}: {
  row: Row;
  side: "b" | "a";
  cumMax: number;
  vap: Map<number, number>;
  best: number;
}) {
  const base = "relative grid h-5 items-center px-2.5 n text-[12px]";
  if (row.k === "gap") {
    return (
      <div className="n flex h-[18px] items-center justify-center border-y border-dashed border-seam text-[11px] text-ink-3">
        {row.n} empty ticks · {fmtPx(row.lo)}–{fmtPx(row.hi)}
      </div>
    );
  }
  if (row.k === "empty") {
    return (
      <div className={`${base} text-ink-3`} style={{ gridTemplateColumns: COLS }}>
        <span>{fmtPx(row.p)}</span>
        <span />
        <span />
        <span className="text-right">{vap.get(row.p) ?? ""}</span>
      </div>
    );
  }
  const tone = side === "b" ? "text-bid" : "text-ask";
  const tint = side === "b" ? "bg-bid/17" : "bg-ask/17";
  const weight = row.p === best ? "font-bold" : "";
  return (
    <div className={base} style={{ gridTemplateColumns: COLS }}>
      <span className={`absolute inset-y-px right-0 ${tint}`} style={{ width: `${(row.cum / cumMax) * 100}%` }} />
      <span className={`relative ${tone} ${weight}`}>{fmtPx(row.p)}</span>
      <span className={`relative text-right ${weight}`}>{row.q}</span>
      <span className="relative text-right text-ink-2">{row.cum}</span>
      <span className="relative text-right text-ink-3">{vap.get(row.p) ?? ""}</span>
    </div>
  );
}

function DepthCurve({ bids, asks, mid }: { bids: Level[]; asks: Level[]; mid: number }) {
  const W = 258;
  const H = 128;
  const lo = bids[bids.length - 1][0] - 2;
  const hi = asks[asks.length - 1][0] + 2;
  const total = Math.max(
    bids.reduce((s, l) => s + l[1], 0),
    asks.reduce((s, l) => s + l[1], 0),
    1,
  );
  const X = (p: number) => ((p - lo) / (hi - lo)) * W;
  const Y = (c: number) => H - 16 - (c / total) * (H - 26);
  const side = (levels: Level[], dir: 1 | -1, edge: number): string => {
    let c = 0;
    const first = levels[0][0] - dir * 0.5;
    const pts = [`M${X(first)},${Y(0)}`];
    for (const [p, q] of levels) {
      c += q;
      pts.push(`L${X(p - dir * 0.5)},${Y(c)}`, `L${X(p + dir * 0.5)},${Y(c)}`);
    }
    pts.push(`L${X(edge)},${Y(c)}`, `L${X(edge)},${Y(0)}`, "Z");
    return pts.join(" ");
  };
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Cumulative depth: bids left, asks right" className="block">
      <path d={side(bids, -1, lo)} className="fill-bid/17 stroke-bid" strokeWidth={1.2} />
      <path d={side(asks, 1, hi)} className="fill-ask/17 stroke-ask" strokeWidth={1.2} />
      <line x1={X(mid)} x2={X(mid)} y1={4} y2={H - 16} className="stroke-ink-2" strokeDasharray="2 3" />
      <line x1={0} x2={W} y1={H - 15.5} y2={H - 15.5} className="stroke-seam" />
      <g className="n fill-ink-2" fontSize={11}>
        <text x={0} y={H - 3}>{fmtPx(lo)}</text>
        <text x={X(mid)} y={H - 3} textAnchor="middle" className="fill-ink-1">{mid.toFixed(1)}</text>
        <text x={W} y={H - 3} textAnchor="end">{fmtPx(hi)}</text>
        <text x={2} y={12}>{total}</text>
      </g>
    </svg>
  );
}

export function BookPanel({
  frame,
  d,
  history,
  explain,
}: {
  frame: Frame | null;
  d: Derived | null;
  history: React.RefObject<History>;
  explain: boolean;
}) {
  const E = (a: string, b: string) => (explain ? b : a);
  if (!frame || !d) {
    return (
      <Panel label="Book" area="book" id="book">
        <VoidState>Awaiting feed</VoidState>
      </Panel>
    );
  }
  const { bids, asks } = frame;
  const both = bids.length > 0 && asks.length > 0;
  const vap = new Map<number, number>();
  for (const r of history.current?.recent ?? []) vap.set(r.px, (vap.get(r.px) ?? 0) + r.qty);

  const aRows = ladder(asks, 1);
  const bRows = ladder(bids, -1);
  const cumMax = Math.max(
    1,
    bids.reduce((s, l) => s + l[1], 0),
    asks.reduce((s, l) => s + l[1], 0),
  );
  const heavy = d.imbalance < 0 ? "Sellers" : "Buyers";
  const bestBid = both ? bids[0][0] : -1;
  const bestAsk = both ? asks[0][0] : -1;

  return (
    <Panel
      label={E("Book", "Book · who is waiting")}
      area="book"
      id="book"
      right={<Lb tone="faint">{`${heavy} heavy${explain ? "" : ` ${fmtSigned(d.imbalance, 2)}`}`}</Lb>}
    >
      <div className="flex h-full flex-col">
        <div className="grid h-[22px] shrink-0 items-center border-b border-seam px-2.5" style={{ gridTemplateColumns: COLS }}>
          <Lb tone="faint">Price</Lb>
          <Lb tone="faint" className="text-right">{E("Size", "Shares")}</Lb>
          <Lb tone="faint" className="text-right">Total</Lb>
          <Lb tone="faint" className="text-right">{E("Vol 5s", "Traded")}</Lb>
        </div>
        <div className="flex min-h-0 flex-1 flex-col justify-end overflow-hidden">
          {aRows.length === 0 ? (
            <div className="n py-1 text-center text-[11px] text-ink-3">no asks</div>
          ) : (
            [...aRows].reverse().map((r, i) => (
              <BookRow key={`a${i}-${r.k === "gap" ? r.lo : r.p}`} row={r} side="a" cumMax={cumMax} vap={vap} best={bestAsk} />
            ))
          )}
        </div>
        <div className="flex h-[30px] shrink-0 items-center gap-2.5 bg-tile px-2.5">
          <Lb tone="dim">{E("Spread", "Gap")}</Lb>
          {d.spread !== null ? <Tiles text={String(d.spread)} size={12} /> : <span className="n text-ink-2">one-sided</span>}
          <span className="flex-1" />
          {d.spread !== null && d.mid !== null ? (
            <Num value={`${((d.spread / d.mid) * 1e4).toFixed(1)} bp`} size={11} tone="dim" />
          ) : null}
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {bRows.length === 0 ? (
            <div className="n py-1 text-center text-[11px] text-ink-3">no bids</div>
          ) : (
            bRows.map((r, i) => (
              <BookRow key={`b${i}-${r.k === "gap" ? r.lo : r.p}`} row={r} side="b" cumMax={cumMax} vap={vap} best={bestBid} />
            ))
          )}
        </div>
        {both && d.mid !== null ? (
          <div className="flex shrink-0 flex-col gap-1.5 border-t border-seam px-2.5 pb-2.5 pt-2">
            <div className="flex justify-between">
              <Lb tone="faint">{E("Cumulative depth", "All waiting orders")}</Lb>
              <Num
                size={11}
                tone="dim"
                value={`bid ${bids.reduce((s, l) => s + l[1], 0)} · ask ${asks.reduce((s, l) => s + l[1], 0)}`}
              />
            </div>
            <DepthCurve bids={bids} asks={asks} mid={d.mid} />
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
