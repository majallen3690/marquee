/** Client-side accumulation of the live feed: everything the chart, strip and
 * agents table need that is not in a single frame. Sampled by SIM time, so the
 * resolution does not depend on playback speed. Lives in a ref, never in state.
 * It can be backfilled from /api/history (a page that joins late, or Replay). */

import type { Burst, Frame, Level, Trade } from "./types";

const COL_STEP = 250e6; // 250 ms: depth columns, samples, volume buckets
export const COL_NS = COL_STEP;

export interface MidPoint {
  t: number;
  mid: number;
}
export interface Col {
  t: number;
  bids: Level[];
  asks: Level[];
}
export interface Sample {
  t: number;
  mid: number;
  spread: number;
  d5: number; // top-5 depth, both sides
  vwap: number | null;
  net: number;
}
export interface Recent {
  t: number;
  px: number;
  qty: number;
}

/** GET /api/history */
export interface HistoryPayload {
  mids: [t: number, mid: number][];
  frames: Frame[]; // a slim frame every 500 ms
  vol: [bucket: number, up: number, dn: number][];
  last_tid: number;
}

export function top5(levels: Level[]): number {
  let sum = 0;
  for (let i = 0; i < Math.min(5, levels.length); i++) sum += levels[i][1];
  return sum;
}

function recentOf(trades: Trade[], now: number): Recent[] {
  return trades.filter((tr) => tr.t >= now - 5e9).map((tr) => ({ t: tr.t, px: tr.px, qty: tr.qty }));
}

export class History {
  mids: MidPoint[] = [];
  cols: Col[] = [];
  samples: Sample[] = [];
  vol = new Map<number, { up: number; dn: number }>();
  inv = new Map<number, { t: number; inv: number }[]>();
  recent: Recent[] = [];
  seenTid = -1;
  sampled = 0;
  oneSided = 0;
  leverT: number | null = null;
  burst: Burst | null = null;
  private lastMid = -Infinity;
  private lastCol = -Infinity;

  reset(): void {
    this.mids = [];
    this.cols = [];
    this.samples = [];
    this.vol.clear();
    this.inv.clear();
    this.recent = [];
    this.seenTid = -1;
    this.sampled = 0;
    this.oneSided = 0;
    this.leverT = null;
    this.burst = null;
    this.lastMid = -Infinity;
    this.lastCol = -Infinity;
  }

  /** Load the run so far. Frames after this are pushed normally; volume and the
   * tape cursor come from the server so nothing is counted twice. */
  backfill(p: HistoryPayload): void {
    this.reset();
    for (const [t, mid] of p.mids) {
      this.mids.push({ t, mid });
      this.lastMid = t;
    }
    for (const [b, up, dn] of p.vol) this.vol.set(b, { up, dn });
    for (const f of p.frames) this.push(f, true);
    this.seenTid = p.last_tid;
    const last = p.frames[p.frames.length - 1];
    if (last) this.recent = recentOf(last.trades, last.t);
  }

  /** A read-only view of the run up to frame `f` (Replay). */
  slice(f: Frame): History {
    const h = new History();
    h.mids = this.mids.filter((p) => p.t <= f.t);
    h.cols = this.cols.filter((c) => c.t <= f.t);
    h.samples = this.samples.filter((s) => s.t <= f.t);
    for (const [b, v] of this.vol) if (b * COL_STEP <= f.t) h.vol.set(b, v);
    for (const [id, series] of this.inv) h.inv.set(id, series.filter((p) => p.t <= f.t));
    h.recent = recentOf(f.trades, f.t);
    h.sampled = this.sampled;
    h.oneSided = this.oneSided;
    h.leverT = this.leverT !== null && this.leverT <= f.t ? this.leverT : null;
    h.burst = f.stats.burst;
    return h;
  }

  push(f: Frame, backfill = false): void {
    // A frame can trail the last grid sample by under 100 ms; only a real jump back means a restart.
    if (!backfill && f.t < this.lastMid - 2e9) this.reset();
    const both = f.bids.length > 0 && f.asks.length > 0;

    if (f.perturbations.length > 0 && this.leverT === null) {
      this.leverT = Math.min(...f.perturbations.map((p) => p.t));
    }
    this.burst = f.stats.burst;

    if (!backfill) {
      let maxTid = this.seenTid;
      for (const tr of f.trades) {
        if (tr.tid <= this.seenTid) continue;
        maxTid = Math.max(maxTid, tr.tid);
        const bucket = Math.floor(tr.t / COL_STEP);
        const v = this.vol.get(bucket) ?? { up: 0, dn: 0 };
        if (tr.side === 0) v.up += tr.qty;
        else v.dn += tr.qty;
        this.vol.set(bucket, v);
        this.recent.push({ t: tr.t, px: tr.px, qty: tr.qty });
      }
      this.seenTid = maxTid;
      const cutoff = f.t - 5e9;
      let drop = 0;
      while (drop < this.recent.length && this.recent[drop].t < cutoff) drop++;
      if (drop > 0) this.recent.splice(0, drop);

      // The mid series comes from the bridge, sampled on the same 100 ms grid the
      // committed crash gate measures on, so headline numbers match it exactly.
      for (const [t, mid] of f.mids) {
        if (t <= this.lastMid) continue;
        this.lastMid = t;
        this.mids.push({ t, mid });
      }
    }

    if (f.t - this.lastCol >= COL_STEP) {
      this.lastCol = f.t;
      this.sampled++;
      if (!both) {
        this.oneSided++;
      } else {
        this.cols.push({ t: f.t, bids: f.bids, asks: f.asks });
        this.samples.push({
          t: f.t,
          mid: (f.bids[0][0] + f.asks[0][0]) / 2,
          spread: f.asks[0][0] - f.bids[0][0],
          d5: top5(f.bids) + top5(f.asks),
          vwap: f.stats.vwap,
          net: f.stats.net,
        });
      }
      for (const a of f.agents) {
        const series = this.inv.get(a.id) ?? [];
        series.push({ t: f.t, inv: a.inv });
        this.inv.set(a.id, series);
      }
    }
  }
}
