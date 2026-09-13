# Todo

Living plan — what's in flight right now. `docs/roadmap-paper.md` has the longer view and
the reasoning behind each item below; this file is just the trackable slice of it.

## Now
- [x] Correct the three defective n1 answer keys found by the 2026-08-21 reference run, and
      write down the rule that closed them (`docs/what-this-measures.md`)
- [x] Record tool *results* in the trace, not just the call — today `search_parameters`
      returns `"[5 items]"`, so an n1 failure cannot be attributed to retrieval or to
      selection without a replay. Unlocks a rank metric (recall@k / MRR): 30 binary results
      become 30 graded ones for free
- [x] Make process a gate rather than a footnote: a run that contradicts its own ledger
      cannot count as passed. Tighten n3's `rel: 0.07` where the frozen fixture makes
      exactness possible
- [x] Trim n2 to 5 regression guards — 16/16, `pass^3` 100%, 1.0 tool call/run: it is
      saturated and discriminates nothing, at 512k tokens a sweep
- [x] Re-run n1 whole under the corrected keys (~1.1M tokens, fits the 2M/day
      Azure quota) for a bootstrapped figure instead of a hand tally
- [x] `--agent-ref <ref>` on `run`/`verify`: benchmark a pinned remote commit of HelioAI in an
      isolated venv (`heliobench/agentsnapshot.py`) — resolves the ref, caches a venv per
      commit, re-execs the CLI inside it, and pins the SHA in the report header as `Agent ref`
      (2026-08-25)
- [x] v0.1.0 tagged 2026-09-11, before any v0.2 change touched the digest

## Planned, written up separately

- [~] `docs/plan-v0.2-hardening.md` — the ordered plan for the next release; A, B1–B4, C1–C2,
      D1–D5, E1 landed 2026-09-11 on `v0.2-hardening`. Open: B5 (real-agent concurrency
      check), C3–C4 (more events), E2–E4 (publication). The ordered plan for the next release: failure accounting
      (`errored` distinct from `failed`), `--jobs` parallelism, n3 beyond one event, the
      correctness debt below, and tagging/publishing. Read it before picking up anything in the
      backlog — several backlog items are folded into it with an order and a reason.
- [ ] `docs/plan-generic-harness.md` — thinking document: how much of this harness is actually
      about heliophysics, and whether the domain-agnostic remainder is worth extracting.
      Nothing committed to; stage 0 is finishing the plan above.

## Toward a benchmark paper
- [ ] Scale: 47 tasks / 18 event clusters → ~250 tasks / ≥100 independent events
- [ ] Independence: task authors who aren't the agent's author (PyHC pool), ≥3 external agent
      scaffolds scored besides HelioAI, benchmark published separately from the agent
- [ ] External catalogues without an open licence (IPShocks, CfA shocks, WDC Kyoto): ship as
      pointer + SHA-256 + fetch script, not redistributed
- [ ] Method-dependent ground truth (θ_Bn, shock normals, ICME boundaries): publish
      inter-catalogue disagreement as the tolerance band
- [ ] Contamination probes: perturb task inputs and check the answer moves; hold out a
      private split
- [ ] Reporting artifacts: Croissant metadata, grader false-accept rate vs. human-checked
      answers, error taxonomy with an agreement statistic

## Backlog — noted during a code review, not yet picked up

- [x] `scripts/reference_values.py:23` hardcoded `RECIPES = /home/furkan/HelioAI/...`. Fixed
      2026-09-11: recipes frozen under `heliobench/recipes/` with upstream commit and sha256
      in `MANIFEST`; windows moved to `fixtures/<event>/windows.json` (plan C1, C2).
- [ ] `scripts/n1_key_candidates.py` reads HelioAI's private 342 MB Chroma index, which this
      repo does not vendor — a third party cannot audit the n1 keys. Consider shipping the
      catalogue metadata (id + document) under the roadmap's pointer + SHA-256 + fetch model.
- [x] `CLAUDE.md` said "58 tasks × 3 = 174" — fixed in c6c4325.
- [x] `cli.py` `--provider` defaulted to `groq` — aligned to `azure` 2026-09-11.
- [x] `_TOOL_OUTPUT_LIMIT` truncation corrupted the n1 rank — truncated-unranked runs are now
      counted apart in the report (2026-09-11).
- [x] The n3 gate fired on correct answers when a ledger entry held a *vector*:
      `provenance_check._NAME_WINDOW` attributed any number within 40 characters of a ledger
      name to that entry, so a component or a magnitude read as contradicting the vector's
      scalar summary (`-0.657` vs `shock_normal_gsm`, `161 km/s` vs `shock_speed_km_s`,
      `9.68 nT` / `24.97 nT` vs `B_up_gsm`, always on `n3_theta_bn`). Ten such gatings across
      the stored sweeps, all on right answers. Replaced by `graders/provenance.py` 2026-09-11.
- [x] Recompute provenance harness-side rather than trusting `collect(trace).contradicted`
      (`graders/__init__.py:65`). Done 2026-09-11: the gate reads the graded answer against
      the ledger; the agent's own counter is reported beside it, never gated on.
- [ ] Follow-up to the above: `docs/what-this-measures.md` should eventually quote the
      gate's measured false-positive rate on human-checked answers (0/241 stored n3 passes
      today) as the paper's grader-audit figure.
- [x] `stats.py:mcnemar` has a CLI surface: `heliobench compare <runA> <runB>` (2026-09-11).
- [ ] `numeric.py` folds unit spellings but never scales (nT ↔ pT): deliberate and
      documented, but worth revisiting if units are added. The `near` ±120-char window is
      fragile to rephrasing; a robustness test would pin it.
