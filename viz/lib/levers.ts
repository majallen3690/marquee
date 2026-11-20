import { postPerturb } from "./useFeed";
import type { Meta, ScheduledLever } from "./types";

/** The scenario's own scripted lever: what "Cut maker risk" fires. Reading it
 * from /api/meta keeps the button, the ticket table and the scenario file in
 * one agreement. Falls back to the committed preset for scenarios without one. */
export function presetFor(meta: Meta | null): ScheduledLever[] {
  if (meta && meta.scheduled.length > 0) return meta.scheduled;
  const makers = (meta?.agents ?? []).filter((a) => a.class === "market_maker");
  return makers.flatMap((m, i) => [
    { t: 0, aid: m.id, param: "soft_limit", value: 5 },
    { t: 0, aid: m.id, param: "hard_limit", value: 10 },
    { t: 0, aid: m.id, param: "quote_size", value: 5 },
    { t: 0, aid: m.id, param: "half_spread", value: i % 2 === 0 ? 12 : 15 },
  ]);
}

export async function cutMakerRisk(meta: Meta | null): Promise<void> {
  await Promise.all(presetFor(meta).map((p) => postPerturb(p.aid, p.param, p.value)));
}
