"""Evaluation for the M7 gate (RL_DESIGN §8–9, ADR-023).

Everything a policy is judged on is unshaped episode P&L, W_T − W_0 with terminal
inventory valued by walking the book, on fixed committed episode sets that training
never sees. Episodes are paired: the same (seed, start) is played by every
controller, and the market is identical up to the entrant's arrival.

Episode sets (fixed, committed, disjoint)
    TRAIN_EVAL   40 episodes drawn from the training seed pool: choosing the best fixed
                 quoting rule (tuned on training seeds, like the policy) and detector G10.
    VALIDATION   20 episodes for picking checkpoints during training.
    HELD_OUT     40 episodes: the gate. Never used for any choice.
    HELD_OUT_2   20 more held-out episodes: ablation A2.

The gate (ADR-023 strengthens §9): on HELD_OUT, risk-adjusted P&L (mean / std) beats
both the rule-based maker *and* the best fixed quoting rule, with no detector tripped
(G1–G10) and no ablation collapse (A1–A6).
"""

import dataclasses
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import numpy as np

from marquee.engine.types import SelfTradePolicy
from marquee.rl.agents import OFFSETS, SIZE_FRACTIONS
from marquee.rl.env import EnvConfig, MarketMakingEnv


@dataclass(frozen=True)
class Episode:
    master_seed: int
    start_step: int
    latency_scale: float = 1.0


def _episodes(n: int, seed_lo: int, draw_seed: int, pool: tuple[int, int] | None = None):
    env = MarketMakingEnv(EnvConfig())
    lo, hi = env._start_steps
    rng = np.random.default_rng(draw_seed)
    seeds = rng.integers(*pool, size=n).tolist() if pool else list(range(seed_lo, seed_lo + n))
    starts = rng.integers(lo, hi + 1, size=n).tolist()
    return tuple(Episode(int(s), int(t)) for s, t in zip(seeds, starts, strict=True))


TRAIN_EVAL = _episodes(40, 0, 11, pool=EnvConfig().seed_pool)
VALIDATION = _episodes(20, 3_000_001, 12)
HELD_OUT = _episodes(40, 2_000_001, 13)
HELD_OUT_2 = _episodes(20, 4_000_001, 14)


# --- policies (picklable specs, built inside the worker) ---------------------

type PolicySpec = tuple  # ("rule",) | ("fixed", (b, a, s)) | ("random", seed) | ("ppo", path)
# | ("model", live_model) — in-process only, never sent to a worker

_PPO_CACHE: dict[str, object] = {}


def _act(spec: PolicySpec, obs: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    kind = spec[0]
    if kind == "fixed":
        return np.asarray(spec[1])
    if kind == "random":
        return np.array([rng.integers(len(OFFSETS)), rng.integers(len(OFFSETS)), rng.integers(3)])
    if kind == "model":  # a live SB3 model, in-process only (validation during training)
        action, _ = spec[1].predict(obs, deterministic=True)
        return action
    if kind == "ppo":
        model = _PPO_CACHE.get(spec[1])
        if model is None:
            from stable_baselines3 import PPO

            model = PPO.load(spec[1], device="cpu")
            _PPO_CACHE[spec[1]] = model
        action, _ = model.predict(obs, deterministic=True)
        return action
    return np.zeros(3, dtype=np.int64)  # "rule": ignored by the env


def run_episode(spec: PolicySpec, cfg: EnvConfig, ep: Episode) -> dict:
    controller = "rule" if spec[0] == "rule" else "learned"
    env = MarketMakingEnv(dataclasses.replace(cfg, controller=controller))
    rng = np.random.default_rng(ep.master_seed)
    obs, _ = env.reset(options=dataclasses.asdict(ep))
    while True:
        obs, _r, _term, trunc, info = env.step(_act(spec, obs, rng))
        if trunc:
            out = info["episode"]
            out.update(dataclasses.asdict(ep))
            return out


def run_eval(
    spec: PolicySpec, episodes, cfg: EnvConfig | None = None, workers: int | None = None
) -> list[dict]:
    cfg = cfg or EnvConfig(latency_jitter=0.0)
    workers = workers or min(12, os.cpu_count() or 1)
    if workers <= 1:
        return [run_episode(spec, cfg, ep) for ep in episodes]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run_episode, [spec] * len(episodes), [cfg] * len(episodes), episodes))


