"""Live simulation session: paced stepping, frame building, live perturbation."""

import json
import threading
from collections import deque
from pathlib import Path

from marquee.agents import InventoryMarketMaker
from marquee.sim.recorder import JsonlRecorder
from marquee.sim.scenario import build_session, load_scenario, write_manifest

FRAME_DEPTH = 12
TAPE_KEEP = 60


class TeeRecorder:
    """ADR-007's one-producer-two-sinks: lines go to JSONL untouched; trade and
    perturbation lines are additionally parsed into ring buffers for the UI."""

    def __init__(self, inner: JsonlRecorder) -> None:
        self._inner = inner
        self.trades: deque[dict] = deque(maxlen=TAPE_KEEP)
        self.perturbations: list[dict] = []

    def record_line(self, line: str) -> None:
        self._inner.record_line(line)
        if line.startswith('{"aid"') and '"k":"prt"' in line:
            self.perturbations.append(json.loads(line))

    def record_trade_line(self, line: str) -> None:
        self._inner.record_trade_line(line)
        self.trades.append(json.loads(line))

    def close(self) -> None:
        self._inner.close()


class LiveSession:
    """Thread-safe stepped run of one scenario. step() is called by the app's
    single pacing task; perturb/pause/speed arrive from HTTP handler threads."""

    def __init__(self, scenario_path: str | Path, out_dir: str | Path) -> None:
        self.config, self._raw = load_scenario(scenario_path)
        self._out = Path(out_dir)
        self._out.mkdir(parents=True, exist_ok=True)
        self._recorder = TeeRecorder(
            JsonlRecorder(self._out / "events.jsonl", self._out / "trades.jsonl")
        )
        self.kernel, _, self.agents = build_session(
            self.config, self._out, recorder=self._recorder
        )
        self._lock = threading.Lock()
        self._sim_target = 0
        self.speed = 1.0
        self.paused = False
        self.done = False

    # -- pacing --------------------------------------------------------------

    def step(self, wall_dt_seconds: float) -> dict:
        """Advance sim time by wall_dt * speed and return a UI frame."""
        with self._lock:
            if not self.paused and not self.done:
                self._sim_target = min(
                    self._sim_target + int(wall_dt_seconds * self.speed * 1e9),
                    self.config.horizon_ns,
                )
                self.kernel.run_until(self._sim_target)
                if self._sim_target >= self.config.horizon_ns:
                    self.done = True
                    self._recorder.close()
                    write_manifest(self._out, self._raw, self.config)
            return self._frame()

    def _frame(self) -> dict:
        snap = self.kernel.engine.snapshot(ts=self.kernel.now, depth=FRAME_DEPTH)
        # The tape is stateless on the wire: every frame carries the last
        # TAPE_KEEP trades and the client replaces wholesale, keying rows by
        # tid for its flash effect. No cursor protocol to get wrong.
        new_trades = [
            {"tid": tr["tid"], "t": tr["t"], "px": tr["px"], "qty": tr["qty"], "side": tr["tks"]}
            for tr in list(self._recorder.trades)
        ]
        makers = [
            {
                "id": agent_id,
                "inv": agent.inventory,
                "soft": agent._soft_limit,
                "hard": agent._hard_limit,
                "size": agent._quote_size,
                "half": agent._half_spread,
            }
            for agent_id, agent in self.agents.items()
            if isinstance(agent, InventoryMarketMaker)
        ]
        return {
            "type": "frame",
            "t": self.kernel.now,
            "horizon": self.config.horizon_ns,
            "status": "done" if self.done else ("paused" if self.paused else "live"),
            "speed": self.speed,
            "events": self.kernel.events_processed,
            "bids": [[level.price, level.qty] for level in snap.bids],
            "asks": [[level.price, level.qty] for level in snap.asks],
            "trades": new_trades,
            "makers": makers,
            "perturbations": [
                {"t": p["t"], "aid": p["aid"], "param": p["prm"], "value": p["v"]}
                for p in self._recorder.perturbations
            ],
        }

    # -- controls ------------------------------------------------------------

    def perturb(self, agent_id: int, param: str, value: int) -> int:
        """Schedule a live perturbation 1 sim-ms ahead (strictly later — the
        ADR-010 rule the kernel enforces). Returns the effective sim time."""
        with self._lock:
            if self.done:
                raise RuntimeError("run complete — nothing left to perturb")
            effective = self.kernel.now + 1_000_000
            self.kernel.schedule_perturbation(effective, agent_id, param, value)
            return effective

    def set_speed(self, speed: float) -> None:
        with self._lock:
            self.speed = max(0.05, min(50.0, float(speed)))

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self.paused = bool(paused)

    def meta(self) -> dict:
        return {
            "scenario": self.config.name,
            "seed": self.config.master_seed,
            "horizon_ns": self.config.horizon_ns,
            "agents": [
                {
                    "id": spec.agent_id,
                    "class": spec.agent_class,
                    "params": spec.params,
                }
                for spec in self.config.agents
            ],
        }
