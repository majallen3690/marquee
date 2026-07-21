"use client";

import { useEffect, useState } from "react";
import { ControlDock } from "@/components/ControlDock";
import { DepthLadder } from "@/components/DepthLadder";
import { HeaderBar } from "@/components/HeaderBar";
import { Panel } from "@/components/primitives";
import { PriceChart } from "@/components/PriceChart";
import { TradeTape } from "@/components/TradeTape";
import { useFeed } from "@/lib/useFeed";

export default function Home() {
  const { frame, connection, midHistory } = useFeed();
  const [scenario, setScenario] = useState("");

  useEffect(() => {
    fetch("/api/meta")
      .then((response) => response.json())
      .then((meta) => setScenario(meta.scenario))
      .catch(() => setScenario("no feed"));
  }, []);

  return (
    <main className="app-grid">
      <HeaderBar frame={frame} connection={connection} scenario={scenario} />
      <Panel label="Controls" className="border-t-0 border-l-0 [grid-area:dock]">
        <ControlDock frame={frame} />
      </Panel>
      <Panel label="Price" className="border-t-0 border-l-0 [grid-area:chart]">
        <PriceChart frame={frame} midHistory={midHistory} />
      </Panel>
      <Panel label="Tape" className="border-t-0 border-l-0 [grid-area:tape]">
        <TradeTape frame={frame} />
      </Panel>
      <Panel label="Book" className="border-t-0 border-x-0 [grid-area:book]">
        <DepthLadder frame={frame} />
      </Panel>
    </main>
  );
}
