"use client";

/** The chart: a depth map (teal bids, coral asks, brighter = more size) under
 * the mid line, VWAP, the amber lever, the measured drop, and numbered events;
 * volume and net taker flow in a pane below. One canvas, redrawn at 10 Hz from
 * the History ref. Flat fills and 1 px lines only: no blur, glow or gradient. */

import { useEffect, useRef } from "react";
import { COL_NS, type History } from "@/lib/history";
import type { Derived } from "@/lib/derive";
import { fmtSec, fmtPx } from "@/lib/format";
import type { Frame } from "@/lib/types";
import { Lb, VoidState } from "./primitives";

const AXW = 62; // right price axis
const VOL_H = 98;
const TIME_H = 26;
const GAP = 6;

interface Tokens {
  gutter: string;
  panel: string;
  seam: string;
  ink1: string;
  ink2: string;
  ink3: string;
  bid: string;
  ask: string;
  amber: string;
  mono: string;
  word: string;
}

function tokens(): Tokens {
  const s = getComputedStyle(document.documentElement);
  const t = (n: string) => s.getPropertyValue(n).trim();
  return {
    gutter: t("--color-gutter"),
    panel: t("--color-panel"),
    seam: t("--color-seam"),
    ink1: t("--color-ink-1"),
    ink2: t("--color-ink-2"),
    ink3: t("--color-ink-3"),
    bid: t("--color-bid"),
    ask: t("--color-ask"),
    amber: t("--color-amber"),
    mono: '"B612 Mono", monospace',
    word: '"Barlow Semi Condensed", sans-serif',
  };
}

