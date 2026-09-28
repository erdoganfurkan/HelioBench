# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — 2026-09-28

The state HelioAI 0.4.0 is measured with. `task_set_digest` is unchanged
(`50009d286465d407`): every stored run keeps comparing. Regrading all 28 stored runs against
the previous commit moves no verdict; the one run affected, `20260819T101256Z`, has 9 traces
whose prompts were hardened on 2026-08-21 and are now unscored instead of re-scored.

### Added
- `verify --canary`: one request of a few dozen tokens through the client a run would
  build. The only check that sees a provider refuse requests — the 400 `MissingSessionID`
  that zeroed the 2026-09-09 sweep — before a sweep spends its quota.
- `run --resume <run dir>`: `meta.json` is written before the first run (`status:
  running`), every record is appended to `results.partial.jsonl` as it lands, an
  interrupted sweep finalises as `status: interrupted`, and `--resume` regrades the
  repetitions whose trace is there and runs the rest. Refused for another task selection or
  another arm.
- `--agent-env HELIOAI_X=VALUE`: the one way to move HelioAI's behaviour (see Changed).
- `report --regrade --out <dir>` regrades a copy; `--in-place` is required to regrade a run
  under `results/` or `heliobench-results/`, which is now refused by default.
- `compare --tier` and `compare --shared`: compare one tier, or only the tasks both runs
  asked in the same wording, through per-task digests (`task_digests` in `meta.json`). The
  comparison lists what else differs between the arms — model, index, experiments,
  dependencies, grader version — and pairs the process metrics (tokens, tool calls, turns,
  wall clock, n1 rank) task by task with an exact sign test. On the 2026-09-23 arms it shows
  that 0.3.0 and the 0.4.0 candidate also ran on two different indexes.
- `report`: the arm's behaviour settings, its dependencies (`env_digest` and key versions),
  the index's digest, the fixtures' digests, whether the run was regraded, resumed or
  interrupted, and which traces were left unscored; a warning when `runs=1`; process by
  tier with wall p50/p95; a per-task matrix; optional cost with `--prices <yaml>`; and
  `--html`, one self-contained page rendered from the same markdown.
