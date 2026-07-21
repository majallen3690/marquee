"use client";

/** Left dock: transport, maker state, perturbation levers. The amber button is
 * the demo's trigger — the human hand on the market. */

import { useEffect, useState } from "react";
import { MicroLabel, Num, TermButton, TermSlider, VoidState } from "./primitives";
import { postControl, postPerturb } from "@/lib/useFeed";
import type { Frame, MakerState } from "@/lib/types";

const SPEEDS = [0.5, 1, 2, 4, 8];

function MakerGauge({ maker }: { maker: MakerState }) {
  const ratio = Math.max(-1, Math.min(1, maker.inv / Math.max(maker.hard, 1)));
  const warn = Math.abs(maker.inv) >= maker.soft;
  const barColor = warn ? "bg-accent" : "bg-ink-2";
  return (
    <div className="border border-hairline p-2">
      <div className="flex items-center justify-between">
        <MicroLabel>MAKER {maker.id}</MicroLabel>
        <span className="text-dense">
          <Num value={maker.inv} tone={warn ? "accent" : "plain"} flash />
          <span className="text-ink-2"> / ±{maker.hard}</span>
        </span>
      </div>
      <div className="relative mt-1.5 h-1.5 bg-surface-2">
        <div className="absolute inset-y-0 left-1/2 w-px bg-hairline" />
        <div
          className={`absolute inset-y-0 ${barColor}`}
          style={
            ratio >= 0
              ? { left: "50%", width: `${ratio * 50}%` }
              : { right: "50%", width: `${-ratio * 50}%` }
          }
        />
      </div>
      <div className="mt-1 flex justify-between text-axis text-ink-2">
        <span>SIZE {maker.size}</span>
        <span>HALF {maker.half}</span>
        <span>SOFT {maker.soft}</span>
      </div>
    </div>
  );
}

function PerturbLever({ maker }: { maker: MakerState }) {
  const [hard, setHard] = useState(maker.hard);
  const [size, setSize] = useState(maker.size);
  const [half, setHalf] = useState(maker.half);
  return (
    <div className="border border-hairline p-2">
      <MicroLabel>PERTURB MAKER {maker.id}</MicroLabel>
      <div className="mt-1.5 flex flex-col gap-1.5">
        <TermSlider label="HARD" min={5} max={500} step={5} value={hard} onChange={setHard} />
        <TermSlider label="SIZE" min={1} max={120} step={1} value={size} onChange={setSize} />
        <TermSlider label="HALF" min={1} max={30} step={1} value={half} onChange={setHalf} />
        <TermButton
          onClick={() => {
            void postPerturb(maker.id, "hard_limit", hard);
            void postPerturb(maker.id, "quote_size", size);
            void postPerturb(maker.id, "half_spread", half);
          }}
        >
          APPLY
        </TermButton>
      </div>
    </div>
  );
}

export function ControlDock({ frame }: { frame: Frame | null }) {
  const [paused, setPaused] = useState(false);
  const [speed, setSpeed] = useState(1);

  // The bridge owns the truth; mirror it so reconnects don't lie.
  useEffect(() => {
    if (frame) {
      setPaused(frame.status === "paused");
      setSpeed(frame.speed);
    }
  }, [frame]);

  if (!frame) return <VoidState>AWAITING FEED</VoidState>;

  const collapseAll = () => {
    for (const maker of frame.makers) {
      void postPerturb(maker.id, "soft_limit", 5);
      void postPerturb(maker.id, "hard_limit", 10);
      void postPerturb(maker.id, "quote_size", 5);
      void postPerturb(maker.id, "half_spread", maker.id % 2 === 0 ? 15 : 12);
    }
  };

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto overflow-x-hidden p-3">
      <div>
        <MicroLabel>TRANSPORT</MicroLabel>
        <div className="mt-1.5 flex flex-wrap gap-1">
          <TermButton
            active={!paused}
            onClick={() => {
              const next = !paused;
              setPaused(next);
              void postControl(next ? "pause" : "resume");
            }}
          >
            {paused ? "RESUME" : "PAUSE"}
          </TermButton>
          {SPEEDS.map((s) => (
            <TermButton
              key={s}
              active={speed === s}
              onClick={() => {
                setSpeed(s);
                void postControl("speed", s);
              }}
            >
              {s}×
            </TermButton>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <MicroLabel>MAKERS</MicroLabel>
        {frame.makers.map((maker) => (
          <MakerGauge key={maker.id} maker={maker} />
        ))}
      </div>

      <div className="flex flex-col gap-2">
        <MicroLabel>LEVERS</MicroLabel>
        <TermButton danger onClick={collapseAll} className="h-8">
          COLLAPSE MAKER RISK
        </TermButton>
        {frame.makers.map((maker) => (
          <PerturbLever key={maker.id} maker={maker} />
        ))}
      </div>
    </div>
  );
}
