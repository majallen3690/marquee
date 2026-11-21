"""Gymnasium environment: one market-making seat in the M7 gate market (RL_DESIGN §2–6).

Episode
    A random window of the scenario (D6): the market runs normally until a start time
    drawn per episode, then the seat's original rule-based maker leaves and a fresh
    entrant takes the seat with no inventory. ``controller="learned"`` makes the
    entrant the policy; ``controller="rule"`` makes it a fresh copy of the rule-based
    maker with the original's parameters, which is the baseline. Same master seed and
    start step give the same market up to the entrant's arrival, so the two are paired.
Step
    100 ms. The action sets the entrant's quotes for the next step (one quote update
    per step, by construction); the simulator then runs to the next decision time.
Reward (§6)
    r = (S + I − η·max(0, I)) / base_size − γ·(q / q_max)², where S is spread capture
    and I is inventory P&L, both marked at the mid of the book *without* the seat's
    own orders. On the last step, inventory still held is valued by walking the book
    (its cost lands in S). The shaped reward trains; the gate scores unshaped P&L.
Randomized per episode (D4, D6, D7)
    master seed from the training pool, start time, and latency scaled ±50%.
Stages (§11)
    0: no rule-based makers at all; 1: the full population (the gate, ADR-023).
"""

import dataclasses
import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import gymnasium as gym
import numpy as np

from marquee.agents.market_maker import InventoryMarketMaker
from marquee.engine import MatchingEngine
from marquee.engine.types import SelfTradePolicy, Side
from marquee.rl.accounting import (
    Ledger,
    TapeRecorder,
    liquidation_value,
    mid_excluding,
    squash,
)
from marquee.rl.agents import OFFSETS, SIZE_FRACTIONS, LearnedMarketMaker, Window
from marquee.sim.kernel import SimKernel
from marquee.sim.scenario import ScenarioConfig, build_agent, load_scenario

REPO = Path(__file__).resolve().parents[3]
GATE_SCENARIO = REPO / "scenarios" / "m7-makers.yaml"  # ADR-023
STEP_NS = 100_000_000
ENTRANT_ID = 3  # unused by every scenario's population
FLOW_STEPS = 20  # 2 s of history for the flow features
OBS_DIM = 33


@dataclass(frozen=True)
class EnvConfig:
    scenario: Path = GATE_SCENARIO
    stage: int = 1
    seat: int = 2  # the rule-based maker whose seat the entrant takes
    controller: str = "learned"  # or "rule": the baseline in the same seat
    episode_steps: int = 300  # 30 sim-seconds
    min_start_s: float = 10.0
    # Training caps the start: each reset simulates the market up to the start, and a
    # start anywhere in 10-150 s spends most compute on warm-up. Start still varies
    # (D6); evaluation uses the full range, so held-out starts include unseen times.
    max_start_s: float | None = None
    eta: float = 0.5
    gamma: float = 0.01
    latency_jitter: float = 0.5  # latency scaled by U[1 − j, 1 + j] per episode
    seed_pool: tuple[int, int] = (1, 1_000_000)  # training master seeds, [lo, hi)
    # ablation switches (RL_DESIGN §8.3); defaults are the trained setting
    stp: SelfTradePolicy = SelfTradePolicy.CANCEL_RESTING  # A3: REJECT_TAKER
    momentum_delta: int = 0  # A4: −1 drops a momentum trader, +1 adds one
    mark: str = "excluded_mid"  # A5: "last_trade"
    size_scale: float = 1.0  # A6: 0.5 halves the seat's base quote size


class MarketMakingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, config: EnvConfig | None = None) -> None:
        self.cfg = config or EnvConfig()
        if self.cfg.controller not in ("learned", "rule"):
            raise ValueError(f"unknown controller {self.cfg.controller!r}")
        if self.cfg.mark not in ("excluded_mid", "last_trade"):
            raise ValueError(f"unknown mark {self.cfg.mark!r}")
        base, _ = load_scenario(self.cfg.scenario)
        self._base = base
        seat = next(a for a in base.agents if a.agent_id == self.cfg.seat)
        if seat.agent_class != "market_maker":
            raise ValueError(f"seat {self.cfg.seat} is not a market maker")
        self._seat_params = dict(seat.params)
        self._seat_params["quote_size"] = max(
            1, round(self._seat_params["quote_size"] * self.cfg.size_scale)
        )
        self._seat_wake = seat.mean_wake_interval_ns
        self.base_size: int = self._seat_params["quote_size"]
        self.q_max: int = self._seat_params["hard_limit"]
        latest = base.horizon_ns - (self.cfg.episode_steps + 1) * STEP_NS
        if self.cfg.max_start_s is not None:
            latest = min(latest, int(self.cfg.max_start_s * 1e9))
        self._start_steps = (int(self.cfg.min_start_s * 1e9) // STEP_NS, latest // STEP_NS)
        if self._start_steps[0] > self._start_steps[1]:
            raise ValueError("scenario horizon too short for this episode length")
        self.action_space = gym.spaces.MultiDiscrete(
            [len(OFFSETS), len(OFFSETS), len(SIZE_FRACTIONS)]
        )
        self.observation_space = gym.spaces.Box(-1.0, 1.0, shape=(OBS_DIM,), dtype=np.float32)

    # -- episode construction ----------------------------------------------------

    def _build(self, master_seed: int, latency_scale: float, t0: int) -> None:
        cfg = self._base
        scaled = {
            "agent_to_exchange_ns": max(1, round(cfg.agent_to_exchange_ns * latency_scale)),
            "exchange_to_agent_ns": max(1, round(cfg.exchange_to_agent_ns * latency_scale)),
            "latency_jitter_ns": round(cfg.latency_jitter_ns * latency_scale),
        }
        config: ScenarioConfig = dataclasses.replace(
            cfg, master_seed=master_seed, self_trade_policy=self.cfg.stp, **scaled
        )
        self.engine = MatchingEngine(self_trade_policy=self.cfg.stp)
        self.tape = TapeRecorder()
        horizon = t0 + (self.cfg.episode_steps + 1) * STEP_NS
        self.kernel = SimKernel(
            master_seed=master_seed,
            engine=self.engine,
            recorder=self.tape,
            horizon_ns=horizon,
            agent_to_exchange_ns=config.agent_to_exchange_ns,
            exchange_to_agent_ns=config.exchange_to_agent_ns,
            latency_jitter_ns=config.latency_jitter_ns,
        )
        specs = list(config.agents)
        momentum = [s for s in specs if s.agent_class == "momentum"]
        if self.cfg.momentum_delta < 0:
            specs.remove(momentum[-1])
        elif self.cfg.momentum_delta > 0:
            specs.append(dataclasses.replace(momentum[-1], agent_id=momentum[-1].agent_id + 1))
        for spec in specs:
            if spec.agent_class == "market_maker" and self.cfg.stage == 0:
                continue
            agent = build_agent(spec)
            if spec.agent_id == self.cfg.seat:
                agent = Window(agent, end_ns=t0)  # leaves the seat at the episode start
            self.kernel.register_agent(agent, spec.mean_wake_interval_ns)
        if self.cfg.controller == "learned":
            self.entrant = LearnedMarketMaker(ENTRANT_ID, self.base_size, self.q_max)
            self.kernel.register_agent(self.entrant, STEP_NS, periodic=True)
        else:
            self.entrant = InventoryMarketMaker(ENTRANT_ID, **self._seat_params)
            self.kernel.register_agent(Window(self.entrant, start_ns=t0), self._seat_wake)

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        opts = options or {}
        rng = self.np_random
        master_seed = int(opts.get("master_seed", rng.integers(*self.cfg.seed_pool)))
        start_step = int(
            opts.get("start_step", rng.integers(self._start_steps[0], self._start_steps[1] + 1))
        )
        j = self.cfg.latency_jitter
        latency_scale = float(opts.get("latency_scale", rng.uniform(1 - j, 1 + j) if j else 1.0))
        self.t0 = start_step * STEP_NS
        self._build(master_seed, latency_scale, self.t0)
        self.kernel.run_until(self.t0 - 1)
        if self.cfg.controller == "learned":
            self.entrant.active = True

        self.k = 0
        self.ledger = Ledger(ENTRANT_ID, cursor=len(self.tape.trades))
        self.m = self._mark(10_000.0)
        m = self.m
        self._mids: deque[float] = deque([m], maxlen=FLOW_STEPS + 1)
        self._flow: deque[tuple[int, int, int]] = deque()  # (t, qty, taker side)
        self._flow_cursor = len(self.tape.trades)
        self.episode = {
            "S": 0.0,
            "I": 0.0,
            "abs_dW": 0.0,
            "steps_two_sided": 0,
            "steps_submitted_two_sided": 0,
            "spreads": [],
            "q_path": [],
        }
        info = {
            "master_seed": master_seed,
            "start_step": start_step,
            "latency_scale": latency_scale,
        }
        return self._obs(), info

    # -- stepping ------------------------------------------------------------------

    def step(self, action):
        if self.cfg.controller == "learned":
            self.entrant.action = (int(action[0]), int(action[1]), int(action[2]))
        self.k += 1
        self.kernel.run_until(self.t0 + self.k * STEP_NS - 1)

        led = self.ledger
        q0, c0 = led.q, led.cash
        led.consume(self.tape.trades)
        m_prev = self.m
        m = self._mark(m_prev)
        S = (led.cash - c0) + (led.q - q0) * m
        I = q0 * (m - m_prev)  # noqa: E741 — the design note's symbol
        truncated = self.k >= self.cfg.episode_steps
        liq_cost = 0.0
        if truncated:
            value = liquidation_value(self.engine, ENTRANT_ID, led.q, fallback=m)
            liq_cost = value - led.q * m  # ≤ 0: what unwinding at the touch-and-beyond costs
            S += liq_cost
        self.m = m
        self._mids.append(m)

        cfg = self.cfg
        reward = (S + I - cfg.eta * max(0.0, I)) / self.base_size - cfg.gamma * (
            led.q / self.q_max
        ) ** 2

        quotes = self._own_quotes()
        two_sided = quotes[0] is not None and quotes[2] is not None
        ep = self.episode
        ep["S"] += S
        ep["I"] += I
        ep["abs_dW"] += abs(S + I)
        ep["steps_two_sided"] += two_sided
        submitted = getattr(self.entrant, "last_quote", None)  # learned controller only
        if submitted is not None:
            ep["steps_submitted_two_sided"] += None not in submitted
        if two_sided:
            ep["spreads"].append(quotes[2] - quotes[0])
        ep["q_path"].append(led.q)
        info = {"S": S, "I": I, "q": led.q, "mid": m, "two_sided": two_sided}
        if truncated:
            info["episode"] = self.summary(liq_cost)
        return self._obs(), float(reward), False, truncated, info

    def _mark(self, fallback: float) -> float:
        """The price inventory is marked at: the own-order-excluded mid (§5 rule 1),
        or, for ablation A5 only, the last trade."""
        if self.cfg.mark == "last_trade":
            return float(self.tape.trades[-1][1]) if self.tape.trades else fallback
        m = mid_excluding(self.engine, ENTRANT_ID)
        if m is None:
            return float(self.tape.trades[-1][1]) if self.tape.trades else fallback
        return m

    def summary(self, liq_cost: float = 0.0) -> dict:
        """Unshaped results for the gate and the detectors (§8–9)."""
        led, ep = self.ledger, self.episode
        spreads = ep["spreads"]
        return {
            "pnl": ep["S"] + ep["I"],  # = W_T − W_0 with W_T at liquidation value
            "spread_capture": ep["S"],
            "inventory_pnl": ep["I"],
            "liquidation_cost": liq_cost,
            "maker_volume": led.maker_volume,
            "taker_volume": led.taker_volume,
            "maker_fills": led.maker_fills,
            "self_trade_volume": led.self_trade_volume,
            "abs_dW": ep["abs_dW"],
            "two_sided_frac": ep["steps_two_sided"] / max(1, self.k),  # resting at step end
            # both sides submitted at the step's quote update (§7 D1; ADR-024); None
            # for the rule-based controller, which does not expose its decisions
            "submitted_two_sided_frac": (
                ep["steps_submitted_two_sided"] / max(1, self.k)
                if hasattr(self.entrant, "last_quote")
                else None
            ),
            "median_spread": float(np.median(spreads)) if spreads else None,
            "final_q": led.q,
            "q_path": list(ep["q_path"]),
            "steps": self.k,
        }

    # -- observation (§3) ----------------------------------------------------------

    def _own_quotes(self) -> tuple[int | None, int | None, int | None, int | None]:
        """(best own bid, its order id, best own ask, its order id) from the book."""
        bid = bid_id = ask = ask_id = None
        for oid, side, px, _rem in self.engine.own_orders(ENTRANT_ID):
            if side is Side.BUY and (bid is None or px > bid):
                bid, bid_id = px, oid
            elif side is Side.SELL and (ask is None or px < ask):
                ask, ask_id = px, oid
        return bid, bid_id, ask, ask_id

    def _queue_frac(self, oid: int | None) -> float:
        if oid is None:
            return 1.0
        ahead = self.engine.queue_ahead(oid)
        mine = next((r for o, _s, _p, r in self.engine.own_orders(ENTRANT_ID) if o == oid), 0)
        if ahead is None or ahead + mine == 0:
            return 1.0
        return ahead / (ahead + mine)

    def _obs(self) -> np.ndarray:
        ex = self.engine.snapshot_excluding(0, 5, ENTRANT_ID)
        rb = ex.bids[0].price if ex.bids else None
        ra = ex.asks[0].price if ex.asks else None
        f: list[float] = []
        for levels, ref in ((ex.bids, rb), (ex.asks, ra)):
            for i in range(5):
                if i < len(levels):
                    f.append(min(abs(levels[i].price - ref) / 10, 1.0))
                    f.append(min(math.log1p(levels[i].qty) / math.log1p(500), 1.0))
                else:
                    f.extend((1.0, 0.0))
        f.append(min((ra - rb) / 10, 1.0) if rb is not None and ra is not None else 1.0)
        bid, bid_id, ask, ask_id = self._own_quotes()
        f.append((rb - bid) / 10 if bid is not None and rb is not None else 1.0)
        f.append((ask - ra) / 10 if ask is not None and ra is not None else 1.0)
        f.append(self._queue_frac(bid_id))
        f.append(self._queue_frac(ask_id))

        led, m = self.ledger, self.m
        scale = self.base_size * 5
        f.append(led.q / self.q_max)
        f.append(squash(led.unrealized(m), scale))
        f.append(squash(led.realized(), scale))
        f.append(1 - self.k / self.cfg.episode_steps)

        # flow over the last FLOW_STEPS steps, from the public tape
        now = self.kernel.now
        trades = self.tape.trades
        for t, _px, qty, _mka, _tka, tks in trades[self._flow_cursor :]:
            self._flow.append((t, qty, tks))
        self._flow_cursor = len(trades)
        cutoff = now - FLOW_STEPS * STEP_NS
        while self._flow and self._flow[0][0] <= cutoff:
            self._flow.popleft()
        mids = np.asarray(self._mids)
        vol = float(np.std(np.diff(mids))) / 5 if len(mids) > 2 else 0.0
        buy = sum(q for _t, q, s in self._flow if s == Side.BUY)
        sell = sum(q for _t, q, s in self._flow if s == Side.SELL)
        f.append(min(vol, 1.0))
        f.append((buy - sell) / (buy + sell) if buy + sell else 0.0)
        f.append(min(len(self._flow) / (FLOW_STEPS * 10), 1.0))
        f.append((m - mids[0]) / 20)

        obs = np.clip(np.asarray(f, dtype=np.float32), -1.0, 1.0)
        assert obs.shape == (OBS_DIM,)
        return obs