function rgba(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

const SHADES = 8;

function niceStep(span: number, target: number): number {
  const raw = span / target;
  for (const s of [1, 2, 5, 10, 25, 50, 100, 200, 500]) if (s >= raw) return s;
  return 1000;
}


function draw(canvas: HTMLCanvasElement, h: History, f: Frame, d: Derived, explain: boolean): void {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth;
  const H = canvas.clientHeight;
  if (W === 0 || H === 0 || h.mids.length < 2) return;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(dpr, dpr);
  const C = tokens();
  ctx.clearRect(0, 0, W, H);

  const pw = W - AXW;
  const ph = H - VOL_H - TIME_H - GAP;
  const t0 = h.mids[0].t;
  const t1 = Math.max(f.t, t0 + 1);
  const x = (t: number) => ((t - t0) / (t1 - t0)) * pw;

  // price range: the mid path, padded so the depth bands near the touch show
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of h.mids) {
    lo = Math.min(lo, p.mid);
    hi = Math.max(hi, p.mid);
  }
  const pad = Math.max(8, (hi - lo) * 0.12);
  lo -= pad;
  hi += pad;
  const y = (p: number) => ((hi - p) / (hi - lo)) * ph;

  // ---- depth map
  let qmax = 1;
  for (const c of h.cols) {
    for (const [, q] of c.bids) qmax = Math.max(qmax, q);
    for (const [, q] of c.asks) qmax = Math.max(qmax, q);
  }
  const bidShade = Array.from({ length: SHADES }, (_, i) => rgba(C.bid, 0.1 + (0.75 * (i + 1)) / SHADES));
  const askShade = Array.from({ length: SHADES }, (_, i) => rgba(C.ask, 0.1 + (0.75 * (i + 1)) / SHADES));
  const cell = Math.max(1, ph / (hi - lo));
  for (let i = 0; i < h.cols.length; i++) {
    const c = h.cols[i];
    const x0 = x(c.t);
    const x1 = i + 1 < h.cols.length ? x(h.cols[i + 1].t) : x(t1);
    const w = Math.max(1, x1 - x0 + 0.6);
    for (const [px, q] of c.bids) {
      if (px < lo || px > hi) continue;
      ctx.fillStyle = bidShade[Math.min(SHADES - 1, Math.floor(Math.sqrt(q / qmax) * SHADES))];
      ctx.fillRect(x0, y(px + 0.5), w, cell);
    }
    for (const [px, q] of c.asks) {
      if (px < lo || px > hi) continue;
      ctx.fillStyle = askShade[Math.min(SHADES - 1, Math.floor(Math.sqrt(q / qmax) * SHADES))];
      ctx.fillRect(x0, y(px + 0.5), w, cell);
    }
  }

  // ---- grid
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(255,255,255,0.05)";
  const pStep = niceStep(hi - lo, 6);
  const priceTicks: number[] = [];
  for (let p = Math.ceil(lo / pStep) * pStep; p < hi; p += pStep) priceTicks.push(p);
  for (const p of priceTicks) {
    const gy = Math.round(y(p)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(0, gy);
    ctx.lineTo(pw, gy);
    ctx.stroke();
  }
  const spanS = (t1 - t0) / 1e9;
  const tStep = spanS <= 20 ? 2 : spanS <= 45 ? 5 : 10;
  const timeTicks: number[] = [];
  for (let s = Math.ceil(t0 / 1e9 / tStep) * tStep; s * 1e9 < t1; s += tStep) timeTicks.push(s);
  for (const s of timeTicks) {
    const gx = Math.round(x(s * 1e9)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(gx, 0);
    ctx.lineTo(gx, ph + GAP + VOL_H);
    ctx.stroke();
  }

  // ---- VWAP (dashed) and mid (solid)
  ctx.strokeStyle = C.ink2;
  ctx.setLineDash([5, 4]);
  ctx.beginPath();
  let started = false;
  for (const s of h.samples) {
    if (s.vwap === null) continue;
    if (!started) ctx.moveTo(x(s.t), y(s.vwap));
    else ctx.lineTo(x(s.t), y(s.vwap));
    started = true;
  }
  ctx.stroke();
  ctx.setLineDash([]);

  // ---- lever: measure box, flag, line
  const leverX = d.leverT !== null ? x(d.leverT) : null;
  const midNow = d.mid ?? h.mids[h.mids.length - 1].mid;
  if (d.fired && leverX !== null && d.m0 !== null && d.move !== null) {
    const yTop = y(d.m0);
    const yEnd = y(d.m0 + d.move);
    ctx.fillStyle = rgba(C.ask, 0.1);
    ctx.fillRect(leverX, Math.min(yTop, yEnd), pw - leverX, Math.abs(yEnd - yTop));
    ctx.strokeStyle = rgba(C.ask, 0.75);
    ctx.strokeRect(leverX + 0.5, Math.min(yTop, yEnd) + 0.5, pw - leverX, Math.abs(yEnd - yTop));
    const xm = (leverX + pw) / 2;
    ctx.strokeStyle = C.ask;
    ctx.beginPath();
    ctx.moveTo(xm, yTop + 2);
    ctx.lineTo(xm, yEnd - (d.move < 0 ? 2 : -2));
    ctx.stroke();
    const dir = d.move < 0 ? 1 : -1;
    ctx.beginPath();
    ctx.moveTo(xm - 4, yEnd - dir * 9);
    ctx.lineTo(xm, yEnd - dir * 2);
    ctx.lineTo(xm + 4, yEnd - dir * 9);
    ctx.stroke();
  }

  ctx.strokeStyle = C.ink1;
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  ctx.moveTo(x(h.mids[0].t), y(h.mids[0].mid));
  for (const p of h.mids) ctx.lineTo(x(p.t), y(p.mid));
  ctx.stroke();
  ctx.lineWidth = 1;

  if (d.fired && leverX !== null && d.m0 !== null && d.move !== null) {
    const bw = 236;
    const bx = pw - bw - 6;
    const by = d.move < 0 ? y(d.m0 + d.move) + 8 : y(d.m0 + d.move) - 44;
    ctx.fillStyle = C.ask;
    ctx.fillRect(bx, by, bw, 36);
    ctx.fillStyle = C.gutter;
    ctx.textAlign = "center";
    ctx.font = `700 12px ${C.mono}`;
    ctx.fillText(`${d.move < 0 ? "−" : "+"}${Math.abs(d.move).toFixed(1)} ticks in ${d.moveWindowS >= 5 ? 5 : d.moveWindowS.toFixed(1)} s`, bx + bw / 2, by + 15);
    ctx.font = `11px ${C.mono}`;
    const ampText = d.amp !== null && d.w5 !== null ? `${d.amp.toFixed(1)}× ${explain ? "any" : "worst"} normal 5 s (${Math.round(d.w5)})` : "no pre-lever baseline (joined late)";
    ctx.fillText(ampText, bx + bw / 2, by + 29);
    ctx.textAlign = "left";
  }

  if (leverX !== null && d.fired) {
    ctx.strokeStyle = C.amber;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(leverX, 0);
    ctx.lineTo(leverX, ph + GAP + VOL_H);
    ctx.stroke();
    ctx.lineWidth = 1;
    const label = explain ? "MAKERS TOLD TO CUT RISK" : "LEVER · MAKER RISK CUT";
    ctx.font = `700 12px ${C.word}`;
    const fw = ctx.measureText(label).width + 18 + label.length * 0.7;
    const fx = leverX - fw >= 0 ? leverX - fw : leverX + 1; // flag flips right if the lever is near the left edge
    ctx.fillStyle = C.amber;
    ctx.fillRect(fx, 0, fw, 20);
    ctx.fillStyle = C.gutter;
    ctx.textAlign = "center";
    ctx.fillText(label, fx + fw / 2, 14);
    ctx.textAlign = "left";
  } else if (d.leftS !== null) {
    const note = `LEVER FIRES IN ${d.leftS.toFixed(1)} S`;
    ctx.font = `700 12px ${C.word}`;
    const nw = ctx.measureText(note).width + 18;
    ctx.fillStyle = C.gutter;
    ctx.fillRect(pw - nw - 8, 6, nw, 22);
    ctx.strokeStyle = C.amber;
    ctx.strokeRect(pw - nw - 7.5, 6.5, nw, 22);
    ctx.fillStyle = C.amber;
    ctx.textAlign = "center";
    ctx.fillText(note, pw - nw / 2 - 8, 21);
    ctx.textAlign = "left";
  }

  // ---- numbered events on the mid line
  d.events.forEach((ev, i) => {
    let m = h.mids[0].mid;
    let best = Infinity;
    for (const p of h.mids) {
      const dt = Math.abs(p.t - ev.t);
      if (dt < best) {
        best = dt;
        m = p.mid;
      }
    }
    const px = x(ev.t);
    const py = y(m);
    const lift = 14 + ((i + 1) % 4) * 17;
    ctx.strokeStyle = C.ink1;
    ctx.beginPath();
    ctx.moveTo(px, py);
    ctx.lineTo(px, py - lift);
    ctx.stroke();
    ctx.fillStyle = C.ink1;
    ctx.fillRect(px - 8, py - lift - 15, 16, 15);
    ctx.fillStyle = C.gutter;
    ctx.font = `700 11px ${C.mono}`;
    ctx.textAlign = "center";
    ctx.fillText(String(i + 1), px, py - lift - 3.5);
    ctx.textAlign = "left";
  });

  // ---- legend: O H L C of the mid over the window the story is about
  const since = h.mids.filter((p) => (d.fired && d.leverT !== null ? p.t >= d.leverT : p.t >= t0 + 2e9));
  if (since.length > 0) {
    const O = d.fired && d.m0 !== null ? d.m0 : since[0].mid;
    const Hh = Math.max(...since.map((p) => p.mid));
    const Ll = Math.min(...since.map((p) => p.mid));
    const Cc = since[since.length - 1].mid;
    const col = Cc < O ? C.ask : C.bid;
    const lx = 14;
    const ly = d.fired ? 4 : ph - 52;
    ctx.fillStyle = rgba(C.gutter, 0.82);
    ctx.fillRect(6, ly, 450, 40);
    ctx.font = `700 11px ${C.word}`;
    ctx.fillStyle = C.ink1;
    let cx = lx;
    const title = d.fired ? "MID · SINCE LEVER" : "MID · 250 MS";
    ctx.fillText(title, cx, ly + 16);
    cx += ctx.measureText(title).width + 10;
    ctx.font = `11px ${C.mono}`;
    for (const [k, v] of [["O", O], ["H", Hh], ["L", Ll], ["C", Cc]] as const) {
      ctx.fillStyle = C.ink2;
      ctx.fillText(k, cx, ly + 16);
      cx += ctx.measureText(k).width + 4;
      ctx.fillStyle = col;
      const txt = v.toFixed(1);
      ctx.fillText(txt, cx, ly + 16);
      cx += ctx.measureText(txt).width + 10;
    }
    ctx.fillStyle = C.ink2;
    const vw = f.stats.vwap;
    ctx.fillText(`VWAP ${vw !== null ? vw.toFixed(1) : "—"}  ·  ${explain ? "teal = buyers, coral = sellers" : "teal bids · coral asks"} · brighter = more size`, lx, ly + 33);
  }

  // ---- right axis with last-price and VWAP pills
  ctx.fillStyle = C.panel;
  ctx.fillRect(pw, 0, AXW, ph + GAP + VOL_H + TIME_H);
  ctx.strokeStyle = C.seam;
  ctx.beginPath();
  ctx.moveTo(pw + 0.5, 0);
  ctx.lineTo(pw + 0.5, ph + GAP + VOL_H + TIME_H);
  ctx.stroke();
  ctx.font = `11px ${C.mono}`;
  const yMid = y(midNow);
  const vwNow = f.stats.vwap;
  const yVw = vwNow !== null ? y(vwNow) : null;
  ctx.fillStyle = C.ink2;
  for (const p of priceTicks) {
    const py = y(p);
    if (Math.abs(py - yMid) < 14 || (yVw !== null && Math.abs(py - yVw) < 14)) continue;
    ctx.fillRect(pw, Math.round(py), 4, 1);
    ctx.fillText(fpxRound(p), pw + 8, py + 4);
  }
  if (yVw !== null && vwNow !== null) {
    ctx.fillStyle = C.panel;
    ctx.fillRect(pw, yVw - 9, AXW, 18);
    ctx.strokeStyle = C.ink2;
    ctx.strokeRect(pw + 0.5, yVw - 8.5, AXW - 1, 17);
    ctx.fillStyle = C.ink2;
    ctx.fillText(vwNow.toFixed(1), pw + 6, yVw + 4);
  }
  const first = since.length > 0 ? since[0].mid : midNow;
  ctx.fillStyle = midNow < first ? C.ask : C.bid;
  ctx.fillRect(pw, yMid - 9, AXW, 18);
  ctx.fillStyle = C.gutter;
  ctx.font = `700 11px ${C.mono}`;
  ctx.fillText(midNow.toFixed(1), pw + 6, yMid + 4);

  // ---- volume + net taker flow pane
  const vTop = ph + GAP;
  const vMid = vTop + VOL_H / 2;
  const hh = VOL_H / 2 - 4;
  ctx.strokeStyle = C.seam;
  ctx.beginPath();
  ctx.moveTo(0, vTop - 2.5);
  ctx.lineTo(W, vTop - 2.5);
  ctx.stroke();
  let vmax = 1;
  for (const v of h.vol.values()) vmax = Math.max(vmax, v.up, v.dn);
  const bw = Math.max(1, (pw * COL_NS) / (t1 - t0) - 1);
  ctx.fillStyle = rgba(C.bid, 0.75);
  for (const [b, v] of h.vol) {
    const bx = x(b * COL_NS);
    if (bx < 0 || bx > pw || v.up === 0) continue;
    const bh = (v.up / vmax) * hh;
    ctx.fillRect(bx, vMid - bh, bw, bh);
  }
  ctx.fillStyle = rgba(C.ask, 0.75);
  for (const [b, v] of h.vol) {
    const bx = x(b * COL_NS);
    if (bx < 0 || bx > pw || v.dn === 0) continue;
    ctx.fillRect(bx, vMid, bw, (v.dn / vmax) * hh);
  }
  ctx.strokeStyle = rgba(C.ink3, 0.6);
  ctx.beginPath();
  ctx.moveTo(0, vMid + 0.5);
  ctx.lineTo(pw, vMid + 0.5);
  ctx.stroke();
  let nmax = 1;
  for (const s of h.samples) nmax = Math.max(nmax, Math.abs(s.net));
  ctx.strokeStyle = C.ink1;
  ctx.lineWidth = 1.3;
  ctx.beginPath();
  let prevY: number | null = null;
  for (const s of h.samples) {
    const sy = vMid - (s.net / nmax) * hh;
    if (prevY === null) ctx.moveTo(x(s.t), sy);
    else {
      ctx.lineTo(x(s.t), prevY);
      ctx.lineTo(x(s.t), sy);
    }
    prevY = sy;
  }
  ctx.stroke();
  ctx.lineWidth = 1;
  ctx.font = `700 11px ${C.word}`;
  ctx.fillStyle = C.ink1;
  const volTitle = explain ? "BUYING ▲ SELLING ▼" : "VOLUME · 250 MS";
  ctx.fillText(volTitle, 8, vTop + 10);
  const lw = ctx.measureText(volTitle).width;
  ctx.font = `11px ${C.mono}`;
  ctx.fillStyle = C.ink2;
  ctx.fillText("net taker", 18 + lw, vTop + 10);
  ctx.fillStyle = f.stats.net < 0 ? C.ask : C.bid;
  ctx.fillText(`${f.stats.net < 0 ? "−" : "+"}${Math.abs(f.stats.net)}`, 18 + lw + 62, vTop + 10);
  ctx.fillStyle = C.bid;
  ctx.fillText("BUY", pw + 8, vTop + 12);
  ctx.fillStyle = C.ask;
  ctx.fillText("SELL", pw + 8, vTop + VOL_H - 4);

  // ---- time axis
  const ay = vTop + VOL_H;
  ctx.strokeStyle = C.seam;
  ctx.beginPath();
  ctx.moveTo(0, ay + 0.5);
  ctx.lineTo(W, ay + 0.5);
  ctx.stroke();
  ctx.fillStyle = C.ink2;
  ctx.font = `11px ${C.mono}`;
  ctx.textAlign = "center";
  for (const s of timeTicks) {
    const tx = x(s * 1e9);
    if (tx < pw - 80) ctx.fillText(`${s}s`, tx, ay + 18);
  }
  ctx.fillStyle = C.ink1;
  ctx.fillRect(pw - 70, ay + 4, 70, 18);
  ctx.fillStyle = C.gutter;
  ctx.font = `700 11px ${C.mono}`;
  ctx.fillText(`${(f.t / 1e9).toFixed(3)}s`, pw - 35, ay + 17);
  ctx.textAlign = "left";
}

function fpxRound(p: number): string {
  return fmtPx(Math.round(p));
}

export function PriceChart({
  frame,
  d,
  history,
  explain,
}: {
  frame: Frame | null;
  d: Derived | null;
  history: React.RefObject<History>;
  explain: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !frame || !d || !history.current) return;
    const redraw = () => draw(canvas, history.current, frame, d, explain);
    redraw();
    window.addEventListener("resize", redraw);
    return () => window.removeEventListener("resize", redraw);
  }, [frame, d, history, explain]);

  if (!frame) return <VoidState>Awaiting feed</VoidState>;
  return (
    <div className="relative size-full">
      <canvas ref={canvasRef} className="size-full" role="img" aria-label="Depth map with mid price, VWAP, the lever and the measured drop; volume and net taker flow below" />
      {d && d.events.length > 0 ? (
        <div
          className="absolute left-2 w-[420px] border border-seam bg-gutter/85 px-2 py-1"
          style={{ bottom: VOL_H + TIME_H + GAP + 10 }}
        >
          <Lb tone="plain">{explain ? "How the crash unfolded" : "What the engine did"}</Lb>
          {d.events.map((ev, i) => (
            <div key={`${ev.kind}-${i}`} className="grid h-4 grid-cols-[20px_62px_1fr] items-center">
              <span className="n flex h-[14px] w-[15px] items-center justify-center bg-ink-1 text-[11px] font-bold text-gutter">
                {i + 1}
              </span>
              <span className="n text-[11px] text-ink-2">{fmtSec(ev.t)}</span>
              <span className="n truncate text-[11px] text-ink-1">{ev.text}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
