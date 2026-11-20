# DESIGN.md — marquee visual system (v3, "departure board")

Supersedes v1 (green terminal) and the v2 amendments. Decision record: ADR-018.
Design canvas (static boards built from a real seeded run):
https://claude.ai/artifact/GYXCs4fpaYsD6xqQr1ybzu

## Direction: a departure board for a market

An instrument you can watch from across a room. The figures a room must read flip on
split-flap tiles. Labels are signage: condensed capitals. Panels butt together on 1 px
seams the way TradingView and exchange terminals pack a screen. Nothing decorative:
every pixel is data, a label for data, or a seam.

Two rules decide most arguments:

1. **Amber means one thing: a human changed a rule here.** The lever, the lever line,
   the scheduled-change table, the amber tick on a sparkline. Never a warning, never
   decoration.
2. **No dead controls.** A tab, button, menu or shortcut hint is drawn only if it works.
   Unbuilt pages do not appear in the nav.

## Tokens (CSS variables in `viz/app/globals.css` — the only place colors and type live)

| Token | Value | Use |
|---|---|---|
| `--color-gutter` | `#0e0e0d` | page, the 1 px seams |
| `--color-panel` | `#171614` | panel surface |
| `--color-tile` | `#24231f` | split-flap tiles, selected rows, empty bars |
| `--color-seam` | `#2e2d29` | all rules |
| `--color-ink-1` | `#edebe6` | figures, primary text |
| `--color-ink-2` | `#b4afa6` | labels, secondary text (8.3:1 on panel) |
| `--color-ink-3` | `#8c887f` | marks and tertiary (5.1:1 on panel) |
| `--color-bid` | `#3fb8a4` | bids, buys, up (7.4:1) |
| `--color-ask` | `#ef7a6f` | asks, sells, down (6.6:1) |
| `--color-amber` | `#e3a84a` | human hand (8.6:1) |

Bid and ask are never the only carrier of direction: ▲▼ and signs always accompany.

## Type

- **Barlow Semi Condensed 600/700, uppercase, +0.06em** — signage: labels, tabs, buttons, chips.
- **Barlow 400/500** — prose and plain-English subtitles.
- **B612 Mono 400/700** — every figure and the tiles. Drawn for Airbus cockpit
  displays; no digit is mistaken for another and nothing shifts as values change.
- **Minimum size 11 px.** Figures 12 px in rows, 14 px in the strip, 17 px for the mid tiles.

## Structure

Header 40 px · stat strip 56 px · body (chart | book 280 | lever + tape 280, agents
table beneath the chart 196) · transport 40 px. Tab row 30 px, data rows 20 px, 10 px
padding, 1 px seams. The page never scrolls.

The stat strip carries one headline for the crash (**peak move since the lever, in 5 s,
and its multiple of the worst normal 5 s**) then supporting figures, each with a
plain-English subtitle. Expert term as label, plain version beneath.

## The headline number

Measured exactly as the committed crash gate measures it (`tests/test_m5_crash.py`):
the bridge samples the mid on the 100 ms grid and the client computes the move over
the 5 s after the lever and the worst-normal range over the 15 s before it. At the
committed seed this is ▼ 107.5, 3.8×. It is derived from the feed, never hard-coded,
so a lever pulled at any other time gets its own honest number.

## Chart

Depth map (teal bids, coral asks, brighter = more size) under the mid line; dashed VWAP;
the amber lever line and flag; a TradingView-style range box measuring the drop;
numbered engine events on the line with a key ("What the engine did"); O/H/L/C legend;
right axis with last-price and VWAP pills; volume and net-taker-flow pane. One canvas,
redrawn at 10 Hz from a ref. Flat fills and 1 px lines only.

## Motion

Performance budget: no shadow, blur, glow or gradient anywhere.
1. A split-flap tile turns once (120 ms) when its digit changes. Tiles update at ~4 Hz.
2. Changed figures in the book and tape flash their semantic color, 300 ms linear decay.
3. Nothing else moves. `prefers-reduced-motion` disables both.

## States

Never blank. *Awaiting feed* before the first frame. *Feed lost* with the restart
command. *Paused*, *Run complete* (lever disabled). *Calm*: stat strip reads "lever
fires in N s", the chart shows a pending lever note. *One-sided book*: the missing side
reads "no bids" / "no asks" and the spread shows "one-sided". A page that joins after
the lever shows "—" for the headline rather than a wrong number.

## Primitives (`viz/components/primitives.tsx`; styling lives here and nowhere else)

`Lb` signage label · `Panel` (tab row, seam) · `Num` (flashing figure) · `Tiles`
(split-flap) · `Btn` (ghost / on / amber / seg / off, with a real shortcut hint) · `Chip` ·
`Stat` (label, figure, subtitle) · `StatusDot` · `Glyph` · `VoidState`.

## Built and not built

Built: **Live**; **Replay** as timeline scrubbing (click the bottom timeline while paused
or finished; the screen shows that moment, read-only, labelled Replay; Esc returns); and
**Learn**, a header toggle that swaps every label for its plain-English name (the trader's
term moves to the subtitle) and starts a five-step guided tour that outlines one panel at a
time, with live numbers in the card.
Designed, not built: Lab, Evaluation (waits for the M7 harness), the narrow watch-only
view, the no-lever counterfactual line.
See PROGRESS.md.
