"""Identity-keyed RNG stream spawning (ADR-006).

Every stream derives from (master_seed, domain, entity_id) — never from spawn
position — so adding/removing/reordering agents leaves every other stream
bit-identical.
"""

import numpy as np

DOMAIN_KERNEL = 0  # latency jitter draws
DOMAIN_AGENT = 1  # agent decision randomness, keyed by agent_id
DOMAIN_WAKE = 2  # per-agent wake scheduling, keyed by agent_id


def stream(master_seed: int, domain: int, entity_id: int = 0) -> np.random.Generator:
    seq = np.random.SeedSequence(master_seed, spawn_key=(domain, entity_id))
    return np.random.Generator(np.random.PCG64(seq))
