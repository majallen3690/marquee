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
