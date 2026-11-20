"use client";

/** The lever, laid out like an order ticket: the rule changes (before → after,
 * in amber) and one button. It fires the scenario's own scripted lever. */

import { Btn, Lb, Panel } from "./primitives";
import { presetFor } from "@/lib/levers";
import type { Derived } from "@/lib/derive";
import type { Frame, Meta } from "@/lib/types";

const COLS = "1fr 74px 74px";
const PARAMS: [string, string][] = [
  ["hard_limit", "hard limit"],
  ["soft_limit", "soft limit"],
  ["quote_size", "quote size"],
  ["half_spread", "half spread"],
];

export function LeverTicket({
  frame,
  meta,
  d,
  replay,
  explain,
  onCut,
}: {
  frame: Frame | null;
  meta: Meta | null;
  d: Derived | null;
  replay: boolean;
  explain: boolean;
  onCut: (() => void) | null;
}) {
  if (!meta || !frame || !d) {
    return (
      <Panel label="Lever" id="lever">
        <div className="p-2.5">
          <Lb>Awaiting feed</Lb>
        </div>
      </Panel>
    );
  }
  const makers = meta.agents.filter((a) => a.class === "market_maker");
  const preset = presetFor(meta);
  const after = (aid: number, param: string) => preset.find((p) => p.aid === aid && p.param === param)?.value;
  const done = frame.status === "done" || replay || onCut === null;
  const status = onCut === null
    ? "This is a recorded run, so the lever is fixed at 30 s. To pull it yourself, run the live version: uv run marquee-demo."
    : replay
    ? "Replay shows the past. Go back to live to change the market."
    : frame.status === "done"
    ? "The run is complete: nothing left to cut."
    : d.fired
      ? explain
        ? "Changes the makers’ rules, not the price. Whatever happens next is up to the agents."
        : "Fired. Written to the event log, so this run replays exactly."
      : d.leftS !== null
        ? `Fires by itself in ${d.leftS.toFixed(1)} s. Press to fire it now.`
        : "Press to fire it now. It lands 1 ms ahead of the playhead.";

  return (
    <Panel label={explain ? "Lever · change a rule" : "Lever"} id="lever">
      <div className="flex flex-col gap-2.5 p-2.5">
        <span className="font-sans text-[12px] leading-[17px] text-ink-2">
          {explain
            ? "Tell both market makers to hold less stock, quote smaller and stand further from the price."
            : "Cut both makers’ risk limits, quote size and how close they quote."}
        </span>
        <div className="-mx-2.5 border-t border-seam">
          <div className="grid h-[22px] items-center border-b border-seam px-2.5" style={{ gridTemplateColumns: COLS }}>
            <Lb tone="faint">Rule</Lb>
            {makers.map((m) => (
              <Lb key={m.id} tone="faint" className="text-right">{`Maker ${m.id}`}</Lb>
            ))}
          </div>
          {PARAMS.map(([key, name]) => (
            <div key={key} className="n grid h-5 items-center px-2.5 text-[12px]" style={{ gridTemplateColumns: COLS }}>
              <span className="text-ink-2">{name}</span>
              {makers.map((m) => (
                <span key={m.id} className="text-right">
                  <span className="text-ink-3">{m.params[key]}→</span>
                  <span className="font-bold text-amber">{after(m.id, key) ?? "—"}</span>
                </span>
              ))}
            </div>
          ))}
        </div>
        <Btn kind={done ? "off" : "amber"} hint="⇧C" h={32} full onClick={() => onCut?.()}>
          Cut maker risk
        </Btn>
        <span className="font-sans text-[12px] leading-[17px] text-ink-2">{status}</span>
      </div>
    </Panel>
  );
}
