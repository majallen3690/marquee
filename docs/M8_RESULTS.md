# M8: a learned market maker absorbs the lever

**Question (ADR-023, fixed with its reading in ADR-026 before any run).** When the market
makers' risk appetite collapses (the M5 lever), does a learned maker in one of the two
seats soften or deepen the price move?
**Setup.** `scenarios/m8-lever.yaml`: the M7 population with the M5 lever at 30 s. Maker 1
is always rule-based and always takes the lever. Maker 2's seat is taken over before the
lever by a rule-based successor that takes the lever (*rule, levered*), one that keeps its
parameters (*rule, holds*), or the learned maker (*learned*), plus no-lever twins.
30 fresh seeds, entry 12-24 s, so the lever lands at a different step each time; the
learned maker never saw a perturbation in training. Model: M7b (`models/m7b.zip`; its
gate failed on one ablation clause, `docs/M7B_RESULTS.md`), with the M7 model as a check.
Raw numbers: `docs/m8-results.json`, `docs/m8-results-m7.json`. Reproduce with
`uv run --group train python -m marquee.rl.m8 --model models/m7b.zip --out docs/m8-results.json`.

## Answer as pre-registered: SOFTENS

Primary comparison, *learned* against *rule, holds* (both successors free of the lever):

| | learned (M7b) | learned (M7, check) |
|---|---|---|
| seeds where the move is smaller | **29 of 30** (p < 10⁻⁷) | 30 of 30 (p < 10⁻⁸) |
| median ratio of move sizes | **0.15** (95% CI 0.10-0.21) | 0.12 (0.08-0.15) |
| the same on executed prices | 30 of 30, ratio 0.17 (0.09-0.23) | 30 of 30, ratio 0.12 |

| 30 seeds, M7b model | median 5 s move (ticks) | seat-2 quoted spread before → after | seat-2 two-sided after | seat-2 mean P&L |
|---|---|---|---|---|
| rule, no lever | 55.0 | 16.5 → 18.5 | 100% | −2,492 |
| rule, levered (the M5 lever) | **187.0** | 16.5 → 67.8 | 50% | +17,107 |
| rule, holds | 95.2 | 16.5 → 27.5 | 100% | +3,684 |
| learned, no lever | 12.5 | 5.0 → 5.0 | 99% | +3,835 |
| **learned** | **12.8** | **5.0 → 6.0** | **100%** | **+5,289** |

## Reading it

- **With the learned maker in the seat, the lever stops mattering.** Its runs move as
  little with maker 1 pulling back as without it (12.8 against 12.5 ticks; larger on 16 of
  30 seeds, p = 0.86). The rule-based market moves 4.0× its twin under the full lever.
- **How: it keeps quoting tight and on both sides.** When maker 1 steps back, the learned
  maker widens by one tick and stays two-sided. That fits the lever study (ADR-022):
  quoting distance is what moves the price. The rule-based successor that "holds" still
  widens from 16.5 to 27.5 ticks, because it prices off the book, which maker 1 just left.
- **It is paid to stay.** Its P&L is higher with the lever than without (+5,289 against
  +3,835), and its inventory after the window stays small (median 19 shares).

## What this does not show

- **The learned maker is a better liquidity provider all the time, not only in the
  crash.** Without any lever its market moves 12.5 ticks against 55.0 with the rule-based
  successor. Much of the "softening" is the gap between a tight, learned quoter and a
  weak rule-based one (it prices off its own quotes; ADR-022/023), not a crash-specific
  skill.
- **It is exempt from the lever by construction.** The lever models makers' risk appetite
  collapsing; the learned maker has no capital limit or risk desk to collapse. A real firm
  quoting through a crash carries risk this simulator does not charge it for.
- One simulated population, one lever, one seat, one trained model (with a second as a
  check). The answer is about this market, not markets.
- The M7b model failed its own gate on one ablation clause; the M7 model failed its gate on
  tail losses. Both give the same M8 answer.
