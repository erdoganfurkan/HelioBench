# Todo

Living plan — what's in flight right now. `docs/roadmap-paper.md` has the longer view and
the reasoning behind each item below; this file is just the trackable slice of it.

## Now
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
