# PROGRESS.md

Read this + DECISIONS.md + ASSUMPTIONS.md and you can continue cold. Update before
ending any work stretch.

## Current milestone: M6 — COMPLETE. ⛔ **STOPPED FOR USER SIGN-OFF. No M7 code until the user approves the anti-degeneracy analysis.**

## M6 results (2026-07-21) — RL design note, no RL code written

Per the user's amendment to the brief (recorded in memory: `m6-signoff-amendment`),
this milestone ends in a hard stop for review. Deliverable:
**[RL_DESIGN.md](RL_DESIGN.md)**, with binding decisions mirrored as **ADR-017** in
DECISIONS.md. Grounded in the literature via WebSearch (Perplexity/Firecrawl MCPs
still unconnected): Spooner et al. 2018 (asymmetric dampening), Gašperov &
Kostanjčar (the documented never-trade optimum), ABIDES-gym, self-play/PFSP survey.

**Governing idea:** reward penalties are negotiable — an optimizer finds the
cheapest way to satisfy them. So degeneracies are removed *by construction*
wherever possible, and reward shaping handles only the residue:

| Degeneracy | Removed how |
|---|---|
| No-trade equilibrium | No quote-withdrawal action exists (mandatory two-sided quoting, DMM-style obligation) |
| Spread blow-out | Offsets capped at 8 ticks + rule-based MMs stay in the population and take the flow |
| Inventory dumping | **No taker action in the action space at all**; forced liquidation is an environment rule, identical for the baseline |
| Self-trade / mid manipulation | `CANCEL_RESTING` policy; **own-order-excluded marking mid**; terminal liquidation walks the book |
| Self-play collapse | Rule-based population as permanent stationary anchor; adaptive opposition only via frozen checkpoints; PFSP a stretch goal |

