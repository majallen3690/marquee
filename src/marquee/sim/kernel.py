"""Discrete-event simulation kernel (ADR-002/003/006/007, taxonomy in ADR-011).

Owns the clock, the event queue, RNG stream spawning, order-id assignment, and
the integer-domain validation chokepoint. Wakes agents on per-agent seeded
schedules, routes their intents to the engine under the latency model, and
emits every processed event to the recorder.
"""

import heapq

import numpy as np

from marquee.engine import MatchingEngine, Order, OrderType
from marquee.engine.types import (
    AgentId,
    BookSnapshot,
    CancelResult,
    CancelStatus,
    ExecutionReport,
    Fill,
    TimeNs,
)
from marquee.sim import rng as rngmod
from marquee.sim.events import (
    Delivery,
    IntentArrival,
    Perturbation,
    PriorityClass,
    Wake,
)
from marquee.sim.protocols import (
    Agent,
    CancelIntent,
    Intent,
    Perturbable,
    Recorder,
    SubmitLimit,
    SubmitMarket,
)
from marquee.sim.recorder import fmt_cxl, fmt_dlv, fmt_ord, fmt_prt, fmt_trade, fmt_wake

_DRAW_BUFFER = 512


class LatencyModel:
    """Base one-way latencies plus optional uniform jitter from the kernel stream
    (ADR-003: stochastic latency draws come from seeded streams, domain 0).

    Jitter draws are batch-buffered: consumption order off the stream is
    identical run-to-run (pure function of the seed), which is the whole
    determinism requirement. Scalar Generator calls cost ~2 µs each and sit on
    the per-message hot path."""

    def __init__(
        self,
        agent_to_exchange_ns: int,
        exchange_to_agent_ns: int,
        jitter_ns: int,
        rng: np.random.Generator,
    ) -> None:
        self._up = agent_to_exchange_ns
        self._down = exchange_to_agent_ns
        self._jitter = jitter_ns
        self._rng = rng
        self._buf: list[int] = []

    def _next_jitter(self) -> int:
        buf = self._buf
        if not buf:
            draws = self._rng.integers(0, self._jitter + 1, size=_DRAW_BUFFER)
            # Reversed so pop() consumes in draw order; tolist() yields built-in ints.
            buf.extend(reversed(draws.tolist()))
        return buf.pop()

    def up(self) -> int:
        if self._jitter:
            return self._up + self._next_jitter()
        return self._up

    def down(self) -> int:
        if self._jitter:
            return self._down + self._next_jitter()
        return self._down


class _Ctx:
    """Read-only AgentContext handed to one agent (ADR-007)."""

    __slots__ = ("_kernel", "_rng", "_agent_id")

    def __init__(self, kernel: "SimKernel", rng: np.random.Generator, agent_id: AgentId) -> None:
        self._kernel = kernel
        self._rng = rng
        self._agent_id = agent_id

    @property
    def now(self) -> TimeNs:
        return self._kernel.now

    @property
    def rng(self) -> np.random.Generator:
        return self._rng

    def book(self, depth: int = 10) -> BookSnapshot:
        return self._kernel.engine.snapshot(ts=self._kernel.now, depth=depth)

    def book_excluding_self(self, depth: int = 10) -> BookSnapshot:
        """The book without this agent's own resting orders (M7, RL_DESIGN §5)."""
        return self._kernel.engine.snapshot_excluding(self._kernel.now, depth, self._agent_id)

    def queue_ahead(self, order_id: int) -> int | None:
        """Quantity ahead of one of this agent's OWN live orders; None for any other
        id, so other agents' queue positions cannot be probed (ADR-011 spirit)."""
        if self._kernel._order_owner.get(order_id) != self._agent_id:
            return None
        return self._kernel.engine.queue_ahead(order_id)


