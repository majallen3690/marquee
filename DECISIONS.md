# DECISIONS.md — Architecture Decision Records

Running log of load-bearing decisions. Each ADR: decision, rationale, rejected
alternatives. Newest at the bottom. Superseded ADRs are marked, never deleted.

These ADRs passed an adversarial review (three independent reviewer passes: determinism/
replay, performance realism, matching semantics) before being committed; the fixes from
that review are folded in below.

---

## ADR-001: Language stack — Python core, Next.js viz

**Decision.** Engine core, simulation kernel, agents, and analysis: Python 3.13, managed
with uv. Visualization: Next.js + TypeScript + Tailwind. Bridge: FastAPI serving a
WebSocket event stream plus a small REST control surface.

**Rationale.** (1) Deadline is ASAP and the Rust toolchain is not installed on the build
machine; Python + uv + Node are. (2) Phase 2 RL (PettingZoo-style env, PPO) is
Python-native, so the sim layer lands in Python regardless — a second engine language
would buy benchmark numbers at the cost of an FFI boundary and a second toolchain for a
solo dev. (3) The credibility core — property-tested correctness and byte-identical
determinism — is language-independent. (4) Owner is fluent in Next.js/Tailwind.
ABIDES (the reference architecture) is itself Python.

**Rejected.**
- Rust engine + PyO3: best raw throughput; adds rustup/maturin/MSVC-link complexity and
  slows time-to-demo. Escape hatch: the engine sits behind a typed interface (ADR-007)
  and can be ported later without touching agents or viz.
- TypeScript engine: one language with the frontend, but no credible RL path.
- JVM/C#: no advantage over Python here given the RL requirement.

## ADR-002: Time model — discrete-event, integer nanoseconds

**Decision.** Discrete-event simulation. Sim time is `int` nanoseconds from sim epoch 0.
The kernel owns a single event queue (binary heap). No wall-clock reads anywhere in the
sim path. Real-time playback for the viz is a pacing layer *outside* the kernel that maps
sim-time to wall-time; it never influences event order.

**Rationale.** Integer time eliminates float-comparison nondeterminism. Discrete-event
(vs. fixed time-step) matches the domain — markets are event-driven — and is the ABIDES
model. Nanosecond resolution leaves room for realistic latency modeling without ever
needing fractional ticks.

**Rejected.** Fixed time-step loop (wastes cycles when idle, quantizes latency); float
seconds (equality/ordering hazards); wall-clock hybrid (kills replay).

## ADR-003: Event ordering and tie-breaking — total deterministic order

**Decision.** Heap key is the tuple `(time_ns, priority_class, seq)`. `seq` is a
monotonically increasing insertion counter, so ordering is a *total* order and heap
behavior is fully deterministic. `priority_class` is a small int enum ordering
same-timestamp event kinds: engine acknowledgments < agent wakeups < perturbations
(see ADR-010 for why perturbations get their own class). Agent→exchange and
exchange→agent messages incur configurable latency; stochastic latency draws come from
seeded streams (ADR-006).

**Additional determinism rules (enforced in review at every gate):**
- No iteration over `set`s in the sim path; agent iteration uses stable ordered lists.
- All IDs (orders, trades, events) are monotonic per-run counters, never UUIDs.
- No `time.time()`, `datetime.now()`, `os.urandom`, or unseeded `random` in sim path.
- Dict iteration is acceptable (Python dicts are insertion-ordered) but must not depend
  on hash order of keys.
- Integer-domain enforcement is active, not aspirational: the kernel validates every
  agent intent with `type(x) is int` (rejects float, bool, and numpy scalars) before it
  reaches the engine, and the recorder hard-errors on any non-`int` numeric — never a
  coercing `default=` hook. Agents convert RNG draws to built-in `int` at the draw site.

**Rejected.** Tie-breaking by agent id (privileges low ids systematically at the same
timestamp — insertion order is fairer and still deterministic); relying on heapq's raw
behavior with equal keys (comparison falls through to payload objects — undefined
intent).

## ADR-004: Price and quantity representation — integers only in the engine

**Decision.** Prices are `int` ticks (tick size defined in scenario config, default
$0.01); quantities are `int` units. The engine and the event log contain no floats.
Floats are permitted only inside agent decision math and offline analysis; agents convert
to integer ticks at the intent boundary. Enforcement is runtime, at the kernel and
recorder chokepoints (see ADR-003), because Python type aliases check nothing by
themselves.

**Convention note.** `BookSnapshot.mid_x2` is twice the mid, kept integer. It exists for
comparison and logging only. Agent code must never compute `mid_x2 // 2` (floors on odd
sums → systematic half-tick downward bias replicated across every agent that copies the
idiom); quoting logic anchors on `best_bid`/`best_ask` directly. The analysis/viz layers
(where floats are allowed) get a single shared helper that halves it in exactly one
place.

**Rationale.** Exact equality and ordering, zero rounding drift, byte-identical logs.
This single rule prevents the largest class of replay-divergence bugs.

**Rejected.** `Decimal` (slower, still needs quantization discipline); floats with
epsilon comparisons (nondeterministic across code paths).

## ADR-005: LOB data structures, complexity, and throughput targets

**Decision (public structure).**
- `orders: dict[order_id -> resting order state]` holding **live orders only** — dict
  membership *is* liveness. O(1) lookup, O(1) cancel (delete the entry, decrement the
  level aggregate).
- Price levels: `dict[tick -> Level]`, each `Level` holding a FIFO `deque` of order ids
  plus aggregate resting quantity and live/dead counts.
- Cancels are lazy with respect to the deque: the bare id stays behind as a tombstone
  and is skipped during matching when its dict lookup misses.
- Best-price tracking: two heaps (max-heap of bid ticks via negation, min-heap of ask
  ticks) with lazy cleanup, **plus** incrementally maintained cached `best_bid`/
  `best_ask` ints updated on add/cancel/match so L1 queries never touch the heaps.

**Binding implementation notes for M1** (from the adversarial review — these prevent
known pathologies, they are not optional polish):
1. The frozen `Order` dataclass is the *boundary* type only. Inside the engine each
   resting order is a plain mutable `__slots__` object (`remaining_qty` decremented in
   place on partial fills). Never `dataclasses.replace()` on the hot path.
2. Tombstone compaction: when a level's `dead_count > live_count` and `dead_count > 16`,
   rebuild its deque keeping live ids. O(len) but amortized O(1) per cancel, and a pure
   function of level contents — replay-safe. Without this, a market maker re-quoting
   behind the touch accumulates unbounded tombstones on levels that never trade.
3. Heap dedupe: track ticks currently in each heap (per-side set used only for O(1)
   membership, never iterated); push a tick only when absent. Compaction guard: when
   stale heap entries outnumber live levels, rebuild the heap from the level dict
   (heapify is O(L), amortized free, deterministic).
4. `snapshot(depth)` is O(depth log L) and is never called by the engine itself; the
   kernel's per-event data contract is L1 / event deltas (ADR-007), not full snapshots.

**Per-operation targets.** Submit: O(log L) amortized (heap push only on level
creation). Match at best: amortized O(1) per fill. Cancel: O(1). Best bid/ask: O(1)
(cached).

