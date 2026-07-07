# PROGRESS.md

Read this + DECISIONS.md + ASSUMPTIONS.md and you can continue cold. Update before
ending any work stretch.

## Current milestone: M0 — COMPLETE. Next: M1 (matching engine).

## Done (M0, 2026-07-07)

- Repo created at `C:\dev\marquee` (moved out of OneDrive; pointer README left behind —
  ASSUMPTIONS.md #8).
- Toolchain: Python 3.13 + uv, pytest + hypothesis + ruff. `uv sync` → `uv run pytest`
  green (8 tests), `uv run ruff check .` clean.
- ADR-001…ADR-010 written in DECISIONS.md, then hardened by an adversarial review pass
  (3 independent reviewer lenses: determinism/replay, performance realism, matching
  semantics; 22 findings, all accepted fixes folded into the ADRs). Highest-impact
  fixes: identity-keyed RNG spawn keys, exact JSONL byte contract for Windows,
  perturbation replay mode (c), on_order_ack in the Agent protocol, ExecutionReport
  conservation identity with REJECTED status, three-way CancelStatus, self-trade policy
  enum, tombstone/heap compaction rules, benchmark protocol.
- Typed boundary vocabulary in `src/marquee/engine/types.py` and
  `src/marquee/sim/protocols.py`. numpy pinned exact (determinism, ADR-006).
- `.gitattributes` protects `*.jsonl`/`*.json` byte-identity.

## Exact next action (M1)

Work test-first against ADR-009/ADR-005. Order of work:

1. `tests/test_engine_properties.py` — Hypothesis property suite BEFORE the engine:
   - price-time priority: fills consume best price first, FIFO within a level
   - maker price rule: every `Fill.price` equals the resting order's price
   - conservation: `qty == sum(fills) + resting_qty + cancelled_qty` for every submit
   - no crossed book after any operation sequence (best_bid < best_ask when both exist)
   - no negative quantities anywhere, ever
   - cancel correctness: CANCELLED removes exactly `removed_qty`; ALREADY_TERMINAL and
     UNKNOWN change nothing; cancelled order never fills afterwards
   - market IOC: empty opposite book → zero fills, full cancel
   - validation: qty <= 0 or LIMIT price < 1 → REJECTED, book unchanged
   - self-trade under ALLOW: executes, both agent ids on the Fill
2. `src/marquee/engine/book.py` — implement per ADR-005 (mutable `_Resting` internals,
   liveness = orders-dict membership, tombstone + heap compaction, cached L1).
3. `bench/lob_bench.py` — per the ADR-005 benchmark protocol. Gate: ≥100k msgs/sec
   median of 5, mixed workload with sweep-heavy segment.
4. Determinism check at engine level: same input event stream twice (separate
   subprocesses, different PYTHONHASHSEED) → byte-identical serialized fill stream.
5. Static analysis pass (`uvx ruff check`, try `uvx semgrep` — if semgrep fails on
   Windows, use `uvx bandit` and note in ASSUMPTIONS.md).

M1 gate (from the brief): all properties pass; determinism test passes; benchmark hits
the stated 100k msgs/sec target.

## Blockers / user actions needed

- `gh auth login` has not been run — no GitHub remote yet. Local commits accumulate
  meanwhile. Repo should be public when created (ASSUMPTIONS.md #3).
- OpenBB + Alpaca MCP servers must be connected before M4 (calibration reference data).

## Milestone map

| Milestone | Status |
|---|---|
| M0 scaffold + ADRs | done |
| M1 matching engine | next |
| M2 sim kernel + agent API | — |
| M3 rule-based agents | — |
| M4 calibration | — |
| M5 viz + flash crash (Phase 1 ends) | — |
| M6–M8 RL | — |
