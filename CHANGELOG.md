# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Three tier-n1 answer keys rejected identifiers the search index describes in the words of
  their own prompt. `n1_wind_position` accepts all 15 Wind GSE position products;
  `n1_amda_imf` and `n1_themis_fgm` now name the dataset that separates their look-alikes.
  This changes `task_set_digest`, so scores from before it do not compare — see the
  correction appended to `results/summary_2026-08-21.md`.

### Added
- `scripts/n1_key_candidates.py`: enumerate an n1 key out of the search index by regex, so
  the accepted identifiers are measured rather than recalled.
- The rule that closes the above, in `docs/what-this-measures.md`: a task is defective when a
  defensible answer exists that its key rejects.
- 58 tasks over 12 events: 30 retrieval, 16 formulary, 12 method-specified analysis, with a
  suite that audits every one of them for solvability.
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
