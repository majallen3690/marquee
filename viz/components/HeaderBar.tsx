"use client";

import { Btn, Lb, Num, StatusDot, Tiles } from "./primitives";
import { fmtSimTime } from "@/lib/format";
import { useThrottled } from "@/lib/useFeed";
import type { Connection, Frame, Meta } from "@/lib/types";

export function HeaderBar({
  frame,
  meta,
  connection,
  replay,
  recorded,
  explain,
  onToggleExplain,
}: {
  frame: Frame | null;
  meta: Meta | null;
  connection: Connection;
  replay: boolean;
  recorded: boolean;
  explain: boolean;
  onToggleExplain: () => void;
}) {
  const clock = useThrottled(frame ? fmtSimTime(frame.t) : "00:00.000", 250);
  const status = replay
    ? { dot: "warn" as const, text: "Replay" }
    : connection === "lost"
      ? { dot: "off" as const, text: "Feed lost" }
      : frame === null
        ? { dot: "warn" as const, text: "Connecting" }
        : frame.status === "done"
          ? { dot: "warn" as const, text: "Run complete" }
          : frame.status === "paused"
            ? { dot: "warn" as const, text: "Paused" }
            : recorded
              ? { dot: "live" as const, text: "Recorded run" }
              : { dot: "live" as const, text: "Live" };

  return (
    <header className="flex items-center gap-6 bg-panel px-3">
      <Tiles text="MARQUEE" size={12} hl={3} />
      <span className="flex-1" />
      <Btn kind={explain ? "on" : "seg"} onClick={onToggleExplain}>
        {explain ? "Learn: on" : "Learn"}
      </Btn>
      <span className="flex h-[26px] items-center gap-2.5 border border-seam px-2">
        <Lb tone="faint">Scenario</Lb>
        <Num value={meta?.scenario ?? "—"} />
        <Num value={meta ? `seed ${meta.seed}` : ""} tone="dim" />
      </span>
      <span className="flex items-center gap-2">
        <Lb tone="faint">Sim time</Lb>
        <Tiles text={clock} size={12} />
      </span>
      <span className="flex items-center gap-1.5">
        <StatusDot tone={status.dot} />
        <Lb tone={status.dot === "live" ? "bid" : "dim"}>{status.text}</Lb>
      </span>
    </header>
  );
}
