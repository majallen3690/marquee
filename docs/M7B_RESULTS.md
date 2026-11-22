# M7b gate: not passed (one shot, final)

**What M7b changed (ADR-025, committed before training).** One reward change for the
tail risk that failed M7: the inventory penalty γ(q/q_max)² raised from 0.01 to a value
in {0.1, 0.3, 1.0}, three runs from the M7 Stage 0 model, 1.5M Stage-1 steps each,
learning rate 1.5e-4. The model is the checkpoint with the best risk-adjusted P&L on 60
validation episodes (VALIDATION + VALIDATION_2): **γ = 1.0 at 1.5M steps** (RA 2.26,
`docs/m7b-selection.json`, all 45 checkpoints listed). Gate: ADR-024's amended gate,
unchanged, once, on HELD_OUT_4 (40 episodes, seeds 7,000,001+).
Raw numbers: `docs/m7b-results.json`. Reproduce with
`uv run --group train python -m marquee.rl.report --model models/m7b.zip --gate amended --held-out 4 --out docs/m7b-results.json`.

## Verdict as pre-registered: FAILED

| Requirement | Result |
|---|---|
| beats the rule-based maker | **yes**: RA 1.86 against −0.52 (36 of 40 paired episodes, p < 10⁻⁶) |
| beats the best fixed rule | **yes**: RA 1.86 against −0.16 |
| detectors G1–G10 clean | **yes**: all pass, including G10 (1.18×) and G2 (100%) |
| no ablation collapse | **no**: A3, clause (b) of ADR-024's rule |

## Held-out performance (HELD_OUT_4, 40 episodes)

| controller | mean P&L | std | risk-adjusted | worst episode |
|---|---|---|---|---|
| **learned (M7b)** | **+4,083** | 2,200 | **1.86** | **−2,848** |
| rule-based maker | −3,530 | 6,808 | −0.52 | |
| best fixed rule (2, 2, 1) | −2,884 | 18,598 | −0.16 | −88,562 |
| do-nothing | −1,066 | 7,964 | −0.13 | |
| random | −609 | 11,463 | −0.05 | |

**The tail problem is fixed.** M7's worst held-out episode lost 59,753; M7b's worst loses
2,848, its largest final inventory is 67 shares against a 360 limit, and its inventory
half-life is 21 steps. It now beats the best fixed rule on risk-adjusted P&L by a wide
margin, because the fixed rule still has rare large losses (−88,562). Per episode it is
not consistently above the fixed rule's P&L (21 of 40, p = 0.87): it wins by being steady.

## Ablations (amended rule)

| | learned | rule-based | best fixed | |
|---|---|---|---|---|
| main | 4,083 (RA 1.86) | −3,530 (−0.52) | −2,884 (−0.16) | |
| A1 latency ×0.5 | 4,062 (1.96) | −4,497 | −1,438 | |
| A1 latency ×1.5 | 3,642 (1.13) | −2,084 | −29 | |
| A2 second held-out set | 3,891 (1.23) | −3,978 | −798 | |
| **A3 REJECT_TAKER** | **1,696 (1.85)** | 108 (0.08) | 943 (0.30) | **collapse (b)** |
| A4 one fewer momentum trader | 4,263 (2.28) | 317 | 2,769 | |
| A4 one more momentum trader | 2,178 (0.55) | −18,144 | −8,598 | |
| A5 mark at last trade | 4,197 (1.64) | −3,530 | −2,884 | |
| A6 base quote size halved | 3,426 (1.16) | −3,191 | −1,373 | |

The policy keeps its lead under every ablation, A3 included. A3 trips clause (b): the
learned maker's mean falls to 0.42× its main run while neither baseline loses half of its
own |mean| (both baselines *improve*, from losses toward zero).

### What A3 is, on inspection (after the verdict; it does not change it)

Under REJECT_TAKER the whole market trades about half as much: the learned maker's
volume falls from 2,648 to 1,255 shares, the best fixed rule's from 2,825 to 1,753, the
rule-based maker's from 769 to 173. The learned maker earns slightly less per share
(1.54 → 1.35 ticks) on half the volume, and its risk-adjusted P&L is unchanged (1.86 →
1.85). The baselines "improve" because they were losing money and now trade less.
Clause (b) compares means against baselines' own |mean|, which reads a quieter market as
"hurt only the policy" when the baselines are loss-making. That is a flaw in the rule I
wrote, found after seeing the result, so it is reported and not used: the gate fails.

## What M7 and M7b show together

The inventory penalty was the real problem: at γ = 1.0 the learned maker is profitable,
steady (worst loss 2,848 on 40 held-out episodes, and no collapse on the 20 of
HELD_OUT_2), beats both baselines on risk-adjusted P&L, passes every detector, and keeps
its lead under every market change tested. It fails its pre-registered gate on one
ablation clause, whose definition turned out to misfire when baselines lose money.