# --- statistics ---------------------------------------------------------------


def risk_adjusted(rows: list[dict]) -> float:
    pnl = np.array([r["pnl"] for r in rows])
    sd = pnl.std(ddof=1)
    return float(pnl.mean() / sd) if sd > 0 else (math.inf if pnl.mean() > 0 else 0.0)


def describe(rows: list[dict]) -> dict:
    pnl = np.array([r["pnl"] for r in rows])
    return {
        "n": len(rows),
        "mean_pnl": float(pnl.mean()),
        "std_pnl": float(pnl.std(ddof=1)),
        "risk_adjusted": risk_adjusted(rows),
        "spread_capture": float(np.mean([r["spread_capture"] for r in rows])),
        "inventory_pnl": float(np.mean([r["inventory_pnl"] for r in rows])),
        "maker_volume": float(np.mean([r["maker_volume"] for r in rows])),
    }


def paired(a: list[dict], b: list[dict]) -> dict:
    """a vs b on the same episodes: how often a made more, exact two-sided sign test."""
    wins = sum(x["pnl"] > y["pnl"] for x, y in zip(a, b, strict=True))
    losses = sum(x["pnl"] < y["pnl"] for x, y in zip(a, b, strict=True))
    n = wins + losses
    k = max(wins, losses)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k, n + 1)) / 2**n) if n else 1.0
    return {"wins": wins, "losses": losses, "sign_p": p}


def inventory_half_life(rows: list[dict]) -> float:
    """Steps for |q| to halve, from a pooled AR(1) fit of q on its own lag."""
    num = den = 0.0
    for r in rows:
        q = np.asarray(r["q_path"], dtype=float)
        num += float(np.dot(q[1:], q[:-1]))
        den += float(np.dot(q[:-1], q[:-1]))
    if den == 0:
        return 0.0
    phi = num / den
    if phi <= 0:
        return 0.0
    if phi >= 1:
        return math.inf
    return math.log(0.5) / math.log(phi)


# --- detectors (§8.2) ---------------------------------------------------------

HALF_LIFE_MAX_STEPS = 100  # a third of an episode (10 s); set here, before any training


def detectors(
    cand: list[dict], rule: list[dict], cand_train: list[dict] | None = None
) -> dict[str, dict]:
    """Each: value, threshold, passed. G8 and G9 do not apply at Stage 1 in a
    scenario without perturbations; they are reported as such, not as passes."""

    def mean(rows, key):
        return float(np.mean([r[key] for r in rows]))

    spreads_c = [r["median_spread"] for r in cand if r["median_spread"] is not None]
    spreads_r = [r["median_spread"] for r in rule if r["median_spread"] is not None]
    maker = sum(r["maker_volume"] for r in cand)
    taker = sum(r["taker_volume"] for r in cand)
    out = {
        "G1 fill rate vs rule": (mean(cand, "maker_fills"), 0.25 * mean(rule, "maker_fills"), ">="),
        "G2 two-sided steps": (mean(cand, "two_sided_frac"), 0.99, ">="),
        "G3 median spread vs rule": (
            float(np.median(spreads_c)) if spreads_c else math.inf,
            2 * float(np.median(spreads_r)),
            "<=",
        ),
        "G4 maker share of volume": (maker / (maker + taker) if maker + taker else 1.0, 0.80, ">="),
        "G5 self-trade volume": (float(sum(r["self_trade_volume"] for r in cand)), 0.0, "<="),
        "G6 directional P&L share": (
            sum(r["inventory_pnl"] for r in cand) / max(1e-9, sum(r["abs_dW"] for r in cand)),
            0.40,
            "<=",
        ),
        "G7 inventory half-life (steps)": (inventory_half_life(cand), HALF_LIFE_MAX_STEPS, "<="),
    }
    res = {
        k: {"value": v, "threshold": t, "passed": v >= t if op == ">=" else v <= t}
        for k, (v, t, op) in out.items()
    }
    res["G8 no forgetting vs Stage-1 population"] = {
        "value": None,
        "threshold": None,
        "passed": None,
        "note": "applies from Stage 2",
    }
    res["G9 held-out perturbation times"] = {
        "value": None,
        "threshold": None,
        "passed": None,
        "note": "no perturbation in M7; M8",
    }
    if cand_train is not None:
        held, train = describe(cand)["mean_pnl"], describe(cand_train)["mean_pnl"]
        res["G10 held-out vs training seeds"] = {
            "value": held / train if train else None,
            "threshold": 0.75,
            "passed": held >= train - 0.25 * abs(train),
            "note": "held-out mean P&L no more than 25% below training seeds (better passes)",
        }
    return res


