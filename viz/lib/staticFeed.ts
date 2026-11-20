"use client";

/** The zero-install demo: play back a run recorded by `marquee.server.record`
 * (frames every 100 ms of sim time) entirely in the browser. Same Frame shape
 * as the live bridge, so every component is unchanged. The lever is disabled:
 * a recorded run cannot be changed. `?at=<seconds>` starts playback there. */

import { useCallback, useEffect, useRef, useState } from "react";
import { BASE_PATH, type Feed } from "./feed";
import { History } from "./history";
import type { Frame, Meta } from "./types";

const TICK_MS = 100;

interface Recording {
  meta: Meta;
  frames: Frame[];
}

export function useStaticFeed(): Feed {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [connection, setConnection] = useState<Feed["connection"]>("connecting");
  const history = useRef(new History());
  const rec = useRef<Recording | null>(null);
  const play = useRef({ i: 0, simT: 0, paused: false, speed: 1 });

  useEffect(() => {
    fetch(`${BASE_PATH}/replay/m5-flash-crash.json`)
      .then((r) => r.json())
      .then((data: Recording) => {
        rec.current = data;
        // ?at=33.5 opens the run at that sim second: a link to one moment.
        const at = Number(new URLSearchParams(window.location.search).get("at"));
        if (Number.isFinite(at) && at > 0) play.current.simT = at * 1e9;
        setMeta(data.meta);
        setConnection("live");
      })
      .catch(() => setConnection("lost"));
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      const r = rec.current;
      if (!r) return;
      const p = play.current;
      if (!p.paused) p.simT += TICK_MS * 1e6 * p.speed;
      let last: Frame | null = null;
      while (p.i < r.frames.length && r.frames[p.i].t <= p.simT) {
        last = r.frames[p.i];
        history.current.push(last);
        p.i++;
      }
      const shown = last ?? (p.i > 0 ? r.frames[p.i - 1] : null);
      if (!shown) return;
      const done = p.i >= r.frames.length;
      setFrame({ ...shown, speed: p.speed, status: done ? "done" : p.paused ? "paused" : "live" });
    }, TICK_MS);
    return () => clearInterval(id);
  }, []);

  const restart = useCallback(() => {
    history.current.reset();
    play.current = { ...play.current, i: 0, simT: 0, paused: false };
  }, []);

  const at = useCallback(async (t: number) => {
    const r = rec.current;
    if (!r) return null;
    const h = new History();
    let pick: Frame | null = null;
    for (const f of r.frames) {
      if (f.t > t) break;
      h.push(f);
      pick = f;
    }
    return pick ? { frame: { ...pick, status: "paused" as const }, history: h.slice(pick) } : null;
  }, []);

  return {
    frame,
    meta,
    connection,
    history,
    recorded: true,
    at,
    controls: {
      pause: () => (play.current.paused = true),
      resume: () => (play.current.paused = false),
      setSpeed: (s) => (play.current.speed = s),
      cut: null,
      restart,
    },
  };
}
