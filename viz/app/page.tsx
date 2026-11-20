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
import { STATIC_BUILD } from "@/lib/feed";
import type { History } from "@/lib/history";
import { useStaticFeed } from "@/lib/staticFeed";
import { useFeed } from "@/lib/useFeed";
import type { Frame } from "@/lib/types";

// One build plays the live bridge; the GitHub Pages build plays a recorded run.
const useMarqueeFeed = STATIC_BUILD ? useStaticFeed : useFeed;

/** Replay: the run as it was at one moment, read from /api/history. */
interface Scrub {
  frame: Frame;
  history: React.RefObject<History>;
}

export default function Live() {
  const feed = useMarqueeFeed();
  const { meta, connection, controls } = feed;
  const [scrub, setScrub] = useState<Scrub | null>(null);
  const [explain, setExplain] = useState(false); // Learn mode: plain-English labels + a guided tour
  const [tour, setTour] = useState<number | null>(null);

  const frame = scrub ? scrub.frame : feed.frame;
  const history = scrub ? scrub.history : feed.history;
  const d = useMemo(() => (frame ? derive(history.current, frame, meta) : null), [frame, meta, history]);

  const goLive = useCallback(() => setScrub(null), []);
  const at = feed.at;
  const goTo = useCallback(
    async (t: number) => {
      try {
        const view = await at(t);
        if (view) setScrub({ frame: view.frame, history: { current: view.history } });
      } catch {
        /* the bridge is gone; the header already says so */
      }
    },
    [at],
  );

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
  const latest = useRef({ frame: feed.frame, controls, replay: false });
  latest.current = { frame: feed.frame, controls, replay: scrub !== null };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) return;
      const { frame: f, controls: c, replay } = latest.current;
      if (e.code === "Escape" && replay) {
        setScrub(null);
        return;
      }
      if (!f || f.status === "done" || replay) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (f.status === "paused") c.resume();
        else c.pause();
      } else if (e.code === "KeyC" && e.shiftKey && c.cut) {
        e.preventDefault();
        c.cut();
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
        recorded={feed.recorded}
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
          <LeverTicket frame={frame} meta={meta} d={d} replay={scrub !== null} explain={explain} onCut={controls.cut} />
          <TapePanel frame={frame} meta={meta} explain={explain} />
        </div>
        <AgentsTable frame={frame} meta={meta} history={history} mid={d?.mid ?? null} explain={explain} />
      </div>
      <TransportBar
        frame={frame}
        d={d}
        history={history}
        replay={scrub !== null}
        controls={controls}
        onScrub={(t) => void goTo(t)}
        onLive={goLive}
      />
      {tour !== null ? <Tour step={tour} d={d} onStep={setTour} onEnd={() => setTour(null)} /> : null}
    </main>
  );
}