# --- ablations (§8.3) ---------------------------------------------------------

ABLATIONS: dict[str, tuple[EnvConfig, tuple]] = {
    "A1 latency x0.5": (EnvConfig(latency_jitter=0.0), "latency:0.5"),
    "A1 latency x1.5": (EnvConfig(latency_jitter=0.0), "latency:1.5"),
    "A2 second held-out set": (EnvConfig(latency_jitter=0.0), "held_out_2"),
    "A3 self-trade REJECT_TAKER": (
        EnvConfig(latency_jitter=0.0, stp=SelfTradePolicy.REJECT_TAKER),
        "held_out",
    ),
    "A4 one fewer momentum trader": (EnvConfig(latency_jitter=0.0, momentum_delta=-1), "held_out"),
    "A4 one more momentum trader": (EnvConfig(latency_jitter=0.0, momentum_delta=1), "held_out"),
    "A5 mark at last trade": (EnvConfig(latency_jitter=0.0, mark="last_trade"), "held_out"),
    "A6 base quote size halved": (EnvConfig(latency_jitter=0.0, size_scale=0.5), "held_out"),
}


def ablation_episodes(which: str):
    if which == "held_out_2":
        return HELD_OUT_2
    if which.startswith("latency:"):
        scale = float(which.split(":")[1])
        return tuple(dataclasses.replace(e, latency_scale=scale) for e in HELD_OUT)
    return HELD_OUT


def ablations(spec: PolicySpec, base_mean: float, workers: int | None = None) -> dict:
    """Collapse = mean P&L below half of the main held-out mean (§8.3)."""
    out = {}
    for name, (cfg, which) in ABLATIONS.items():
        rows = run_eval(spec, ablation_episodes(which), cfg, workers)
        m = describe(rows)["mean_pnl"]
        out[name] = {
            "mean_pnl": m,
            "vs_main": m / base_mean if base_mean else None,
            "collapsed": base_mean > 0 and m < 0.5 * base_mean,
        }
    return out


# --- baselines (§8.1) -----------------------------------------------------------

FIXED_GRID = tuple((o, o, s) for o in range(len(OFFSETS)) for s in range(len(SIZE_FRACTIONS)))
DO_NOTHING = ("fixed", (len(OFFSETS) - 1, len(OFFSETS) - 1, 0))  # widest, smallest


def best_fixed(workers: int | None = None) -> tuple[tuple[int, int, int], dict]:
    """The strongest static quoting rule, chosen on TRAIN_EVAL (training seeds) by
    risk-adjusted P&L, exactly as a policy would be tuned. Returns it and the table."""
    table = {}
    for action in FIXED_GRID:
        table[action] = describe(run_eval(("fixed", action), TRAIN_EVAL, workers=workers))
    best = max(table, key=lambda a: table[a]["risk_adjusted"])
    return best, table
