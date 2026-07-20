# PROGRESS.md

Read this + DECISIONS.md + ASSUMPTIONS.md and you can continue cold. Update before
ending any work stretch.

## Current milestone: M5 core (crash mechanics) — COMPLETE. Next: M5 UI (DESIGN.md → bridge → viz).

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

## Exact next action (M5 UI — the crash mechanics beneath it are done)

Order of work (design bar rules in the brief are binding):
1. **DESIGN.md first** — type scale, spacing, color tokens, motion rules; dense
   pro-terminal direction. Load a frontend-design skill if available. Record as ADR.
2. **Bridge** (`server/`): FastAPI; kernel loop in a thread with a pacing layer
   (ADR-002: pacing outside the kernel); WebSocket fanning out sampled L1
   depth (snapshot cadence ~50ms), trades, stats; REST: pause/resume/perturb —
   perturb calls `kernel.schedule_perturbation` (live-insertion path already
   enforces the ADR-010 effective-time rule); add the live-insertion replay (c)
   test (extract schedule from log → re-sim → byte-identical).
3. **Viz** (`viz/`): Next.js + Tailwind; primitives FIRST (Panel, NumberCell, Ladder
   row, Tape row, Sparkline) then compose screens; order-book depth ladder + price
   chart + trade tape + agent-population controls. No emoji, no purple gradients,
   no template-shadcn look.
4. **Gate:** one command runs sim+bridge+viz; watch the committed crash live;
   perturb MM params from the UI and see the regime change; Playwright screenshot
   pass reviewed against DESIGN.md; demo GIF for README; DEMO.md (3-minute script).

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
| M5 viz + flash crash (Phase 1 ends) | next |
| M6 RL design note (**STOP for user sign-off**) | — |
| M7 RL env + training | — |
| M8 integration | — |
