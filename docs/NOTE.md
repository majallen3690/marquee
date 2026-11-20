# Maker withdrawal amplifies the price move, through distance, not depth

*A controlled study in a deterministic limit-order-book simulator.*
Marquee technical note, November 2026. Every number below is reproducible with the
commands in §9, and the main ones are asserted by tests.

## 1. Summary

In a population of eleven rule-based agents trading through a from-scratch matching
engine, cutting the two market makers' risk appetite at t = 30 s roughly **doubles how far
the price moves in the next five seconds**: median 64.8 ticks against 27.0 for the same
seeds with nothing changed, larger on 23 of 30 seeds (sign test p = 0.005; 28 of 30 on
executed prices). It does **not** reliably push the price down: the move is downward on
16 of 30 seeds. The three trend-following agents are the amplifier: without them the
lever's effect shrinks to a median of 21.2 ticks.

**Taking the lever apart (§6) shows what does the work: how far the makers quote from
the best price, not how much they quote.** Widening their quotes alone moves the price
4.8× as far as the untouched twin, on all 30 seeds, and the move grows steadily with the
distance. Cutting their quote size alone removes 78% of the shares near the price and
changes nothing. Cutting their inventory limits changes nothing on its own and *weakens*
the effect of the wider quotes.

The project's demo seed (777002) falls 107.5 ticks in five seconds, 3.8× its worst normal
5-second range; its untouched twin rises 58 ticks over the same window. It is the
deepest fall of the 30 seeds and was chosen for the demo. The committed crash test
alone cannot show that the lever caused it, because the twin passes the test's ratio
too. This note reports the controlled result and what it does and does not support.

## 2. The system

- **Matching engine.** Price-time priority limit order book, property-tested against a
  shadow book rebuilt from engine outputs (`tests/test_engine_*`), about 406k messages/s.
- **Kernel.** Event-driven and fully deterministic: a run is a function of its scenario
  file and seed, and replays byte for byte, including perturbations inserted by hand
  mid-run (`tests/test_live_replay.py`, `tests/test_scenario_replay.py`).
- **Agents.** Two inventory-managing market makers that are most of the book's depth,
  three momentum traders with position caps (45, 60, 80; checked before each order, so
  they can overshoot by one order), and six noise traders that supply small, quickly
  cancelled flow. They see only what a participant sees: the book, their fills, their
  inventory.
- **Calibration.** A calmer sibling scenario reproduces four stylized facts of real
  markets: fat-tailed returns, volatility clustering, no linear predictability of
  returns, and long-memory order flow (`tests/test_m4_gate.py`).

## 3. The experiment

**Scenario.** `scenarios/m5-flash-crash.yaml`: 60 s of sim time, the eleven agents above.

**The lever.** At exactly 30 s, four parameters change on both makers: hard inventory
limit 300/360 → 10, soft limit 150/180 → 5, quote size 60/80 → 5, half-spread 2/3 →
12/15 ticks. Nothing else in the scenario changes, ever.

**Metric.** The committed crash gate's own (`tests/test_m5_crash.py`). The mid is sampled
on a 100 ms grid. *Move* is the signed largest deviation of the mid in the 5 s after the
lever from the mid at the lever. *Normal range* is the worst max-minus-min of the mid
over 5 s windows in the 15 s before the lever.

**Control, by construction.** For every seed, the same scenario is also run with its
perturbations removed. Because the simulator is deterministic, the two runs are identical
event for event until 30 s (asserted on the grid by
`tests/test_bridge.py::test_counterfactual_is_the_same_run_until_the_lever`). Any
difference after 30 s is the lever's, not chance's.

**Ablation.** Both arms repeated with the three momentum traders removed.

**Seeds.** The committed 777002 plus 1001–1029, fixed in code so the sweep itself is
reproducible.

## 4. Results

| 30 seeds | lever | no lever (control) | lever, no momentum | control, no momentum |
|---|---|---|---|---|
| median size of the 5 s move (ticks) | **64.8** | 27.0 | 21.2 | 14.5 |
| move larger than its own control | **23 / 30** | — | 24 / 30 | — |
| median paired ratio (lever ÷ control) | **2.11** | — | 1.53 | — |
| price moved down | 16 / 30 | 11 / 30 | | |
| passes the committed gate (≥ 25 ticks, ≥ 2× normal) | 10 / 30 | 4 / 30 | | |

95% bootstrap intervals for the medians: lever 37.8–80.5 ticks, control 20.0–30.8, paired
ratio 1.86–2.69. Measured on executed prices instead of the mid, the lever's move is
bigger than its twin's on 28 of 30 seeds (median 94.0 against 37.0 ticks).

- **The lever amplifies.** Paired with its own untouched twin, the five-second move is
  larger on 23 of 30 seeds (two-sided exact sign test p = 0.005), with a median ratio of
  2.11. Asserted by `tests/test_seed_sweep.py` (`pytest -m slow`).
- **It does not point.** Down on 16 seeds, up on 14. The lever removes the liquidity that
  was absorbing order flow; whichever way the flow is leaning then moves the price further.
- **Trend-followers are the amplifier.** With them, the lever's move is larger than
  without them on 25 of 30 seeds (median 64.8 against 21.2 ticks). Without them the lever
  still amplifies, but by about half as much.
- **The demo seed is the tail.** 777002 ranks first of 30 by signed move: −107.5 ticks
  (about 1.1% of a ~9,926 price), against +58 for its twin and +30.5 for its no-momentum
  variant.

