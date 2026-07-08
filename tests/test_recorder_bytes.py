"""Recorder byte-contract tests (ADR-006, M2 gate)."""

import json

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from marquee.sim.recorder import (
    JsonlRecorder,
    canonical_line,
    fmt_cxl,
    fmt_dlv,
    fmt_ord,
    fmt_trade,
    fmt_wake,
)


def test_canonical_line_exact_bytes() -> None:
    line = canonical_line({"b": 2, "a": 1, "k": "ord"})
    assert line == '{"a":1,"b":2,"k":"ord"}'  # sorted keys, no spaces


@given(
    obj=st.dictionaries(
        st.text(min_size=1, max_size=12),
        st.one_of(st.integers(), st.text(max_size=20)),
        max_size=12,
    )
)
def test_fast_serializer_matches_reference_encoder(obj: dict) -> None:
    """The hot-path serializer must be byte-identical to json.dumps with the
    ADR-006 arguments for ANY int/str dict — including unicode and characters
    that need escaping (ensure_ascii)."""
    reference = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert canonical_line(obj) == reference


def test_recorder_rejects_non_int_numerics() -> None:
    for bad in (1.5, np.int64(3), True, None, [1]):
        with pytest.raises(TypeError, match="built-in int or str"):
            canonical_line({"t": 0, "v": bad})


def test_fixed_schema_formatters_match_reference_encoder() -> None:
    """Each fmt_* line must be byte-identical to canonical_line (and therefore
    to json.dumps with the ADR-006 arguments) of the equivalent dict."""
    cases = [
        (fmt_wake(5, 2, 17, 3), {"t": 5, "p": 2, "s": 17, "k": "wake", "aid": 3}),
        (
            fmt_ord(5, 0, 17, 3, 42, 1, 0, 100, 7, 0, 7, 0),
            {
                "t": 5, "p": 0, "s": 17, "k": "ord", "aid": 3, "oid": 42,
                "side": 1, "ot": 0, "px": 100, "qty": 7, "st": 0, "rq": 7, "cq": 0,
            },
        ),
        (
            fmt_cxl(5, 0, 17, 3, 42, 0, 7),
            {"t": 5, "p": 0, "s": 17, "k": "cxl", "aid": 3, "oid": 42, "cs": 0, "rm": 7},
        ),
        (
            fmt_dlv(5, 1, 17, 3, "ack", 42),
            {"t": 5, "p": 1, "s": 17, "k": "dlv", "aid": 3, "dk": "ack", "oid": 42},
        ),
        (
            fmt_trade(5, 1, 100, 7, 42, 41, 3, 2, 0),
            {
                "t": 5, "tid": 1, "px": 100, "qty": 7, "tko": 42, "mko": 41,
                "tka": 3, "mka": 2, "tks": 0,
            },
        ),
    ]
    for line, equivalent in cases:
        assert line == canonical_line(equivalent)
        assert line == json.dumps(equivalent, sort_keys=True, separators=(",", ":"))


def test_fixed_schema_formatters_reject_non_int() -> None:
    with pytest.raises(TypeError):
        fmt_wake(np.int64(5), 2, 17, 3)
    with pytest.raises(TypeError):
        fmt_wake(5, 2, 17, True)
    with pytest.raises(TypeError):
        fmt_trade(5, 1, 100.0, 7, 42, 41, 3, 2, 0)
    with pytest.raises(TypeError):
        fmt_dlv(5, 1, 17, 3, "bogus-kind", 42)


def test_files_are_lf_only_utf8(tmp_path) -> None:
    rec = JsonlRecorder(tmp_path / "events.jsonl", tmp_path / "trades.jsonl")
    rec.record_line(fmt_wake(1, 2, 0, 3))
    rec.record_line(fmt_dlv(2, 1, 1, 3, "ack", 9))
    rec.record_trade_line(fmt_trade(2, 1, 100, 5, 9, 8, 3, 2, 0))
    rec.close()

    raw = (tmp_path / "events.jsonl").read_bytes()
    assert b"\r" not in raw  # Windows text mode would have written CRLF
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 2
    for line in raw.decode("utf-8").splitlines():
        parsed = json.loads(line)
        assert list(parsed.keys()) == sorted(parsed.keys())

    traw = (tmp_path / "trades.jsonl").read_bytes()
    assert b"\r" not in traw
    assert traw.count(b"\n") == 1
