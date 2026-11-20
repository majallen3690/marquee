"""The lever's effect across seeds (ADR-020). Slow: 60 full runs, about 3 minutes.
Run with `uv run pytest -m slow`.

What holds across seeds is not "a crash" but amplification: pulling maker
liquidity makes the next 5 s move bigger. The direction is set by the order flow
and is not a property of the lever (the committed seed is the deepest fall of 30).
"""

import statistics

import pytest

from marquee.analysis.seed_sweep import COMMITTED_SEED, default_seeds, sweep


@pytest.mark.slow
def test_lever_amplifies_the_move_across_seeds() -> None:
    rows = sweep(default_seeds(30))
    lever = {r.seed: r for r in rows if r.lever}
    control = {r.seed: r for r in rows if not r.lever}
    bigger = sum(abs(lever[s].move) > abs(control[s].move) for s in lever)
    ratio = statistics.median(abs(lever[s].move) / max(abs(control[s].move), 0.5) for s in lever)
    assert bigger >= 20, f"lever made the move bigger on only {bigger}/30 seeds"
    assert ratio >= 1.5, f"median paired amplification {ratio:.2f} < 1.5"
    # Honest about direction: the lever does not reliably push the price down.
    down = sum(lever[s].move < 0 for s in lever)
    assert 5 <= down <= 25
    assert min(lever.values(), key=lambda r: r.move).seed == COMMITTED_SEED
