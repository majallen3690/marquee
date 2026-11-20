"use client";

/** All eleven agents: inventory against its limit, P&L, fills, who sold after
 * the lever, and a sparkline of inventory since the start. Noise traders are
 * one row: they are flow, not depth. */

import { Chip, Lb, Panel, Tiles, VoidState } from "./primitives";
import { fmtSigned, LONG_CLASS } from "@/lib/format";
import type { History } from "@/lib/history";
import type { AgentLedger, Frame, Meta } from "@/lib/types";

const COLS = "26px 96px 46px 150px 60px 96px 56px 118px 1fr 104px";

function Spark({ series, cap, leverT }: { series: { t: number; inv: number }[]; cap: number; leverT: number | null }) {
  const W = 88;
  const H = 18;
  if (series.length < 2) return <span className="block" style={{ width: W, height: H }} />;
  const t0 = series[0].t;
  const t1 = series[series.length - 1].t;
  const x = (t: number) => ((t - t0) / Math.max(t1 - t0, 1)) * W;
  const y = (v: number) => H / 2 - Math.max(-1, Math.min(1, v / Math.max(cap, 1))) * (H / 2 - 1);
  const path = series.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t).toFixed(1)},${y(p.inv).toFixed(1)}`).join(" ");
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true" className="block">
      <line x1={0} x2={W} y1={H / 2} y2={H / 2} className="stroke-seam" />
      {leverT !== null && leverT >= t0 ? <rect x={x(leverT) - 0.5} y={0} width={1} height={H} className="fill-amber" /> : null}
      <path d={path} fill="none" className="stroke-ink-1" strokeWidth={1.2} />
    </svg>
  );
}

function UseBar({ inv, cap, hot, soft }: { inv: number; cap: number; hot: boolean; soft: boolean }) {
  const f = Math.min(1, Math.abs(inv) / Math.max(cap, 1));
  return (
    <span className="flex items-center gap-2">
      <span className="relative h-1.5 w-14 bg-tile">
        <span className={`absolute inset-y-0 left-0 ${hot ? "bg-ask" : "bg-ink-2"}`} style={{ width: `${f * 100}%` }} />
      </span>
      <span className="text-[11px] text-ink-2">
        {Math.abs(inv)}/{cap}
        {soft && Math.abs(inv) > cap ? " soft" : ""}
      </span>
    </span>
  );
}

export function AgentsTable({
  frame,
  meta,
  history,
  mid,
  explain,
}: {
  frame: Frame | null;
  meta: Meta | null;
  history: React.RefObject<History>;
  mid: number | null;
  explain: boolean;
}) {
  const E = (a: string, b: string) => (explain ? b : a);
  if (!frame || !meta || mid === null) {
    return (
      <Panel label="Agents" area="agents" id="agents">
        <VoidState>Awaiting feed</VoidState>
      </Panel>
    );
  }
  const spec = new Map(meta.agents.map((a) => [a.id, a]));
  const makers = new Map(frame.makers.map((m) => [m.id, m]));
  const leverT = history.current?.leverT ?? null;
  const pnl = (a: AgentLedger) => a.cash + a.inv * mid;
  const named = frame.agents.filter((a) => a.cls !== "noise");
  const noise = frame.agents.filter((a) => a.cls === "noise");

  const rows = named.map((a) => {
    const isMaker = a.cls === "market_maker";
    const m = makers.get(a.id);
    const cap = isMaker ? (m?.hard ?? 1) : (spec.get(a.id)?.params.max_position ?? 1);
    let state: string;
    let hot: boolean;
    if (isMaker && m) {
      hot = Math.abs(a.inv) > m.soft;
      state = Math.abs(a.inv) >= m.hard ? "Hard limit" : hot ? "Soft limit" : "Quoting";
    } else {
      hot = Math.abs(a.inv) >= cap;
      state = hot ? "At cap" : a.inv === 0 ? "Flat" : a.inv < 0 ? "Short" : "Long";
    }
    const p = pnl(a);
    return (
      <div key={a.id} className="n grid h-6 items-center px-2.5 text-[12px]" style={{ gridTemplateColumns: COLS }}>
        <Tiles text={String(a.id).padStart(2, "0")} size={11} />
        <span className="font-sans text-[13px]">{LONG_CLASS[a.cls]}</span>
        <span className="text-right font-bold">{fmtSigned(a.inv)}</span>
        <span className="pl-3.5">
          <UseBar inv={a.inv} cap={cap} hot={hot} soft={!isMaker} />
        </span>
        <span className={`text-right ${p >= 0 ? "text-bid" : "text-ask"}`}>{fmtSigned(Math.round(p))}</span>
        <span className="text-right text-ink-2">
          {a.fm} · {a.ft}
        </span>
        <span className="text-right text-ink-2">{a.vol ? Math.round((a.mvol / a.vol) * 100) : 0}%</span>
        <span className="text-right">{a.sold_after}</span>
        <span className="pl-3.5">
          <Spark series={history.current?.inv.get(a.id) ?? []} cap={cap} leverT={leverT} />
        </span>
        <span className="text-right">
          <Chip tone={hot ? "ask" : "dim"}>{state}</Chip>
        </span>
      </div>
    );
  });
  const nPnl = noise.reduce((s, a) => s + pnl(a), 0);
  const nVol = noise.reduce((s, a) => s + a.vol, 0);
  const nMake = noise.reduce((s, a) => s + a.mvol, 0);

  return (
    <Panel
      label={`${E("Agents", "Agents · who is trading")} ${frame.agents.length}`}
      area="agents"
      id="agents"
      right={<Lb tone="faint">mk = resting · tk = aggressive · amber tick = lever</Lb>}
    >
      <div className="grid h-[22px] items-center border-b border-seam px-2.5" style={{ gridTemplateColumns: COLS }}>
        <Lb tone="faint">ID</Lb>
        <Lb tone="faint">Agent</Lb>
        <Lb tone="faint" className="text-right">{E("Inv", "Holds")}</Lb>
        <Lb tone="faint" className="pl-3.5">{E("Limit use", "Near its limit?")}</Lb>
        <Lb tone="faint" className="text-right">P&amp;L</Lb>
        <Lb tone="faint" className="text-right">Fills mk · tk</Lb>
        <Lb tone="faint" className="text-right">Maker %</Lb>
        <Lb tone="faint" className="text-right">{E("Sold after lever", "Sold after cut")}</Lb>
        <Lb tone="faint" className="pl-3.5">Inventory</Lb>
        <Lb tone="faint" className="text-right">State</Lb>
      </div>
      {rows}
      {noise.length > 0 ? (
        <div className="n grid h-6 items-center px-2.5 text-[12px] text-ink-2" style={{ gridTemplateColumns: COLS }}>
          <span className="text-[11px]">{`${noise[0].id}–${noise[noise.length - 1].id}`}</span>
          <span className="font-sans text-[13px] text-ink-1">Noise × {noise.length}</span>
          <span className="text-right">{fmtSigned(noise.reduce((s, a) => s + a.inv, 0))}</span>
          <span />
          <span className={`text-right ${nPnl >= 0 ? "text-bid" : "text-ask"}`}>{fmtSigned(Math.round(nPnl))}</span>
          <span className="text-right">
            {noise.reduce((s, a) => s + a.fm, 0)} · {noise.reduce((s, a) => s + a.ft, 0)}
          </span>
          <span className="text-right">{nVol ? Math.round((nMake / nVol) * 100) : 0}%</span>
          <span className="text-right text-ink-1">{noise.reduce((s, a) => s + a.sold_after, 0)}</span>
          <span />
          <span className="text-right">
            <Chip tone="dim">Flow</Chip>
          </span>
        </div>
      ) : null}
    </Panel>
  );
}