Plus two project-specific degeneracies the literature does not cover: **scenario-
script memorization** (M8's crash fires at a fixed t=30s) and **seeded-order-flow
memorization** (rule-based agents are deterministic per identity-keyed seed) —
both would have silently inflated every Phase 2 number.

Reward: `r = S + (I − η·max(0,I)) − γ·(q/q_max)²` on an exact spread-capture /
inventory-P&L decomposition. Algorithm: PPO, 2×64 MLP. Gate restated measurably:
beat the rule-based MM on risk-adjusted P&L over ≥20 held-out seeds with zero of
detectors G1–G10 tripped and no >50% ablation collapse (A1–A6).

### On sign-off, M7 begins in this order
1. **Measure** training throughput before sizing any run (§13 of RL_DESIGN.md) —
   the estimate is ~16× real-time per env, but M7 verifies rather than trusts it.
2. Engine plumbing, with tests, engine invariants unchanged: queue-ahead quantity
   for an order id; own-order-excluded mid; snapshot excluding one agent.
3. PettingZoo-style env wrapping `SimKernel` (reuse `build_session`; stepped
   execution already exists via `run_until`).
4. **Detectors G1–G10 and ablations A1–A6 implemented *before* training**, so the
   first trained policy meets an already-tested harness.
5. PPO training script — checkpointed, resumable; Stage 0 → Stage 1 curriculum.

## Previous milestone: M5 — COMPLETE (gate passed live in a browser). Phase 1 done.

## M5 gate results (2026-07-08, verified in a real browser via Playwright)

`uv run marquee-demo` → FastAPI serves the built Next.js export + live feed at
:8420, opens the browser. Verified end to end:
- Market runs live: sim clock, ~128k events, ladder/chart/tape all streaming.
- **Committed crash visible** at t=30s behind the amber PERTURB rule.
- **Live UI perturbation works**: clicked COLLAPSE MAKER RISK at sim 00:25.909,
  got a second PERTURB rule and an immediate regime change (volatility burst,
  then a ~250-tick tear when the config perturbation compounded it). The ask
  side stripped to 2 levels vs 9 bids — liquidity retreat rendered as data.
- Screenshots reviewed against DESIGN.md: `docs/m5-pre-crash.png` (full 60s run)
  and `docs/m5-live-perturb.png` (live lever). Two layout bugs found in review
  and fixed (horizontal scrollbar from the transport row; dock overflow).
- DEMO.md written (3-minute script). DESIGN.md + ADR-015/016 recorded.

**Determinism bug found and fixed during this milestone** (see ADR-015): recorded
perturbation sequence must be *processing* order, not push order — otherwise a
live insertion that fires before a config perturbation inverts the `s` field on
re-simulation and breaks byte-identity. Found by reading the live demo's actual
event log, not by the test suite; now pinned by a coexistence test.

**Remaining M5 polish (not gate-blocking):** demo GIF for the README was not
captured (`docs/` has the two stills instead); the M5 tag awaits `gh auth login`.

## M5 core results (2026-07-08)

Perturbations wired end-to-end per ADR-010: `SimKernel.schedule_perturbation`
(strictly-later effective-time rule for live insertion, Perturbable protocol,
loud failures), MM lever params (limits/size/spread), `prt` events recorded with
full heap keys, scenario-config `perturbations:` section. Committed
`scenarios/m5-flash-crash.yaml` (seed 777002): calm anchored market (worst 5s
range 28 ticks) → at t=30s maker risk appetite collapses → **107.5-tick crash in
5 seconds, 3.84× amplification**, persistent regime change after. Gates in
`tests/test_m5_crash.py`: crash criteria (script-checked from the YAML),
perturbation log/schedule round-trip, replay mode (c) byte-identity across hash
seeds. Agent-model additions (ADR-014): momentum `max_position`, noise
`anchor_weight` — both default off; M3/M4 committed trajectories bit-unchanged
(legacy RNG draw path preserved, verified by re-running their gates). 64 tests.

**Standing context:** the user twice claimed Phase 1 / M5 complete on 2026-07-08; the
repo disproved it (see git history — M2, M3, M4 were all built and gated on
2026-07-08). The user's M6 amendment stands recorded (memory: m6-signoff-amendment):
after the M6 design note, STOP for sign-off before any M7 code.

## M4 gate results (2026-07-08)

`scenarios/m4-calibrated.yaml` — M3 population, 180 sim-seconds, seed 424242, ~7.5k
trades, 1,799 mid log-returns at 100ms. All ADR-013 thresholds pass via
`marquee.analysis.stylized_facts` (test: `tests/test_m4_gate.py`), and the long run
still passes the M3 market-quality bounds:

| Fact | Threshold | Measured |
|---|---|---|
| Fat tails (excess kurtosis) | ≥ 2.0 | **25.1** |
| Raw-return ACF lag 1 / lags 3+ | ≤ 0.30 / ≤ 0.15 | **−0.098 / ≤ 0.054** |
| Squared-return ACF lag 1 / positive lags | ≥ 0.10 / ≥ 6 of 10 | **0.27 / 10 of 10** |
| Trade-sign ACF lag 1 | ≥ 0.05 | **0.51** |

Honest deviations (magnitudes vs real markets) are disclosed in ADR-013 and feed
LIMITATIONS.md at M8: trade-sign memory too strong (momentum herding, no order
splitting), spread too tight (13-agent competition), lag-3+ ACF bound looser than
real-market values (small-population statistics). OpenBB/Alpaca cross-check of
thresholds queued (ASSUMPTIONS #9) — literature-defended meanwhile (Cont 2001, Roll
1984, Bouchaud / Lillo-Farmer).

## M3 gate results (2026-07-08)

`scenarios/m3-mixed.yaml` (2 inventory MMs / 3 momentum / 8 noise, 30 sim-sec, seed
31337): 99.97% two-sided, median spread 1 tick, p95 1, max 14, L1 depth ~155/side,
43 trades/sim-sec — verified by `marquee.analysis.run_stats` bounds committed in the
scenario (test: `tests/test_m3_gate.py`). ADR-012 records the agent designs; the MM
hard-limit regime is the M5 flash-crash lever.

## Architecture (cold-resume summary)

- `engine/` — M1 matching engine (406k msgs/s, shadow-book property suite).
- `sim/` — M2 kernel (byte-identical replay, 35k events/s full loop), recorder with
  exact byte contract + fmt_* fast path, scenario runner + manifest, replay mode (b).
- `agents/` — M3: InventoryMarketMaker (skew/widen/limits/unwind), MomentumTrader,
  NoiseTrader, + RandomPoster (M2 fixture). ExecutionReport echoes side/price/qty.
- `analysis/` — run_stats (market quality vs bounds), stylized_facts (ADR-013 gate).
  Both replay the recorded order stream; CLI + library. 55 tests green; ruff clean.

## Exact next action (M6 — RL design note, then STOP)

**Phase 1 is complete.** M6 is a *writing* milestone: no RL code, no env, no
training scripts. Write into DECISIONS.md (ADR-017):
1. Observation space per agent class (what the RL market maker sees: own
   inventory/limits, L1+depth, recent volatility, time — all from the existing
   pull-based `ctx.book()` contract, no new engine surface).
2. Action space (quote offsets + sizes as discrete tick offsets, or skip/pull).
3. The market-maker problem framed precisely (objective, horizon, episode
   boundary, what "good" means).
4. **Reward design with explicit anti-degeneracy analysis** — enumerate and give
   a concrete mitigation each for: no-trade equilibrium, spread blow-out,
   inventory dumping, reward hacking via self-trades (note: `SelfTradePolicy`
   already exists as a config enum precisely for this — ADR-009 rule 5) or other
   simulator exploits, and collapse under self-play non-stationarity.
5. Algorithm choice (PPO baseline unless argued otherwise) and curriculum
   (train against the rule-based population first, then mixed).
6. Evaluation metrics that distinguish "learned to trade" from "exploited the
   simulator" — including the degeneracy detectors the M7 gate needs.

Then **STOP and present it to the user for sign-off** before any M7 code. This
is a standing user amendment (2026-07-08), recorded in memory
(`m6-signoff-amendment`) and non-negotiable.

## Blockers / user actions needed

- `gh auth login` still not done as of the M4 commit — no remote. Once done: create
  public repo, push all commits, tag M5 when it lands.
- OpenBB + Alpaca MCPs still unconnected — ADR-013 cross-check queued on them.
- Independent engine review still pending (two attempts died on subagent limits).

## Milestone map

| Milestone | Status |
|---|---|
| M0 scaffold + ADRs | done |
| M1 matching engine | done (independent review re-run pending) |
| M2 sim kernel + agent API | done |
| M3 rule-based agents | done |
| M4 calibration (stylized facts) | done |
| M5 viz + flash crash (**Phase 1 complete**) | done — gate passed live |
| M6 RL design note (**STOP for user sign-off**) | next |
| M7 RL env + training | — |
| M8 integration | — |
