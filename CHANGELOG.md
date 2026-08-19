# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
