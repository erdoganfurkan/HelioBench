# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- The trace records what each tool returned, not only that it was called: `search_parameters`
  used to reach the trace as `"[5 items]"`, which cannot say whether a wrong answer was never
  retrieved or was retrieved and passed over. The report grades n1 by MRR and recall@k
  alongside the pass rate.
- A run whose answer contradicts its own provenance ledger now fails, whatever the number
  says. On the reference run's n3 sweep this turns 36/36 into 35/36.
- Tier n3 tolerance tightened from 5–10% to 1% (1° on the shock-normal angle). The truth is
  derived from frozen bytes by a method the prompt states; the reference run's worst deviation
  was 0.33%, so the old band was wide enough to accept a number reached some other way.
- Tier n2 trimmed from 16 tasks to 5, one per formula. It scored 16/16 with `pass^3` at 100%
  on 1.0 tool calls per run — saturated, and 512k tokens a sweep.

### Fixed
- `verify` refuses a machine with under 2 GB free where the agent writes. A sweep that fills
  the disk dies with the quota already spent, and it surfaces as a sqlite error inside the
  agent loop rather than as anything mentioning storage — which is exactly what happened on
  2026-08-21, 69 runs into a 90-run sweep.
- A fourth defective key: `n1_dst_index` accepted only `amda/dst` while 24 MMS MEC
  ephemeris products carry the same index as a model input. The prompt now asks for the
  index rather than a copy of it, and the key accepts `amda/omni_dst` too.
- Three tier-n1 answer keys rejected identifiers the search index describes in the words of
  their own prompt. `n1_wind_position` accepts all 15 Wind GSE position products;
  `n1_amda_imf` and `n1_themis_fgm` now name the dataset that separates their look-alikes.
  This changes `task_set_digest`, so scores from before it do not compare — see the
  correction appended to `results/summary_2026-08-21.md`.

### Added
- `heliobench report --regrade <run>`: score stored traces again with today's graders and
  task set. Costs nothing — graders read traces, never the agent — and it is how a corrected
  key, a tightened tolerance or a new gate reaches a run that already happened.
- `scripts/n1_key_candidates.py`: enumerate an n1 key out of the search index by regex, so
  the accepted identifiers are measured rather than recalled.
- The rule that closes the above, in `docs/what-this-measures.md`: a task is defective when a
  defensible answer exists that its key rejects.
- 47 tasks over 18 event clusters: 30 retrieval, 5 formulary, 12 method-specified analysis,
  with a suite that audits every one of them for solvability.
- Deterministic graders, cluster-bootstrap intervals, `pass^k`, paired McNemar, and a report
  whose header pins the model snapshot, the search index and the task-set digest.
- A Claude Code skill and plugin that run the graders and are forbidden from replacing them.
- The null agent: the floor, and the way to test the pipeline without an API key.
- `Trace`, the only thing graders may read, with exact token accounting
  recovered by wrapping the provider SDK call (HelioAI discards `response.usage`).
- `Agent` protocol and the HelioAI adapter: environment pinned before import, offline
  replay by seeding a session's workspace, preflight that refuses to run against an
  unreachable search index.
- Repository skeleton: packaging, licence, citation metadata, CI, datasheet outline.
- `heliobench list` and the YAML task schema.
