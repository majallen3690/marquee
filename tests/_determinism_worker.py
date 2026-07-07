"""Subprocess worker for the engine determinism gate.

Generates a fixed seeded workload, feeds it through a fresh engine, and prints
the SHA-256 of the serialized output stream. The parent test runs this twice
under different PYTHONHASHSEED values and compares hashes (ADR-006 gate a):
same-process double-runs would share one hash seed and mask latent
str-hash-order dependence.
"""

import hashlib
import sys

import numpy as np

from marquee.engine import MatchingEngine, Order, OrderType, Side


def main(seed: int, n_messages: int) -> None:
    rng = np.random.Generator(np.random.PCG64(seed))
    engine = MatchingEngine()
    digest = hashlib.sha256()

    next_id = 1
    issued: list[int] = []
    mid = 10_000

    for _ in range(n_messages):
        roll = int(rng.integers(0, 100))
        if roll < 55 or not issued:  # limit order near a drifting mid
            mid += int(rng.integers(-3, 4))
            mid = max(mid, 10)
            side = Side.BUY if int(rng.integers(0, 2)) == 0 else Side.SELL
            offset = int(rng.integers(0, 8))
            price = mid - offset if side is Side.BUY else mid + offset
            out = engine.submit(
                Order(
                    order_id=next_id,
                    agent_id=int(rng.integers(0, 16)),
                    side=side,
                    order_type=OrderType.LIMIT,
                    price=max(price, 1),
                    qty=int(rng.integers(1, 200)),
                    ts=next_id,
                )
            )
            issued.append(next_id)
            next_id += 1
        elif roll < 80:  # cancel a previously issued id
            target = issued[int(rng.integers(0, len(issued)))]
            out = engine.cancel(target)
        else:  # market order, occasionally sweep-sized
            qty = int(rng.integers(1, 200)) * (10 if roll >= 97 else 1)
            side = Side.BUY if int(rng.integers(0, 2)) == 0 else Side.SELL
            out = engine.submit(
                Order(
                    order_id=next_id,
                    agent_id=int(rng.integers(0, 16)),
                    side=side,
                    order_type=OrderType.MARKET,
                    price=0,
                    qty=qty,
                    ts=next_id,
                )
            )
            issued.append(next_id)
            next_id += 1
        digest.update(repr(out).encode("utf-8"))

    print(digest.hexdigest())


if __name__ == "__main__":
    main(seed=int(sys.argv[1]), n_messages=int(sys.argv[2]))