class _AgentSlot:
    __slots__ = ("agent", "ctx", "wake_rng", "mean_wake_interval_ns", "wake_buf", "periodic")

    def __init__(
        self,
        agent: Agent,
        ctx: _Ctx,
        wake_rng: np.random.Generator,
        mean_wake_interval_ns: int,
        periodic: bool = False,
    ) -> None:
        self.agent = agent
        self.ctx = ctx
        self.wake_rng = wake_rng
        self.mean_wake_interval_ns = mean_wake_interval_ns
        self.wake_buf: list[float] = []
        self.periodic = periodic

    def next_interval(self) -> int:
        """Exponential inter-wake time, batch-buffered (same stream-consumption
        order every run — see LatencyModel). A periodic slot wakes on an exact
        grid and draws nothing: the learning agent's decision clock (M7)."""
        if self.periodic:
            return self.mean_wake_interval_ns
        buf = self.wake_buf
        if not buf:
            draws = self.wake_rng.exponential(self.mean_wake_interval_ns, size=128)
            buf.extend(reversed(draws.tolist()))
        interval = int(buf.pop())
        return interval if interval > 0 else 1


def _require_int(agent_id: int, field: str, value: object) -> None:
    # type() is exact on purpose: bool and numpy integer types must be rejected,
    # not coerced — they would serialize differently on replay (ADR-003/004).
    if type(value) is not int:
        raise TypeError(
            f"agent {agent_id} produced non-int intent field {field!r}: "
            f"{value!r} ({type(value).__name__})"
        )


