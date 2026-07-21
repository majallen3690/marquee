"use client";

/** DESIGN.md primitives — styling lives HERE and nowhere else. */

import { useEffect, useRef, useState } from "react";

export function MicroLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-micro font-medium uppercase tracking-[0.08em] text-ink-2">
      {children}
    </span>
  );
}

export function Panel({
  label,
  right,
  children,
  className = "",
}: {
  label: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex min-h-0 flex-col border border-hairline bg-surface-1 ${className}`}>
      <header className="flex h-7 shrink-0 items-center justify-between border-b border-hairline px-3">
        <MicroLabel>{label}</MicroLabel>
        {right}
      </header>
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  );
}

type Tone = "plain" | "dim" | "bid" | "ask" | "accent";

const TONE_TEXT: Record<Tone, string> = {
  plain: "text-ink-1",
  dim: "text-ink-2",
  bid: "text-bid",
  ask: "text-ask",
  accent: "text-accent",
};

/** A figure. Flashes its semantic color when the value changes (motion rule 2). */
export function Num({
  value,
  tone = "plain",
  flash = false,
  className = "",
}: {
  value: string | number;
  tone?: Tone;
  flash?: boolean;
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
    <span className={`${TONE_TEXT[tone]} ${flashClass} ${className}`}>{value}</span>
  );
}

export function TermButton({
  children,
  onClick,
  active = false,
  danger = false,
  className = "",
}: {
  children: React.ReactNode;
  onClick: () => void;
  active?: boolean;
  danger?: boolean;
  className?: string;
}) {
  const base = danger
    ? "border-accent text-accent hover:bg-accent hover:text-surface-0"
    : active
      ? "border-hairline bg-surface-2 text-ink-1"
      : "border-hairline text-ink-2 hover:bg-surface-2 hover:text-ink-1";
  return (
    <button
      onClick={onClick}
      className={`h-6 border px-2 text-micro font-medium uppercase tracking-[0.08em] transition-colors duration-100 ease-linear ${base} ${className}`}
    >
      {children}
    </button>
  );
}

export function TermSlider({
  label,
  min,
  max,
  step,
  value,
  onChange,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="flex items-center gap-2">
      <span className="w-14 shrink-0 text-micro uppercase tracking-[0.08em] text-ink-2">
        {label}
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-0.5 min-w-0 flex-1 cursor-ew-resize appearance-none bg-hairline accent-(--color-accent)"
      />
      <span className="w-10 shrink-0 text-right text-dense text-ink-1">{value}</span>
    </label>
  );
}

export function StatusDot({ tone }: { tone: "live" | "warn" | "off" }) {
  const color =
    tone === "live" ? "bg-bid" : tone === "warn" ? "bg-accent" : "bg-ink-3";
  return <span className={`inline-block size-1.5 ${color}`} />;
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
      <MicroLabel>{children}</MicroLabel>
    </div>
  );
}
