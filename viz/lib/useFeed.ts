"use client";

import { useEffect, useRef, useState } from "react";
import type { Feed } from "./feed";
import { cutMakerRisk } from "./levers";
import { History, type HistoryPayload, type MidPoint } from "./history";
import type { Connection, Frame, Meta } from "./types";

const RENDER_EVERY_MS = 100; // React sees 10 frames/s; History still sees all 20

/** Single WebSocket feed with reconnect. Frames land in `history` (a ref) at
 * the wire rate; React state updates at 10 Hz so the tree does not re-render
 * on every frame. */
export function useFeed(): Feed {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [counterfactual, setCounterfactual] = useState<MidPoint[] | null>(null);
  const history = useRef(new History());

  useEffect(() => {
    fetch("/api/meta")
      .then((r) => r.json())
      .then(setMeta)
      .catch(() => setMeta(null));
    // The no-lever twin is computed once on the server (about 3 s), so ask after meta.
    fetch("/api/counterfactual")
      .then((r) => r.json())
      .then((b: { mids: [number, number][] }) => setCounterfactual(b.mids.map(([t, mid]) => ({ t, mid }))))
      .catch(() => setCounterfactual(null));
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let closed = false;
    let lastRender = 0;
    let ready = false; // false until /api/history has been loaded; frames queue meanwhile
    let queue: Frame[] = [];

    const accept = (next: Frame) => {
      history.current.push(next);
      const now = performance.now();
      // always render a status change (pause / done) immediately
      if (now - lastRender >= RENDER_EVERY_MS || next.status !== "live") {
        lastRender = now;
        setFrame(next);
      }
    };

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ready = false;
      queue = [];
      ws.onopen = () => {
        setConnection("live");
        // A page that joins mid-run (or reconnects) backfills the run so far.
        loadHistory()
          .then((p) => history.current.backfill(p))
          .catch(() => history.current.reset())
          .finally(() => {
            ready = true;
            for (const f of queue) accept(f);
            queue = [];
          });
      };
      ws.onmessage = (event) => {
        const next: Frame = JSON.parse(event.data);
        if (ready) accept(next);
        else queue.push(next);
      };
      ws.onclose = () => {
        if (closed) return;
        setConnection("lost");
        retry = setTimeout(connect, 1000);
      };
    };
    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, []);

  return {
    frame,
    meta,
    connection,
    history,
    recorded: false,
    counterfactual,
    controls: {
      pause: () => void postControl("pause"),
      resume: () => void postControl("resume"),
      setSpeed: (s) => void postControl("speed", s),
      cut: () => void cutMakerRisk(meta),
      restart: null,
    },
    at: async (t) => {
      const payload = await loadHistory();
      if (payload.frames.length === 0) return null;
      const full = new History();
      full.backfill(payload);
      // the last snapshot at or before t (the first one, if t precedes them all)
      let pick = payload.frames[0];
      for (const f of payload.frames) if (f.t <= t) pick = f;
      return { frame: pick, history: full.slice(pick) };
    },
  };
}

/** Re-emit a value at most every `ms` — drives the tiles at ~4 Hz. */
export function useThrottled<T>(value: T, ms: number): T {
  const [out, setOut] = useState(value);
  const last = useRef(0);
  useEffect(() => {
    const now = performance.now();
    if (now - last.current >= ms) {
      last.current = now;
      setOut(value);
      return;
    }
    const id = setTimeout(() => {
      last.current = performance.now();
      setOut(value);
    }, ms - (now - last.current));
    return () => clearTimeout(id);
  }, [value, ms]);
  return out;
}

export async function loadHistory(): Promise<HistoryPayload> {
  const response = await fetch("/api/history");
  if (!response.ok) throw new Error(`history ${response.status}`);
  return response.json();
}

export async function postControl(action: string, value?: number): Promise<void> {
  await fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, value }),
  });
}

export async function postPerturb(agentId: number, param: string, value: number): Promise<void> {
  await fetch("/api/perturb", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_id: agentId, param, value }),
  });
}
