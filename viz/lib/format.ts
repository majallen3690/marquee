/** Formatting helpers. Display-layer halving of mid is sanctioned here (ADR-004). */

export function fmtPx(ticks: number): string {
  return ticks.toLocaleString("en-US");
}

export function fmtMid(bestBid: number, bestAsk: number): string {
  const midX2 = bestBid + bestAsk;
  const whole = Math.floor(midX2 / 2);
  return midX2 % 2 === 0 ? fmtPx(whole) : `${fmtPx(whole)}.5`;
}

export function midValue(bestBid: number, bestAsk: number): number {
  return (bestBid + bestAsk) / 2;
}

export function fmtQty(qty: number): string {
  return String(qty);
}

export function fmtSimTime(ns: number): string {
  const totalMs = Math.floor(ns / 1e6);
  const minutes = Math.floor(totalMs / 60_000);
  const seconds = Math.floor((totalMs % 60_000) / 1000);
  const ms = totalMs % 1000;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
}
