# RL_DESIGN.md — Phase 2 design note (M6)

**Status: signed off by the author 2026-11-20. ADR-023 amends it: the gate is scored in `scenarios/m7-makers.yaml` (the M5 population without the lever) and must also beat the best fixed quoting rule.**
Binding decisions are mirrored into DECISIONS.md as ADR-017.

---

## 0. Thesis

> Most degeneracies in RL market making are conventionally fought with reward
> penalties. Penalties are negotiable — the optimizer looks for the cheapest way
> to satisfy them. **Wherever a degeneracy can be removed by construction — from
> the action space, the environment's rules, or the accounting — this design
> removes it there, and uses reward shaping only for what is left.**

Everything below follows from that. The reward function is deliberately the
*small* part of this note; the action space and the P&L accounting are the
load-bearing parts.

## 1. Scope

Phase 2 trains **one** learning agent: a market maker that replaces one of the
two rule-based market makers (`InventoryMarketMaker`, ADR-012) in an otherwise
unchanged population. Momentum and noise traders stay rule-based.

**Why one learning agent.** The credible claim for this project is "a learned
market maker beats a hand-written one on risk-adjusted P&L without cheating."
Making every class learn multiplies the non-stationarity problem, multiplies the
compute, and makes any negative result uninterpretable — you cannot tell whether
the market maker failed or the environment moved under it. A minimal shared
observation base is specified in §12 so a learning momentum trader is a small
increment later, but it is explicitly out of scope for M7/M8.

## 2. The market-making problem, precisely

At each decision step the agent chooses where and how large to quote on both
sides of the book. It earns the spread when both sides fill, and loses when the
price moves against inventory it is holding. Formally, over an episode of `T`
steps it maximizes risk-adjusted terminal wealth

```
W_T = c_T + q_T · m_T^liq
```

where `c` is cash in tick-units, `q` is signed inventory in units, and
`m^liq` is the price actually obtainable by liquidating `q` against the book
(§5) — not a free mark.

The tension is the whole problem: quoting tighter and larger increases spread
capture *and* increases inventory accumulated against adverse moves. A market
maker that ignores inventory is a directional speculator wearing a costume; a
market maker that refuses inventory does not trade.

### 2.1 The regime this market is actually in

The calibrated market (ADR-013) has a **median quoted spread of 1 tick** with
~150 units of L1 depth per side and ~42 trades/sim-second. This is the
*tick-constrained* regime, and it has three consequences that shape every choice
below:

1. **The edge is thin.** One tick per round trip is the floor and usually the
   whole prize. Adverse selection can erase it in one bad fill.
2. **Queue position dominates.** With everyone at the same price, *when* you
   joined decides whether you fill. Price-time priority is exact in this engine,
   so this is simulated correctly — which means queue position must be
   observable to the agent (§3), or it is choosing blind.
3. **The no-trade degeneracy is maximally attractive.** When the edge is one
   tick, "don't play" is a genuinely competitive strategy against a naive
   reward. Hence the structural obligation in §4.

## 3. Observation space

All features are **stationary and relative**. No absolute price, no wall-clock,
no seed, no other agent's private state. A policy that sees absolute price
memorizes a price level and fails on held-out scenarios; a policy that sees
another agent's inventory has learned something no real participant can observe.

| Group | Features | Dims |
|---|---|---|
| Book shape | For 5 levels per side: price offset from that side's best (ticks, /10) and `log1p(qty)` scaled | 20 |
| Touch | Spread (ticks, /10); own bid offset from best bid; own ask offset from best ask; **queue-ahead fraction at own bid and at own ask** | 5 |
| Own state | `q/q_max`; unrealized P&L (scaled); realized P&L this episode (scaled); fraction of episode remaining | 4 |
| Flow | Realized volatility over last N steps; trade-sign imbalance over last N; trade arrival rate; mid drift over last N (ticks, clipped) | 4 |

**≈33 dims**, each clipped to roughly [−1, 1].

