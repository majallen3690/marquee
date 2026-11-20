"use client";

/** Trade tape: newest first, price colored by aggressor, with who hit the book. */

import { Glyph, Lb, Num, Panel, VoidState } from "./primitives";
import { fmtPx, fmtSec, SHORT_CLASS } from "@/lib/format";
import type { Frame, Meta } from "@/lib/types";

const COLS = "58px 1fr 34px 64px";

export function TapePanel({ frame, meta, explain }: { frame: Frame | null; meta: Meta | null; explain: boolean }) {
  const cls = new Map((meta?.agents ?? []).map((a) => [a.id, a.class]));
  const rows = frame ? [...frame.trades].reverse().slice(0, 18) : [];
  return (
    <Panel label={explain ? "Tape · trades" : "Tape"} id="tape" right={<Lb tone="faint">taker = who hit the book</Lb>}>
      {!frame ? (
        <VoidState>Awaiting feed</VoidState>
      ) : rows.length === 0 ? (
        <VoidState>No prints yet</VoidState>
      ) : (
        <div className="h-full overflow-hidden">
          <div className="grid h-[22px] items-center border-b border-seam px-2.5" style={{ gridTemplateColumns: COLS }}>
            <Lb tone="faint">Time</Lb>
            <Lb tone="faint" className="text-right">Price</Lb>
            <Lb tone="faint" className="text-right">Qty</Lb>
            <Lb tone="faint" className="text-right">{explain ? "Who hit" : "Taker"}</Lb>
          </div>
          {rows.map((tr, i) => {
            const c = cls.get(tr.tka);
            return (
              <div key={tr.tid} className="n grid h-5 items-center px-2.5 text-[12px]" style={{ gridTemplateColumns: COLS }}>
                <span className="text-[11px] text-ink-2">{fmtSec(tr.t)}</span>
                <span className="text-right">
                  <Glyph dir={tr.side === 0 ? "up" : "down"} />{" "}
                  <Num value={fmtPx(tr.px)} tone={tr.side === 0 ? "bid" : "ask"} flash={i === 0} />
                </span>
                <span className="text-right">{tr.qty}</span>
                <span className={`text-right text-[11px] ${c && c !== "noise" ? "text-ink-1" : "text-ink-2"}`}>
                  {c ? `${SHORT_CLASS[c]} ${tr.tka}` : tr.tka}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
