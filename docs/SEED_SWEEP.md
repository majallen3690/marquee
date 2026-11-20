# Seed sweep: what the lever does in general (ADR-020)

One seed is an anecdote. This runs the committed flash-crash scenario on 30 seeds
(the committed 777002 plus 1001 to 1029), each twice: with the scripted lever at
30 s, and without it. Without the lever is the control: same seed, identical order
flow up to 30 s. Metrics are exactly the committed crash gate's
(`tests/test_m5_crash.py`): the mid on the 100 ms grid, the signed largest move in
the 5 s after 30 s, and the worst 5 s range in the 15 s before.

Reproduce: `uv run python -m marquee.analysis.seed_sweep --seeds 30 --out docs/seed-sweep.json`
(about 3 minutes). Asserted by `tests/test_seed_sweep.py` (`uv run pytest -m slow`).

## Result

| | with lever | without lever |
|---|---|---|
| median size of the 5 s move (ticks) | 64.8 | 27.0 |
| mean size of the 5 s move (ticks) | 69.9 | 32.4 |
| move bigger than its own control | 23 of 30 | |
| median paired ratio (with / without) | 2.11 | |
| price moved down | 16 of 30 | 11 of 30 |
| passes the committed gate (≥ 25 ticks and ≥ 2× normal) | 10 of 30 | 4 of 30 |

**What holds:** cutting the makers' risk limits roughly doubles how far the price
moves in the next 5 seconds. **What does not:** the direction. The lever removes the
liquidity that absorbs order flow; whichever way the flow is leaning then moves the
price further. On 14 seeds that is up.

**About the committed seed.** 777002 is the deepest fall of the 30 (rank 1 by signed
move), so the demo shows the most dramatic case, not the typical one. Its own control
moves +58 ticks, which is itself 2.07× that seed's normal range: the committed gate's
amplification test alone would pass with no lever at all. `test_m5_crash.py` now also
asserts the same-seed comparison (−107.5 with the lever against +58 without).

**Without the three momentum traders** (`docs/seed-sweep-no-momentum.json`) the lever
still amplifies, by about half as much: median 21.2 ticks against 14.5 for the control,
larger on 24 of 30 seeds. With them, the lever's move is larger than without them on 25 of
30 seeds. They are the amplifier, not the cause.

**The gate is weaker than its name.** It measures an unsigned move against the same
run's recent past. That catches a dislocation, not a crash, and not causation. The
paired control and this sweep are the evidence for causation; the word "crash" applies
to the committed seed only.

## Every seed (sorted by the move with the lever)

| seed | move with lever | move without | normal 5 s range | ratio with | ratio without |
|---|---|---|---|---|---|
| 777002 | -107.5 | +58.0 | 28.0 | 3.84 | 2.07 |
| 1025 | -93.5 | +44.5 | 37.0 | 2.53 | 1.20 |
| 1010 | -86.5 | -21.5 | 58.0 | 1.49 | 0.37 |
| 1002 | -83.0 | -28.0 | 22.0 | 3.77 | 1.27 |
| 1028 | -82.0 | -13.5 | 83.5 | 0.98 | 0.16 |
| 1013 | -81.0 | -21.0 | 27.5 | 2.95 | 0.76 |
| 1003 | -78.0 | -28.0 | 36.0 | 2.17 | 0.78 |
| 1016 | -66.5 | +28.0 | 32.5 | 2.05 | 0.86 |
| 1020 | -51.0 | -22.0 | 19.0 | 2.68 | 1.16 |
| 1007 | -50.0 | +119.0 | 55.5 | 0.90 | 2.14 |
| 1024 | -38.0 | +18.0 | 28.5 | 1.33 | 0.63 |
| 1012 | -37.5 | +7.0 | 55.0 | 0.68 | 0.13 |
| 1006 | -23.0 | -31.0 | 20.0 | 1.15 | 1.55 |
| 1021 | -16.0 | +8.0 | 56.5 | 0.28 | 0.14 |
| 1004 | -13.0 | +18.5 | 27.5 | 0.47 | 0.67 |
| 1023 | -8.5 | +9.5 | 38.5 | 0.22 | 0.25 |
| 1022 | +11.5 | +7.0 | 32.5 | 0.35 | 0.22 |
| 1027 | +13.0 | +7.0 | 29.0 | 0.45 | 0.24 |
| 1001 | +18.5 | +8.5 | 82.0 | 0.23 | 0.10 |
| 1017 | +22.5 | -28.5 | 94.0 | 0.24 | 0.30 |
| 1026 | +29.0 | +38.0 | 11.0 | 2.64 | 3.45 |
| 1008 | +40.5 | +46.0 | 30.0 | 1.35 | 1.53 |
| 1005 | +63.0 | -30.5 | 62.0 | 1.02 | 0.49 |
| 1009 | +73.0 | +19.0 | 79.5 | 0.92 | 0.24 |
| 1011 | +80.0 | +46.5 | 112.0 | 0.71 | 0.42 |
| 1014 | +80.0 | -26.0 | 71.5 | 1.12 | 0.36 |
| 1018 | +131.5 | -50.5 | 78.5 | 1.68 | 0.64 |
| 1029 | +161.0 | +82.5 | 113.0 | 1.42 | 0.73 |
| 1015 | +177.0 | +21.0 | 38.5 | 4.60 | 0.55 |
| 1019 | +281.5 | +84.0 | 29.5 | 9.54 | 2.85 |
