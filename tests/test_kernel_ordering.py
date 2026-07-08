"""Kernel-level event ordering, latency, and chokepoint tests (M2 gate)."""

import numpy as np
import pytest

from marquee.engine import MatchingEngine, Side
from marquee.engine.types import CancelResult, CancelStatus, ExecutionReport, Fill
from marquee.sim import ListRecorder, SimKernel, SubmitLimit
from marquee.sim.events import Delivery, IntentArrival, PriorityClass, Wake
from marquee.sim.protocols import AgentContext, CancelIntent, Intent


class OneShotAgent:
    """Emits a fixed intent list on its first wake, then nothing."""

    def __init__(self, agent_id: int, intents: list[Intent]) -> None:
        self._agent_id = agent_id
        self._intents = intents
        self.acks: list[ExecutionReport] = []
        self.fills: list[Fill] = []
        self.cancel_acks: list[CancelResult] = []
        self.wake_times: list[int] = []

    @property
    def agent_id(self) -> int:
        return self._agent_id

    def on_wake(self, ctx: AgentContext) -> list[Intent]:
        self.wake_times.append(ctx.now)
        if self.wake_times[0] == ctx.now and len(self.wake_times) == 1:
            return list(self._intents)
        return []

    def on_order_ack(self, ctx: AgentContext, report: ExecutionReport) -> list[Intent]:
        self.acks.append(report)
        return []

    def on_fill(self, ctx: AgentContext, fill: Fill) -> list[Intent]:
        self.fills.append(fill)
        return []

    def on_cancel_ack(self, ctx: AgentContext, result: CancelResult) -> list[Intent]:
        self.cancel_acks.append(result)
        return []


def make_kernel(recorder: ListRecorder, up: int = 1000, down: int = 1000) -> SimKernel:
    return SimKernel(
        master_seed=42,
        engine=MatchingEngine(),
        recorder=recorder,
        horizon_ns=10_000_000_000,
        agent_to_exchange_ns=up,
        exchange_to_agent_ns=down,
        latency_jitter_ns=0,
    )


def test_same_timestamp_orders_by_priority_class_then_seq() -> None:
    """Crafted same-t events must dispatch: arrivals < deliveries < wakes,
    and FIFO within a class (seq order)."""
    rec = ListRecorder()
    kernel = make_kernel(rec)
    a = OneShotAgent(1, [])
    b = OneShotAgent(2, [])
    kernel.register_agent(a, mean_wake_interval_ns=1_000_000)
    kernel.register_agent(b, mean_wake_interval_ns=1_000_000)

    t = 500
    # Push deliberately out of dispatch order; heap must sort them back.
    kernel._push(t, PriorityClass.WAKE, Wake(1))
    kernel._push(t, PriorityClass.DELIVERY, Delivery(1, CancelResult(9, CancelStatus.UNKNOWN, 0)))
    kernel._push(t, PriorityClass.INTENT_ARRIVAL, IntentArrival(1, SubmitLimit(Side.BUY, 100, 1)))
    kernel._push(t, PriorityClass.WAKE, Wake(2))  # same class as first wake, later seq

    kernel._horizon = t  # stop right after the crafted batch
    kernel._queue = [e for e in kernel._queue]  # initial wakes not scheduled (run() adds them)
    kernel.run()

    crafted = [e for e in rec.events if e["t"] == t]
    assert [e["k"] for e in crafted] == ["ord", "dlv", "wake", "wake"]
    assert [e["k"] == "wake" and e["aid"] for e in crafted[2:]] == [1, 2]  # seq FIFO
    # seq strictly increasing overall in the recorded stream at equal (t, p)
    wake_seqs = [e["s"] for e in crafted if e["k"] == "wake"]
    assert wake_seqs == sorted(wake_seqs)