- n1 detail records `hedged` (an accepted id beside a non-accepted one — 184 of the 560
  stored passes), `first_accepted` and `unreturned` (quoted ids no search in the run
  returned, the harness's own view of invention); the report shows them beside the score.
  Reported, not gated.
- `verify` holds every n1 answer key to the index the agent will search, and refuses a task
  none of whose accepted ids is in it.
- `scripts/regrade_stored.py`: copy, regrade and diff every stored run; `--against` diffs
  two regrades, which is the table a scoring PR pastes.
- `scripts/contamination_check.py`: the benchmark's answers inside what reaches the agent's
  context — its skills, system prompts, recipes, a profile. HelioAI `release/0.4.0` carries
  none.
- `scripts/retrieval_replay.py`: replay a run's recorded searches through a HelioAI checkout
  with no model; recall@k and the HNSW noise floor for zero tokens.
- An optional `quality` on tasks (`paper_quality | proxy | candidate_interval`); the twelve
  n3 tasks are `proxy` — their windows are a rule around the shock time, not a paper's.
  Outside the digest.
- CI runs on Python 3.12–3.14 and ends with the null pipeline end to end: two sweeps, the
  HTML report, a comparison and a regrade of a copy.
- The recipe functions that derive tier-n3 truth are frozen under `heliobench/recipes/`,
  byte-for-byte from HelioAI at the commits recorded in `MANIFEST`, and hash-checked by a
  test. `scripts/reference_values.py` used to exec them from an absolute path on one machine,
  which made "reproducible by anyone, forever" false. `--check` compares the stored
  `reference.json` with what the frozen bytes derive without writing anything; a test does
  the same, and another checks every n3 answer key against the derived figure.
- `fixtures/<event>/windows.json`: the shock time, the averaging windows the frozen
  `rankine_hugoniot` recipe derives from it, and which saved series is which quantity.
  Written by `scripts/build_fixture.py`, read by `scripts/reference_values.py`, so a second
  event is two script runs rather than an edit to either. A test checks that every n3 prompt
  states the window edges the truth used.
- `--jobs N` on `run` and `verify`: repetitions in flight at once, default 1. One event loop
  for the sweep and a semaphore; records are sorted by `(task_id, run)` so the output does not
  depend on completion order — `--agent null --jobs 8` writes the same `results.csv` as
  `--jobs 1`. `meta.json` records `jobs`; above 1 the report withholds per-run wall clock,
  which under contention measures queueing, and the disk floor rises by 0.5 GB per extra job.
  Concurrency against the real agent has not been validated yet (B5 in
  `docs/plan-v0.2-hardening.md`): keep `--jobs 1` for a published number until it is.
- Exponential backoff on transient provider failures (rate limit, timeout, connection reset,
  5xx) inside the HelioAI adapter, layered over the token meter. Each retry is recorded as a
  `retry` event and reported as `Provider retries`; a `BadRequestError` is never retried.
- `heliobench compare <run A> <run B>`: exact paired McNemar between two runs, under both
  `pass^k` and majority collapsing, with the tasks that moved. Refuses when the two
  `task_set_digest` differ. Every paired comparison before this was a hand-run scratch script.

### Changed
- Every HelioAI variable that changes what the agent does — `HELIOAI_EXPERIMENTS`,
  `HELIOAI_ROLE_MODELS`, the judgment backend, vision, MCP servers, the hybrid search, the
  loop limits — is pinned to HelioAI's default before import, and moved only by
  `--agent-env`. They used to be inherited from the shell or a `.env` and recorded nowhere,
  so two arms differing by an experiment printed the same header. The header now carries
  what HelioAI parsed from them and a masked snapshot of every `HELIOAI_*` variable.
- `preflight` builds every client a run will build — the lead's and each `role_models`
  role's — so a missing key fails before the sweep. 154 stored runs died on their first
  provider call.
- The tool-output limit kept in a trace rises from 4000 to 16000 characters and travels in
  each `tool_output` event as `limit`.
- The harness's own backoff becomes record-only against HelioAI, which retries every
  provider call itself (`call_with_retry`, four attempts, Retry-After honoured): stacked,
  one rate limit could cost twenty requests. Transient failures are still recorded as
  `retry` events, with `"by": "agent"`.
- A finished run's agent workspace is removed once the files its artifacts point at are
  copied under the run directory (`artifacts/`, `kept` in the trace); the temporary storage
  root is removed at exit. `--keep-workspaces` keeps both. An n3 session seeds ~37 MB, and
  379 MB of them were sitting in `/tmp` from the September sweeps.
- The provenance gate is the harness's verdict, computed in `heliobench/graders/provenance.py`
  from the ledger and the reply, not the agent's own `contradicted` counter. That counter had
  fired ten times across the stored sweeps, every time on a correct answer — a vector
  component, a vector magnitude or a literature value quoted beside the right result. The
  gate now asks one question of the graded answer: is any accepted value in the ledger, a
  reconstructed vector component or magnitude, or a difference or ratio of two ledger
  scalars? If none is and a same-unit ledger scalar sits within a quarter of it, the session
  computed one number and the reply stated another. Every number in the prose is still
  classified (matched / derived / unsourced) and reported beside the agent's own count, so a
  disagreement between the two is visible. Regrading the six August arms moves n3 from
  86.1–97.2% to 91.7–100%; the gate fires on none of them, the agent's counter on ten.
- A tier-n1 run whose search output was cut at the trace's 4000-character limit before any
  accepted id appeared is left out of the rank metric and counted apart, rather than as
  "never returned". The `truncated` flag was recorded and read by nobody.
- `--provider` on the CLI defaults to `azure`, as the HelioAI adapter already did; a run
  launched without the flag used to land on groq.
- A run the provider or the network lost is `errored`, not `failed`. `results.json` and
  `results.csv` carry `outcome` ∈ {passed, failed, errored} beside the boolean; errored runs
  leave every denominator, a task whose every repetition errored is unscored, and a tier with
  more than 10% of its runs errored is flagged as not comparable. Classification is by
  exception class in `heliobench/graders/outcome.py` and defaults to the agent's fault: only
  timeouts, connection failures, rate limits and a full disk are excused. Re-grading the
  2026-08-25 `1fcb2f0` arm turns 32/36 (88.9%) into 32/34 with 2 errored (93.1%), with no
  flag passed and no CSV edited.

### Fixed
- The token meter counted nothing for a streamed completion: HelioAI 0.4.0 streams every
  lead turn, and the 0.4.0-candidate sweep reported `0 ⚠️ not exact` over 47 tasks. The
  stream is handed back wrapped and its usage read off the final chunk; cached prompt
  tokens are counted apart; sub-agents that `role_models` puts on a client of their own are
  costed from their `sub_agent_end` account and flagged as self-reported.
- HelioAI 0.4.0's registry returns a `ToolResult`, and the recorder stored its Python repr
  in all 47 traces of the 0.4.0-candidate sweep. It now stores `for_llm()`, the text the
  model was shown.
- A stream that dies half-way raises httpx's own classes (`RemoteProtocolError`,
  `ReadTimeout`, `ReadError`, …), which were scored as the agent's fault; they are errored.
- `report --regrade` graded a trace whose prompt had since been hardened against the new
  key, and wrote the new digest, which `compare` would have accepted. Such traces are now
  `unscored_traces` in `meta.json`.
- `--agent-ref main` asked `git ls-remote` for `main`, which matches any ref ending in it;
  only `refs/heads/<ref>` and `refs/tags/<ref>` are asked for now, and a name that is both
  at different commits is refused.
- Two sweeps started in the same second shared a run directory.
- The HelioAI adapter's tool-output recorder wrapped `registry.call_tool` — a module-level
  singleton — once per run and put the original back on exit. Under `--jobs > 1` the
  wrappers nested: every trace in flight received every run's tool output, and the first run
  to finish unwrapped the rest, which then recorded nothing. Those are the events the n1
  rank, `truncated` and invented-id metrics read. The registry is now wrapped once by the
  first run to start and dispatches to the recorder held in the current asyncio task context,
  the same mechanism HelioAI uses for its own per-session state; the last run out restores
  the class method. Tested against a stand-in registry in CI and through the real
  `stream_chat` where the agent is installed. `--agent null` could not have shown this: it
  never touches the registry, so the byte-identical `--jobs 1`/`--jobs 8` check above proved
  the runner and nothing about the adapter.

## [0.1.0] — 2026-09-11

The first tagged state. Tagged as it stood so that the August 2026 campaigns
(`results/summary_2026-08-21.md`, `results/summary_2026-08-25.md`) stay reproducible against
a fixed `task_set_digest` before v0.2 changes it.

### Added
- `--agent-ref <branch|tag|commit>` on `run` and `verify`: benchmark a pinned remote commit
  of HelioAI in an isolated venv, instead of whatever `helioai-agent` is installed in the
  harness venv. The ref is resolved via `git ls-remote`, the venv is cached per commit, and
  the resolved SHA is recorded in the report header as `Agent ref`. Requires `uv`.

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
