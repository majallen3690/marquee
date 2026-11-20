"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AgentsTable } from "@/components/AgentsTable";
import { BookPanel } from "@/components/BookPanel";
import { HeaderBar } from "@/components/HeaderBar";
import { LeverTicket } from "@/components/LeverTicket";
import { Panel } from "@/components/primitives";
import { PriceChart } from "@/components/PriceChart";
import { StatStrip } from "@/components/StatStrip";
import { Tour, TOUR_AREAS } from "@/components/Tour";
import { TapePanel } from "@/components/TapePanel";
import { TransportBar } from "@/components/TransportBar";
import { derive } from "@/lib/derive";
import { History } from "@/lib/history";
import { cutMakerRisk } from "@/lib/levers";
import { loadHistory, postControl, useFeed } from "@/lib/useFeed";
import type { Frame } from "@/lib/types";

/** Replay: the run as it was at one moment, read from /api/history. */
interface Scrub {
  frame: Frame;
  history: React.RefObject<History>;
}

export default function Live() {
  const feed = useFeed();
  const { meta, connection } = feed;
  const [scrub, setScrub] = useState<Scrub | null>(null);
  const [explain, setExplain] = useState(false); // Learn mode: plain-English labels + a guided tour
  const [tour, setTour] = useState<number | null>(null);

  const frame = scrub ? scrub.frame : feed.frame;
  const history = scrub ? scrub.history : feed.history;
  const d = useMemo(() => (frame ? derive(history.current, frame, meta) : null), [frame, meta, history]);

  const goLive = useCallback(() => setScrub(null), []);
  const goTo = useCallback(async (t: number) => {
    try {
      const payload = await loadHistory();
      if (payload.frames.length === 0) return;
      const full = new History();
      full.backfill(payload);
      // the last snapshot at or before t (the first one, if t precedes them all)
      let pick = payload.frames[0];
      for (const f of payload.frames) if (f.t <= t) pick = f;
      setScrub({ frame: pick, history: { current: full.slice(pick) } });
    } catch {
      /* the bridge is gone; the header already says so */
    }
  }, []);

  // Below 1440 px the screen shrinks to fit rather than overflow, until the narrow
  // watch-only view is built (DESIGN.md). Above it, nothing changes.
  useEffect(() => {
    const fit = () => {
      const z = Math.min(1, window.innerWidth / 1440);
      document.documentElement.style.zoom = String(z);
      document.documentElement.style.setProperty("--app-h", `${window.innerHeight / z}px`);
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  // Keyboard: Space pauses, Shift+C cuts maker risk, Esc leaves Replay. The hints on the buttons are real.
  const latest = useRef({ frame: feed.frame, meta, replay: false });
  latest.current = { frame: feed.frame, meta, replay: scrub !== null };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) return;
      const { frame: f, meta: m, replay } = latest.current;
      if (e.code === "Escape" && replay) {
        setScrub(null);
        return;
      }
      if (!f || f.status === "done" || replay) return;
      if (e.code === "Space") {
        e.preventDefault();
        void postControl(f.status === "paused" ? "resume" : "pause");
      } else if (e.code === "KeyC" && e.shiftKey) {
        e.preventDefault();
        void cutMakerRisk(m);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const caption = !d
    ? ""
    : d.fired
      ? "The makers’ risk limits were cut. Nobody scripts the price."
      : d.leftS !== null
        ? `Calm so far: makers quote both sides. The lever fires in ${d.leftS.toFixed(0)} s.`
        : "No lever scheduled: watching a market nobody is steering.";

  return (
    <main className="seam app-grid relative" data-tour={tour !== null ? TOUR_AREAS[tour] : undefined}>
      <HeaderBar
        frame={frame}
        meta={meta}
        connection={connection}
        replay={scrub !== null}
        explain={explain}
        onToggleExplain={() => {
          setExplain(!explain);
          setTour(explain ? null : 0);
        }}
      />
      <StatStrip frame={frame} d={d} explain={explain} />
      <div className="seam live-grid">
        <Panel
          label={explain ? "Price, and the orders waiting" : "Price & depth"}
          area="chart"
          id="chart"
          right={<span className="font-sans text-[12px] text-ink-2">{caption}</span>}
        >
          <PriceChart frame={frame} d={d} history={history} explain={explain} />
        </Panel>
        <BookPanel frame={frame} d={d} history={history} explain={explain} />
        <div className="seam" style={{ gridArea: "side", gridTemplateRows: "auto minmax(0, 1fr)" }}>
          <LeverTicket frame={frame} meta={meta} d={d} replay={scrub !== null} explain={explain} />
          <TapePanel frame={frame} meta={meta} explain={explain} />
        </div>
        <AgentsTable frame={frame} meta={meta} history={history} mid={d?.mid ?? null} explain={explain} />
      </div>
      <TransportBar
        frame={frame}
        d={d}
        history={history}
        replay={scrub !== null}
        onScrub={(t) => void goTo(t)}
        onLive={goLive}
      />
      {tour !== null ? <Tour step={tour} d={d} onStep={setTour} onEnd={() => setTour(null)} /> : null}
    </main>
  );
}