def test_latency_round_trip_timing() -> None:
    """Intent from a wake at t arrives at t+up; ack lands at t+up+down."""
    rec = ListRecorder()
    kernel = make_kernel(rec, up=1_000, down=3_000)
    agent = OneShotAgent(7, [SubmitLimit(Side.BUY, 100, 5)])
    kernel.register_agent(agent, mean_wake_interval_ns=50_000_000)
    kernel.run()

    first_wake = agent.wake_times[0]
    ord_events = [e for e in rec.events if e["k"] == "ord"]
    dlv_events = [e for e in rec.events if e["k"] == "dlv" and e["dk"] == "ack"]
    assert ord_events[0]["t"] == first_wake + 1_000
    assert dlv_events[0]["t"] == first_wake + 1_000 + 3_000
    assert agent.acks[0].resting_qty == 5


def test_maker_gets_fill_taker_gets_ack_fills() -> None:
    rec = ListRecorder()
    kernel = make_kernel(rec)
    maker = OneShotAgent(1, [SubmitLimit(Side.SELL, 100, 10)])
    taker = OneShotAgent(2, [SubmitLimit(Side.BUY, 100, 10)])
    kernel.register_agent(maker, mean_wake_interval_ns=1_000_000)
    kernel.register_agent(taker, mean_wake_interval_ns=1_000_000)
    kernel.run()

    # Whoever rested first is maker; exactly one side gets on_fill, the other
    # sees its fill inside its ack.
    fills_via_callback = maker.fills + taker.fills
    assert len(fills_via_callback) == 1
    ack_fills = [f for a in (maker.acks + taker.acks) for f in a.fills]
    assert len(ack_fills) == 1
    assert fills_via_callback[0] == ack_fills[0]


def test_cancel_ownership_enforced() -> None:
    """Cancelling another agent's order answers UNKNOWN and leaves the book alone."""
    rec = ListRecorder()
    kernel = make_kernel(rec)
    owner = OneShotAgent(1, [SubmitLimit(Side.SELL, 100, 10)])
    thief = OneShotAgent(2, [CancelIntent(1)])  # order_id 1 will belong to agent 1
    kernel.register_agent(owner, mean_wake_interval_ns=1_000_000)
    kernel.register_agent(thief, mean_wake_interval_ns=1_000_000)
    kernel.run()

    assert len(thief.cancel_acks) == 1
    assert thief.cancel_acks[0].status is CancelStatus.UNKNOWN
    # The order survived: owner's ack shows it resting and no fills happened.
    assert owner.acks[0].resting_qty == 10
    assert rec.trades == []


def test_int_chokepoint_rejects_numpy_and_float_fields() -> None:
    rec = ListRecorder()
    kernel = make_kernel(rec)
    bad = OneShotAgent(1, [SubmitLimit(Side.BUY, np.int64(100), 5)])
    kernel.register_agent(bad, mean_wake_interval_ns=1_000_000)
    with pytest.raises(TypeError, match="non-int"):
        kernel.run()

    rec2 = ListRecorder()
    kernel2 = make_kernel(rec2)
    bad2 = OneShotAgent(1, [SubmitLimit(Side.BUY, 100, 5.0)])
    kernel2.register_agent(bad2, mean_wake_interval_ns=1_000_000)
    with pytest.raises(TypeError, match="non-int"):
        kernel2.run()

    rec3 = ListRecorder()
    kernel3 = make_kernel(rec3)
    bad3 = OneShotAgent(1, [SubmitLimit(Side.BUY, 100, True)])  # bool is not int here
    kernel3.register_agent(bad3, mean_wake_interval_ns=1_000_000)
    with pytest.raises(TypeError, match="non-int"):
        kernel3.run()


def test_two_kernels_same_config_identical_streams() -> None:
    def run() -> tuple[list[dict], list[dict]]:
        rec = ListRecorder()
        kernel = make_kernel(rec)
        kernel.register_agent(OneShotAgent(1, [SubmitLimit(Side.SELL, 100, 10)]), 2_000_000)
        kernel.register_agent(OneShotAgent(2, [SubmitLimit(Side.BUY, 101, 10)]), 2_000_000)
        kernel.run()
        return rec.events, rec.trades

    events_a, trades_a = run()
    events_b, trades_b = run()
    assert events_a == events_b
    assert trades_a == trades_b
    assert trades_a  # the scenario actually trades — the check is not vacuous
