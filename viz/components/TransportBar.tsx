"use client";

/** Bottom bar: pause / resume, speed, and a read-only run timeline with the
 * lever and the engine's events marked. (Scrubbing arrives with Replay.) */

import { useEffect, useRef, useState } from "react";
import { Btn, Lb, Num } from "./primitives";
import { fmtSimTime } from "@/lib/format";
import type { Controls } from "@/lib/feed";
import type { History } from "@/lib/history";
import type { Derived } from "@/lib/derive";
import type { Frame } from "@/lib/types";

const SPEEDS = [0.5, 1, 2, 4, 8];
const W = 560;
const H = 26;

function Timeline({
  frame,
  d,
  history,
  onScrub,
}: {
  frame: Frame;
  d: Derived;
  history: React.RefObject<History>;
  onScrub: ((t: number) => void) | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const seek = (clientX: number) => {
    const r = box.current?.getBoundingClientRect();
    if (!r || !onScrub) return;
    onScrub(Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * frame.horizon);
  };
  const mids = history.current?.mids ?? [];
  const x = (t: number) => (t / frame.horizon) * W;
  let path = "";
  if (mids.length > 1) {
    let lo = Infinity;
    let hi = -Infinity;
    for (const p of mids) {
      lo = Math.min(lo, p.mid);
      hi = Math.max(hi, p.mid);
    }
    const step = Math.max(1, Math.floor(mids.length / 300));
    const pts: string[] = [];
    for (let i = 0; i < mids.length; i += step) {
      const p = mids[i];
      pts.push(`${pts.length ? "L" : "M"}${x(p.t).toFixed(1)},${(3 + ((hi - p.mid) / Math.max(hi - lo, 1)) * (H - 9)).toFixed(1)}`);
    }
    path = pts.join(" ");
  }
  const px = x(frame.t);
  return (
    <div
      ref={box}
      className={onScrub ? "cursor-pointer" : ""}
      onPointerDown={(e) => {
        if (!onScrub) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        seek(e.clientX);
      }}
      onPointerMove={(e) => {
        if (onScrub && e.buttons === 1) seek(e.clientX);
      }}
    >
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={`Run timeline, playhead at ${(frame.t / 1e9).toFixed(0)} seconds of ${(frame.horizon / 1e9).toFixed(0)}`}
      className="block"
    >
      <rect x={0} y={H - 2} width={W} height={2} className="fill-tile" />
      <rect x={0} y={H - 2} width={px} height={2} className="fill-ink-2" />
      <path d={path} fill="none" className="stroke-ink-3" strokeWidth={1} />
      {d.events.map((e, i) => (
        <rect key={i} x={x(e.t) - 1} y={H - 4} width={2} height={4} className="fill-ink-2" />
      ))}
      {d.leverT !== null ? <rect x={x(d.leverT) - 1} y={0} width={2} height={H} className="fill-amber" /> : null}
      <rect x={px - 1} y={0} width={2} height={H} className="fill-ink-1" />
      <rect x={px - 4} y={0} width={8} height={5} className="fill-ink-1" />
    </svg>
    </div>
  );
}

export function TransportBar({
  frame,
  d,
  history,
  replay,
  controls,
  onScrub,
  onLive,
}: {
  frame: Frame | null;
  d: Derived | null;
  history: React.RefObject<History>;
  replay: boolean;
  controls: Controls;
  onScrub: (t: number) => void;
  onLive: () => void;
}) {
  const [speed, setSpeed] = useState(1);
  useEffect(() => {
    if (frame) setSpeed(frame.speed); // the bridge owns the truth
  }, [frame]);
  const paused = frame?.status === "paused";
  const done = frame?.status === "done";
  const canScrub = replay || paused || done; // the past is only reviewable when the run is standing still
  return (
    <footer className="flex items-center gap-3 bg-panel px-3">
      {replay ? (
        <Btn kind="amber" hint="Esc" onClick={onLive}>
          Back to live
        </Btn>
      ) : done && controls.restart ? (
        <Btn kind="on" onClick={controls.restart}>
          Play again
        </Btn>
      ) : (
        <Btn kind={done ? "off" : "on"} hint="Space" onClick={() => (paused ? controls.resume() : controls.pause())}>
          {paused ? "Resume" : "Pause"}
        </Btn>
      )}
      <span className="flex gap-px">
        {SPEEDS.map((s) => (
          <Btn
            key={s}
            kind={speed === s ? "on" : "seg"}
            onClick={() => {
              setSpeed(s);
              controls.setSpeed(s);
            }}
          >
            {s === 0.5 ? "½×" : `${s}×`}
          </Btn>
        ))}
      </span>
      <Num value="00:00" size={11} tone="dim" />
      {frame && d ? (
        <Timeline frame={frame} d={d} history={history} onScrub={canScrub ? onScrub : null} />
      ) : (
        <span style={{ width: W }} />
      )}
      <Num value={frame ? fmtSimTime(frame.horizon).slice(0, 5) : "01:00"} size={11} tone="dim" />
      <span className="flex-1" />
      <Lb tone={replay ? "amber" : "faint"}>
        {replay
          ? "Replay · the past, read-only"
          : canScrub
            ? "Click the timeline to review"
            : frame
              ? `${frame.events.toLocaleString("en-US")} events`
              : ""}
      </Lb>
    </footer>
  );
}
