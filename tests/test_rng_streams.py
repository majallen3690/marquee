"""Identity-keyed RNG stream properties (ADR-006, M2 gate)."""

from marquee.sim import rng as rngmod


def draws(gen) -> list[int]:
    return [int(gen.integers(0, 2**31)) for _ in range(64)]


def test_streams_are_deterministic_by_identity() -> None:
    a = rngmod.stream(123, rngmod.DOMAIN_AGENT, 5)
    b = rngmod.stream(123, rngmod.DOMAIN_AGENT, 5)
    assert draws(a) == draws(b)


def test_streams_differ_across_ids_domains_and_seeds() -> None:
    base = draws(rngmod.stream(123, rngmod.DOMAIN_AGENT, 5))
    assert base != draws(rngmod.stream(123, rngmod.DOMAIN_AGENT, 6))
    assert base != draws(rngmod.stream(123, rngmod.DOMAIN_WAKE, 5))
    assert base != draws(rngmod.stream(124, rngmod.DOMAIN_AGENT, 5))


def test_population_change_leaves_other_streams_bit_identical() -> None:
    """The ADR-006 property: removing agent 2 must not shift agent 3's stream.
    Guaranteed by construction with identity keys — this test pins the
    construction so a refactor to sequential spawn() fails loudly."""
    with_full_population = [
        draws(rngmod.stream(999, rngmod.DOMAIN_AGENT, aid)) for aid in (1, 2, 3)
    ]
    with_agent_2_removed = [
        draws(rngmod.stream(999, rngmod.DOMAIN_AGENT, aid)) for aid in (1, 3)
    ]
    assert with_full_population[0] == with_agent_2_removed[0]
    assert with_full_population[2] == with_agent_2_removed[1]
