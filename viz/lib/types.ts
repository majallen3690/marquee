/** Wire contract with the bridge (marquee.server.session._frame / meta). */

export type Level = [price: number, qty: number];

export interface Trade {
  tid: number;
  t: number;
  px: number;
  qty: number;
  side: number; // taker side: 0 = buy (up-tick), 1 = sell
  tka: number; // taker agent id
}

export interface MakerState {
  id: number;
  inv: number;
  soft: number;
  hard: number;
  size: number;
  half: number;
}

export interface AgentLedger {
  id: number;
  cls: "market_maker" | "momentum" | "noise";
  inv: number;
  cash: number; // ticks * shares; P&L = cash + inv * mid
  fm: number; // fills as maker
  ft: number; // fills as taker
  vol: number;
  mvol: number; // volume filled as maker
  sold_after: number; // taker-sell volume since the first lever
}

/** The biggest taker-sell burst since the first lever (grouped by time and taker). */
export interface Burst {
  t: number;
  aid: number;
  qty: number;
  lo: number;
  hi: number;
}

export interface RunStats {
  trades: number;
  vwap: number | null;
  net: number; // taker buys minus taker sells, whole run
  burst: Burst | null;
}

export interface PerturbationMark {
  t: number;
  aid: number;
  param: string;
  value: number;
}

export interface Frame {
  type: "frame";
  t: number;
  horizon: number;
  status: "live" | "paused" | "done";
  speed: number;
  events: number;
  bids: Level[];
  asks: Level[];
  trades: Trade[];
  makers: MakerState[];
  agents: AgentLedger[];
  stats: RunStats;
  mids: [t: number, mid: number][]; // last 60 samples on the 100 ms gate grid
  perturbations: PerturbationMark[];
}

export interface AgentSpec {
  id: number;
  class: AgentLedger["cls"];
  params: Record<string, number>;
}

export interface ScheduledLever {
  t: number;
  aid: number;
  param: string;
  value: number;
}

export interface Meta {
  scenario: string;
  seed: number;
  horizon_ns: number;
  scheduled: ScheduledLever[];
  agents: AgentSpec[];
}

export type Connection = "connecting" | "live" | "lost";
