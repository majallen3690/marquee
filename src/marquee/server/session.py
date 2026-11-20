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
GRID_NS = 100_000_000  # the 100 ms grid the M5 crash gate measures on
MIDS_KEEP = 60
SNAP_NS = 500_000_000  # replay snapshots; a multiple of GRID_NS
VOL_BUCKET_NS = 250_000_000


class TeeRecorder:
    """ADR-007's one-producer-two-sinks: lines go to JSONL untouched; trade and
    perturbation lines are additionally parsed into ring buffers for the UI."""

    def __init__(self, inner: JsonlRecorder) -> None:
        self._inner = inner
        self.trades: deque[dict] = deque(maxlen=TAPE_KEEP)
        self.perturbations: list[dict] = []
        # Run-long ledger, so a page that connects mid-run still shows true totals
        # (the tape ring only keeps TAPE_KEEP trades). Integer ticks and shares.
        self.ledger: dict[int, dict[str, int]] = {}
        self.n_trades = 0
        self.price_volume = 0  # sum of px * qty
        self.volume = 0
        self.net_taker = 0  # taker buys minus taker sells
        self.max_tid = -1
        self.vol: dict[int, list[int]] = {}  # 250 ms bucket -> [taker-buy qty, taker-sell qty]
        # The biggest taker-sell burst since the first lever, grouped by (t, taker):
        # the engine event "X sells N through hi -> lo". Server-side so a late page has it.
        self._bursts: dict[tuple[int, int], dict[str, int]] = {}
        self.burst: dict[str, int] | None = None

    def _row(self, agent_id: int) -> dict[str, int]:
        return self.ledger.setdefault(
            agent_id, {"inv": 0, "cash": 0, "fm": 0, "ft": 0, "vol": 0, "mvol": 0, "sold_after": 0}
        )

    def record_line(self, line: str) -> None:
        self._inner.record_line(line)
        if line.startswith('{"aid"') and '"k":"prt"' in line:
            self.perturbations.append(json.loads(line))

    def record_trade_line(self, line: str) -> None:
        self._inner.record_trade_line(line)
        trade = json.loads(line)
        self.trades.append(trade)
        qty, px = trade["qty"], trade["px"]
        taker_buys = trade["tks"] == 0
        after_lever = bool(self.perturbations) and trade["t"] >= self.perturbations[0]["t"]
        for agent_id, buys, is_maker in (
            (trade["tka"], taker_buys, False),
            (trade["mka"], not taker_buys, True),
        ):
            row = self._row(agent_id)
            row["inv"] += qty if buys else -qty
            row["cash"] += -qty * px if buys else qty * px
            row["vol"] += qty
            if is_maker:
                row["mvol"] += qty
                row["fm"] += 1
            else:
                row["ft"] += 1
                if not buys and after_lever:
                    row["sold_after"] += qty
        bucket = self.vol.setdefault(trade["t"] // VOL_BUCKET_NS, [0, 0])
        bucket[0 if taker_buys else 1] += qty
        self.max_tid = max(self.max_tid, trade["tid"])
        if after_lever and not taker_buys:
            key = (trade["t"], trade["tka"])
            b = self._bursts.setdefault(
                key, {"t": trade["t"], "aid": trade["tka"], "qty": 0, "lo": px, "hi": px}
            )
            b["qty"] += qty
            b["lo"], b["hi"] = min(b["lo"], px), max(b["hi"], px)
            if self.burst is None or b["qty"] > self.burst["qty"]:
                self.burst = b
        self.n_trades += 1
        self.price_volume += px * qty
        self.volume += qty
        self.net_taker += qty if taker_buys else -qty

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
        self._grid_next = GRID_NS  # skip t=0: empty book, same as sample_mid_series
        self.mid_series: list[tuple[int, float]] = []  # (t, mid) on the grid
        self._last_mid: float | None = None
        self.snapshots: list[dict] = []  # a slim frame every SNAP_NS, for backfill and scrubbing
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
                self._advance(self._sim_target)
                if self._sim_target >= self.config.horizon_ns:
                    self.done = True
                    self._recorder.close()
                    write_manifest(self._out, self._raw, self.config)
            return self._frame()

    def _advance(self, target: int) -> None:
        """Run to `target`, stopping at every grid instant to sample the mid, so the
        UI's headline number is measured exactly as the committed crash gate
        (tests/test_m5_crash.py) measures it, at any playback speed."""
        while self._grid_next <= target:
            self.kernel.run_until(self._grid_next)
            snap = self.kernel.engine.snapshot(ts=self._grid_next, depth=1)
            if snap.bids and snap.asks:
                self._last_mid = (snap.bids[0].price + snap.asks[0].price) / 2
            if self._last_mid is not None:  # a one-sided book carries the last mid forward
                self.mid_series.append((self._grid_next, self._last_mid))
            if self._grid_next % SNAP_NS == 0:
                self.snapshots.append(self._frame(slim=True))
            self._grid_next += GRID_NS
        self.kernel.run_until(target)

    def _frame(self, slim: bool = False) -> dict:
        snap = self.kernel.engine.snapshot(ts=self.kernel.now, depth=FRAME_DEPTH)
        # The tape is stateless on the wire: every frame carries the last
        # TAPE_KEEP trades and the client replaces wholesale, keying rows by
        # tid for its flash effect. No cursor protocol to get wrong.
        new_trades = [
            {
                "tid": tr["tid"],
                "t": tr["t"],
                "px": tr["px"],
                "qty": tr["qty"],
                "side": tr["tks"],
                "tka": tr["tka"],
            }
            for tr in list(self._recorder.trades)
        ]
        ledger = self._recorder.ledger
        empty = {"inv": 0, "cash": 0, "fm": 0, "ft": 0, "vol": 0, "mvol": 0, "sold_after": 0}
        agents = [
            {"id": spec.agent_id, "cls": spec.agent_class, **ledger.get(spec.agent_id, empty)}
            for spec in self.config.agents
        ]
        recorder = self._recorder
        stats = {
            "trades": recorder.n_trades,
            "vwap": recorder.price_volume / recorder.volume if recorder.volume else None,
            "net": recorder.net_taker,
            "burst": dict(recorder.burst) if recorder.burst else None,
        }
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
            "agents": agents,
            "stats": stats,
            # the last MIDS_KEEP grid samples, wholesale like the tape; the client dedupes by t
            "mids": [] if slim else [[t, mid] for t, mid in self.mid_series[-MIDS_KEEP:]],
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

    def history(self) -> dict:
        """Everything a page needs to backfill (or scrub) the run so far: the whole
        gate-grid mid series, a slim frame every 500 ms, and the volume buckets."""
        with self._lock:
            return {
                "mids": [[t, mid] for t, mid in self.mid_series],
                "frames": list(self.snapshots),
                "vol": [[b, v[0], v[1]] for b, v in sorted(self._recorder.vol.items())],
                "last_tid": self._recorder.max_tid,
            }

    def meta(self) -> dict:
        return {
            "scenario": self.config.name,
            "seed": self.config.master_seed,
            "horizon_ns": self.config.horizon_ns,
            # The scenario's scripted levers, so the UI can say "fires in 6.0 s".
            "scheduled": [
                {"t": p.t_ns, "aid": p.agent_id, "param": p.param, "value": p.value}
                for p in self.config.perturbations
            ],
            "agents": [
                {
                    "id": spec.agent_id,
                    "class": spec.agent_class,
                    "params": spec.params,
                }
                for spec in self.config.agents
            ],
        }
