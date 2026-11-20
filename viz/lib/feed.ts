/** What the page needs from a feed, live (the bridge) or recorded (a static file). */

import type { History } from "./history";
import type { Connection, Frame, Meta } from "./types";

export interface Controls {
  pause(): void;
  resume(): void;
  setSpeed(speed: number): void;
  /** null when the lever cannot be pulled (a recorded run cannot change). */
  cut: (() => void) | null;
  /** null for the live bridge: it runs one run per process. */
  restart: (() => void) | null;
}

export interface Feed {
  frame: Frame | null;
  meta: Meta | null;
  connection: Connection;
  history: React.RefObject<History>;
  /** true when playing a recorded run with no server behind it */
  recorded: boolean;
  controls: Controls;
  /** the run as it was at sim time t, for Replay */
  at(t: number): Promise<{ frame: Frame; history: History } | null>;
}

export const STATIC_BUILD = process.env.NEXT_PUBLIC_MARQUEE_STATIC === "1";
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
