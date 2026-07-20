"""Stylized-facts computation for calibration (M4 gate).

Computes, from a recorded run, the four facts the brief names, with thresholds
defended in ADR-013 against values reported for real markets:

  1. Fat tails       — excess kurtosis of mid log-returns > 0 (real intraday:
                       ~2-50 at seconds-to-minutes scales; Cont 2001)
  2. No linear
     predictability  — raw-return autocorrelation ~ 0 beyond microstructure
                       lags (tick-scale lag-1 is legitimately negative:
                       bid-ask bounce)
  3. Volatility
     clustering      — autocorrelation of squared returns positive and slowly
                       decaying
  4. Order-flow
     clustering      — trade-sign autocorrelation positive (buys follow buys;
                       Bouchaud/Farmer long memory of order flow)

Mid sampling: L1 reconstructed by order-stream replay on a fixed grid;
one-sided/empty samples carry the last known mid forward. The single
sanctioned mid_x2 halving lives here (ADR-004).

Usage:
    uv run python -m marquee.analysis.stylized_facts scenarios/m4-calibrated.yaml runs/out
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from marquee.engine import MatchingEngine, Order, OrderType, SelfTradePolicy, Side


def mid_from_x2(mid_x2: int) -> float:
    """The one sanctioned halving of mid_x2 (ADR-004). Analysis layer only."""
    return mid_x2 / 2.0


def acf(series: np.ndarray, max_lag: int) -> np.ndarray:
    """Biased sample autocorrelation, lags 1..max_lag."""
    x = series - series.mean()
    denominator = float(np.dot(x, x))
    if denominator == 0.0:
        return np.zeros(max_lag)
    return np.array(
        [float(np.dot(x[:-lag], x[lag:])) / denominator for lag in range(1, max_lag + 1)]
    )


@dataclass(frozen=True, slots=True)
class StylizedFacts:
    n_returns: int
    return_std: float
    excess_kurtosis: float
    acf_raw: tuple[float, ...]  # lags 1..K
    acf_squared: tuple[float, ...]
    n_trades: int
    acf_trade_signs: tuple[float, ...]


def sample_mid_series(
    run_dir: str | Path,
    self_trade_policy: SelfTradePolicy,
    horizon_ns: int,
    sample_interval_ns: int,
) -> list[float]:
    engine = MatchingEngine(self_trade_policy=self_trade_policy)
    mids: list[float] = []
    last_mid: float | None = None
    next_sample = sample_interval_ns  # skip t=0 (empty book, nothing to carry)

    def take_samples_up_to(t: int) -> None:
        nonlocal next_sample, last_mid
        while next_sample <= t and next_sample <= horizon_ns:
            best_bid = engine.best_bid
            best_ask = engine.best_ask
            if best_bid is not None and best_ask is not None:
                last_mid = mid_from_x2(best_bid + best_ask)
            if last_mid is not None:
                mids.append(last_mid)
            next_sample += sample_interval_ns

    with open(Path(run_dir) / "events.jsonl", encoding="utf-8", newline="\n") as f:
        for raw in f:
            ev = json.loads(raw)
            take_samples_up_to(ev["t"])
            kind = ev["k"]
            if kind == "ord":
                engine.submit(
                    Order(
                        order_id=ev["oid"],
                        agent_id=ev["aid"],
                        side=Side(ev["side"]),
                        order_type=OrderType(ev["ot"]),
                        price=ev["px"],
                        qty=ev["qty"],
                        ts=ev["t"],
                    )
                )
            elif kind == "cxl" and ev["cs"] == 0:
                engine.cancel(ev["oid"])
    take_samples_up_to(horizon_ns)
    return mids


def compute_stylized_facts(
    run_dir: str | Path,
    self_trade_policy: SelfTradePolicy,
    horizon_ns: int,
    sample_interval_ns: int = 100_000_000,  # 100 sim-ms returns
    max_lag: int = 10,
) -> StylizedFacts:
    mids = sample_mid_series(run_dir, self_trade_policy, horizon_ns, sample_interval_ns)
    log_mids = np.log(np.array(mids, dtype=np.float64))
    returns = np.diff(log_mids)

    std = float(returns.std())
    if std > 0:
        centered = returns - returns.mean()
        m2 = float(np.mean(centered**2))
        m4 = float(np.mean(centered**4))
        excess_kurtosis = m4 / (m2 * m2) - 3.0
    else:
        excess_kurtosis = 0.0

    signs: list[int] = []
    with open(Path(run_dir) / "trades.jsonl", encoding="utf-8", newline="\n") as f:
        for raw in f:
            trade = json.loads(raw)
            signs.append(1 if trade["tks"] == 0 else -1)  # Side.BUY == 0
    sign_series = np.array(signs, dtype=np.float64)

    return StylizedFacts(
        n_returns=len(returns),
        return_std=std,
        excess_kurtosis=excess_kurtosis,
        acf_raw=tuple(round(v, 4) for v in acf(returns, max_lag)),
        acf_squared=tuple(round(v, 4) for v in acf(returns**2, max_lag)),
        n_trades=len(signs),
        acf_trade_signs=tuple(round(v, 4) for v in acf(sign_series, max_lag)),
    )


def check_facts(facts: StylizedFacts, thresholds: dict) -> list[str]:
    """Returns violations; empty == calibration gate pass (thresholds: ADR-013)."""
    violations: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            violations.append(message)

    require(
        facts.n_returns >= thresholds["min_returns"],
        f"n_returns {facts.n_returns} < {thresholds['min_returns']} (not enough data)",
    )
    require(facts.return_std > 0, "returns are constant — dead market")
    require(
        facts.excess_kurtosis >= thresholds["min_excess_kurtosis"],
        f"excess_kurtosis {facts.excess_kurtosis:.2f} < {thresholds['min_excess_kurtosis']}"
        " (no fat tails)",
    )
    raw_tail = facts.acf_raw[2:]  # lags 3..K: beyond microstructure effects
    require(
        max(abs(v) for v in raw_tail) <= thresholds["max_abs_raw_acf_lag3plus"],
        f"raw-return ACF lags 3+ {raw_tail} exceed "
        f"±{thresholds['max_abs_raw_acf_lag3plus']} (linear predictability)",
    )
    require(
        abs(facts.acf_raw[0]) <= thresholds["max_abs_raw_acf_lag1"],
        f"raw-return ACF lag1 {facts.acf_raw[0]} exceeds "
        f"±{thresholds['max_abs_raw_acf_lag1']}",
    )
    require(
        facts.acf_squared[0] >= thresholds["min_sq_acf_lag1"],
        f"squared-return ACF lag1 {facts.acf_squared[0]} < "
        f"{thresholds['min_sq_acf_lag1']} (no volatility clustering)",
    )
    positive_sq = sum(1 for v in facts.acf_squared if v > 0)
    require(
        positive_sq >= thresholds["min_sq_acf_positive_lags"],
        f"only {positive_sq}/{len(facts.acf_squared)} squared-return ACF lags positive "
        f"(need {thresholds['min_sq_acf_positive_lags']} — clustering should decay slowly)",
    )
    require(
        facts.acf_trade_signs[0] >= thresholds["min_trade_sign_acf_lag1"],
        f"trade-sign ACF lag1 {facts.acf_trade_signs[0]} < "
        f"{thresholds['min_trade_sign_acf_lag1']} (no order-flow clustering)",
    )
    return violations


def main() -> None:
    import yaml

    from marquee.sim.scenario import load_scenario

    scenario_path, run_dir = sys.argv[1], sys.argv[2]
    config, raw = load_scenario(scenario_path)
    thresholds = yaml.safe_load(raw).get("stylized_facts_thresholds")
    if thresholds is None:
        sys.exit(f"{scenario_path} has no stylized_facts_thresholds section")

    facts = compute_stylized_facts(run_dir, config.self_trade_policy, config.horizon_ns)
    for field in facts.__dataclass_fields__:
        print(f"{field:20} {getattr(facts, field)}")
    violations = check_facts(facts, thresholds)
    if violations:
        print("\nCALIBRATION: FAIL")
        for violation in violations:
            print(f"  - {violation}")
        sys.exit(1)
    print("\nCALIBRATION: PASS")


if __name__ == "__main__":
    main()
