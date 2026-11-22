# ASSUMPTIONS.md

Assumptions made to keep moving. Each entry: the assumption, why it was safe, and what
would change if it's wrong. Corrections welcome at any time.

1. **"ASAP" deadline means fastest credible path, not corner-cutting.** Milestone gates
   from the brief still apply; what changed is the stack choice (single backend
   language, ADR-001) and pacing. If a specific hard date exists, say so — it may change
   how much M4 calibration depth is worth before M5.

2. **Project name is "marquee"**, taken from the original folder name. Renaming later is
   cheap (package name + README).

3. **GitHub repo will be public** — this is a portfolio artifact for recruiters/judges.
   `gh` is installed but **not authenticated**; run `gh auth login` once, and the repo
   gets created and pushed at the next work stretch. Local git history is accumulating
   meanwhile.

4. **Consumer hardware, CPU-only.** No GPU is assumed anywhere, including Phase 2 RL
   (small nets, short episodes, checkpointing per the brief). If a GPU exists, training
   gets faster but nothing in the design changes.

5. **Single instrument (one symbol) for all of Phase 1.** Multi-asset adds nothing to
   the emergence story and complicates the book, agents, and viz. Revisit only if a
   Phase 2 experiment needs cross-asset effects.

6. **MCP availability this session:** OpenBB, Alpaca, Perplexity, Firecrawl, Semgrep,
   and Sequential Thinking servers are not connected; GitHub MCP needs auth.
   Substitutions: WebSearch for research passes; local git + gh CLI for GitHub.
   Semgrep works natively on Windows via `uvx semgrep` (verified at M1, v1.168.0) —
   no fallback needed; bandit is run additionally since it's free.

9. **M4 thresholds defended from literature, not live data (2026-07-08).** OpenBB and
   Alpaca MCPs were still unconnected when M4 ran, so ADR-013 thresholds cite the
   canonical empirical literature (Cont 2001; Roll 1984; Bouchaud/Lillo-Farmer) from
   model knowledge instead of freshly pulled reference series. Blast radius: the
   *ranges* used are textbook-stable, but the numbers should be cross-checked against
   real intraday data once the MCPs connect — if that shifts a threshold, re-run the
   committed scenario (it passes with wide margin on 3 of 4 facts, and the 4th —
   trade-sign ACF — exceeds real values in a direction ADR-013 already discloses).

7. **Tick size default $0.01, integer quantities.** Standard equity convention; it's a
   per-scenario config value, not a constant (ADR-004).