**Queue-ahead requires new engine plumbing** (M7 work item): resting quantity
ahead of a given order id at its level. The engine's per-level FIFO deque makes
this a linear scan of one level — acceptable off the hot path, computed only for
the learning agent's two orders per decision step.

**Deliberately excluded, and why:**
- *Absolute price / price level* — non-stationary; invites memorization.
- *Wall-clock and sim epoch time* — see degeneracy D6 (schedule memorization).
- *Other agents' inventories, parameters, or identities* — unobservable in a
  real market; would let the policy learn "MM #2 is about to unwind."
- *The perturbation schedule* — the agent must react to a crash it can observe,
  never to a clock it has memorized.

## 4. Action space — where most degeneracies die

**MultiDiscrete, three independent heads, one quote update per decision step.**

| Head | Values | Meaning |
|---|---|---|
| `bid_offset` | 9: {−2,−1,0,1,2,3,4,6,8} | Ticks relative to best bid. 0 = join; negative = improve (inside the spread); positive = rest behind. |
| `ask_offset` | 9: same set | Mirrored on the ask. |
| `size` | 3: {0.25, 0.5, 1.0} × base | Quote size, applied to both sides. |

21 logits total. Quotes are clamped to stay uncrossed and ≥ 1 tick. The previous
step's quotes are cancelled and replaced — exactly one quote update per step, by
construction.

**What this action space makes *impossible*, not merely unattractive:**

| Removed | How |
|---|---|
| No-trade / quote-withdrawal | There is no "don't quote" action. Two-sided quoting every step is mandatory. |
| Unbounded spread blow-out | Max offset is 8 ticks. The agent cannot quote at infinity. |
| Inventory dumping | **There is no taker action.** The policy cannot send market orders. Inventory is managed only by skewing and sizing quotes — the Avellaneda–Stoikov formulation, and what real market makers actually do. |
| Order spam / churn | One quote update per step is structural; there is no message-rate lever to abuse. |
| Quote-stuffing the mid | Marking uses an own-order-excluded mid (§5). |

**Is the mandatory two-sided quote defensible, or is it cheating?** It is a
*designated market maker obligation*, and it is what real venues require: NYSE
DMMs and Nasdaq registered market makers carry affirmative two-sided quoting
obligations with maximum-spread and minimum-size terms. Modelling the agent as a
DMM rather than a voluntary liquidity provider is a modelling choice, stated
plainly, and it is the same regime the rule-based baseline plays in — so the
comparison stays fair.

**Risk control is the environment's job, not the policy's.** At `|q| ≥ q_max`
the environment force-liquidates the excess at market — *identical to the
rule-based MM's hard-limit rule (ADR-012)*, so both compete under the same risk
constraints. Because it is an environment rule rather than an action, the agent
cannot elect to dump; it can only avoid reaching the limit.

## 5. P&L accounting — the reward substrate

Let `q_t` = signed inventory, `c_t` = cash (tick-units), and `m_t` = the
**reference mid computed from the book with the agent's own resting orders
removed**. Mark-to-market wealth `W_t = c_t + q_t·m_t`, and the step change
decomposes exactly:

```
ΔW_t  =  [ c_t − c_{t−1} + (q_t − q_{t−1})·m_t ]  +  [ q_{t−1}·(m_t − m_{t−1}) ]
      =              S_t  (spread capture)         +        I_t  (inventory P&L)
```

`S_t` is what you earned by transacting away from the mid; `I_t` is what the
market did to the position you were already holding. This split is the basis of
both the reward (§6) and the "did it learn to make markets or to speculate?"
evaluation (§8).

**Three accounting rules that close exploits:**

1. **Own-order-excluded mid.** If `m` were the raw book mid, the agent could
   post a one-lot far from the touch to shift the quoted mid at marking time and
   manufacture unrealized P&L. Excluding its own resting orders removes the
   channel entirely. (Marking to last-trade instead is *worse* — a single
   one-lot print sets it.)
2. **Self-trade policy = `CANCEL_RESTING`** for all RL scenarios. The enum has
   existed since ADR-009 rule 5, put there for exactly this milestone. Wash
   volume cannot be manufactured, so no volume- or flow-based term can be gamed.
