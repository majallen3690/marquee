/** Everything the strip, chart markers and agents table show that is computed
 * rather than received. Pure: (history, frame, meta) -> numbers. Every figure
 * here is derived from the feed; nothing is hard-coded (the headline must hold
 * for a lever pulled at any time, not just the scenario's scripted 30 s). */

import { fmtPx, SHORT_CLASS } from "./format";
import { top5, type History, type MidPoint, type Sample } from "./history";
import type { Frame, Meta } from "./types";

export type Regime = "stable" | "stressed" | "dislocated";

export interface Ev {
  t: number;
  kind: "limit" | "cap" | "sweep" | "depth" | "spread";
  text: string;
}

export interface Derived {
  mid: number | null;
  spread: number | null;
  d5: number;
  base: { d5: number; spread: number };
  imbalance: number;
  fired: boolean;
  leverT: number | null; // fired lever, else the scripted one
  leftS: number | null; // seconds until the scripted lever
  m0: number | null; // mid when the lever fired
  move: number | null; // signed extreme move since the lever, within 5 s
  moveWindowS: number;
  w5: number | null; // worst normal 5 s range before the lever
  amp: number | null;
  /** the no-lever twin's signed extreme move over the same window (ADR-021) */
  controlMove: number | null;
  regime: Regime;
  twoSidedPct: number;
  events: Ev[];
}

/** the grid sample at or just before t (the gate's mid_at_t) */
function midAtOrBefore(h: History, t: number): number | null {
  let out: number | null = null;
  for (const p of h.mids) {
    if (p.t > t) break;
    out = p.mid;
  }
  return out;
}

