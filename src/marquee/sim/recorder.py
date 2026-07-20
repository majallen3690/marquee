"""JSONL recorder implementing the exact ADR-006 byte contract.

Serialization: json.dumps(obj, sort_keys=True, separators=(",", ":"),
ensure_ascii=True), files opened with encoding="utf-8", newline="\n", one "\n"
per record. Values must be built-in int or str — the recorder hard-errors on
anything else (float, bool, numpy scalars) rather than coercing, because a
coercing fallback would serialize the same value differently on record vs
replay and silently break byte-identity.
"""

import json
from pathlib import Path

# Token caches: string -> its exact JSON encoding as json.dumps(ensure_ascii=True)
# would produce it. Escapes are computed BY json.dumps, so the fast path below is
# byte-identical to the reference encoder for any input (pinned by a Hypothesis
# test). Keys/values in practice come from a tiny fixed schema vocabulary, so the
# caches stay small; the size guard only matters for pathological callers.
_MAX_CACHE = 4096
_key_cache: dict[str, str] = {}
_str_cache: dict[str, str] = {}


def _encode_str(s: str) -> str:
    token = _str_cache.get(s)
    if token is None:
        token = json.dumps(s, ensure_ascii=True)
        if len(_str_cache) < _MAX_CACHE:
            _str_cache[s] = token
    return token


def canonical_line(obj: dict) -> str:
    """Exact ADR-006 serialization: byte-identical to
    json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
    ~4x faster (this sits on the per-event hot path — 30k events/sec gate)."""
    parts = []
    for key in sorted(obj):
        key_token = _key_cache.get(key)
        if key_token is None:
            key_token = json.dumps(key, ensure_ascii=True) + ":"
            if len(_key_cache) < _MAX_CACHE:
                _key_cache[key] = key_token
        value = obj[key]
        value_type = type(value)
        if value_type is int:
            parts.append(f"{key_token}{value}")
        elif value_type is str:
            parts.append(f"{key_token}{_encode_str(value)}")
        else:
            raise TypeError(
                f"recorder values must be built-in int or str; "
                f"key {key!r} has {type(value).__name__} ({value!r})"
            )
    return "{" + ",".join(parts) + "}"


# -- fixed-schema fast path (ADR-006 pre-authorized) --------------------------
# The kernel's five event shapes are static, so their lines are built by
# f-string with keys ALREADY in sorted order — byte-identical to canonical_line
# of the equivalent dict (pinned by tests) at a fraction of the cost. The
# unrolled type checks keep the hard-error contract: bool/numpy values raise,
# never serialize.

_DK_TOKENS = frozenset(("ack", "fill", "cxl"))


def fmt_wake(t: int, p: int, s: int, aid: int) -> str:
    if type(t) is not int or type(p) is not int or type(s) is not int or type(aid) is not int:
        raise TypeError("fmt_wake: all fields must be built-in int")
    return f'{{"aid":{aid},"k":"wake","p":{p},"s":{s},"t":{t}}}'


def fmt_ord(
    t: int, p: int, s: int, aid: int, oid: int, side: int, ot: int,
    px: int, qty: int, st: int, rq: int, cq: int,
) -> str:
    if (
        type(t) is not int or type(p) is not int or type(s) is not int
        or type(aid) is not int or type(oid) is not int or type(side) is not int
        or type(ot) is not int or type(px) is not int or type(qty) is not int
        or type(st) is not int or type(rq) is not int or type(cq) is not int
    ):
        raise TypeError("fmt_ord: all fields must be built-in int")
    return (
        f'{{"aid":{aid},"cq":{cq},"k":"ord","oid":{oid},"ot":{ot},"p":{p},"px":{px},'
        f'"qty":{qty},"rq":{rq},"s":{s},"side":{side},"st":{st},"t":{t}}}'
    )


def fmt_cxl(t: int, p: int, s: int, aid: int, oid: int, cs: int, rm: int) -> str:
    if (
        type(t) is not int or type(p) is not int or type(s) is not int
        or type(aid) is not int or type(oid) is not int or type(cs) is not int
        or type(rm) is not int
    ):
        raise TypeError("fmt_cxl: all fields must be built-in int")
    return f'{{"aid":{aid},"cs":{cs},"k":"cxl","oid":{oid},"p":{p},"rm":{rm},"s":{s},"t":{t}}}'


def fmt_dlv(t: int, p: int, s: int, aid: int, dk: str, oid: int) -> str:
    if (
        type(t) is not int or type(p) is not int or type(s) is not int
        or type(aid) is not int or type(oid) is not int or dk not in _DK_TOKENS
    ):
        raise TypeError("fmt_dlv: int fields must be built-in int; dk must be a known token")
    return f'{{"aid":{aid},"dk":"{dk}","k":"dlv","oid":{oid},"p":{p},"s":{s},"t":{t}}}'


def fmt_prt(t: int, p: int, s: int, aid: int, prm: str, v: int) -> str:
    if (
        type(t) is not int or type(p) is not int or type(s) is not int
        or type(aid) is not int or type(v) is not int or not prm.isidentifier()
    ):
        raise TypeError(
            "fmt_prt: int fields must be built-in int; param must be an identifier"
        )
    return f'{{"aid":{aid},"k":"prt","p":{p},"prm":"{prm}","s":{s},"t":{t},"v":{v}}}'


def fmt_trade(
    t: int, tid: int, px: int, qty: int, tko: int, mko: int, tka: int, mka: int, tks: int,
) -> str:
    if (
        type(t) is not int or type(tid) is not int or type(px) is not int
        or type(qty) is not int or type(tko) is not int or type(mko) is not int
        or type(tka) is not int or type(mka) is not int or type(tks) is not int
    ):
        raise TypeError("fmt_trade: all fields must be built-in int")
    return (
        f'{{"mka":{mka},"mko":{mko},"px":{px},"qty":{qty},"t":{t},"tid":{tid},'
        f'"tka":{tka},"tko":{tko},"tks":{tks}}}'
    )


class JsonlRecorder:
    """Writes events.jsonl (every kernel-processed event) and trades.jsonl (fills)."""

    def __init__(self, events_path: str | Path, trades_path: str | Path) -> None:
        # Long-lived handles by design; close() is the recorder's contract.
        # 1 MiB buffers: ~100k small writes per run otherwise hit the OS too often.
        self._events = open(  # noqa: SIM115
            events_path, "w", encoding="utf-8", newline="\n", buffering=1 << 20
        )
        self._trades = open(  # noqa: SIM115
            trades_path, "w", encoding="utf-8", newline="\n", buffering=1 << 20
        )

    def record_line(self, line: str) -> None:
        self._events.write(line)
        self._events.write("\n")

    def record_trade_line(self, line: str) -> None:
        self._trades.write(line)
        self._trades.write("\n")

    def close(self) -> None:
        self._events.close()
        self._trades.close()


class ListRecorder:
    """In-memory recorder for tests and benchmarks. Parses lines back to dicts
    so test assertions stay structural."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.trades: list[dict] = []

    def record_line(self, line: str) -> None:
        self.events.append(json.loads(line))

    def record_trade_line(self, line: str) -> None:
        self.trades.append(json.loads(line))

    def close(self) -> None:
        pass