**Throughput targets.**
- **Engine (M1 gate): ≥ 100,000 messages/sec** sustained on a mixed add/cancel/match
  workload — explicitly including a sweep-heavy segment (~20% of volume as multi-level
  market orders) — single-threaded CPython, consumer hardware. Justification of the
  order of magnitude: the live demo needs ~10^3–10^4 events/sec; a calibration run of
  ~10^6–10^7 events must finish in minutes. 100k/s gives 10–100× headroom over the demo.
  A well-written pure-Python book measures in the 10^5 range; the target is stated
  before the engine exists, per the brief.
- **Full sim loop (M2 gate): ≥ 30,000 events/sec** kernel + agents + recorder, so the
  calibration-time claim is gated directly rather than inferred from the engine-only
  number (recording and dispatch overhead is real: ~2 µs/event for naive `json.dumps`
  alone).

**Benchmark protocol (binding).** The benchmark is a standalone script
(`uv run python bench/lob_bench.py`), never run under pytest or coverage
(instrumentation cuts pure-Python throughput 3–10×). It asserts no active trace hooks
before timing, does a ≥10^5-message warm-up, times ≥10^6 messages with
`time.perf_counter_ns` around the whole batch, and reports the median of 5 runs. The
workload generator is committed with a fixed seed so numbers are comparable across
commits. The script warns when the Windows power plan is not High Performance.
If fill/report construction cost threatens the gate, the pre-authorized escape hatch is
switching `Fill`/`ExecutionReport`/`CancelResult` to non-frozen `slots` dataclasses
(≈4× faster construction; immutability there is convention, not a correctness
dependency — determinism comes from ADR-004/006).

**Rejected.** Sorted-containers dependency (no asymptotic win over lazy heaps at this
scale); doubly-linked list per level for O(1) mid-queue removal (more pointer
bookkeeping in Python than lazy deletion + compaction costs); arrays-of-structs / numpy
book (fights the object model, hurts readability — revisit only if the benchmark
misses).

## ADR-006: Seeding, RNG streams, and replay-log format

**Decision (streams).** One master seed per scenario config. Every stream is derived
from *identity*, not spawn position:
`SeedSequence(master_seed, spawn_key=(domain, id))` — domain 0 reserved for the kernel
(latency draws), domain 1 for agents keyed by `agent_id`. Adding, removing, or
reordering agents leaves every other agent's stream bit-identical (sequential
`.spawn()` would scramble all streams downstream of any population change, confounding
"same config minus one agent" experiments and the M5 perturbation comparisons). Each
agent gets its own `numpy.random.Generator(PCG64(child))`. Nobody shares a stream.
Property test at M2: streams of surviving agents are identical across configs that
differ by one agent.

**Decision (log format).** Two append-only JSONL files per run, written by the
recorder: `events.jsonl` (every kernel-processed event, in processing order, including
its full heap key `(time_ns, priority_class, seq)`) and `trades.jsonl` (fills only).
Exact serialization is part of the contract:
`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`, files
opened with `encoding="utf-8", newline="\n"`, one `\n` per record — otherwise Windows
text mode writes CRLF/cp1252 and byte-identity dies silently the first time a log is
compared cross-platform or against a git-checked-out golden. `.gitattributes` marks
`*.jsonl` / `*.json` as `-text`. (Fast serialization — f-string line building over
already-ordered int fields, buffered writes — is an M2 implementation concern and does
not change these bytes.)

**Decision (manifest & version discipline).** `manifest.json` records master seed, full
scenario config, config hash, git SHA, working-tree dirtiness plus a SHA-256 of
`git diff HEAD` when dirty (a solo dev's tree is dirty most of the time; a clean-SHA
field alone routinely lies), and exact package versions. The config hash is the SHA-256
of the raw scenario file bytes as committed — never of a re-serialization, whose bytes
depend on YAML library versions. numpy is pinned exact in both `pyproject.toml` and the
lockfile: NEP 19 guarantees bit-stream stability for the PCG64 BitGenerator but **not**
for `Generator` distribution methods, so a numpy bump is a determinism-breaking change
that requires regenerating golden logs. The replay tool loads the manifest first and
refuses to run (loud override flag exists) when git SHA, dirty-diff hash, config hash,
or pinned interpreter/numpy versions differ from the current environment.

**Determinism gates.**
(a) Same seed + config, run twice **as separate subprocesses with different explicit
`PYTHONHASHSEED` values** (e.g. 1 and 2) → SHA-256 of both JSONL files identical. Same-
process double-runs share one hash seed and would let latent str-hash-order dependence
pass the gate, surfacing later as an unreproducible heisenbug.
(b) Order-stream replay: feed `events.jsonl` order flow back through a fresh engine with
agents disabled → identical `trades.jsonl`.
(c) Perturbed re-simulation: see ADR-010 — this is the M5 gate.

**Rejected.** Global `random`/numpy singleton (any import-order change breaks replay);
UUID event ids (nondeterministic); binary log format (premature — JSONL is diffable and
debuggable; revisit only if logs outgrow files); sequential `SeedSequence.spawn()`
(position-dependent streams, see above).

## ADR-007: Interface boundaries — engine ↔ kernel ↔ agents ↔ recorder ↔ viz

**Decision.** Typed boundaries, enforced by module layout and reviewed at every gate:
- **Engine** (`marquee.engine`): a pure library. `submit(order) -> ExecutionReport`,
  `cancel(order_id) -> CancelResult`, `snapshot(depth) -> BookSnapshot`, plus O(1)
  cached L1 accessors. Knows nothing of time, agents, or I/O; timestamps are passed in.
  Deterministic function of its input sequence.
- **Kernel** (`marquee.sim`): owns the clock, event queue, and RNG spawning. Wakes
  agents, validates and routes agent intents to the engine, emits every processed event
  to the recorder.
- **Agents**: implement a Protocol with three callbacks, all returning intents:
  `on_wake(ctx)`, `on_order_ack(ctx, report)`, `on_fill(ctx, fill)`. The ack callback
  exists because the kernel assigns order ids — without it an agent can never construct
  a cancel for its own resting quote (found in review; would have blocked the first
  market maker at M3). Acks and fills are delivered under the same latency model as
  everything else. **Market data is pull-based:** agents call `ctx.book(depth)` during
  their callbacks. There is no per-event push of book snapshots to N agents — that costs
  O(N · depth) allocations per event and an ordering obligation, and no Phase-1 agent
  needs it. Agents see only the read-only context (time, book view, own RNG); they never
  touch the engine, the recorder, or each other.
- **Recorder**: consumes the typed event stream; writes JSONL. It logs *events*, never
  per-event book snapshots. In M5 the same stream fans out to the WebSocket bridge (one
  producer, two sinks); the bridge samples `snapshot(depth)` at a configured cadence for
  the depth-ladder display.
- **Viz**: consumes JSON over WebSocket; sends control commands (pause, parameter
  perturbation) back through the bridge. Perturbations become kernel events per ADR-010
  and are therefore replayable.

