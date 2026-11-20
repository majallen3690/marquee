"use client";

/** DESIGN.md primitives — styling lives HERE and nowhere else.
 * Departure board: Barlow Semi Condensed capitals for signage, B612 Mono for
 * every figure, split-flap tiles for the figures a room must read. */

import { useEffect, useRef, useState } from "react";

export type Tone = "plain" | "dim" | "faint" | "bid" | "ask" | "amber";

const TONE_TEXT: Record<Tone, string> = {
  plain: "text-ink-1",
  dim: "text-ink-2",
  faint: "text-ink-3",
  bid: "text-bid",
  ask: "text-ask",
  amber: "text-amber",
};

/** Signage label: condensed capitals. */
export function Lb({
  children,
  tone = "dim",
  className = "",
}: {
  children: React.ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={`font-word text-[11px] font-semibold uppercase tracking-[0.06em] whitespace-nowrap ${TONE_TEXT[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

/** A panel on a 1px seam. One tab row; a tab is drawn only if it works. */
export function Panel({
  label,
  right,
  children,
  className = "",
  area,
  id,
}: {
  label: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  area?: string;
  id?: string;
}) {
  return (
    <section
      data-panel={id}
      className={`flex min-h-0 min-w-0 flex-col overflow-hidden bg-panel ${className}`}
      style={area ? { gridArea: area } : undefined}
    >
      <header className="flex h-[30px] shrink-0 items-center gap-4 border-b border-seam px-2.5">
        <span className="flex h-[30px] items-center border-b-2 border-ink-1 pt-0.5 font-word text-[12px] font-semibold uppercase tracking-[0.06em] whitespace-nowrap text-ink-1">
          {label}
        </span>
        <span className="flex-1" />
        {right}
      </header>
      <div className="relative min-h-0 flex-1">{children}</div>
    </section>
  );
}

/** A figure. Flashes its semantic color when the value changes. */
export function Num({
  value,
  tone = "plain",
  flash = false,
  size = 12,
  bold = false,
  className = "",
}: {
  value: string | number;
  tone?: Tone;
  flash?: boolean;
  size?: number;
  bold?: boolean;
  className?: string;
}) {
  const prev = useRef(value);
  const [flashClass, setFlashClass] = useState("");
  useEffect(() => {
    if (!flash || prev.current === value) return;
    prev.current = value;
    const cls = tone === "bid" ? "flash-bid" : tone === "ask" ? "flash-ask" : "flash-plain";
    setFlashClass("");
    const raf = requestAnimationFrame(() => setFlashClass(cls));
    return () => cancelAnimationFrame(raf);
  }, [value, flash, tone]);
  return (
    <span
      className={`n ${TONE_TEXT[tone]} ${flashClass} ${bold ? "font-bold" : ""} ${className}`}
      style={{ fontSize: size }}
    >
      {value}
    </span>
  );
}

function Tile({ ch, w, h, size, on }: { ch: string; w: number; h: number; size: number; on: boolean }) {
  const prev = useRef(ch);
  const [turning, setTurning] = useState(false);
  useEffect(() => {
    if (prev.current === ch) return;
    prev.current = ch;
    setTurning(true);
    const id = setTimeout(() => setTurning(false), 130);
    return () => clearTimeout(id);
  }, [ch]);
  return (
    <span
      className={`n relative flex items-center justify-center font-bold ${on ? "bg-amber text-gutter" : "bg-tile text-ink-1"} ${turning ? "flap" : ""}`}
      style={{ width: w, height: h, fontSize: size }}
    >
      {ch}
      <span className={`absolute inset-x-0 top-1/2 h-px bg-gutter ${on ? "opacity-35" : ""}`} />
    </span>
  );
}

/** Split-flap tiles. Fixed-width cells: a changing number never moves the layout. */
export function Tiles({ text, size = 14, hl }: { text: string; size?: number; hl?: number }) {
  const w = Math.round(size * 0.8);
  const h = Math.round(size * 1.38);
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={text} role="img">
      {[...text].map((ch, i) =>
        ",.:".includes(ch) ? (
          <span
            key={i}
            className="n text-center font-bold text-ink-2"
            style={{ width: Math.round(size * 0.34), fontSize: size }}
          >
            {ch}
          </span>
        ) : (
          <Tile key={i} ch={ch} w={w} h={h} size={size} on={hl === i} />
        ),
      )}
    </span>
  );
}

type BtnKind = "ghost" | "on" | "amber" | "seg" | "off";

const BTN: Record<BtnKind, string> = {
  ghost: "border-seam bg-transparent text-ink-1 hover:bg-tile",
  on: "border-ink-1 bg-ink-1 text-gutter",
  amber: "border-amber bg-amber text-gutter hover:brightness-110",
  seg: "border-tile bg-tile text-ink-1 hover:border-seam",
  off: "border-seam bg-transparent text-ink-3 cursor-not-allowed",
};

export function Btn({
  children,
  onClick,
  kind = "ghost",
  hint,
  h = 26,
  full = false,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  kind?: BtnKind;
  hint?: string;
  h?: number;
  full?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={kind === "off"}
      onClick={onClick}
      style={{ height: h }}
      className={`inline-flex items-center justify-center border px-2.5 font-word text-[12px] font-bold uppercase tracking-[0.06em] whitespace-nowrap ${BTN[kind]} ${full ? "w-full" : ""}`}
    >
      {children}
      {hint ? (
        <kbd className="n ml-[7px] border border-current px-[3px] text-[11px] font-normal tracking-normal opacity-70">
          {hint}
        </kbd>
      ) : null}
    </button>
  );
}

export function Chip({ children, tone }: { children: React.ReactNode; tone: Tone }) {
  return (
    <span
      className={`inline-flex h-[18px] items-center border border-current px-1.5 font-word text-[11px] font-bold uppercase tracking-[0.06em] whitespace-nowrap ${TONE_TEXT[tone]}`}
    >
      {children}
    </span>
  );
}

/** Label / figure / plain-English subtitle: one cell of the stat strip. */
export function Stat({ label, children, sub }: { label: string; children: React.ReactNode; sub: string }) {
  return (
    <div className="flex flex-col gap-px whitespace-nowrap">
      <Lb tone="faint">{label}</Lb>
      {children}
      <span className="font-sans text-[11px] text-ink-2">{sub}</span>
    </div>
  );
}

export function StatusDot({ tone }: { tone: "live" | "warn" | "off" }) {
  const color = tone === "live" ? "bg-bid" : tone === "warn" ? "bg-amber" : "bg-ink-3";
  return <span className={`inline-block size-[7px] ${color}`} />;
}

/** Direction glyphs are text, never emoji (DESIGN.md). */
export function Glyph({ dir }: { dir: "up" | "down" | "flat" }) {
  if (dir === "up") return <span className="text-bid">▲</span>;
  if (dir === "down") return <span className="text-ask">▼</span>;
  return <span className="text-ink-2">·</span>;
}

/** Designed empty/waiting state (DESIGN.md: never blank). */
export function VoidState({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center">
      <Lb>{children}</Lb>
    </div>
  );
}
