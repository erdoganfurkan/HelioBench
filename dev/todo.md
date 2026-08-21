# Todo

Living plan — what's in flight right now. `docs/roadmap-paper.md` has the longer view and
the reasoning behind each item below; this file is just the trackable slice of it.

## Now
- [x] Correct the three defective n1 answer keys found by the 2026-08-21 reference run, and
      write down the rule that closed them (`docs/what-this-measures.md`)
- [ ] Record tool *results* in the trace, not just the call — today `search_parameters`
      returns `"[5 items]"`, so an n1 failure cannot be attributed to retrieval or to
      selection without a replay. Unlocks a rank metric (recall@k / MRR): 30 binary results
      become 30 graded ones for free
- [ ] Make process a gate rather than a footnote: a run that contradicts its own ledger
      cannot count as passed. Tighten n3's `rel: 0.07` where the frozen fixture makes
      exactness possible
- [ ] Trim n2 to ~4 regression guards — 16/16, `pass^3` 100%, 1.0 tool call/run: it is
      saturated and discriminates nothing, at 512k tokens a sweep
- [ ] Re-run n1 whole in one shot under the corrected keys (~1.1M tokens, fits the 2M/day
      Azure quota) for a bootstrapped figure instead of a hand tally
- [ ] v0.1 release (not yet released — see `CHANGELOG.md` `[Unreleased]`)

## Toward a benchmark paper
- [ ] Scale: 58 tasks / 12 events → ~250 tasks / ≥100 independent events
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
