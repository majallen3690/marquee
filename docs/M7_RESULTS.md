# M7 gate, first run: not passed

**Model:** `models/m7-stage1.zip` (PPO 2×64, Stage 0 for 300k steps, then Stage 1; the
checkpoint at 1.2M Stage-1 steps, chosen by the 20 VALIDATION episodes).
**Gate:** ADR-023, set before training. On 40 held-out episodes in
`scenarios/m7-makers.yaml`, beat the rule-based maker *and* the best fixed quoting rule on
risk-adjusted P&L (mean ÷ std), with no detector tripped and no ablation collapse.
**Raw numbers:** `docs/m7-results.json`; reproduce with
`uv run --group train python -m marquee.rl.report --model models/m7-stage1.zip`.

## Verdict as pre-registered: FAILED

| Requirement | Result |
|---|---|
| beats the rule-based maker | **yes**: 1.95 against −0.66 |
| beats the best fixed rule | **yes**: 1.95 against −0.04 |
| detectors G1–G10 clean | **no**: G2 two-sided steps 96.4%, threshold 99% |
| no ablation collapse | **no**: A3 (0.43× of main P&L) and A4 +1 momentum trader (0.47×) |

## Held-out performance (40 episodes, ticks per 30 s episode)

| controller | mean P&L | std | risk-adjusted | spread capture | inventory P&L | shares made |
|---|---|---|---|---|---|---|
| **learned** | **+3,757** | 1,930 | **1.95** | 5,572 | −1,815 | 2,851 |
| rule-based maker | −5,214 | 7,936 | −0.66 | 5,886 | −11,100 | 751 |
| best fixed rule (join both sides, half size) | −589 | 16,086 | −0.04 | 4,757 | −5,346 | 2,910 |
| do-nothing (widest, smallest) | −378 | 5,513 | −0.07 | 2,293 | −2,671 | 227 |
| random | −2,056 | 16,608 | −0.12 | 6,198 | −8,254 | 1,997 |

The best fixed rule scored 0.65 on the training episodes it was chosen on, and −0.04
held out. The learned maker scored 1.07× its training-seed mean held out (G10), and 0.90×
on a second held-out set (A2). It earns from the spread: spread capture is positive, and
inventory P&L is a cost, not the source of profit (G6 −0.24).

## Detectors

| | value | threshold | |
|---|---|---|---|
| G1 fill rate vs rule-based | 771 fills/episode | ≥ 40 | pass |
| **G2 two-sided steps** | **96.4%** | ≥ 99% | **fail** |
| G3 median quoted spread | 4 ticks | ≤ 33.5 | pass |
| G4 maker share of own volume | 99.99% | ≥ 80% | pass |
| G5 self-trade volume | 0 | 0 | pass |
| G6 directional P&L share | −0.24 | ≤ 0.40 | pass |
| G7 inventory half-life | 17.5 steps (1.75 s) | ≤ 100 | pass |
| G8 forgetting vs Stage-1 population | — | — | applies from Stage 2 |
| G9 held-out perturbation times | — | — | applies to M8 (no perturbation here) |
| G10 held-out vs training seeds | 1.07× | ≥ 0.75× | pass |

## Ablations (mean P&L relative to the main held-out run; collapse < 0.5×)

| | learned | vs main | |
|---|---|---|---|
| A1 latency ×0.5 | 4,270 | 1.14 | |
| A1 latency ×1.5 | 3,824 | 1.02 | |
| A2 second held-out set | 3,378 | 0.90 | |
| **A3 self-trade policy REJECT_TAKER** | 1,628 | **0.43** | **collapse** |
| A4 one fewer momentum trader | 4,022 | 1.07 | |
| **A4 one more momentum trader** | 1,761 | **0.47** | **collapse** |
| A5 mark at last trade | 3,532 | 0.94 | |
| A6 base quote size halved | 3,976 | 1.06 | |

## What the failures are, on inspection

These diagnostics were run after the verdict. They do not change it.

**G2 measures resting quotes at the end of each step, not quoting.** Over 10 held-out
episodes the policy *submitted* both a bid and an ask on 100% of steps and was never at
its inventory limit. The 3.8% "one-sided" steps are steps where one side was completely
filled during the 100 ms step. RL_DESIGN §7 D1 defines G2 as "two-sided quoting on ≥ 99%
of steps", to catch quote withdrawal, which the action space makes impossible. The
implementation (`marquee.rl.evaluate.detectors`, written before training) checks
something stricter than that.

**A3 and A4 change the market for every controller, not only the policy.**

| same 40 held-out episodes | learned | rule-based | best fixed | do-nothing |
|---|---|---|---|---|
| main | +3,757 (RA 1.95) | −5,214 (−0.66) | −589 (−0.04) | −378 (−0.07) |
| A3 REJECT_TAKER | +1,628 (RA 2.07) | −449 (−0.23) | +1,212 (0.99) | +64 (0.07) |
| A4 +1 momentum trader | +1,761 (RA 0.32) | −18,802 (−0.89) | −9,089 (−0.29) | −1,833 (−0.21) |

With an extra trend-follower every maker loses more (the rule-based maker 3.6× more); the
learned maker is the only one that stays profitable. Under REJECT_TAKER its risk-adjusted
P&L rises. RL_DESIGN §8.3 reads a collapse as "the policy was leaning on that artifact";
when the ablation moves the whole market, an absolute 50% threshold cannot tell that
apart from a harder market.

## What it would take to pass, honestly

Changing the criteria after seeing these results and re-scoring the same episodes would
be grading on our own curve. A proposed amendment (ADR-024, **awaiting the author's
decision**):

1. **G2 counts quotes submitted per step,** as §7 D1 defines it. The end-of-step resting
   measure stays in the report as a secondary number.
2. **An ablation collapses if the policy loses its lead,** that is, it no longer beats
   both baselines on risk-adjusted P&L *under the same ablation*, or its own P&L drops
   below half while the baselines' do not. The absolute 50% figure stays reported.
3. **Re-score on a fresh held-out set** (HELD_OUT_3, 40 new episodes, generated and
   committed before anything is run on it), so the amended gate is not fitted to the
   episodes above.

If the author rejects the amendment, M7's result stands as written here: a learned maker
that clearly out-earns both baselines and generalizes across seeds, latency and quote
size, but fails the pre-registered gate on one measurement and two market-shifting
ablations.

## Training notes

Stage 1 validation risk-adjusted P&L rose from −1.47 (200k) to 3.0 (1.2M), then became
unstable after 2M steps (0.48 at 2.4M, std ×4). The run crashed at ~2.6M steps on memory:
sixteen environment processes each loaded torch they never use. Fixed (torch is imported
only in the trainer's main process; validation runs in-process). A lower learning rate
would likely reduce the late instability; not yet tried.