**Rationale.** The perturbation-as-event rule is what makes the M5 gate ("perturb a
parameter, see the regime change, reproduce from seed") satisfiable. Everything else is
standard layering so the engine stays unit-testable in isolation.

## ADR-008: Repo location, layout, and toolchain

**Decision.** Repo lives at `C:\dev\marquee` (outside OneDrive — sync interferes with
git, node_modules, and benchmark stability; a pointer README remains in the old folder).
Monorepo layout:

```
marquee/
  src/marquee/engine/     # LOB + matching (pure, no I/O)
  src/marquee/sim/        # kernel, agent API, recorder
  src/marquee/agents/     # rule-based agent implementations (M3)
  src/marquee/analysis/   # run analysis (M3), stylized facts (M4)
  bench/                  # standalone throughput benchmarks (never under pytest)
  tests/                  # pytest + hypothesis
  scenarios/              # committed scenario configs (YAML)
  viz/                    # Next.js app (M5)
  server/                 # FastAPI bridge (M5)
```

Python tooling: uv (env + deps), pytest + hypothesis (tests), ruff (lint + format).
Frontend tooling (M5): pnpm. Static analysis at gates: semgrep CLI if its Windows support
holds, otherwise ruff + bandit with the substitution noted in ASSUMPTIONS.md.

**Rejected.** Separate repos per layer (overhead for a solo dev); Poetry (uv already
installed and faster).

## ADR-009: Matching semantics — execution price, market orders, validation, self-trades

**Decision.** The rules the engine lives by, pinned before M1 so the property suite has
a spec to test against:

1. **Maker price rule.** Every fill executes at the *resting* (maker) order's price. A
   marketable limit walks levels best-first, filling at each level's own price, while
   `level_price <= taker_limit` (buy) / `>= taker_limit` (sell). Any remainder rests at
   the taker's own limit price. (Without this stated, a taker-price implementation
   systematically distorts the trade-price series and silently poisons all M4
   calibration.)
2. **Market orders are IOC.** Fill whatever is available at successive best levels;
   the remainder is *cancelled*, never rested. A market order into an empty opposite
   book cancels in full with zero fills — a defined outcome, not an error.
3. **Conservation identity.** For every submit:
   `order.qty == sum(fill.qty) + resting_qty + cancelled_qty`. This holds by
   construction in `ExecutionReport` (which carries all three terms plus a status) and
   is a Hypothesis property at M1. A REJECTED report has zero fills, zero resting, and
   `cancelled_qty == qty`, so the identity is universal.
4. **Validation.** The engine rejects `qty <= 0` (all orders) and `price < 1` tick
   (limit orders) with status REJECTED. There are deliberately **no** price bands,
   circuit breakers, or halts above the 1-tick floor: the flash-crash demo requires
   that the book *can* crash; the 1-tick floor only prevents nonphysical zero/negative
   prints. This is intent, not omission.
5. **Self-trade policy** is a per-scenario config enum: `ALLOW` (Phase 1 default),
   `CANCEL_RESTING`, `REJECT_TAKER`. ALLOW is simplest and deterministic, and `Fill`
   carries both agent ids so analysis can flag wash volume. The policy is a config
   field from day one because Phase 2 RL must be able to flip it without an engine
   interface change — self-trading is a documented reward-hacking vector (M6).
6. **Cancel outcomes** are a three-way enum, O(1) to compute with no extra state:
   `CANCELLED` (was live, now removed), `ALREADY_TERMINAL` (id was issued but the order
   already filled or cancelled — benign race under latency), `UNKNOWN` (id never
   issued — caller bug, fail loudly). Order ids are assigned by the *kernel* (ADR-007)
   as a dense monotonic counter; the engine validates strict increase on submit and
   raises on violation. UNKNOWN is then an id-range check and ALREADY_TERMINAL is "not
   live and id <= max seen". Agents disambiguate filled-vs-cancelled from their own
   ack/fill bookkeeping. When `CANCEL_RESTING` self-trade prevention removes a resting
   order mid-match, the taker's `ExecutionReport.stp_cancelled` carries the removed ids
   so the kernel can notify their owner.