function median(xs: number[]): number {
  if (xs.length === 0) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

/** The gate's "worst normal 5 s": over the 150 grid samples up to the lever,
 * the largest max-min of mid across 50-sample windows, stepped 10 samples
 * (tests/test_m5_crash.py). Null when the page joined too late to have them all. */
function worstNormalRange(h: History, leverT: number): number | null {
  const pre = h.mids.filter((p) => p.t > leverT - 15e9 && p.t <= leverT);
  if (pre.length < 150) return null;
  let worst = 0;
  for (let i = 0; i < pre.length - 50; i += 10) {
    let lo = Infinity;
    let hi = -Infinity;
    for (let j = i; j < i + 50; j++) {
      lo = Math.min(lo, pre[j].mid);
      hi = Math.max(hi, pre[j].mid);
    }
    worst = Math.max(worst, hi - lo);
  }
  return worst;
}

export function derive(h: History, f: Frame, meta: Meta | null, control: MidPoint[] | null = null): Derived {
  const both = f.bids.length > 0 && f.asks.length > 0;
  const mid = both ? (f.bids[0][0] + f.asks[0][0]) / 2 : null;
  const spread = both ? f.asks[0][0] - f.bids[0][0] : null;
  const d5 = top5(f.bids) + top5(f.asks);
  const bq = f.bids.slice(0, 5).reduce((s, l) => s + l[1], 0);
  const aq = f.asks.slice(0, 5).reduce((s, l) => s + l[1], 0);
  const imbalance = bq + aq > 0 ? (bq - aq) / (bq + aq) : 0;

  const leverT = h.leverT;
  const fired = leverT !== null;
  const scripted = meta?.scheduled.length ? Math.min(...meta.scheduled.map((s) => s.t)) : null;
  const leftS = !fired && scripted !== null && scripted > f.t ? (scripted - f.t) / 1e9 : null;

  const pre: Sample[] = h.samples.filter((s) => leverT === null || s.t < leverT);
  const base = {
    d5: pre.length ? pre.reduce((s, x) => s + x.d5, 0) / pre.length : d5,
    spread: pre.length ? median(pre.map((x) => x.spread)) : (spread ?? 1),
  };

  let m0: number | null = null;
  let move: number | null = null;
  let w5: number | null = null;
  let amp: number | null = null;
  let moveWindowS = 0;
  if (leverT !== null) {
    m0 = midAtOrBefore(h, leverT);
    const end = leverT + 5e9;
    moveWindowS = Math.min(5, (f.t - leverT) / 1e9);
    if (m0 !== null) {
      for (const p of h.mids) {
        if (p.t <= leverT || p.t > end) continue;
        if (move === null || Math.abs(p.mid - m0) > Math.abs(move)) move = p.mid - m0;
      }
    }
    w5 = worstNormalRange(h, leverT);
    if (move !== null && w5 !== null && w5 > 0) amp = Math.abs(move) / w5;
  }

  let controlMove: number | null = null;
  if (leverT !== null && control && control.length > 0) {
    let c0: number | null = null;
    for (const p of control) {
      if (p.t > leverT) break;
      c0 = p.mid;
    }
    if (c0 !== null) {
      for (const p of control) {
        if (p.t <= leverT || p.t > Math.min(leverT + 5e9, f.t)) continue;
        if (controlMove === null || Math.abs(p.mid - c0) > Math.abs(controlMove)) controlMove = p.mid - c0;
      }
    }
  }

  const depthRatio = base.d5 > 0 ? d5 / base.d5 : 1;
  const spreadRatio = base.spread > 0 && spread !== null ? spread / base.spread : 1;
  const regime: Regime =
    depthRatio < 0.4 || spreadRatio >= 3
      ? "dislocated"
      : depthRatio < 0.7 || spreadRatio >= 1.8
        ? "stressed"
        : "stable";

  const events: Ev[] = [];
  if (leverT !== null) {
    const label = (id: number): string => {
      const cls = f.agents.find((a) => a.id === id)?.cls ?? "noise";
      return `${SHORT_CLASS[cls]} ${id}`;
    };
    for (const m of f.makers) {
      const hit = (h.inv.get(m.id) ?? []).find((p) => p.t >= leverT && Math.abs(p.inv) >= m.hard);
      if (hit) events.push({ t: hit.t, kind: "limit", text: `Maker ${m.id} hits its hard limit` });
    }
    for (const spec of meta?.agents ?? []) {
      if (spec.class !== "momentum" || !spec.params.max_position) continue;
      const cap = spec.params.max_position;
      const hit = (h.inv.get(spec.id) ?? []).find((p) => p.t >= leverT && Math.abs(p.inv) >= cap);
      if (hit) events.push({ t: hit.t, kind: "cap", text: `Momentum ${spec.id} reaches its cap of ${cap}` });
    }
    if (h.burst && h.burst.qty >= 10) {
      const b = h.burst;
      events.push({
        t: b.t,
        kind: "sweep",
        text: `${label(b.aid)} sells ${b.qty} through ${fmtPx(b.hi)} → ${fmtPx(b.lo)}`,
      });
    }
    const post = h.samples.filter((s) => s.t >= leverT);
    if (post.length > 0) {
      const lo = post.reduce((a, b) => (b.d5 < a.d5 ? b : a));
      // only call the trough once the book has begun to refill, so the marker does not chase
      if (d5 >= lo.d5 * 1.25 || f.t - lo.t >= 1e9) {
        events.push({ t: lo.t, kind: "depth", text: `Top-5 depth bottoms at ${lo.d5}` });
      }
      const hi = post.reduce((a, b) => (b.spread > a.spread ? b : a));
      if ((spread !== null && spread <= hi.spread * 0.8) || f.t - hi.t >= 1e9) {
        events.push({ t: hi.t, kind: "spread", text: `Spread peaks at ${hi.spread} ticks` });
      }
    }
    events.sort((a, b) => a.t - b.t);
  }

  return {
    mid,
    spread,
    d5,
    base,
    imbalance,
    fired,
    leverT: leverT ?? scripted,
    leftS,
    m0,
    move,
    moveWindowS,
    w5,
    amp,
    regime,
    twoSidedPct: h.sampled > 0 ? (1 - h.oneSided / h.sampled) * 100 : 100,
    events,
    controlMove,
  };
}
