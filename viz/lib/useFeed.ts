"use client";

import { useEffect, useRef, useState } from "react";
import type { Connection, Frame, MidPoint } from "./types";
import { midValue } from "./format";

const MID_HISTORY_MAX = 2400; // 2 minutes at 20 fps

/** Single WebSocket feed with reconnect; accumulates the mid series client-side. */
export function useFeed() {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const midHistory = useRef<MidPoint[]>([]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => setConnection("live");
      ws.onmessage = (event) => {
        const next: Frame = JSON.parse(event.data);
        if (next.bids.length > 0 && next.asks.length > 0) {
          const history = midHistory.current;
          const point = { t: next.t, mid: midValue(next.bids[0][0], next.asks[0][0]) };
          if (history.length === 0 || point.t > history[history.length - 1].t) {
            history.push(point);
            if (history.length > MID_HISTORY_MAX) history.shift();
          }
        }
        setFrame(next);
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

  return { frame, connection, midHistory };
}

export async function postControl(action: string, value?: number): Promise<void> {
  await fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, value }),
  });
}

export async function postPerturb(
  agentId: number,
  param: string,
  value: number,
): Promise<void> {
  await fetch("/api/perturb", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_id: agentId, param, value }),
  });
}