**Rejected.** Remainder-rests market orders (turns them into limit-at-fill-price orders
nobody asked for); boolean cancel result (collapses benign races and caller bugs into
one bit — undebuggable in M3 multi-agent runs); price bands (would suppress the
project's headline phenomenon).

## ADR-010: Perturbations and the three replay modes

**Decision.** A live UI perturbation (e.g. tightening market-maker inventory limits
mid-run) is recorded and replayed as follows:
- The bridge hands the perturbation to the kernel, which schedules it as a kernel event
  with **effective time strictly greater than the sim time of the event being processed
  at arrival** (next-nanosecond boundary), in the dedicated PERTURBATION priority class
  (ADR-003).
- `events.jsonl` records the perturbation's full payload and its complete heap key
  `(time_ns, priority_class, seq)` — like every other event.
- **Replay mode (c), perturbed re-simulation:** master seed + config + the perturbation
  schedule extracted from the log, pre-scheduled into the queue before the run starts →
  must reproduce byte-identical `events.jsonl` / `trades.jsonl`. This is the M5 gate
  check.

**Why the effective-time rule matters:** the naive design ("enqueue when it arrives")
makes the perturbation's `seq` depend on wall-clock arrival relative to other
insertions; on re-simulation it would be inserted at a different point in the insertion
sequence, get a different `seq`, and — precisely in the event-dense flash-crash window —
order differently against same-timestamp events. Deriving its ordering from
`(strictly-later time, own priority class)` makes live insertion order irrelevant.

**Rejected.** Treating perturbations as out-of-band config mutation (unreplayable —
fails the M5 gate); replaying by injecting "at the same wall-clock offset" (wall clock
is banned from the sim path, ADR-002).

## ADR-011: Kernel event taxonomy, wake scheduling, and delivery contract (M2)

**Decision (taxonomy).** Priority classes, ordering same-timestamp events (ADR-003):
`INTENT_ARRIVAL(0) < DELIVERY(1) < WAKE(2) < PERTURBATION(3)`. Inbound intents process
before outbound deliveries at the same instant; wakes see a settled book; perturbations
order last and deterministically (ADR-010).

**Decision (wake scheduling).** The kernel Poisson-wakes each agent: exponential
inter-wake intervals with a per-agent configured mean, drawn from a dedicated
identity-keyed stream (domain 2, keyed by agent_id — separate from the agent's decision
stream so agent-side draw counts never shift wake times). Initial wakes are drawn the
same way — staggered starts, no thundering herd at t=0. Agents do not control the
clock; they react in callbacks and act on wakes.

**Decision (delivery contract).** Four callbacks: `on_wake`, `on_order_ack` (the
submitter's ExecutionReport, carrying its taker fills), `on_fill` (maker side of each
trade), `on_cancel_ack` (result of the agent's own CancelIntent, and STP removals of
its resting orders — the engine reports `StpCancel(order_id, agent_id, qty)` so the
kernel routes without an ownership map for fills). In a self-trade under ALLOW, one
agent receives both its taker ack and its maker fill; inventory bookkeeping nets to
zero with no special case.

**Decision (cancel ownership).** The kernel keeps an order→owner map and answers a
cancel of another agent's order with `UNKNOWN` — byte-identical to a bogus id, so
probing foreign order ids yields nothing. Closes a documented M6 RL exploit (cancelling
competitors' quotes) at the kernel, before any RL code exists.

**Decision (hot-path serialization).** The kernel writes pre-serialized lines through
`fmt_wake/fmt_ord/fmt_cxl/fmt_dlv/fmt_trade` — fixed-schema f-string builders with
keys pre-sorted and unrolled `type(x) is int` checks (bool/numpy raise). Byte-identical
to the reference `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=True)`
encoding, pinned by tests including a Hypothesis equivalence property for the generic
`canonical_line`. This is the fast path ADR-006 pre-authorized; profiling showed
generic dict serialization at ~36% of loop time.

**Decision (buffered draws).** Latency jitter and wake-interval draws are batch-drawn
(512/128) from their streams and consumed in order. Determinism holds — consumption is
a pure function of the seed; the buffered idiom is simply *the* idiom from M2 onward
(changing it later is a golden-log-regenerating change, same class as a numpy bump).

**Measured (M2 gate).** Full loop (kernel + 12 agents + JSONL recorder to disk):
median 34.9k events/sec on battery, 61k boosted — target 30k. Benchmarks now warn when
on battery (sustained clocks sag 30–50% vs AC).

**Rejected.** Agent-controlled wake requests (ABIDES-style setWakeup — more API for no
Phase-1 need; revisit for RL if policies need variable think-time); per-event push of
book snapshots (ADR-007 already settled pull-based); orjson dependency (fixed-schema
f-strings beat it without a dep); trusting agents about cancel targets (exploit
surface).

## ADR-012: Rule-based agent population (M3)

**Decision (population).** Three classes, all YAML-parameterized, all randomness from
each agent's identity-keyed stream, floats confined to decision math with `int` at the
intent boundary (ADR-004):

1. **InventoryMarketMaker** — cancel-and-replace quoting each wake. Quotes anchor on
   `best_bid`/`best_ask` directly (never a halved mid — ADR-004): bid at
   `best_bid + 1 − half − widen − skew`, ask at `best_ask − 1 + half + widen − skew`,
   clamped uncrossed and ≥ 1. `skew = round(inventory × skew_per_unit)` (doubled past
   the soft limit) shifts *both* quotes against inventory; `widen` is a realized-vol
   proxy (range of recent `mid_x2` × factor — the factor absorbs the /2 so no halving
   idiom exists to copy). Three regimes: symmetric under soft limit; shrunken
   risk-side size past it; at the hard limit the risk-increasing side is pulled and
   the excess unwound with a market order. **The hard limit is the M5 flash-crash
   lever.** Empty/one-sided book → wide two-sided quotes around the last reference or
   anchor, so the market can restart. Report echoes (side/price/qty added to
   ExecutionReport this milestone) make ack bookkeeping order-independent — under
   latency jitter, same-wake acks can arrive reordered and positional correlation
   would mislabel quote sides.
2. **MomentumTrader** — market-buys after ≥ threshold up-moves of the mid over a
   lookback, sells the mirror; per-wake activation probability + cooldown. The
   deliberate positive-feedback destabilizer.
3. **NoiseTrader** — per-wake mixture: cancel oldest own order / market order /
   resting limit near the touch, occasionally *inside* the spread (uninformed
   improvement is how spreads tighten without any agent knowing a "true" price).
   Exponential-ish sizes; bounded open-order set.

**Decision (no fundamental-value agent yet).** ABIDES anchors prices with a
mean-reverting fundamental + value traders. Deliberately omitted at M3: the gate is
market *quality* (two-sidedness, spread, depth, activity), which MM + noise provide
with all-relative quoting; price is then a random walk driven by flow imbalance.
Revisit at M4 **only if** stylized-facts calibration demands mean reversion — logged
in ASSUMPTIONS.md.

**Decision (gate bounds, committed in m3-mixed.yaml).** 30 sim-seconds, 13 agents
(2 MM / 3 momentum / 8 noise): two-sided ≥ 99% of 10ms samples; median spread ≤ 6
ticks, p95 ≤ 20; mean L1 depth ≥ 10 units/side; longest one-sided stretch ≤ 300ms
(covers cold start); trades/sim-sec in [10, 400]. Measured on the committed seed:
99.97% two-sided, median spread 1 tick, p95 1, L1 depth ~155/side, 43 trades/sec —
comfortably inside, and the tight spread is the *expected* outcome of competitive
quoting plus improving noise flow (liquid real-world names sit at 1 tick too).

**Rejected.** Avellaneda-Stoikov closed-form quoting (needs a vol estimate and a
terminal horizon that don't exist here; the discrete skew/widen/limit scheme exhibits
the same qualitative behavior and every parameter is a demo-explainable integer);
momentum via limit orders (dilutes the feedback loop that M5's crash needs); pure-
random noise without spread-improvement (spreads never tighten, book goes static).

## ADR-013: Stylized-facts calibration thresholds (M4)

**Decision.** The committed `m4-calibrated.yaml` (M3 population, 180 sim-seconds,
seed 424242; 100ms mid sampling → 1,799 log-returns) must pass all thresholds below,
computed by `marquee.analysis.stylized_facts` from the recorded run. Reference values
are the canonical empirical literature — Cont (2001) "Empirical properties of asset
returns: stylized facts and statistical issues"; Roll (1984) for tick-scale bid-ask
bounce; Bouchaud et al. / Lillo & Farmer for order-flow long memory. Cross-checking
against fresh OpenBB/Alpaca reference data is queued for when those MCP servers are
connected (ASSUMPTIONS.md #9) — thresholds below are set from literature plus honest
margins, not tuned to one lucky run.

| Fact | Threshold | Real-market reference | Measured (committed seed) |
|---|---|---|---|
| Fat tails | excess kurtosis ≥ 2.0 | ~2–50 intraday, falling under time aggregation (Cont) | **25.1** |
| No linear predictability | \|ACF₁\| ≤ 0.30; \|ACF₃₊\| ≤ 0.15 | ACF₁ < 0 at tick scale (bounce, Roll); insignificant beyond minutes (Cont) | **−0.098; ≤ 0.054** |
| Volatility clustering | ACF of r² at lag 1 ≥ 0.10; ≥ 6/10 lags positive | 0.1–0.4 at lag 1, slow (power-law) decay (Cont) | **0.27; 10/10 positive** |
| Order-flow clustering | trade-sign ACF₁ ≥ 0.05 | 0.1–0.3, long memory (Bouchaud; Lillo-Farmer) | **0.51** |
| Sample size | ≥ 1,500 returns | — | 1,799 |

**Honest deviations, stated up front.** (a) The lag-3+ raw-ACF bound (0.15) is looser
than real-market values (~0.05): with 13 agents and ~1,800 samples the standard error
alone is ~0.024 and small-population oscillation is real; measured values (≤ 0.054)
are far inside the bound anyway. (b) Trade-sign ACF₁ = 0.51 *exceeds* the real-market
0.1–0.3: our momentum traders herd and nobody order-splits, so flow memory is
stronger than an anonymized real book. Sign and slow decay — the fact itself — are
right; the magnitude is an artifact of population size and is recorded as a known
limitation (feeds LIMITATIONS.md at M8), not hidden by loosening the gate direction.
(c) The market stays too tight (median spread 1 tick, p95 1): competitive quoting in
a 13-agent world converges harder than real books. Also recorded.

**Decision (no fundamental agent).** The ADR-012 question — would calibration require
a mean-reverting fundamental? — is answered: no. All four facts emerge from
MM inventory dynamics + momentum feedback + noise flow alone. The fundamental/value
agent stays out of Phase 1.

**Rejected.** Tuning the population until magnitudes match real markets exactly
(overfitting a 13-agent sim to a thousands-of-participants market misrepresents both;
the claim defended is *emergence of the facts*, with magnitudes disclosed);
GARCH-fitting as the clustering test (heavier machinery, same conclusion as direct
ACF thresholds, harder to explain in a demo).

## ADR-014: Flash-crash scenario design (M5 core)

**Decision.** `m5-flash-crash.yaml` (seed 777002, 60 sim-seconds): a calm anchored
market for 30s, then one perturbation instant collapses both makers' risk appetite —
`soft_limit 150/180 → 5`, `hard_limit 300/360 → 10`, `quote_size 60/80 → 5`,
`half_spread 2/3 → 12/15`. Committed-seed result: pre-market worst 5-second range 28
ticks; post-perturbation move **107.5 ticks down within 5 seconds** (3.84× the worst
normal burst), then a persistent wide-and-jumpy regime. Gate is script-checked
(`crash_criteria` in the YAML, `tests/test_m5_crash.py`) plus replay mode (c)
byte-identity across subprocesses with different hash seeds.

**Model changes this required — three failure modes found by measurement, each fix a
piece of honest microstructure, not a scripted crash:**
1. *Noise-owned book:* in the M3/M4 population the makers carried only 4% of executed
   liquidity — pulling them removed nothing. Crash populations need makers to BE the
   book (noise demoted to small fast-turnover flow; maker share is what makes "makers
   pull back" mean something).
2. *Unwind-momentum ratchet:* with unbounded momentum, the maker's own hard-limit
   unwind fed the trend signal that re-pinned it — price ran thousands of ticks.
   Fixes: momentum traders got `max_position` (every real trend-follower is
   position-bounded), and noise got an optional value-anchored side bias
   (Lux-Marchesi-style stabilizer; weight per x2-tick, clamped ±0.25). Both default
   OFF and the anchor-off path preserves the exact legacy RNG draw sequence, so the
   committed M3/M4 runs and their recorded measurements are bit-unchanged.
3. *Self-healing ladder:* shrinking quote size alone produced no crash — makers
   re-quoting every 10–15ms relative to the touch refill the ladder faster than any
   momentum lookback registers a move. Liquidity must *retreat*, not just thin:
   the half_spread blow-out is what opens the vacuum that market orders fall through.

**Emergence claim, stated precisely.** The perturbation changes *risk parameters* of
one agent class at one instant; every subsequent order, cancellation, trade, and the
crash trajectory itself follow from agent interaction. Across neighboring seeds the
same lever produces regime changes of varying magnitude and direction (21–107 ticks,
up or down in the four-seed scan) — the committed seed was chosen for demo vividness,
which is disclosed, and reproducibility is from that seed.

**Rejected.** Scripting a sell program at T (the thing the project exists to not do);
igniting via maker inventory alone (inventory at an arbitrary T is near zero in a
calm anchored market — measured twice); making the base market fragile enough to
crash on its own (destroys the "healthy until the lever" narrative and failed the
amplification test).

## ADR-015: Live bridge — pacing, fan-out, and the perturbation seq trap (M5)

**Decision (architecture).** `marquee.server`: a `LiveSession` owning one kernel
stepped by wall-clock pacing, and a FastAPI app with one pacing task, N WebSocket
subscribers, and a small REST surface (`/api/meta`, `/api/perturb`, `/api/control`).
The kernel gained `start()` / `run_until(target_ns)` — peek-based stepping that never
discards events — and `build_session()` is shared by `run_scenario`, the bridge, and
replay tests. Pacing lives strictly outside the sim path (ADR-002); the guarantee is
tested, not asserted: stepping in 250ms increments produces byte-identical logs to a
single `run()`.

**Decision (transport).** Frames at 20 Hz carry L1 depth (12 levels/side), the last
60 trades wholesale (stateless — the client keys rows by trade id, so there is no
cursor protocol to desynchronize), maker inventory/limits, and the perturbation list.
Slow subscribers drop stale frames rather than queue them. `uvicorn` is pinned
*with* `websockets`: bare uvicorn has no WebSocket implementation and degrades to
"Unsupported upgrade request", which surfaces only as a permanently reconnecting UI.

**Decision (the seq trap — a determinism bug this milestone found and fixed).**
Perturbations must not touch the kernel's global insertion counter, and their
recorded sequence must be *processing* order, not push order. Two distinct failures:
1. *Global counter:* a live-inserted perturbation consumes a mid-run seq that
   re-simulation consumes pre-run, shifting the seq of every subsequent event.
   Fixed with a dedicated perturbation counter (cross-class heap comparisons never
   reach the third tuple element, so the counters cannot collide).
2. *Push vs processing order:* when a scenario carries its own perturbations AND the
   user inserts one live that fires earlier, push order (config first, live later)
   differs from re-simulation's (whole extracted schedule pushed in time order).
   Behavior is identical but the recorded `s` field inverts, breaking byte-identity.
   Fixed by recording a processing-order counter.

Failure 2 survived the first fix and a passing live-insertion test — that test used a
config with no perturbations of its own, so the two orders coincided. It was caught
by *reading the live demo's actual event log*, and is now pinned by a test where
config and live perturbations coexist with the live one firing first. Lesson worth
keeping: determinism tests must exercise the case where two independent orderings
disagree, or they only prove the easy half.

**Rejected.** Running the kernel in a thread with a queue to the event loop (the
executor hop is simpler and the lock is uncontended); server-side mid history
(client-side accumulation costs nothing and survives reconnects); incremental tape
diffs (a cursor protocol to get wrong, for 60 rows).

## ADR-016: Visual system — instrument, not dashboard (M5)

**Decision.** Full system in DESIGN.md; the load-bearing choices: one dark palette
(cold near-black, phosphor green bid / red ask, amber reserved exclusively for the
human's hand — controls and the perturbation marker), IBM Plex Mono at five sizes
with hierarchy from size/weight/case only, hairline 1px separations with zero border
radius and zero shadows anywhere, and a full-viewport non-scrolling grid.

Motion is deliberately near-absent: data never animates position, and the single
effect in the product is a 300ms linear color decay on changed figures. That flash
is the heartbeat of the interface; anything else moving would compete with it.

The ladder is the product and gets the design weight: center-out layout with the
mid as the largest figure on screen, depth bars as 18%-alpha semantic fill that
*are* the depth visualization (no separate depth chart), and a designed
`— NO BIDS —` state that the flash crash actually makes real.

**Enforcement.** Styling lives only in `components/primitives.tsx` and the token
block in `globals.css`; screens compose primitives. The canvas chart is the one
component that needs literal colors — it reads them from the CSS custom properties
rather than duplicating hex values, so tokens stay single-source.

**Rejected.** shadcn/ui (its defaults are the exact template look the brief bans, and
this UI needs seven bespoke primitives, not fifty generic ones); a charting library
(canvas is ~80 lines and the design demands specific gridline/annotation behavior);
Framer Motion (the design's motion budget is one CSS keyframe); light mode
(instruments have one face).

## ADR-017: RL design — degeneracies removed by construction, not by penalty (M6)

**Full analysis: [RL_DESIGN.md](RL_DESIGN.md).** It lives in its own file because it
is a reviewable design note, not a few-line decision record; the binding decisions
are recorded here.

**Governing principle.** Reward penalties are negotiable — the optimizer hunts for
the cheapest way to satisfy them. Wherever a degeneracy can be removed by
construction (action space, environment rules, accounting), it is removed there;
reward shaping handles only the residue. The action space and the P&L accounting
are therefore the load-bearing parts of this design, not the reward function.

**Scope.** One learning agent: a market maker replacing one rule-based
`InventoryMarketMaker`. Momentum and noise stay rule-based — a second learner
would make a negative result uninterpretable (was it the agent, or the moving
environment?).

**Action space (MultiDiscrete, 9×9×3, one quote update per step).** Bid/ask offsets
relative to the touch, plus size. **No taker action. No quote-withdrawal action.**
This makes no-trade, unbounded spread blow-out, inventory dumping, and message spam
*unreachable* rather than merely penalized. Mandatory two-sided quoting is a
designated-market-maker obligation (the regime NYSE DMMs and Nasdaq registered
market makers actually operate under), and the rule-based baseline plays under the
same hard-limit forced-liquidation rule, so the comparison stays fair.

**Observation (~33 dims).** Stationary and relative only. Excluded on purpose:
absolute price, wall-clock/sim time, other agents' private state, the perturbation
schedule. New engine plumbing required in M7: queue-ahead quantity for an order id.

**Accounting (the real exploit closures).** Mark to an **own-order-excluded mid**
(blocks manufacturing unrealized P&L by shifting the quoted mid);
`SelfTradePolicy = CANCEL_RESTING` for all RL scenarios (the enum has existed since
ADR-009 rule 5 for exactly this); **terminal inventory liquidated by walking the
book**, never marked at mid. Wealth change decomposes exactly into spread capture
`S` and inventory P&L `I` — the basis of both the reward and the
speculator-vs-market-maker test.

**Reward.** `r = S + (I − η·max(0, I)) − γ·(q/q_max)²` — asymmetrically dampened
P&L (Spooner et al. 2018: keep all downside of holding, damp the upside, so
directional bets are negative-expectation while incidental inventory is fine),
plus a normalized running inventory penalty. `η = 0.5` baseline; `γ` swept and
reported with the sweep. **The reward is a shaped training signal; the gate is
unshaped risk-adjusted P&L.**

**Two project-specific degeneracies** the generic literature does not cover, both
of which would have inflated every number in Phase 2: **scenario-script
memorization** (the M8 crash fires at a fixed t=30s — mitigated by randomized
episode offsets, randomized perturbation timing, held-out perturbation times) and
**seeded-order-flow memorization** (rule-based agents are deterministic given
identity-keyed streams, so a fixed training seed set lets the policy memorize
literal order flow — mitigated by per-episode seed randomization and a disjoint,
committed held-out seed set).

**Algorithm.** PPO, 2×64 MLP. On-policy stability under a shifting opponent
population, no replay buffer on a consumer machine, native MultiDiscrete, widely
understood hyperparameters. Rejected: DQN/Rainbow (replay memory, factored-action
awkwardness, off-policy staleness against a moving population), SAC (continuous-
first, no benefit on a discrete quote grid). Tile-coded SARSA is retained as a
cheap *baseline*, not the method.

**Curriculum.** Stage 0 no competing MM → Stage 1 full calibrated population
(**the gate scenario**) → Stage 2 frozen checkpoint as opponent → Stage 3 stretch
PFSP over a checkpoint pool. Rule-based agents present at every stage as a
stationary anchor; adaptive opposition only ever via frozen checkpoints.

**Gate (M7), measurable.** Beat the rule-based MM on risk-adjusted P&L (mean
episode P&L / std) over ≥20 held-out seeds, with zero of detectors G1–G10 tripped
and no >50% collapse on ablations A1–A6. The ablation battery is the general test
of "skill transfers, exploits do not" — including A5, changing the marking rule:
if P&L depends on how we mark, it was never real.

**Compute.** ~16× real-time per env (measured: 35k events/wall-sec; ~2,175
events/sim-sec in the M5 run) → 1M steps in roughly 20–60 min across 6 envs. M7
measures before trusting this arithmetic; all runs checkpoint and resume.

**Stated risks.** The one-tick spread may leave too thin an edge to learn from;
the baseline could be weak (bounded by the fixed-width quoting curve); detectors
catch known failure modes only; **a negative result is acceptable and will be
published as one** — Phase 1 was built to stand alone precisely so Phase 2 can
fail honestly.

## ADR-018: Instrument v3 — the departure board (supersedes ADR-016's look; pre-M7 UI pass)

**Decision.** Replace the v1 green-terminal look with the v3 "departure board" system in
DESIGN.md, and rebuild the Live screen on it: a stat strip with one headline for the
crash, a depth-map chart with the lever, a TradingView-style range box and numbered
engine events, a price-anchored order book with cumulative depth, a lever ticket, an
attributed tape, and an agents table. Split-flap tiles for the figures a room must read;
amber reserved for "a human changed a rule". Design canvas:
https://claude.ai/artifact/GYXCs4fpaYsD6xqQr1ybzu — every figure on it comes from a real
seeded run.

**Why.** v1 showed *that* the price fell but not *why*. The demo's narration (DEMO.md)
says the ladder thins, the spread blows out and momentum piles in; none of that was
data on screen. The council review of the v9 canvas (a trader, a beginner, a recruiter,
an executor) converged on: one headline number, causal markers on the chart, plain-English
subtitles, no dead controls, and a frozen visual identity.

**Rejected.** A separate depth chart (the depth *map* is the history; the book is the
instant). Green/red for status (those colors mean bid/ask). More visual rounds after
this one: the identity is frozen; remaining work is content. A "Collapse maker risk"
label (reads as if the risk collapsed): the button is "Cut maker risk". A scrubber that
cannot scrub: Live shows a read-only timeline; scrubbing arrives with Replay.

**Scope.** Live only. Agents, Replay, Lab, Evaluation, Learn and the narrow view are
designed (canvas) and specified (DESIGN.md) but not built; each needs backend work.

## ADR-019: Bridge frame v2 — agent ledger, run stats, and the gate-grid mid series

**Decision.** The bridge frame gains `agents` (per-agent inventory, cash, maker/taker fills,
volume, maker volume, taker-sell volume since the first lever), `stats` (trade count,
run VWAP, net taker flow), `mids` (the last 60 samples on the 100 ms grid) and a taker
agent id on every trade. `/api/meta` gains `scheduled` (the scenario's scripted lever).
The ledger is accumulated server-side from the trade stream, so a page that connects
mid-run still shows true totals.

**The mid series is the gate's.** `LiveSession._advance` stops at every 100 ms grid
instant to sample the mid (carrying the last mid through a one-sided book), exactly as
`sample_mid_series` does for the committed crash gate. `test_ui_mid_series_is_the_gate_series`
asserts the live series equals the gate's, element for element, so the headline the UI
computes (move after the lever, multiple of the worst normal 5 s) is the number the gate
asserts, at any playback speed. At the committed seed: 107.5 ticks, 3.84×.

**Invariants tested.** Inventory and cash each net to exactly zero across all agents
(trading is zero-sum); no taker-sell volume is attributed to "after the lever" before
the lever fires.

**Late joiners and Replay.** `GET /api/history` returns the whole gate-grid mid series, a
slim frame every 500 ms (book, ledger, stats, lever marks), the volume buckets, and the
tape cursor. A page that connects (or reconnects) mid-run backfills from it before
processing live frames, so a reload loses nothing and the headline survives. Replay is
the same data: with the run paused or finished, clicking the timeline renders the
snapshot at that time through the same components, read-only, labelled Replay; Esc
returns to live. The biggest taker-sell burst after the lever is tracked server-side
for the same reason. Snapshots cost about 1 MB per 60 sim-seconds.

**Known limit.** Replay resolution is 500 ms for the book and 100 ms for the mid. Exact
event-level replay (re-simulating from `events.jsonl`) is a separate, later piece.

## ADR-020: The lever amplifies; it does not reliably crash (seed sweep, claim reframe)

**Finding.** A 30-seed sweep (`marquee.analysis.seed_sweep`, results in
`docs/SEED_SWEEP.md`), each seed run with and without the scripted lever, using the
crash gate's exact metrics. With the lever the median 5 s move is 64.8 ticks against
27.0 without; the move is bigger than its own same-seed control on 23 of 30 seeds
(median paired ratio 2.11). The direction is not stable: the price falls on 16 seeds
and rises on 14. The committed seed 777002 is the deepest fall of the 30. Its own
no-lever control moves +58 ticks, 2.07× its normal range, so the gate's amplification
test alone would pass without any lever.

**Decision.**
1. The headline claim becomes "pulling maker liquidity roughly doubles the next
   5-second move; on the committed seed that is a 107.5-tick fall, against +58 with no
   lever". "Crash" applies to the committed seed only and the docs say the seed was
   chosen. README, DEMO.md and the UI label ("Move since lever") follow.
2. Two tests hold it: `test_m5_crash.py::test_the_lever_is_the_cause_on_the_committed_seed`
   (paired control, fast) and `test_seed_sweep.py` (30 seeds, `pytest -m slow`, asserts
   ≥ 20/30 bigger and a median paired ratio ≥ 1.5, and that direction is mixed).
3. The committed gate is kept as written (it is a regression test for the demo seed),
   with its weakness documented rather than hidden.

**Why.** An interviewer's first question about a single-seed result is "did you pick
the seed?". The answer is now yes, here is the distribution, and here is what holds.
The reframed claim is smaller and true, which is worth more than a larger one that
breaks on the second seed.

**Rejected.** Re-tuning the scenario until most seeds crash downward: that would be
fitting the story, not measuring the market.

## ADR-021: The no-lever line — the control run, drawn on the chart

**Decision.** The chart draws a dotted line from the lever on: the same scenario and
seed run with no perturbation at all (`marquee.analysis.counterfactual.control_mids`,
`build_session(include_config_perturbations=False)`). The strip's headline subtitle adds
the control's move over the same 5 s window ("no lever +58.0"). The live bridge computes
it once on first request (`/api/counterfactual`, about 1–3 s, its own lock so stepping
never waits); the recorded demo carries it in the recording.

**Why.** It is the comparison the claim rests on (ADR-020), made visible: on the
committed seed the price rises to 9984 without the lever and falls to the 9800s with it.
`test_counterfactual_is_the_same_run_until_the_lever` asserts the two runs are identical
on the grid up to 30 s, so the line is a true twin, not a simulation "like" this one.

**Scope.** For a lever pulled by hand at another time the control is still correct
("nobody touched anything"), since every run before a perturbation is identical. A
second lever pulled later compares against the untouched run, not against the first lever.

## ADR-022: The lever taken apart — quoting distance, not depth, carries the effect

**Finding.** `marquee.analysis.lever_study` runs the committed scenario on the sweep's 30
seeds with the lever's four parameters taken apart (each alone, and the lever minus
each) and dosed (all four, or the half-spread alone, moved a fraction s of the way to
the lever's values in log space), every run paired with its untouched twin. Results in
`docs/LEVER_STUDY.md`. Widening the quotes alone gives a median 5 s move of 152.2 ticks
against 27.0, bigger than the twin on 30 of 30 seeds; the move rises steadily with the
distance (about 12 ticks per tick). Cutting quote size alone removes 78% of top-5 depth
and leaves the move unchanged (ratio 1.03); cutting inventory limits alone does nothing
(0.98) and, combined with the wider quotes, halves their effect (152 → 62). Executed
prices agree on every arm.

**Decision.**
1. The headline claim gains its mechanism: the lever works through how far the makers
   quote from the price, not how much they quote. README, NOTE §1/§6–§8 and SEED_SWEEP
   say so; NOTE §7's "depth is what the lever removes" is corrected rather than kept.
2. Every claim is reported with a 95% bootstrap interval and an exact sign test, and is
   also measured on executed prices (`trade_move`, `trade_end`), so a quote-only artifact
   would show up as disagreement.
3. `tests/test_lever_study.py` holds it (slow: distance-only ≥ 27/30 on mid and on trades,
   ratio ≥ 3; limits-only and size-only ratio within 0.8–1.25 and p > 0.05; size-only
   still removes ≥ 70% of depth; monotone dose) plus fast tests of the instruments.
4. The committed scenario and its lever are unchanged; the demo is unchanged.

**Why.** "Remove liquidity and prices swing more" is textbook, and a bundled lever
invites "of course, you deleted the book". Taking it apart turns a demonstration into a
result that can be wrong and is not, and that names the variable a learned maker
(Phase 2) would actually control.

**Caveats recorded with the result.** Makers re-quote every 10–15 ms (fast refill), and
they price relative to the current best quotes, often their own. Both plausibly make
distance matter more and depth less than in real markets; neither is tested. Distance
alone leans up (22 of 30 seeds, p = 0.016), unexplained.

**Rejected.** A variance-based metric in place of the gate's: keeping the committed
gate's own metric makes every number comparable with ADR-020 and the demo.

## ADR-023: M7 setup — sign-off, gate market, a stronger gate, paired entrants

**M6 sign-off.** The author opened M7 on 2026-11-20 ("m7 begin"), signing off the M6
design (RL_DESIGN.md, ADR-017). The November proposal is adopted with it: the M7 gate is
§9's, strengthened below; the question "does a learned maker soften or deepen the lever's
effect?" becomes M8's headline, measured with the paired 30-seed design (ADR-020/022).
Timebox: three weeks, to 2026-12-11; without a gate result by then Phase 1 ships alone.

**Measured before sizing (§13).** The bare simulator runs at about 75x real time
(~150-180k events/s, no recording). One environment managed ~420 steps/s, but resets
dominated: each episode first simulates the market up to its random start. With training
starts capped at 40 s, 16 parallel environments give ~1,080 steps/s, so 1M steps take
about 15 minutes.

**Decisions.**
1. **Gate market: `scenarios/m7-makers.yaml`, the M5 population with no lever.** In the
   M4 calibrated market the rule-based makers are the resting side of 0.3-2% of volume
   (noise traders provide the liquidity); beating one there proves nothing. In the M5
   population maker 1 is the resting side of ~35% of volume and maker 2 of ~12%. M8
   then adds the lever to the same population.
2. **A stronger gate.** A fixed rule ("join the best price on both sides, full size")
   already beats the rule-based maker on 32 of 40 held-out episodes; the rule-based maker
   prices off the book, often its own quote, and is picked off by the trend-followers
   (risk-adjusted P&L -0.66). So the learned maker must beat, on HELD_OUT, both the
   rule-based maker *and the best fixed quoting rule*, chosen like a policy on training
   seeds (27 symmetric rules), with no detector tripped and no ablation collapse.
3. **Retire and replace, so comparisons are paired.** At the episode start the seat's
   rule-based maker cancels its quotes and leaves; a fresh entrant takes the seat flat:
   the policy, or a fresh rule-based maker with the same parameters for the baseline.
   Same seed and start step give an identical market up to the entrant's arrival
   (tested). Without this the baseline would carry inventory the policy never had.
4. **The learned maker quotes relative to the book without its own orders,** never to
   its own quote (the walk-away mechanism of ADR-022). Its action space is otherwise
   RL_DESIGN §4 unchanged.
5. **Training starts in 10-40 s; evaluation in 10-150 s.** Start time still varies in
   training (D6), and held-out episodes include start times training never saw.
6. **G7 threshold fixed before training:** inventory half-life at most 100 steps (10 s,
   a third of an episode), from a pooled AR(1) fit. G8 applies from Stage 2 and G9 to
   perturbed scenarios (M8); both are reported as not applicable, not as passes.

**Committed episode sets** (in `marquee.rl.evaluate`, generated from fixed seeds):
TRAIN_EVAL 40 from the training pool, VALIDATION 20 (checkpoint choice), HELD_OUT 40
(the gate, never used for a choice), HELD_OUT_2 20 (ablation A2). Seeds are disjoint.

## ADR-024: M7 first gate run failed as pre-registered; gate amended, re-scored on HELD_OUT_3

**Result.** `docs/M7_RESULTS.md`. The learned maker beats both baselines on held-out
risk-adjusted P&L (1.95 against −0.66 rule-based and −0.04 best fixed rule) and
generalizes (G10 1.07×, A2 0.90×), but fails G2 (96.4% two-sided steps, threshold 99%)
and two ablations (A3 REJECT_TAKER 0.43×, A4 +1 momentum trader 0.47×). **The gate is
recorded as failed.**

**Diagnosis, after the verdict.** G2 as implemented counts resting quotes at step end;
the policy submits both sides on 100% of steps and the gaps are fills. A3 and A4 move
the market for every controller (the rule-based maker loses 3.6× more with an extra
momentum trader); the learned maker is the only profitable controller under A4 and its
risk-adjusted P&L rises under A3.

**Amendment, accepted by the author on 2026-11-21** (the M6 sign-off reserved this
call). Fixed here, in code and tests, and committed before anything ran on HELD_OUT_3:

1. **G2** is the share of steps on which the policy *submitted* both a bid and an ask
   (`submitted_two_sided_frac`), threshold 99% unchanged. Resting both sides at step
   end is still reported, as a secondary number that is not judged.
2. **Ablation collapse** (`lead_collapse`). Under each ablation the candidate, the
   rule-based maker and the best fixed rule are all played on the same episodes. The
   policy collapses if (a) its risk-adjusted P&L no longer beats *both* baselines under
   that ablation, or (b) its mean P&L falls below half its main held-out mean while
   neither baseline loses as much as half of its own main |mean|, that is, the ablation
   hurt only the policy. The plain ratio to the main run stays in the report.
3. **Episodes.** Main set HELD_OUT_3 (40 episodes, seeds 5,000,001+), committed in
   `4be9546` before any run on it. Ablations use HELD_OUT_3; A2 keeps HELD_OUT_2.
   The best fixed rule stays the one chosen on TRAIN_EVAL (2, 2, 1). G1–G10 otherwise
   unchanged.
4. **One shot.** The model is unchanged (`models/m7-stage1.zip`). The HELD_OUT_3 result
   stands, pass or fail; no further amendment of M7's gate after seeing it.

Rejected: re-scoring HELD_OUT under the amended criteria. It would be grading on our
own curve. The original run stays reproducible with `--gate original --held-out 1`.

**Outcome (2026-11-21): failed, final.** On HELD_OUT_3 the learned maker beats the
rule-based maker (RA 0.19 against −0.62) but not the best fixed rule (0.191 against
0.198), and G10 trips (0.56×). Every ablation passes the amended rule. The cause is one
episode lost 59,753 to inventory carried near the limit into a move: missing tail-risk
control, not a measurement artifact. M7 closes as failed; see `docs/M7_RESULTS.md`.

## ADR-025: M7b — one reward change for tail risk, retrained, one shot on HELD_OUT_4

**Why.** M7 failed (ADR-024) on rare large inventory losses: one HELD_OUT_3 episode lost
59,753 holding 339 of 360 shares into a move. The inventory penalty γ(q/q_max)² at
γ = 0.01 costs 0.01 per step at the limit, against typical per-step reward around 0.3,
so it barely registers. The author approved one retry with a reward change
(2026-11-21). Fixed here before any M7b training:

1. **Reward.** Unchanged form, r = (S + I − η·max(0, I)) / base − γ·(q/q_max)², η = 0.5.
   Only γ changes, to one of **{0.1, 0.3, 1.0}**, chosen on validation (below). No other
   reward term, no new observation, no action-space change.
2. **Training.** Three runs, one per γ, each initialised from the M7 Stage 0 model
   (`runs/s0/latest.zip`) and trained 1.5M Stage-1 steps, PPO as M7 except learning
   rate 1.5e-4 (M7 at 3e-4 became unstable after 2M). 8 environments each, seed 0.
   Checkpoints every 100k.
3. **Choice.** Every checkpoint of all three runs is played on VALIDATION (20) plus
   VALIDATION_2 (40 new, seeds 6,000,001+): 60 episodes. The model is the checkpoint
   with the highest risk-adjusted P&L on those 60. Nothing else picks it.
4. **Gate.** ADR-024's amended gate, unchanged, on **HELD_OUT_4** (40 episodes, seeds
   7,000,001+), committed with this ADR. The best fixed rule stays (2, 2, 1), chosen on
   TRAIN_EVAL. One shot: the result stands, pass or fail; M7b is not retried.

**Rejected.** Fine-tuning the M7 model (it learned to ignore inventory; a clean start
from Stage 0 tests the reward, not a patch). A drawdown or CVaR term (a new reward form
is a bigger change than the failure calls for). Choosing on HELD_OUT_3 (it already
judged M7).

## ADR-026: M8 — does a learned maker soften or deepen the lever's effect?

The question ADR-023 set for M8, fixed here with its harness (`marquee.rl.m8`,
`scenarios/m8-lever.yaml`, `tests/test_m8.py`) before any run with a learned model.

**Market.** `m8-lever.yaml` is the M7 gate population (`m7-makers`, CANCEL_RESTING) with
the M5 lever added verbatim at t = 30 s, horizon 60 s. Maker 1 is always the rule-based
maker and always takes the lever.

**Arms.** Maker 2's seat is retired and taken over at the same entry time by:
*rule, levered* (a rule-based successor that takes the lever: the M5 lever in this
population), *rule, holds* (a rule-based successor that keeps its normal parameters),
or *learned* (the learned maker, which decides for itself), plus the no-lever twins
(rule, learned). Same seed and entry give an identical market until the lever (tested).

**Seeds and timing.** 30 seeds 8,000,001-8,000,030, outside the training pool and every
M7/M7b set. Entry step per seed drawn once (rng 18) in 12.0-24.0 s, so the lever lands
at step 60-180 of the learned maker's episode. It never saw a perturbation in training,
so it cannot have memorized one (D6; G9 does not apply).

**Measure.** The committed crash gate's move (signed largest deviation of the public
mid in the 5 s after the lever from the mid at the lever, 100 ms grid), and the same on
executed prices. Also what the entrant does: its quoted spread before and after, how
often it stays two-sided, its inventory, its volume in the window.

**Primary comparison and its reading, fixed now.** *learned* against *rule, holds*:
both successors are free of the lever, so the only difference is who sits in the seat.
Per seed, is the learned arm's |move| smaller? Exact sign test, and the median paired
ratio |learned| / |rule, holds| with a 95% bootstrap interval. **Softens** if p < 0.05,
the learned move is smaller on more seeds, and the interval lies below 1; **deepens**
if the mirror holds; otherwise **no detectable difference**. Reported alongside, not
read as the answer: learned against *rule, levered*; each lever arm against its twin
(including whether the lever amplifies at all in this population); executed prices.

**Model.** Primary: the M7b model chosen under ADR-025, whatever its gate verdict,
which is reported beside the result. Secondary: the M7 model (`models/m7-stage1.zip`).
