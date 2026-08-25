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
- [ ] v0.1 release (not yet released — see `CHANGELOG.md` `[Unreleased]`)

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

- [ ] `scripts/reference_values.py:23` hardcodes `RECIPES = /home/furkan/HelioAI/...` — the
      n3 truth depends on recipes outside the repo, on a machine-specific path. Contradicts
      "reproducible by anyone, forever": make the path configurable, or freeze the recipes
      into the repo.
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
- [ ] `stats.py:mcnemar` is implemented but has no CLI surface. Add
      `heliobench compare <runA> <runB>` (refusing when `task_set_digest` differs).
- [ ] `numeric.py` folds unit spellings but never scales (nT ↔ pT): deliberate and
      documented, but worth revisiting if units are added. The `near` ±120-char window is
      fragile to rephrasing; a robustness test would pin it.
