# PROGRESS.md

Read this + DECISIONS.md + ASSUMPTIONS.md and you can continue cold. Update before
ending any work stretch.

## Current milestone: M1 — COMPLETE (gate passed). Next: M2 (sim kernel + agent API).

## M1 gate results (2026-07-07)

- **Property tests: PASS.** `tests/test_engine_properties.py` — 200-example Hypothesis
  suite over arbitrary op sequences, parameterized over all three self-trade policies.
  Core oracle is a *shadow book* rebuilt purely from ExecutionReports/CancelResults and
  compared level-by-level against `snapshot()` after every operation. Covers:
  price-time priority (price monotone across fills, maker ids increasing within level),
  maker price rule, conservation identity, no crossed book, no negative quantities,
  cancel correctness (three-way status), IOC market orders, rejection paths.
  Plus 13 example-based semantics pins in `tests/test_engine_semantics.py`.
- **Determinism: PASS.** `tests/test_engine_determinism.py` — same 30k-message seeded
  workload in two subprocesses with different PYTHONHASHSEED → identical SHA-256.
- **Throughput: PASS.** `bench/lob_bench.py` (protocol per ADR-005): median
  **406,520 msgs/sec** over 5 runs of 1M mixed messages (55% limits / 25% cancels /
  20% markets incl. sweeps) — 4× the stated 100k target, ±1% run variance.
- **Static analysis: PASS.** ruff clean; `uvx semgrep scan --config auto` clean;
  `uvx bandit -r src` clean.
- **Review caveat (honest note):** the independent 3-agent adversarial review of
  `book.py` **errored out on session usage limits** (0 findings returned because the
  reviewers died, not because they found nothing). A careful inline trace of the
  assigned attack surfaces (stale-counter accounting across drop/recreate/rebuild,
  level counter drift on fill/cancel/STP paths, FIFO through compaction, dict-order
  determinism) found no defects, and the shadow-book suite is a strong oracle — but
  **re-run the independent review at the start of the next session** (script saved, see
  git history / workflow `m1-engine-review`) before building M2 on top.

## Engine summary (for cold resume)

`src/marquee/engine/book.py` — `MatchingEngine.submit/cancel/snapshot/best_bid/best_ask`.
Internals per ADR-005: liveness = orders-dict membership; lazy tombstones with per-level
compaction (dead > live and dead > 16); per-side lazy heaps with in_heap dedupe + rebuild
when stale > live levels. Semantics per ADR-009 (maker price, IOC markets, REJECTED
status, 3-way cancel status, self-trade policies ALLOW/CANCEL_RESTING/REJECT_TAKER with
`stp_cancelled` reporting). Kernel assigns ids; engine enforces strict increase.

## Exact next action (M2)

1. Re-run the independent engine review (see caveat above); fix anything confirmed.
2. Then M2, test-first: event-driven kernel per ADR-002/003/006/007 —
   - `tests/test_kernel_ordering.py` first: heap total order (time, priority, seq),
     latency application, deterministic delivery order.
   - `src/marquee/sim/kernel.py`: clock, event queue, agent registry (stable order),
     intent validation chokepoint (`type(x) is int` — ADR-003), id assignment,
     ack/fill delivery with latency, wakeup scheduling.
   - RNG: identity-keyed spawn (`SeedSequence(master, spawn_key=(domain, id))`) +
     property test that removing one agent leaves other streams bit-identical.
   - Recorder: JSONL writer with the exact ADR-006 byte contract + manifest.json.
   - M2 gate: scripted multi-agent scenario replays byte-identically (subprocess,
     different PYTHONHASHSEED); kernel event-ordering tests pass; full-loop throughput
     ≥ 30k events/sec.

## Blockers / user actions needed

- `gh auth login` has not been run — no GitHub remote yet. Local commits accumulate.
- OpenBB + Alpaca MCP servers must be connected before M4.
- Subagent session limit was hit this session (resets 11pm Asia/Calcutta) — affects
  workflow-based review passes only; solo work unaffected.

## Milestone map

| Milestone | Status |
|---|---|
| M0 scaffold + ADRs | done |
| M1 matching engine | done — gate passed (see caveat: re-run independent review) |
| M2 sim kernel + agent API | next |
| M3 rule-based agents | — |
| M4 calibration | — |
| M5 viz + flash crash (Phase 1 ends) | — |
| M6–M8 RL | — |
