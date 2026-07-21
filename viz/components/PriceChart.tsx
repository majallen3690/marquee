"use client";

/** Canvas mid-price chart. 1px line, faint gridlines, amber perturbation
 * rules — the only annotation (DESIGN.md motion rule 4). */

import { useEffect, useRef } from "react";
import type { Frame, MidPoint } from "@/lib/types";
import { VoidState } from "./primitives";

/** Canvas takes literal colors, so read them from the DESIGN.md tokens rather
 * than duplicating hex values here (tokens stay the single source). */
function readTokens(): { line: string; grid: string; axis: string; accent: string } {
  const style = getComputedStyle(document.documentElement);
  const token = (name: string) => style.getPropertyValue(name).trim();
  return {
    line: token("--color-ink-1"),
    grid: token("--color-ink-3"),
    axis: token("--color-ink-2"),
    accent: token("--color-accent"),
  };
}

function draw(
  canvas: HTMLCanvasElement,
  history: MidPoint[],
  perturbTimes: number[],
) {
  const dpr = window.devicePixelRatio || 1;
  const { clientWidth: w, clientHeight: h } = canvas;
  if (w === 0 || h === 0 || history.length < 2) return;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const COLORS = readTokens();
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  ctx.font = '10px "IBM Plex Mono", monospace';

  const PAD_R = 56;
  const PAD_Y = 10;
  const t0 = history[0].t;
  const t1 = history[history.length - 1].t;
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of history) {
    if (p.mid < lo) lo = p.mid;
    if (p.mid > hi) hi = p.mid;
  }
  const span = Math.max(hi - lo, 4);
  lo -= span * 0.08;
  hi += span * 0.08;

  const x = (t: number) => ((t - t0) / Math.max(t1 - t0, 1)) * (w - PAD_R);
  const y = (mid: number) => PAD_Y + (1 - (mid - lo) / (hi - lo)) * (h - 2 * PAD_Y);

  // gridlines + axis figures
  ctx.strokeStyle = COLORS.grid;
  ctx.fillStyle = COLORS.axis;
  ctx.lineWidth = 1;
  const STEPS = 4;
  for (let i = 0; i <= STEPS; i++) {
    const value = lo + ((hi - lo) * i) / STEPS;
    const gy = Math.round(y(value)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(0, gy);
    ctx.lineTo(w - PAD_R, gy);
    ctx.stroke();
    ctx.fillText(value.toFixed(1), w - PAD_R + 8, gy + 3);
  }

  // perturbation rules
  for (const pt of perturbTimes) {
    if (pt < t0 || pt > t1) continue;
    const px = Math.round(x(pt)) + 0.5;
    ctx.strokeStyle = COLORS.accent;
    ctx.beginPath();
    ctx.moveTo(px, 0);
    ctx.lineTo(px, h);
    ctx.stroke();
    ctx.fillStyle = COLORS.accent;
    ctx.fillText("PERTURB", px + 4, 12);
    ctx.fillStyle = COLORS.axis;
  }

  // the price line
  ctx.strokeStyle = COLORS.line;
  ctx.beginPath();
  ctx.moveTo(x(history[0].t), y(history[0].mid));
  for (const p of history) ctx.lineTo(x(p.t), y(p.mid));
  ctx.stroke();
}

export function PriceChart({
  frame,
  midHistory,
}: {
  frame: Frame | null;
  midHistory: React.RefObject<MidPoint[]>;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!canvasRef.current) return;
    const perturbTimes = [...new Set((frame?.perturbations ?? []).map((p) => p.t))];
    draw(canvasRef.current, midHistory.current ?? [], perturbTimes);
  }, [frame, midHistory]);

  if (!frame) return <VoidState>AWAITING FEED</VoidState>;
  return <canvas ref={canvasRef} className="size-full" />;
}
