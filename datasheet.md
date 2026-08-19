# Datasheet for HelioBench

Following Gebru et al., *Datasheets for Datasets* (CACM 2021). Written from the start rather
than at submission time, because the sections nobody can answer later are exactly the ones
that decide whether the benchmark is usable by anyone else.

> **Status: complete for v0.1.** Answers describe the 58-task set as shipped. A section is
> never left blank — "not applicable, because X" is an answer; silence is not.

## 1. Motivation

- **For what purpose was the dataset created?** To measure whether an AI agent can carry out
  real heliophysics data analysis end to end: resolve a physical quantity to a concrete
  archived product, retrieve it, handle instrument fill values and coverage gaps, and compute
  a derived quantity that matches a vetted reference. No existing benchmark measures this.
- **Who created it and who funded it?** Furkan Erdogan, unfunded, alongside HelioAI.
- **Any other comments?** The benchmark was created by the author of one of the agents it
  evaluates. The harness is therefore agent-neutral by construction, and independent task
  authorship is a stated requirement before any comparative claim is published.

## 2. Composition

Instances are tasks, one YAML file each, carrying the prompt, the expected answer, the
tolerance, the clustering key, the provenance of the truth, and its licence.

v0.1 holds **58 tasks over 12 events**: 30 retrieval (n1), 16 formulary (n2), 12
method-specified analysis (n3). The n3 tasks all concern a single event — the 17 March 2015
interplanetary shock — which is why intervals are clustered by event rather than by task.

No personal data, no human subjects. The only bundled measurements are 1.1 MB of
NASA/CDAWeb spacecraft data (CC0) frozen under `fixtures/`.

## 3. Collection process

n1 answer keys were checked against the live 82 433-product speasy index at authoring time,
and the generator refuses to emit a set whose key names a product that does not exist. n2
reference values were produced by calling PlasmaPy, never typed by hand. n3 reference values
were derived from the frozen fixture by `scripts/reference_values.py`, using the analysis
recipes shipped with the agent.

Tasks were written by the repository's author. **Independent task authorship is a stated
prerequisite before any comparative claim is published** — see `docs/roadmap-paper.md`.

## 4. Preprocessing / cleaning / labeling

Fixture data is written by the agent's own datastore, which blanks each dataset's declared
fill values to NaN at download. No other cleaning is applied, and the frozen bytes are never
regenerated: a fixture rebuilt against a changed archive would silently move every n3 answer.

## 5. Uses

- **Intended:** comparing agent scaffolds and models on heliophysics analysis; measuring the
  effect of a change to an agent's architecture on the same task set.
- **Out of scope:** claiming scientific validity of any individual result an agent produces.
  Passing a task means agreeing with a reference implementation under a stated method — not
  that the physics was done well.

## 6. Distribution

MIT, on GitHub, installable from source. Every task file carries its own `provenance` and
`licence` field.

Third-party catalogues without an open licence are never redistributed. Where such a
catalogue is used, the repository ships a pointer, a checksum and a fetch script; only the
task specification lives here. v0.1 uses none: its ground truth comes from open reference
implementations and CC0 spacecraft data.

## 7. Maintenance

Maintained by the author in the HelioBench repository. Editing any prompt, expected value or
tolerance changes `task_set_digest`, which is recorded in every run's `meta.json`; scores
across different digests are not comparable, and the report states the digest so that is
visible rather than assumed. Task-set changes are released under semantic versioning.
