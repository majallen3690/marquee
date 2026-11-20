# DEMO.md — the 3-minute walkthrough

One command, one browser tab, one crash.

No time to install? The recorded run plays in any browser at
https://majallen3690.github.io/marquee/ (built by `.github/workflows/pages.yml` from
`uv run python -m marquee.server.record`; the lever is fixed there, since a recording
cannot change). `?at=29` opens it one second before the lever.

```
uv run marquee-demo
```

Serves the built front end and the live feed at http://127.0.0.1:8420/ and opens
it. (`--scenario`, `--port`, `--no-browser` available; the default scenario is
the committed `m5-flash-crash.yaml`, seed 777002.) Rebuild the front end after
changing it: `cd viz && pnpm build`. The screen is designed for 1440×900; narrower windows shrink it to fit.

---

## 0:00 — What this is (20 seconds)

> "This is a market-microstructure sandbox. Everything on screen comes out of a
> limit order book and matching engine I wrote from scratch, plus eleven trading
> agents that only see what a real participant sees — the book, their own fills,
> their own inventory. Nothing about the price is scripted."

If the audience is new to markets, click **Learn** in the header first: every label
becomes plain English and a five-step tour walks the screen.

Point at the layout: the **strip** across the top (the numbers that matter),
the **chart** (a depth map: teal bids, coral asks, brighter means more size),
the **book** (center right), the **lever** and **tape** (far right), the
**agents** table under the chart. Note the header: scenario, seed, sim clock, LIVE.

## 0:20 — The market is alive and nobody is driving (40 seconds)

Let it run. The strip says *Stable* and *lever fires in N s*. Talk over it:

> "Two market makers quote both sides and manage inventory. Three momentum
> traders chase trends. Six noise traders supply and take liquidity at random.
> Price discovery is entirely emergent — no agent knows a 'true' price."

Point at the book: the depth bars breathing, the spread tiles flipping between
a tick and a handful of ticks. Point at the tape: green/red flow, with who hit
the book.

> "And it isn't just alive, it's *realistic*. This population reproduces four
> stylized facts of real markets — fat-tailed returns, volatility clustering,
> no linear predictability, and long-memory order flow. That's the M4
> calibration suite, thresholds defended against the empirical literature."

## 1:00 — The lever (30 seconds)

Point at the **Lever** panel, top right: the table shows each maker's risk rules
before and after (hard limit 300 → 10, quote size 60 → 5, half-spread 2 → 12).

> "Here's the interesting part. I can reach into one agent class mid-run.
> This is the market makers' risk appetite — their inventory limits, their
> quote size, how far from the touch they're willing to quote."

> "In the committed scenario this fires automatically at t=30 seconds. I can
> also press it myself: Shift-C."

## 1:30 — The crash (45 seconds)

At t=30s the lever lands. An amber line and flag appear on the chart, and the
strip's headline switches from "—" to the crash number.

> "The makers just de-risked. They shrank, they pulled their limits in, and
> they backed away from the touch. Nobody told the price to fall."

Watch it happen:
- The **depth map thins** — the bands fade, the spread tiles climb (it peaks at
  well over a hundred ticks)
- The **mid tears downward** — a shaded box measures it: **107.5 ticks in five
  seconds** on this seed
- The **tape goes one-sided** red
- The numbered markers on the price line, and the key beside them ("What the
  engine did"), narrate it in order: both makers hit their hard limits, the
  momentum traders reach their caps, the biggest sweep, depth bottoming out, the
  spread peaking
- The strip chip flips *Stable → Dislocated*; the book stays **two-sided** — this
  is a crash, not a halt

> "That drop is 3.8× larger than the worst five-second move the market made on
> its own in the fifteen seconds before. The shock is scripted; the fall isn't.
> The same seed with no lever goes *up* 58 ticks in those five seconds."

Who sold? Point at the agents table, **Sold after lever** column: on this seed
most of the aggressive selling is ordinary noise flow hitting an empty book. The
three momentum traders sell less, but they feed the trend, and every one ends
at its position cap.

> "Take the three momentum traders out and the same seed moves 30 ticks, 1.5×
> normal, not 107. They aren't the main source of selling; they're the
> amplifier."

## 2:15 — It's reproducible, exactly, and you can go back (30 seconds)

> "Every run is byte-identical from its seed. Same seed, same event log, down
> to the byte — verified in CI across separate processes with different hash
> seeds."

> "Including this: if I perturb it live, by hand, the run is *still* exactly
> reproducible. The perturbation goes into the event log with its ordering key,
> and re-simulating from that log reproduces the run byte-for-byte. That took a
> real fix — perturbations get their own sequence counter, otherwise a live
> insertion silently shifts every later event."

Pause (Space) or let the run finish, then click the timeline at the bottom: the
whole screen shows the market as it was at that moment, labelled **Replay**.
Esc goes back to live.

## 2:45 — Where it goes (15 seconds)

> "Phase 1 is this: a correct, fast, deterministic engine, agents whose
> interaction produces real market statistics, and a live instrument to watch
> it in. Phase 2 replaces the hand-written market maker with a reinforcement-
> learning one and asks whether it learns to trade — or just learns to exploit
> my simulator. The design note for that is written before any training code."

---

## If something goes wrong

| Symptom | Do this |
|---|---|
| `Feed lost` in the header | The server exited; restart `uv run marquee-demo` |
| Blank panels, `Awaiting feed` | First frame not arrived yet; ≤1 second |
| `Run complete` | 60 sim-seconds elapsed; restart for a fresh run (click the timeline to review it first) |
| Want the crash sooner | The speed buttons in the bottom bar (up to 8×), or pause |
| Reloaded the page mid-run | It backfills the whole run from the server; nothing is lost |

## Talking points if asked

- **"Did you just pick a seed that crashes?"** Yes, and the repo says so. Across 30
  seeds the lever roughly doubles the next 5-second move (median 65 vs 27 ticks,
  bigger on 23 of 30), but the direction follows the order flow: on 14 seeds the
  price spikes up instead. 777002 is the deepest fall of the 30. The defensible
  claim is "pulling maker liquidity amplifies dislocations", and
  `docs/SEED_SWEEP.md` plus `pytest -m slow` back it.

- **"Is the engine actually correct?"** Property-based test suite: price-time
  priority, the maker-price rule, share conservation across fills, no crossed
  book, cancel semantics — checked against a shadow book rebuilt purely from
  engine outputs, over randomized operation sequences.
- **"Is it fast?"** 406k messages/sec through the book; 35k events/sec for the
  full loop including agents and JSONL recording (on battery).
- **"Is the number on screen the number in the tests?"** Yes. The bridge samples
  the mid on the same 100 ms grid as the committed crash gate, and a test asserts
  the two series are identical, so the headline (107.5 ticks, 3.8×) is the one CI
  asserts.
- **"Why does the crash need the spread blow-out?"** Because makers re-quote
  every 10–15ms. Thinning size alone self-heals faster than any momentum
  lookback can see. Liquidity has to *retreat*, not just shrink — which is what
  actually happens in real dislocations.
