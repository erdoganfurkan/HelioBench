# Datasheet for HelioBench

Following Gebru et al., *Datasheets for Datasets* (CACM 2021). Written from the start rather
than at submission time, because the sections nobody can answer later are exactly the ones
that decide whether the benchmark is usable by anyone else.

> **Status: outline.** Sections marked ⏳ are answered as the task set is built. A section is
> never left blank at release — "not applicable, because X" is an answer; silence is not.

## 1. Motivation

- **For what purpose was the dataset created?** To measure whether an AI agent can carry out
  real heliophysics data analysis end to end: resolve a physical quantity to a concrete
  archived product, retrieve it, handle instrument fill values and coverage gaps, and compute
  a derived quantity that matches a vetted reference. No existing benchmark measures this.
- **Who created it and who funded it?** ⏳
- **Any other comments?** The benchmark was created by the author of one of the agents it
  evaluates. The harness is therefore agent-neutral by construction, and independent task
  authorship is a stated requirement before any comparative claim is published.

## 2. Composition ⏳

Instances are tasks, one YAML file each, carrying the prompt, the expected answer, the
tolerance, the clustering key, the provenance of the truth, and its licence.

## 3. Collection process ⏳

## 4. Preprocessing / cleaning / labeling ⏳

## 5. Uses

- **Intended:** comparing agent scaffolds and models on heliophysics analysis; measuring the
  effect of a change to an agent's architecture on the same task set.
- **Out of scope:** claiming scientific validity of any individual result an agent produces.
  Passing a task means agreeing with a reference implementation under a stated method — not
  that the physics was done well.

## 6. Distribution ⏳

Third-party catalogues without an open licence are never redistributed. Where such a
catalogue is used, the repository ships a pointer, a checksum and a fetch script; only the
task specification lives here.

## 7. Maintenance ⏳