class SimKernel:
    """Event loop. Construct, register_agent() in scenario order, then run()."""

    def __init__(
        self,
        master_seed: int,
        engine: MatchingEngine,
        recorder: Recorder,
        horizon_ns: int,
        agent_to_exchange_ns: int = 1_000_000,
        exchange_to_agent_ns: int = 1_000_000,
        latency_jitter_ns: int = 0,
    ) -> None:
        self.engine = engine
        self.now: TimeNs = 0
        self._master_seed = master_seed
        self._recorder = recorder
        self._horizon = horizon_ns
        self._latency = LatencyModel(
            agent_to_exchange_ns,
            exchange_to_agent_ns,
            latency_jitter_ns,
            rngmod.stream(master_seed, rngmod.DOMAIN_KERNEL),
        )
        self._queue: list[tuple[int, int, int, object]] = []
        self._seq = 0
        # Perturbations use their OWN sequence counter (ADR-010): if they drew
        # from the global one, a live-inserted perturbation would consume a
        # mid-run seq that re-simulation consumes pre-run, shifting the seq of
        # every subsequent event and breaking replay mode (c) byte-identity.
        # Cross-class heap ordering never reaches the third tuple element
        # (priority classes differ), so the two counters cannot collide.
        self._perturbation_seq = 0
        self._perturbation_processed = 0
        self._slots: dict[int, _AgentSlot] = {}  # insertion-ordered = registration order
        self._next_order_id = 1
        self._order_owner: dict[int, int] = {}  # ownership check on cancels (ADR-011)
        self.events_processed = 0
        self._started = False

    # -- setup ---------------------------------------------------------------

    def register_agent(
        self, agent: Agent, mean_wake_interval_ns: int, periodic: bool = False
    ) -> None:
        aid = agent.agent_id
        if aid in self._slots:
            raise ValueError(f"duplicate agent_id {aid}")
        ctx = _Ctx(self, rngmod.stream(self._master_seed, rngmod.DOMAIN_AGENT, aid), aid)
        wake_rng = rngmod.stream(self._master_seed, rngmod.DOMAIN_WAKE, aid)
        self._slots[aid] = _AgentSlot(agent, ctx, wake_rng, mean_wake_interval_ns, periodic)

    def schedule_perturbation(
        self, effective_ns: int, agent_id: AgentId, param: str, value: int
    ) -> None:
        """Schedule a parameter change (ADR-010). Pre-run scheduling accepts any
        future time; once the clock has advanced, effective time must be
        STRICTLY later than now — the live-insertion rule that makes seq
        assignment independent of wall-clock arrival."""
        if type(value) is not int:
            raise TypeError(f"perturbation value must be built-in int, got {value!r}")
        if agent_id not in self._slots:
            raise ValueError(f"perturbation targets unknown agent_id {agent_id}")
        if not isinstance(self._slots[agent_id].agent, Perturbable):
            raise TypeError(f"agent {agent_id} does not implement apply_perturbation")
        if effective_ns <= self.now and self.now > 0:
            raise ValueError(
                f"perturbation effective time {effective_ns} must be strictly after "
                f"current sim time {self.now} (ADR-010)"
            )
        heapq.heappush(
            self._queue,
            (
                effective_ns,
                int(PriorityClass.PERTURBATION),
                self._perturbation_seq,
                Perturbation(agent_id, param, value),
            ),
        )
        self._perturbation_seq += 1

    # -- scheduling ----------------------------------------------------------

    def _push(self, time_ns: int, priority: PriorityClass, payload: object) -> None:
        heapq.heappush(self._queue, (time_ns, int(priority), self._seq, payload))
        self._seq += 1

    def _schedule_next_wake(self, slot: _AgentSlot) -> None:
        self._push(self.now + slot.next_interval(), PriorityClass.WAKE, Wake(slot.agent.agent_id))

    def _schedule_intents(self, agent_id: AgentId, intents: list[Intent]) -> None:
        for intent in intents:
            if isinstance(intent, SubmitLimit):
                _require_int(agent_id, "price", intent.price)
                _require_int(agent_id, "qty", intent.qty)
            elif isinstance(intent, SubmitMarket):
                _require_int(agent_id, "qty", intent.qty)
            elif isinstance(intent, CancelIntent):
                _require_int(agent_id, "order_id", intent.order_id)
            else:
                raise TypeError(f"agent {agent_id} returned non-intent {intent!r}")
            self._push(
                self.now + self._latency.up(),
                PriorityClass.INTENT_ARRIVAL,
                IntentArrival(agent_id, intent),
            )

    def _deliver(
        self, agent_id: AgentId, payload: ExecutionReport | Fill | CancelResult
    ) -> None:
        self._push(
            self.now + self._latency.down(), PriorityClass.DELIVERY, Delivery(agent_id, payload)
        )

    # -- main loop -----------------------------------------------------------

    def start(self) -> None:
        """Schedule initial wakes (idempotent). Initial wakes are drawn, not
        zero: staggered starts, from the same identity-keyed stream as every
        later wake."""
        if self._started:
            return
        self._started = True
        for slot in self._slots.values():
            self._schedule_next_wake(slot)

    def run_until(self, target_ns: int) -> None:
        """Process every event with time <= min(target_ns, horizon). Peek-based:
        events beyond the target stay queued (resumable stepping — the bridge's
        pacing loop lives on this)."""
        self.start()
        target = min(target_ns, self._horizon)
        queue = self._queue
        while queue and queue[0][0] <= target:
            time_ns, priority, seq, payload = heapq.heappop(queue)
            self.now = time_ns
            self.events_processed += 1
            if type(payload) is Wake:
                self._on_wake(time_ns, priority, seq, payload)
            elif type(payload) is IntentArrival:
                self._on_intent_arrival(time_ns, priority, seq, payload)
            elif type(payload) is Delivery:
                self._on_delivery(time_ns, priority, seq, payload)
            elif type(payload) is Perturbation:
                self._on_perturbation(time_ns, priority, seq, payload)

    def run(self) -> None:
        self.run_until(self._horizon)

    # -- dispatch ------------------------------------------------------------

    def _on_wake(self, t: int, p: int, s: int, ev: Wake) -> None:
        self._recorder.record_line(fmt_wake(t, p, s, ev.agent_id))
        slot = self._slots[ev.agent_id]
        intents = slot.agent.on_wake(slot.ctx)
        self._schedule_intents(ev.agent_id, intents)
        self._schedule_next_wake(slot)

    def _on_intent_arrival(self, t: int, p: int, s: int, ev: IntentArrival) -> None:
        intent = ev.intent
        if isinstance(intent, CancelIntent):
            # Ownership chokepoint: agents may cancel only their own orders. A
            # foreign id is answered UNKNOWN — indistinguishable from a bogus id,
            # so probing other agents' order ids yields nothing (M6 exploit
            # surface, closed at the kernel per ADR-011).
            if self._order_owner.get(intent.order_id) != ev.agent_id:
                result = CancelResult(intent.order_id, CancelStatus.UNKNOWN, 0)
            else:
                result = self.engine.cancel(intent.order_id)
            self._recorder.record_line(
                fmt_cxl(
                    t, p, s, ev.agent_id, intent.order_id,
                    int(result.status), result.removed_qty,
                )
            )
            self._deliver(ev.agent_id, result)
            return

        oid = self._next_order_id
        self._next_order_id += 1
        self._order_owner[oid] = ev.agent_id
        if isinstance(intent, SubmitLimit):
            order_type, price, qty = OrderType.LIMIT, intent.price, intent.qty
        else:
            order_type, price, qty = OrderType.MARKET, 0, intent.qty
        order = Order(
            order_id=oid,
            agent_id=ev.agent_id,
            side=intent.side,
            order_type=order_type,
            price=price,
            qty=qty,
            ts=t,
        )
        report = self.engine.submit(order)
        self._recorder.record_line(
            fmt_ord(
                t, p, s, ev.agent_id, oid, int(intent.side), int(order_type),
                price, qty, int(report.status), report.resting_qty, report.cancelled_qty,
            )
        )
        for fill in report.fills:
            self._recorder.record_trade_line(
                fmt_trade(
                    t, fill.trade_id, fill.price, fill.qty, fill.taker_order_id,
                    fill.maker_order_id, fill.taker_agent_id, fill.maker_agent_id,
                    int(fill.taker_side),
                )
            )
            self._deliver(fill.maker_agent_id, fill)
        for sc in report.stp_cancelled:
            self._deliver(sc.agent_id, CancelResult(sc.order_id, CancelStatus.CANCELLED, sc.qty))
        self._deliver(ev.agent_id, report)

    def _on_perturbation(self, t: int, p: int, s: int, ev: Perturbation) -> None:
        # Record PROCESSING order, not push order. Push order differs between a
        # live run (config perturbations pushed pre-run, live ones pushed later
        # with higher seq even when they fire earlier) and its re-simulation
        # (whole extracted schedule pushed pre-run in time order). Processing
        # order is identical in both, so recording it keeps replay mode (c)
        # byte-identical when config and live perturbations coexist.
        processed_seq = self._perturbation_processed
        self._perturbation_processed += 1
        self._recorder.record_line(
            fmt_prt(t, p, processed_seq, ev.agent_id, ev.param, ev.value)
        )
        agent = self._slots[ev.agent_id].agent
        agent.apply_perturbation(ev.param, ev.value)  # type: ignore[attr-defined]

    def _on_delivery(self, t: int, p: int, s: int, ev: Delivery) -> None:
        payload = ev.payload
        slot = self._slots[ev.agent_id]
        if type(payload) is ExecutionReport:
            kind = "ack"
            oid = payload.order_id
            intents = slot.agent.on_order_ack(slot.ctx, payload)
        elif type(payload) is Fill:
            kind = "fill"
            oid = payload.maker_order_id
            intents = slot.agent.on_fill(slot.ctx, payload)
        else:
            kind = "cxl"
            oid = payload.order_id
            intents = slot.agent.on_cancel_ack(slot.ctx, payload)
        self._recorder.record_line(fmt_dlv(t, p, s, ev.agent_id, kind, oid))
        self._schedule_intents(ev.agent_id, intents)
