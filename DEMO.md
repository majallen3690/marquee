# DEMO.md — the 3-minute walkthrough

One command, one browser tab, one crash.

```
uv run marquee-demo
```

Serves the built front end and the live feed at http://127.0.0.1:8420/ and opens
it. (`--scenario`, `--port`, `--no-browser` available; the default scenario is
the committed `m5-flash-crash.yaml`, seed 777002.)

---

## 0:00 — What this is (20 seconds)

> "This is a market-microstructure sandbox. Everything on screen comes out of a
> limit order book and matching engine I wrote from scratch, plus eleven trading
> agents that only see what a real participant sees — the book, their own fills,
> their own inventory. Nothing about the price is scripted."

Point at the three panels: **book ladder** (right), **price** (center),
**tape** (bottom). Note the header: scenario name, sim clock, LIVE.

## 0:20 — The market is alive and nobody is driving (40 seconds)

Let it run. Talk over it:

> "Two market makers quote both sides and manage inventory. Three momentum
> traders chase trends. Six noise traders supply and take liquidity at random.
> Price discovery is entirely emergent — no agent knows a 'true' price."

Point at the ladder: depth bars breathing, spread holding ~1 tick, the mid
flashing on every change. Point at the tape: green/red flow.

> "And it isn't just alive, it's *realistic*. This population reproduces four
> stylized facts of real markets — fat-tailed returns, volatility clustering,
> no linear predictability, and long-memory order flow. That's the M4
> calibration suite, thresholds defended against the empirical literature."

## 1:00 — The lever (30 seconds)

Move to the **CONTROLS** dock on the left. Show the market-maker inventory
limit slider.

> "Here's the interesting part. I can reach into one agent class mid-run.
> This is the market makers' risk appetite — their inventory limits, their
> quote size, how far from the touch they're willing to quote."

> "In the committed scenario this fires automatically at t=30 seconds. Watch
> the price panel."

## 1:30 — The crash (45 seconds)

At t=30s the perturbation lands. An amber `PERTURB` rule appears on the chart.

> "The makers just de-risked. They shrank, they pulled their limits in, and
> they backed away from the touch. Nobody told the price to fall."

Watch it happen:
- The **ladder thins** — depth bars collapse, the spread blows out
- The **mid tears downward** — 107 ticks in five seconds on this seed
- The **tape goes one-sided** red as momentum traders pile in
- The market **stays two-sided** — this is a crash, not a halt

> "That drop is 3.8× larger than the worst five-second move the market made on
> its own in the previous thirty seconds. And it's not scripted — it's forced
> unwinds hitting a book that just got thin, amplified by trend-followers.
> Remove the momentum traders and it doesn't happen."

## 2:15 — It's reproducible, exactly (30 seconds)

> "Every run is byte-identical from its seed. Same seed, same event log, down
> to the byte — verified in CI across separate processes with different hash
> seeds."

> "Including this: if I perturb it live, by hand, the run is *still* exactly
> reproducible. The perturbation goes into the event log with its ordering key,
> and re-simulating from that log reproduces the run byte-for-byte. That took a
> real fix — perturbations get their own sequence counter, otherwise a live
> insertion silently shifts every later event."

Optionally: drag the slider yourself and watch the regime change again.

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
| `FEED LOST` in the header | The server exited; restart `uv run marquee-demo` |
| Blank panels, `AWAITING FEED` | First frame not arrived yet; ≤1 second |
| Run says `COMPLETE` | 60 sim-seconds elapsed; restart for a fresh run |
| Want the crash sooner | `--speed` in the UI (up to 50×), or pause and step |

## Talking points if asked

- **"Is the engine actually correct?"** Property-based test suite: price-time
  priority, the maker-price rule, share conservation across fills, no crossed
  book, cancel semantics — checked against a shadow book rebuilt purely from
  engine outputs, over randomized operation sequences.
- **"Is it fast?"** 406k messages/sec through the book; 35k events/sec for the
  full loop including agents and JSONL recording (on battery).
- **"Why does the crash need the spread blow-out?"** Because makers re-quote
  every 10–15ms. Thinning size alone self-heals faster than any momentum
  lookback can see. Liquidity has to *retreat*, not just shrink — which is what
  actually happens in real dislocations.
