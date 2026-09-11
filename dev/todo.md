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

- [ ] `docs/plan-v0.2-hardening.md` — the ordered plan for the next release: failure accounting
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
- [ ] `CLAUDE.md` still says "58 tasks × 3 = 174"; the real figure after the n2 trim is
      47 tasks × 3 = 141 (README / skill / datasheet agree). Bring CLAUDE.md in line.
- [ ] `cli.py` `--provider` defaults to `groq` while the HelioAI adapter defaults to `azure`
      (commit b4e8fdb). `run --agent helioai` without a flag lands on groq, contrary to the
      stated intent. Align the CLI default to `azure`.
- [ ] `helioai.py:_TOOL_OUTPUT_LIMIT = 4000` truncates tool output, so an accepted id beyond
      the cut is read as "never returned" and corrupts the n1 rank metric. The `truncated`
      flag is recorded but not read by the grader or the report — surface it explicitly.
- [ ] The n3 gate fires on correct answers when a ledger entry holds a *vector*.
      `provenance_check._NAME_WINDOW` attributes any number within 40 characters of a ledger
      name to that entry, so a component or a magnitude reads as contradicting the vector's
      scalar summary. Seen three times across five arms, always on `n3_theta_bn`:
      `-0.657` vs `shock_normal_gsm`, `161 km/s` vs `shock_speed_km_s`, and `9.68 nT` /
      `24.97 nT` vs `B_up_gsm`. Costs about one run a sweep, at the gate, on right answers.
      Fixed in HelioAI, but the harness reads the agent's own counter — see the next item.
- [ ] Recompute provenance harness-side rather than trusting `collect(trace).contradicted`
      (`graders/__init__.py:65`). The one hard gate is currently a number the agent under
      test computes about itself: loosening its own detector would pass the gate unnoticed.
      The 2026-08-25 `_MIN_BARE_INT` change was legitimate and checkable in the traces, which
      is exactly why the general case is not.
- [ ] `stats.py:mcnemar` is implemented but has no CLI surface. Add
      `heliobench compare <runA> <runB>` (refusing when `task_set_digest` differs).
- [ ] `numeric.py` folds unit spellings but never scales (nT ↔ pT): deliberate and
      documented, but worth revisiting if units are added. The `near` ±120-char window is
      fragile to rephrasing; a robustness test would pin it.
