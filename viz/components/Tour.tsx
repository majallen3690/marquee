"use client";

/** Learn mode's guided tour: five steps, each outlining one panel (CSS, by
 * data-panel) with a card that explains it in plain English. The numbers in the
 * card come from the live feed. */

import { Btn, Lb } from "./primitives";
import type { Derived } from "@/lib/derive";

export const TOUR_AREAS = ["strip", "book", "lever", "chart", "agents"] as const;

interface Step {
  area: (typeof TOUR_AREAS)[number];
  title: string;
  body: (d: Derived | null) => string;
  at: React.CSSProperties; // where the card sits, clear of the outlined panel
}

const STEPS: Step[] = [
  {
    area: "strip",
    title: "The numbers that matter",
    body: () =>
      "Top left is the price: the middle of the best buy and the best sell. The red figure is how far it has fallen since the market makers cut risk. Everything on this strip updates as it happens, and each figure has its plain name above and its trader's name below.",
    at: { left: 12, top: 140 },
  },
  {
    area: "book",
    title: "Who is waiting",
    body: () =>
      "Each row is a price. Teal rows are buyers waiting, coral rows are sellers waiting, and the bar is how many shares. The gap between the best buy and the best sell is the spread: when it is wide, trading is costly and the price jumps.",
    at: { left: 12, top: 140 },
  },
  {
    area: "lever",
    title: "The one thing you can change",
    body: () =>
      "Two market makers keep both sides of the market stocked. The lever tells them to hold less stock, quote smaller and stand further from the price. It is the only thing the scenario changes: nobody ever tells the price what to do.",
    at: { left: 12, top: 140 },
  },
  {
    area: "chart",
    title: "The lever’s effect",
    body: (d) =>
      d?.fired && d.move !== null
        ? `The makers were told to cut risk. They shrank their orders and stepped back, so every trade moved the price further: ${d.move < 0 ? "−" : "+"}${Math.abs(d.move).toFixed(1)} ticks in ${d.moveWindowS >= 5 ? "5" : d.moveWindowS.toFixed(1)} seconds. The numbered markers list what happened, in order. Nobody scripted the price.`
        : "When the lever fires the makers shrink their orders and step back from the price. With fewer orders waiting, every trade moves the price further, in whichever direction the flow is going. Watch the coloured bands thin out. Nobody scripts the price.",
    at: { right: 12, top: 430 },
  },
  {
    area: "agents",
    title: "Who did what",
    body: () =>
      "After the cut, most of the selling was ordinary random traders hitting an empty book; the trend-followers (momentum) added to it and ran into their limits. Every number comes from one seeded run and replays exactly: pause, then click the timeline to go back in time.",
    at: { right: 12, top: 180 },
  },
];

export function Tour({
  step,
  d,
  onStep,
  onEnd,
}: {
  step: number;
  d: Derived | null;
  onStep: (n: number) => void;
  onEnd: () => void;
}) {
  const s = STEPS[step];
  const last = step === STEPS.length - 1;
  return (
    <section
      aria-label={`Guided tour, step ${step + 1} of ${STEPS.length}`}
      className="absolute z-10 flex w-[400px] flex-col gap-2.5 border border-ink-2 border-t-[3px] border-t-amber bg-panel px-4 py-3.5"
      style={s.at}
    >
      <div className="flex items-center gap-[3px]">
        {STEPS.map((_, i) => (
          <span key={i} className={`h-[3px] w-[22px] ${i <= step ? "bg-ink-1" : "bg-tile"}`} />
        ))}
        <span className="flex-1" />
        <Lb tone="dim">{`Tour · ${step + 1} of ${STEPS.length}`}</Lb>
      </div>
      <span className="font-word text-[22px] font-bold tracking-[0.01em]">{s.title}</span>
      <span className="font-sans text-[13px] leading-[19px] text-ink-1">{s.body(d)}</span>
      <div className="flex items-center gap-1.5">
        {step > 0 ? (
          <Btn h={28} onClick={() => onStep(step - 1)}>
            Back
          </Btn>
        ) : null}
        <Btn kind="on" h={28} onClick={() => (last ? onEnd() : onStep(step + 1))}>
          {last ? "Done" : "Next"}
        </Btn>
        <span className="flex-1" />
        {!last ? (
          <button type="button" onClick={onEnd} className="font-word text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-2 underline">
            End tour
          </button>
        ) : null}
      </div>
    </section>
  );
}