## 5. What the committed gate does and does not show

The gate asserts a move of at least 25 ticks that is at least twice the run's own worst
recent 5-second range, and that the market stays two-sided. That catches a *dislocation
on this seed*. It does not show cause: the demo seed's untouched twin moves +58 ticks,
2.07× its normal range, and would pass the ratio on its own. It does not show direction
either, since the move is unsigned. The gate is kept as written, as a regression test for
the demo, and two tests now carry the causal claim: the paired control on the committed
seed (fast) and the 30-seed sweep (slow).

## 6. Which part of the lever does the work

Full tables, method and the chart: `docs/LEVER_STUDY.md` (ADR-022). Same 30 seeds, each
arm paired with its own untouched twin.

| 30 seeds | median 5 s move (95% CI) | ratio to twin | bigger than twin |
|---|---|---|---|
| no lever | 27.0 (20.0–30.8) | — | — |
| full lever | 64.8 (37.8–80.5) | 2.11 | 23 / 30 |
| inventory limits only | 21.2 (16.0–28.8) | 0.98 | 15 / 30 |
| quote size only (removes 78% of top-5 depth) | 27.5 (18.8–32.5) | 1.03 | 15 / 27 |
| **quoting distance only** | **152.2** (109.0–185.8) | **4.79** | **30 / 30** |
| everything except distance (removes 79% of depth) | 21.8 (14.0–28.0) | 0.98 | 14 / 29 |

- **Distance is the whole effect, and it is graded.** Dosing the half-spread alone from
  its normal 2 ticks out to 12 raises the median move steadily from 27 to 152 ticks,
  about 12 ticks per tick of distance, with no threshold; from 4 ticks out the move is
  bigger than its twin on every seed.
- **Depth is not the mechanism.** Arms that remove most of the shares near the price but
  keep the remaining quotes at the touch do nothing.
- **Tight limits weaken it.** Distance alone moves 152 ticks; with the limit cut added,
  62. The committed lever's plateau in the dose-response is this dampening.
- **Executed prices agree** on every arm, and traded volume in the window is about the
  same everywhere, so this is trading at new prices, not quotes moving in an empty book.

## 7. Mechanism, on the demo seed

Before the lever the makers *are* the book: they hold a median 69% of the shares resting
in it (asserted at ≥ 60% by `test_makers_are_the_book_before_the_lever`), even though they
are the passive side of only about 28% of traded volume, since noise traders trade a lot
against each other. After the lever each can hold only ten shares, so both hit their
hard limits within half a second (30.10 s and 30.40 s) and quote tiny and far from the
price. Top-5 depth falls from an average of 425 shares before the lever to 19, and the
spread peaks at 159 ticks.

§6 changes how to read that. The empty book is not by itself what moves the price; the
retreat of the quotes is. Each maker quotes a set number of ticks outside the current
best bid and ask, and with the wider setting the best price on a side is often its own
previous quote, so the quotes step away and incoming orders trade at the new, worse
prices. Most aggressive selling in the next five seconds is ordinary noise flow. The
momentum traders sell less, but they sell into the trend, and all three reach their
position caps within 3.5 s. Without them, the same seed moves 30.5 ticks.

## 8. Limitations

- **One scenario, rule-based agents.** Eleven agents with hand-written rules. The result
  is about this population; it is not a claim about real markets.
- **Fast refill.** The makers re-quote every 10–15 ms and quote both sides until a limit
  binds, so depth they withdraw comes back almost at once. That is why size cuts do
  nothing here. With slow refill, as in real markets under stress, depth would likely
  matter more.
- **Makers price from the book.** Quoting relative to the current best price, often their
  own quote, is what lets wide quotes walk away. A maker anchored to a slower fair-value
  estimate might behave differently. Untested.
- **Thirty seeds, one window.** Enough to see a 2× effect clearly (p = 0.005), not enough
  to estimate tails. Only the 5 s after the lever is measured.
- **Ticks, not prices.** Moves are in ticks of an abstract instrument; the stylized
  facts (§2) are the only link to real-market behaviour.
- **Momentum caps are soft.** The cap is checked before each order, so an agent can
  overshoot by one order (88 against a cap of 80 on the demo seed).

## 9. Reproduce

```
uv sync
uv run pytest                                   # fast suite, including the paired control
uv run pytest -m slow                           # 30-seed sweep and lever study (minutes)
uv run python -m marquee.analysis.seed_sweep --seeds 30 --out docs/seed-sweep.json
uv run python -m marquee.analysis.lever_study --out docs/lever-study.json
uv run python -m marquee.analysis.lever_plot docs/lever-study.json docs/lever-dose.svg
uv run marquee-demo                             # watch it live; the dotted line is the control
```

Raw numbers: `docs/seed-sweep.json` (with and without the lever),
`docs/seed-sweep-no-momentum.json` (the momentum ablation) and `docs/lever-study.json`
(the lever taken apart and dosed). Decisions: ADR-020, ADR-021 and ADR-022 in
`DECISIONS.md`.

## 10. Next

The natural Phase 2 question follows directly: replace one rule-based maker with a
learned one and ask whether it **softens or deepens** the lever's effect, measured with
the same paired, multi-seed design. §6 sharpens it: the interesting control a learned
maker has is *where* it quotes under stress, not how much. That is a proposed amendment
to the Phase 2 design (`RL_DESIGN.md`), pending the author's sign-off.
