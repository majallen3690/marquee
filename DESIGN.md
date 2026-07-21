# DESIGN.md — marquee visual system

Recorded as ADR-016. Binding for all M5+ UI work. Styling lives ONLY in the
primitives listed at the bottom; screens compose primitives and never restyle.

## Direction: instrument, not dashboard

The benchmark object is a scientific/trading instrument — a Bloomberg keyboard,
an oscilloscope, a TT ladder — not a SaaS dashboard. One dense, full-viewport
screen. Panels are separated by hairline rules, never floating cards. Nothing
has a border radius. Nothing has a drop shadow. Nothing bounces. The interface
is judged by how it looks while *numbers are moving through it*.

The one thing a viewer should remember: **a wall of calm green/red figures, and
the moment the wall tears** — the flash crash arriving as a visible regime
change in an instrument that until then looked bored.

## Color tokens (CSS variables, dark only — instruments have one face)

```css
--bg-0:      #0B0F0D;  /* page — near-black with a cold phosphor cast */
--bg-1:      #101512;  /* panel interior */
--bg-2:      #161D19;  /* hover / selected row */
--hairline:  #1E2A24;  /* ALL borders. 1px. No other border color exists. */
--text-1:    #D6E2DA;  /* primary figures */
--text-2:    #5C6E64;  /* labels, axes, secondary */
--text-3:    #33413A;  /* faint — grid lines, disabled */
--bid:       #33E087;  /* bids, up-ticks. Fill variant: 18% alpha. */
--ask:       #F4544C;  /* asks, down-ticks. Fill variant: 18% alpha. */
--accent:    #FFB454;  /* amber — interaction, cursor, perturbation, alerts.
                          The ONLY non-semantic color. Use sparingly. */
```

Rules: no gradients anywhere; no purple/indigo ever; green/red are reserved for
market semantics (never for buttons or status); amber marks the human's hand —
controls, the perturbation lever, the crash marker on the chart.

## Typography

One family: **IBM Plex Mono** (self-hosted via @fontsource — the demo must work
offline). Terminal-true: every character the UI renders is tabular by nature.
Hierarchy comes from size, weight, and case — never from a second family.

| Role | Size/weight | Notes |
|---|---|---|
| Mid price (ladder center) | 22px / 600 | the largest number on screen |
| Panel figures | 13px / 400 | default data size; 20px row height |
| Dense figures (tape, depth) | 12px / 400 | 18px row height |
| Micro-labels | 11px / 500 | UPPERCASE, +0.08em tracking, --text-2 |
| Axis / meta | 10px / 400 | --text-2 |

Wordmark: `MARQUEE` 13px/600, +0.2em tracking, with the `Q` in --accent.
Direction glyphs are text (`▲ ▼ ·`), never emoji (banned by the brief).

## Spacing & structure

4px base grid; panel padding 12px; ladder/tape rows 20px/18px. Full-viewport
CSS grid, **no page scroll**:

```
┌──────────────────────────────────────────────────────────┐ 28px header
│ MARQUEE   m5-flash-crash   SIM 00:31.204   ● LIVE  1.0×  │
├──────────┬────────────────────────────────┬──────────────┤
│ CONTROLS │ PRICE                          │ BOOK         │
│ AGENTS   │ (canvas chart, flex)           │ (ladder,     │
│ 232px    ├────────────────────────────────┤  296px)      │
│          │ TAPE (140px)                   │              │
└──────────┴────────────────────────────────┴──────────────┘
```

## Motion rules (restraint is the aesthetic)

1. Data never animates position. Numbers change instantly.
2. A changed price/qty cell flashes its semantic color at 25% alpha and decays
   linearly over 300ms. This is the heartbeat of the whole interface.
3. Controls: 100ms linear background change on hover. No easing curves, no
   transforms, no scale effects.
4. The chart draws continuously; the perturbation moment gets a 1px amber
   vertical rule with a `PERTURB` tag — the only annotation.
5. Nothing else moves. If it isn't rule 1–4, it doesn't animate.

## The ladder (the product)

Center-out layout: asks stack upward above the spread row, bids downward below.
Columns: `depth bar+qty | price | cum`. Depth bars grow horizontally from the
qty edge in 18%-alpha semantic fill; the bar IS the data visualization — no
separate depth chart. The spread row between sides carries mid (22px), spread
in ticks, and last-trade direction glyph. Price column right-aligned, qty
right-aligned, all tabular. Empty side: `— NO BIDS —` in --text-2 (a designed
state; the flash crash makes it real).

## States

Loading/disconnect: full-panel `AWAITING FEED` / `FEED LOST`, 11px tracked
uppercase --text-2, centered. Done: `RUN COMPLETE — t=60.000s`. Never blank.

## Primitives (build these first; styling lives here ONLY)

`Panel` (hairline frame + micro-label header) · `Num` (formatted figure,
semantic coloring, flash-on-change) · `MicroLabel` · `TermButton` ·
`TermSlider` (perturb lever) · `StatusDot` · `Glyph` (▲▼·)

Screens compose these. A screen file containing a raw hex color or font-size
is a review failure (the brief's known failure mode — enforced at the M5 gate).
