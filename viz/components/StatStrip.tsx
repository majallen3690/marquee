"use client";

/** The strip under the header: one headline number for the crash, then the
 * supporting figures, each with a plain-English subtitle. Tiles update at ~4 Hz. */

import { Chip, Lb, Num, Stat, Tiles } from "./primitives";
import { fmtMid, fmtSigned } from "@/lib/format";
import { useThrottled } from "@/lib/useFeed";
import type { Derived } from "@/lib/derive";
import type { Frame } from "@/lib/types";

const REGIME = {
  stable: { tone: "bid", chip: "Stable", plain: "Calm", sub: "both sides deep" },
  stressed: { tone: "amber", chip: "Stressed", plain: "Strained", sub: "book is thinning" },
  dislocated: { tone: "ask", chip: "Dislocated", plain: "Thin and jumpy", sub: "called dislocated" },
} as const;

export function StatStrip({ frame, d, explain }: { frame: Frame | null; d: Derived | null; explain: boolean }) {
  const E = (a: string, b: string) => (explain ? b : a);
  const midText = useThrottled(d?.mid != null ? fmtMid(d.mid) : "—", 250);
  if (!frame || !d) {
    return <div data-panel="strip" className="bg-panel" />;
  }
  const r = REGIME[d.regime];
  const heavy = d.imbalance < 0 ? "sellers" : "buyers";
  const net = frame.stats.net;

  let crash: React.ReactNode;
  if (!d.fired) {
    crash = (
      <Stat
        label={E("Move since lever", "Price change since the cut")}
        sub={d.leftS !== null ? `lever fires in ${d.leftS.toFixed(1)} s` : "no lever scheduled"}
      >
        <Num value="—" size={14} tone="dim" />
      </Stat>
    );
  } else if (d.move === null) {
    crash = (
      <Stat label={E("Move since lever", "Price change since the cut")} sub="page joined after the lever">
        <Num value="—" size={14} tone="dim" />
      </Stat>
    );
  } else {
    const down = (d.move ?? 0) < 0;
    const mag = Math.abs(d.move ?? 0);
    const win = d.moveWindowS >= 5 ? "in 5 s" : `${d.moveWindowS.toFixed(1)} s in`;
    const amp = d.amp !== null ? ` · ${d.amp.toFixed(1)}× ${E("normal", "any normal 5 s")}` : "";
    const ctl = d.controlMove !== null ? ` · no lever ${d.controlMove < 0 ? "−" : "+"}${Math.abs(d.controlMove).toFixed(1)}` : "";
    crash = (
      <Stat label={E("Move since lever", "Price change since the cut")} sub={`${win}${amp}${ctl}`}>
        <Num value={`${down ? "▼" : "▲"} ${mag.toFixed(1)}`} size={14} bold tone={down ? "ask" : "bid"} />
      </Stat>
    );
  }

  return (
    <div data-panel="strip" className="flex items-center gap-6 bg-panel px-3">
      <div className="flex flex-col gap-0.5">
        <Lb tone="faint">{E("Mid", "Price now")}</Lb>
        <Tiles text={midText} size={17} />
        <span className="font-sans text-[11px] text-ink-2">midpoint of best buy and sell</span>
      </div>
      {crash}
      <Stat label={E("Spread", "Gap buy ↔ sell")} sub={E("buy↔sell gap", "called the spread")}>
        <span className="n text-[14px]">
          {d.spread !== null ? (
            <>
              {d.spread} <span className="text-[11px] text-ink-2">ticks</span>
            </>
          ) : (
            <span className="text-ask">one-sided</span>
          )}
        </span>
      </Stat>
      <Stat label={E("Top-5 depth", "Orders near the price")} sub={E("orders near the price", "called top-5 depth")}>
        <span className="n text-[14px]">
          {d.d5} <span className="text-[11px] text-ink-2">/ {Math.round(d.base.d5)} {d.fired ? "before" : "avg so far"}</span>
        </span>
      </Stat>
      <Stat label="VWAP" sub="average price paid">
        <Num value={frame.stats.vwap !== null ? fmtMid(frame.stats.vwap) : "—"} size={14} />
      </Stat>
      <Stat label={E("Imbalance", "Buyers vs sellers")} sub={E(`${heavy} outweigh`, "called imbalance")}>
        <Num value={fmtSigned(d.imbalance, 2)} size={14} />
      </Stat>
      <Stat label={E("Net flow", "Net buying")} sub={E("buys minus sells", "called net taker flow")}>
        <Num value={fmtSigned(net)} size={14} tone={net < 0 ? "ask" : "bid"} />
      </Stat>
      <Stat label={E("Two-sided", "Both sides quoted")} sub="time with bids and asks">
        <Num value={`${d.twoSidedPct.toFixed(1)}%`} size={14} />
      </Stat>
      <span className="flex-1" />
      <div className="flex flex-col items-end gap-[3px]">
        <Chip tone={r.tone}>{E(r.chip, r.plain)}</Chip>
        <span className="font-sans text-[11px] text-ink-2">{E(r.sub === "called dislocated" ? "thin and jumpy" : r.sub, r.sub === "called dislocated" ? "called dislocated" : r.sub)}</span>
      </div>
    </div>
  );
}
