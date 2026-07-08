# PROGRESS.md

Read this + DECISIONS.md + ASSUMPTIONS.md and you can continue cold. Update before
ending any work stretch.

## Current milestone: M2 — COMPLETE (gate passed). Next: M3 (rule-based agents).

**Reality check recorded 2026-07-08:** the user twice stated "Phase 1 is complete —
M5's gate passed" and asked for Phase 2 (M6). The repo shows otherwise: only M0/M1/M2
exist. Verified: git log has M0+M1 commits only (M2 committed this stretch), no
agents/analysis/viz code, no remote, nothing in the old OneDrive folder. Proceeded per
the brief's gating rule with M2. **The user's M6 amendment is recorded** (memory:
m6-signoff-amendment): when M6 legitimately happens, STOP after the design note for
user sign-off before any M7 code.

## M2 gate results (2026-07-08)

- **Byte-identical replay: PASS.** `tests/test_scenario_replay.py` — the committed
  `scenarios/m2-scripted.yaml` (4 agents, 5 sim-seconds, latency jitter on) run in two
  subprocesses with different PYTHONHASHSEED → identical SHA-256 for events.jsonl and
  trades.jsonl; non-vacuous (both files non-empty).
- **Order-stream replay (ADR-006 mode b): PASS.** Order stream extracted from
  events.jsonl through a fresh engine reproduces trades.jsonl byte-for-byte.
- **Kernel ordering tests: PASS.** Same-timestamp events dispatch by priority class
  (arrival < delivery < wake) then insertion seq; latency round-trip timing exact;
  maker/taker fill routing; cancel ownership enforcement; int chokepoint rejects
  numpy/float/bool intent fields.
- **RNG stream tests: PASS.** Identity-keyed spawning pinned: removing an agent leaves
  other agents' streams bit-identical (ADR-006 property).
- **Recorder byte contract: PASS.** LF-only UTF-8; fixed-schema fmt_* lines pinned
  byte-identical to the reference encoder (+ Hypothesis equivalence property for
  canonical_line); non-int numerics hard-error.
- **Full-loop throughput: PASS.** `bench/sim_bench.py`: median **34,903 events/sec ON
  BATTERY** (first run boosted: 61k) vs 30k target. Bench warns on battery; AC numbers
  will be comfortably higher. Optimization history in ADR-011 (fixed-schema
  serialization, O(1) L1 snapshot fast path, buffered jitter/wake draws).
- **Static analysis: PASS.** ruff clean, semgrep clean, bandit clean (git-subprocess
  Lows reviewed + nosec-annotated).
- 43 tests total.

## Standing caveat

The independent multi-agent adversarial review of `engine/book.py` has now failed
TWICE on subagent session limits (latest reset: 4:30am Asia/Calcutta). Inline invariant
trace + the shadow-book property suite stand in; re-run the workflow
(`m1-engine-review` script in session workflow dir) when limits allow, ideally before
M3 builds agent behavior on top.

## Architecture now standing (cold-resume summary)

- `engine/` — MatchingEngine (M1): price-time priority, ADR-009 semantics, 406k msgs/s.
- `sim/kernel.py` — SimKernel (M2): heap (t, priority, seq); wake/ack/fill/cancel-ack
  lifecycle; identity-keyed RNG (kernel=0, agent=1, wake=2); latency model w/ jitter;
  int chokepoint; cancel ownership; order-id assignment.
- `sim/recorder.py` — canonical JSONL byte contract + fmt_* fast path; `sim/replay.py`
  — replay mode (b); `sim/scenario.py` — YAML configs, manifest (seed/config-hash/git
  provenance/versions).
- `agents/scripted.py` — RandomPoster (M2 test fixture, not an M3 agent).
- `scenarios/m2-scripted.yaml` — committed gate scenario.

## Exact next action (M3 — rule-based agent population)

Test-first, per the brief:
1. Agents: inventory-aware market maker (quoting under inventory risk — skew quotes by
   inventory, widen on volatility, pull quotes at inventory limits), momentum traders
   (trend-follow on recent mid returns), noise/liquidity traders (upgrade RandomPoster
   semantics: random marketable + resting flow). All parameterized via scenario YAML.
2. `analysis/run_stats.py`: automated run-analysis script — spread time series, depth,
   trade frequency, two-sidedness; configured sane bounds → pass/fail verdict.
3. M3 gate: a committed mixed-population scenario produces a continuously two-sided
   market over a long run — bounds verified by the script, not eyeballed.
4. Agent-level unit tests (quoting logic, inventory skew sign, momentum signal sign)
   + kernel integration smoke.

## Blockers / user actions needed

- `gh auth login` still not done (checked this stretch) — no remote, local commits
  only. Once done: create public repo `marquee`, push, then tag releases at M5/M8.
- OpenBB + Alpaca MCP servers still not connected — required before M4 calibration.
- Subagent limits block workflow reviews (see standing caveat).

## Milestone map

| Milestone | Status |
|---|---|
| M0 scaffold + ADRs | done |
| M1 matching engine | done (gate passed; independent review re-run still pending) |
| M2 sim kernel + agent API | done — gate passed |
| M3 rule-based agents | next |
| M4 calibration | — |
| M5 viz + flash crash (Phase 1 ends) | — |
| M6 RL design note (**STOP for user sign-off — recorded amendment**) | — |
| M7 RL env + training | — |
| M8 integration | — |