3. **Terminal liquidation is real.** At episode end, remaining inventory is
   liquidated by walking the book, and `W_T` uses the price actually obtained.
   Marking terminal inventory at mid would pay the agent for a position it never
   had to exit.

## 6. Reward

Per decision step, in tick-units, scaled so a full-size round trip at one tick
of edge is ≈ 1.0:

```
r_t  =  S_t  +  ( I_t − η·max(0, I_t) )  −  γ·(q_t / q_max)²
```

**Term by term:**

- `S_t` — spread capture. The thing we actually want maximized.
- `I_t − η·max(0, I_t)` — **asymmetrically dampened inventory P&L**
  ([Spooner et al., 2018](https://arxiv.org/pdf/1804.04216)). Losses from
  holding are kept in full; *gains* from holding are damped by `η`. This
  deliberately breaks the symmetry that makes directional betting look
  attractive: the agent keeps all the downside of a position and only
  `(1−η)` of the upside, so accumulating inventory as a bet is
  negative-expectation while accumulating it *incidentally, as a consequence of
  providing liquidity* remains fine. Baseline `η = 0.5`; `η = 0` recovers plain
  P&L (speculation-prone), `η = 1` removes all reward for holding gains.
- `−γ·(q_t/q_max)²` — running quadratic inventory penalty, normalized so `γ` is
  scale-free.

**On `γ` calibration.** The classic failure is a `γ` so large that shedding
inventory at any cost beats holding it. In this design the usual escape hatch
(market-order dumping) does not exist, so a miscalibrated `γ` cannot produce a
spread-paying churn machine; it manifests instead as *over-defensive, heavily
skewed quoting with a collapsed fill rate on one side* — which detector **G3**
and the per-side fill-rate metric catch directly. `γ` is swept in M7 over a
range whose upper bound is set by requiring the per-episode holding penalty at
typical inventory to stay below the round-trip cost of that inventory, and the
chosen value is reported with the sweep, not asserted.

**The reward is a shaped training signal; it is not the evaluation metric.**
The gate (§9) is *unshaped* risk-adjusted P&L. Optimizing a shaped proxy and
scoring on the true objective is the point — and stating it forecloses the
"you graded yourself on your own curve" objection.

## 7. Anti-degeneracy analysis

Each degeneracy: the mechanism, why the optimizer finds it attractive, the
mitigation, and the automated detector that fires if the mitigation fails.

### D1 — No-trade equilibrium
**Mechanism.** With reward `≈ P&L − inventory penalty`, never quoting yields
exactly 0 with zero variance. Any trading carries risk of negative reward, so 0
is a strong local optimum. This is not speculative: it is a *documented* result
that reward families not normalized by traded volume admit "never trade" as the
optimal policy, and this market's one-tick edge (§2.1) makes it especially
tempting.
**Mitigation (structural).** No quote-withdrawal action exists (§4); two-sided
quoting is mandatory every step. The degenerate policy is not merely
disincentivized, it is unreachable.
**Detector G1.** Fill rate ≥ 25% of the rule-based MM's fill rate on the same
scenario. **G2.** Two-sided quoting on ≥ 99% of steps.

### D2 — Spread blow-out
**Mechanism.** Quote as wide as allowed; fill rarely but at large edge; carry
almost no inventory. Degenerate because it is nominally a market maker while
providing no useful liquidity.
**Mitigations.** (a) Offsets are capped at 8 ticks — severity is bounded by
construction. (b) **Competition does the rest**: the rule-based market makers
remain in the population at every curriculum stage, so a wide-quoting RL agent
simply cedes all flow to them and earns ≈ 0. The population, not a penalty
term, punishes this.
**Detector G3.** Median own quoted spread ≤ 2× the rule-based MM's median on
the same scenario.

### D3 — Inventory dumping
**Mechanism.** Accumulate, then market-order it away to escape the inventory
penalty — paying real spread cost to dodge a synthetic one. Classic symptom of
`γ` miscalibration.
**Mitigation (structural).** **The policy has no taker action** (§4). The only
liquidation channel is the environment's hard-limit rule, which is identical for
the rule-based baseline. Dumping is not a strategy the policy can select.
**Detector G4.** Maker share of own executed volume ≥ 80% (forced liquidations
are the only taker volume, and they should be rare).

### D4 — Reward hacking via self-trades and simulator exploits
**Mechanisms and closures**, each specific:

| Exploit | Closure |
|---|---|
| Self-trading to manufacture volume | `SelfTradePolicy = CANCEL_RESTING` (§5.2). **Detector G5: self-trade volume ≡ 0.** |
| Posting a far-away lot to move the marking mid | Own-order-excluded mid (§5.1) |
| Holding inventory to the buzzer and marking it at mid | Terminal liquidation walks the book (§5.3) |
| Cancelling competitors' orders | Already closed at the kernel: cancels of another agent's order return `UNKNOWN`, indistinguishable from a bogus id (ADR-011) |
| Message-rate abuse | One quote update per step, structural (§4) |
| Overfitting the fixed latency constants | Latency randomized ±50% across training episodes; ablation A1 re-tests at held-out latency |
| Floating-point / tick-boundary artifacts | Engine is integer-only end to end (ADR-004); no epsilon surfaces exist to exploit |

### D5 — Collapse under self-play non-stationarity
**Mechanism.** When the opponent is itself learning, the environment moves under
the policy; policies chase each other and cycle, or drift jointly into mutual
quote-widening. Standard self-play cycles precisely because agents forget how to
play earlier versions of themselves.
**Mitigations.** (a) **The rule-based population is a permanent stationary
anchor** — it is present at every stage and never learns, so total joint drift
is bounded by agents that will not move. (b) Adaptive opposition is introduced
only as **frozen checkpoints**, never a second simultaneously-learning agent.
(c) Stage 3 uses **prioritized fictitious self-play** — sample opponents from a
pool of past checkpoints rather than only the newest, which is the standard cure
for cycling. (d) Evaluation is always against a **fixed held-out population**,
so measured progress is real progress and not a treadmill artifact.
**Detector G8.** Performance against the *frozen Stage-1 population* must not
degrade as later stages train — the canonical forgetting signature.

### D6 — Memorizing the scenario script (project-specific)
**Mechanism.** M8 puts the trained agent into the flash-crash scenario, where
the perturbation fires at exactly t=30 s. An agent trained on that scenario can
learn "at step 300, go defensive" — a memorized clock, not a learned response.
It would look spectacular in the demo and mean nothing.
**Mitigations.** (a) Episodes are **randomly offset windows** of the scenario,
so a given sim time never lands at a fixed step index. (b) Perturbation timing
and magnitude are **randomized during training**. (c) The observation exposes
only *fraction of episode remaining*, never absolute sim time. (d) Evaluation
uses **held-out perturbation times** never seen in training.
**Detector G9.** Performance on held-out perturbation times within 25% of
performance on trained ones. A memorizer collapses; a responder does not.

### D7 — Memorizing the seeded order flow (project-specific)
**Mechanism.** Every rule-based agent is deterministic given its identity-keyed
stream (ADR-006). Train on a fixed seed set and the policy can memorize the
literal order flow rather than learn a policy — the RL equivalent of
training on the test set. Easy to do by accident, and it would inflate every
number in this project.
**Mitigation.** Master seed randomized per episode from a large training seed
pool; evaluation uses a **disjoint held-out seed set**, fixed and committed.
**Detector G10.** Mean episode P&L on held-out seeds within 25% of training
seeds.

## 8. Evaluation — "learned to trade" vs "exploited the simulator"

### 8.1 Baselines it must be scored against
1. **Rule-based `InventoryMarketMaker`** — the thing to beat (the gate).
2. **Do-nothing** (minimum-size, maximum-width quotes) — if the RL agent ≈ this,
   it learned nothing.
3. **Random quoting** — sanity floor.
4. **Fixed-width quoting at each of several widths** — the spread blow-out
   reference curve.
5. *(Optional, cheap)* **Tile-coded SARSA** in the Spooner formulation — a
   classical baseline that costs almost nothing to run and makes "did deep RL
   actually buy anything?" answerable.

### 8.2 Degeneracy detectors (all automated; any trip fails the gate)

| ID | Check |
|---|---|
| G1 | Fill rate ≥ 25% of rule-based MM's |
| G2 | Two-sided quoting on ≥ 99% of steps |
| G3 | Median quoted spread ≤ 2× rule-based MM's |
| G4 | Maker share of own volume ≥ 80% |
| G5 | Self-trade volume ≡ 0 |
| G6 | **Directional P&L share ≤ 40%** — `Σ I_t / Σ|ΔW_t|`. A market maker earns from spread capture; a speculator earns from `I`. |
| G7 | Inventory mean-reverts — `|q|` autocorrelation half-life below threshold |
| G8 | No degradation vs frozen Stage-1 population as training proceeds |
| G9 | Held-out perturbation times within 25% of trained ones |
| G10 | Held-out seeds within 25% of training seeds |

### 8.3 Ablation battery — the exploitation test

The core intuition: **a genuine skill transfers; a simulator exploit does not.**
Re-run the *trained, frozen* policy with one thing changed at a time. A P&L
collapse of >50% on any of these is evidence the policy was leaning on that
specific artifact rather than on market making:

| ID | Perturbation |
|---|---|
| A1 | Latency ±50% |
| A2 | Held-out seed set |
| A3 | Self-trade policy flipped to `REJECT_TAKER` |
| A4 | Population composition ±1 momentum trader |
| A5 | Marking rule changed (own-excluded mid → last-trade) |
| A6 | Base quote size halved |

A5 deserves emphasis: if P&L depends on *how we mark*, the P&L was never real.

### 8.4 P&L attribution
Every evaluation reports the `S` / `I` decomposition from §5. The headline
sentence we want to be able to write — and to have earned — is: *"N% of the
learned agent's P&L is spread capture, versus M% for the rule-based baseline."*

## 9. The M7 gate (restating the brief in measurable terms)

The trained market maker beats the rule-based market maker on **risk-adjusted
P&L** — mean episode P&L divided by its standard deviation — across **≥ 20
held-out seeds** in the calibrated scenario, **with zero degeneracy detectors
tripped (G1–G10) and no ablation collapse (A1–A6)**.

Reported alongside, always: the full detector table, the ablation table, the
P&L attribution, and the raw distributions — not just the ratio.

## 10. Algorithm

**PPO** (clipped objective, GAE), small MLP: 2 hidden layers × 64 units,
separate policy and value heads, three independent categorical heads over the
`MultiDiscrete` action.

**Why.** On-policy and stable under mild non-stationarity, which matters because
the opponent population changes between curriculum stages. No replay buffer, so
memory stays small on a consumer machine. Native `MultiDiscrete` support.
Hyperparameters are widely understood, which matters for a solo developer whose
debugging budget is finite.

**Rejected.** *DQN/Rainbow* — replay buffer memory, awkward with factored action
spaces, and off-policy staleness interacts badly with a shifting opponent
population. *SAC* — continuous-action-first, more machinery for no benefit given
a discrete quote grid. *Tabular / tile-coded Q-learning* — genuinely viable here
and retained as a *baseline* (§8.1.5), but it caps representational capacity for
the richer observation of §3.

## 11. Curriculum

| Stage | Population | Purpose | Stationary? |
|---|---|---|---|
| 0 | Noise + momentum only, no competing MM | Learn to quote and hold inventory at all | Yes |
| 1 | **Full calibrated population, both rule-based MMs present** | Learn to compete for flow — *this is the gate scenario* | Yes |
| 2 | One rule-based MM replaced by a **frozen checkpoint** of the trained agent | Adaptive opposition, without a moving target | Yes (opponent frozen) |
| 3 *(stretch)* | Prioritized fictitious self-play over a checkpoint pool | Robustness against a strategy distribution | No |

Rule-based agents are present in **every** stage (D5 anchor). Stage 3 is
explicitly a stretch goal: the project's claim rests on Stage 1, and if Stage 3
destabilizes, Stage 1's result stands on its own.

## 12. Other agent classes (deferred, interface only)

If a learning momentum trader is added later it reuses the §3 observation base
minus market-maker-specific fields, with a directional action space
`{buy, hold, sell} × size`, an unchanged P&L substrate (§5), and a position
limit mirroring `max_position` from ADR-012. **It is not in M7 or M8 scope**, for
the reason in §1: a second learner makes a negative result uninterpretable.

## 13. Compute budget

Measured, not guessed, from this repo:
- Full loop ≈ **35,000 events/wall-second** (M2 gate, on battery).
- The M5 live run showed **106,844 events at sim t=49.1 s ≈ 2,175
  events/sim-second**.
- → roughly **16× real-time** per environment.

A 30-sim-second episode with 100 ms decision steps = **300 decisions ≈ 1.9
wall-seconds** of simulation. Policy inference (2×64 MLP, 300 forward passes) is
negligible beside ~65k engine events. With 6 parallel environments,
**1M steps ≈ 20–60 minutes** depending on Python overhead.

That is comfortably an overnight-between-sessions budget with room to spare, but
**M7 begins by measuring it rather than trusting this arithmetic**, and sizes the
run to what it finds. Every run checkpoints and is resumable (the brief's
constraint: long runs happen between sessions).

## 14. Open risks, stated honestly

1. **The one-tick spread may leave too little edge to learn from.** If spread
   capture is dominated by queue-position luck, the learning signal is thin and
   PPO may not separate from the baseline. Contingency: a scenario variant with
   a larger tick size (wider relative spread) as a *diagnostic*, reported as
   such and never swapped in for the gate.
2. **The rule-based baseline may be weak.** Beating a bad baseline proves
   nothing. Mitigation: the baseline is the same agent that produced the
   calibrated market passing all four stylized facts, and the fixed-width
   quoting curve (§8.1.4) bounds how much of any win is just "the baseline was
   badly tuned."
3. **Detectors could be satisfied while something subtler is wrong.** Detectors
   catch known failure modes; they cannot catch unknown ones. The ablation
   battery is the general-purpose net, and the honest position — which will be
   stated in LIMITATIONS.md — is that "no detector tripped" is evidence, not
   proof.
4. **Negative results are acceptable and will be published as such.** If the
   trained agent does not beat the baseline cleanly, M8 reports that, with the
   diagnostics. Phase 1 was explicitly built to stand alone for exactly this
   reason.

---

## References

- Spooner, Fearnley, Savani, Koukorinis — *Market Making via Reinforcement
  Learning* (AAMAS 2018), [arXiv:1804.04216](https://arxiv.org/pdf/1804.04216) —
  asymmetrically dampened P&L; plain P&L induces speculative inventory holding.
- Gašperov & Kostanjčar — *Reinforcement Learning Approaches to Optimal Market
  Making*, [Mathematics 9(21):2689](https://www.mdpi.com/2227-7390/9/21/2689) —
  survey of reward families; the never-trade degenerate optimum.
- Ganesh et al. — *Reinforcement Learning for Market Making in a Multi-agent
  Dealer Market*, [arXiv:1911.05892](https://arxiv.org/pdf/1911.05892).
- Amrouni et al. — *ABIDES-gym: gym environments for multi-agent discrete event
  simulation and application to financial markets* — the reference architecture's
  RL layer; state collection decoupled from kernel interruption.
- Vinyals et al. (AlphaStar) / *A Survey on Self-Play Methods in RL*,
  [arXiv:2408.01072](https://arxiv.org/pdf/2408.01072) — cycling in naive
  self-play; prioritized fictitious self-play over a checkpoint pool.
- Avellaneda & Stoikov — *High-frequency trading in a limit order book* —
  inventory managed through reservation-price skew rather than hedging.
