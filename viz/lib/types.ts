/** Wire contract with the bridge (marquee.server.session._frame). */

export type Level = [price: number, qty: number];

export interface Trade {
  tid: number;
  t: number;
  px: number;
  qty: number;
  side: number; // taker side: 0 = buy (up-tick), 1 = sell
}

export interface MakerState {
  id: number;
  inv: number;
  soft: number;
  hard: number;
  size: number;
  half: number;
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
  perturbations: PerturbationMark[];
}

export type Connection = "connecting" | "live" | "lost";

export interface MidPoint {
  t: number;
  mid: number;
}
