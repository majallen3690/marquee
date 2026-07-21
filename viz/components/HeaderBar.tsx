"use client";

import { Num, StatusDot } from "./primitives";
import { fmtSimTime } from "@/lib/format";
import type { Connection, Frame } from "@/lib/types";

export function HeaderBar({
  frame,
  connection,
  scenario,
}: {
  frame: Frame | null;
  connection: Connection;
  scenario: string;
}) {
  const status =
    connection === "lost"
      ? { dot: "off" as const, text: "FEED LOST" }
      : frame === null
        ? { dot: "warn" as const, text: "CONNECTING" }
        : frame.status === "done"
          ? { dot: "warn" as const, text: "RUN COMPLETE" }
          : frame.status === "paused"
            ? { dot: "warn" as const, text: "PAUSED" }
            : { dot: "live" as const, text: "LIVE" };

  return (
    <header className="flex h-7 items-center gap-4 border-b border-hairline bg-surface-1 px-3 [grid-area:header]">
      <span className="text-figure font-semibold tracking-[0.2em]">
        MAR<span className="text-accent">Q</span>UEE
      </span>
      <span className="text-micro uppercase tracking-[0.08em] text-ink-2">{scenario}</span>
      <span className="flex-1" />
      <span className="text-dense text-ink-2">
        SIM <Num value={frame ? fmtSimTime(frame.t) : "—"} tone="plain" />
      </span>
      <span className="text-dense text-ink-2">
        {frame ? `${frame.speed}×` : ""}
      </span>
      <span className="text-dense text-ink-2">
        {frame ? `${frame.events.toLocaleString("en-US")} EV` : ""}
      </span>
      <span className="flex items-center gap-1.5 text-micro uppercase tracking-[0.08em] text-ink-2">
        <StatusDot tone={status.dot} /> {status.text}
      </span>
    </header>
  );
}
