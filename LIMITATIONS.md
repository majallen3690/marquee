# Limitations

What this project does not show, in one place. Each result's own write-up has the
details; this file is the short version for anyone deciding how much to trust it.

## The market is a simulation

- **One population of hand-written agents.** Two market makers, three trend-followers and
  six noise traders. Every result is about this population. None of it is a claim about
  real markets.
- **The only link to real markets is four stylized facts** (fat tails, volatility
  clustering, no linear predictability, long-memory order flow; `tests/test_m4_gate.py`).
  Matching those does not make the simulator a model of any real market.
- **Ticks, not prices.** Moves are measured in ticks of an abstract instrument.
- **Fast refill.** Makers re-quote every 10–15 ms, so depth they withdraw comes back
  almost at once. That is likely why cutting quote size does nothing here. In real markets
  under stress, refill is slower and depth would likely matter more.
- **Makers price from the book.** The rule-based makers quote relative to the current best
  price, often their own quote. That is what lets wide quotes walk away. A maker anchored
  to a slower fair-value estimate might behave differently. Untested.

## The lever results (Phase 1)

- **The demo seed was chosen.** Seed 777002 has the deepest fall of the 30 seeds and was
  picked for the demo. Across seeds the lever roughly doubles the move, and the direction
  is a coin flip (down on 16 of 30). The README and the note say so.
- **The committed crash test alone does not prove causation.** The same seed with no
  lever also passes the test's ratio. The paired 30-seed sweep is what carries the claim.
- **Thirty seeds, one 5-second window.** Enough to see a 2× effect clearly (p = 0.005).
  Not enough to estimate tails.

## The learned market maker (Phase 2)

- **It did not pass its own quality gate.** The gate was written before training
  (ADR-023). The first model tied the best fixed quoting rule and had one held-out
  episode that lost 59,753. A retrained model fixed the tail losses and beat both
  baselines, but tripped one ablation clause. Both are reported as failures
  (`docs/M7_RESULTS.md`, `docs/M7B_RESULTS.md`).
- **The gate was amended once, before the run it governed.** After the first run failed,
  the author accepted an amendment to two checks (ADR-024). It was committed before any
  episode on a fresh held-out set was played, and that run failed too. Read ADR-024 and
  judge for yourself whether the amendment was fair.
- **One gate clause misreads a quieter market.** The retrained model failed because its
  P&L halved under one ablation while the baselines improved. Every controller's volume
  halves there, and the model's risk-adjusted lead is unchanged. This is noted, not used:
  the verdict stands as pre-registered.

## The M8 answer: a learned maker softens the lever

- **Much of the effect is a better quoter, not a crash skill.** With no lever at all, the
  market with the learned maker moves 12.5 ticks against 55.0 with the rule-based
  successor. The learned maker quotes tighter all the time.
- **It is exempt from the lever by construction.** The lever models makers' risk appetite
  collapsing. The learned maker has no capital limit or risk desk to collapse, and the
  simulator does not charge it for the risk it carries through the crash.
- **One population, one lever, one seat, two models.** Both models give the same answer.
  That is two models from one training setup, not independent evidence.

## How it was built

- **Implemented with an AI coding agent.** The author specified the project, set the
  gates and made the calls on every result. The code was written with Claude, and the
  commits say so.
- **Pre-registration rests on commit order.** The gates, episode sets and M8 reading were
  committed before the runs they govern (see the ADRs in `DECISIONS.md` and the commit
  history). Nothing external timestamps them.
- **Single author, no outside review.** Nothing here has been peer reviewed.

**This is a research and education tool. It is not a trading product, and nothing here is
financial advice.**
