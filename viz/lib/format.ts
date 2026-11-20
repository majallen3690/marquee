/** Formatting helpers. Display-layer halving of mid is sanctioned here (ADR-004). */

// Prices carry no thousands separator: in a monospace face the comma takes a full
// cell and "9,776.5" reads as "9, 776. 5". Trading screens print 9776.5.
export function fmtPx(ticks: number): string {
  return String(ticks);
}

export function fmtMid(mid: number): string {
  return mid.toFixed(1);
}

export function fmtSigned(value: number, digits = 0): string {
  const body = Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${value < 0 ? "−" : "+"}${body}`;
}

/** mm:ss.mmm */
export function fmtSimTime(ns: number): string {
  const totalMs = Math.floor(ns / 1e6);
  const minutes = Math.floor(totalMs / 60_000);
  const seconds = Math.floor((totalMs % 60_000) / 1000);
  const ms = totalMs % 1000;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
}

/** ss.mmm, for the tape and the event key */
export function fmtSec(ns: number): string {
  return fmtSimTime(ns).slice(3);
}

export const SHORT_CLASS = { market_maker: "Maker", momentum: "Mom", noise: "Noise" } as const;
export const LONG_CLASS = { market_maker: "Market maker", momentum: "Momentum", noise: "Noise" } as const;
