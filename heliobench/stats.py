"""Turning per-run verdicts into numbers that survive a statistician.

Three choices here are not defaults, and each has a reason.

Confidence intervals are bootstrapped over **events**, not over tasks. Twelve questions about
one interplanetary shock are twelve looks at the same shock; treating them as independent
understates the interval by a factor that has been measured as high as three.

The bootstrap is used rather than a normal approximation because the task set is in the tens,
and below a few hundred items the central limit theorem is a wish.

`pass^k` is reported beside the mean. A tool a scientist runs once and cannot reproduce is
not a tool, and an agent that passes on one attempt in three is exactly that.

An errored run — the provider timed out, the quota ran dry — is neither a pass nor a fail:
it is a repetition that did not happen. It leaves every denominator here, and a task whose
repetitions all errored contributes nothing. The count is reported beside the score so a
reader can see how much of the sweep is missing, and a tier missing more than a tenth of its
runs is flagged as not yet comparable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

# Fraction of a tier's runs that may error before its score stops being quotable.
ERRORED_LIMIT = 0.10


@dataclass
class Summary:
    """Attributes:
    mean: average per-task success rate over the k runs that completed.
    pass_k: fraction of scored tasks that passed on *every* completed run.
    pass_any: fraction that passed at least once — the gap to `pass_k` is the flakiness.
    ci: 95% cluster-bootstrap interval on `mean`.
    n_errored: runs that did not complete and were left out of every figure above.
    n_unscored: tasks whose every run errored, absent from `n_tasks`.
    """

    n_tasks: int
    n_events: int
    runs: int
    mean: float
    pass_k: float
    pass_any: float
    ci: tuple[float, float]
    n_errored: int = 0
    n_unscored: int = 0

    @property
    def comparable(self) -> bool:
        """Whether few enough runs errored for the score to be quoted against another arm."""
        total = (self.n_tasks + self.n_unscored) * self.runs
        return total == 0 or self.n_errored / total <= ERRORED_LIMIT

    def as_dict(self) -> dict:
        return {
            "n_tasks": self.n_tasks,
            "n_events": self.n_events,
            "runs": self.runs,
            "mean": round(self.mean, 4),
            "pass_k": round(self.pass_k, 4),
            "pass_any": round(self.pass_any, 4),
            "ci95": [round(self.ci[0], 4), round(self.ci[1], 4)],
            "n_errored": self.n_errored,
            "n_unscored": self.n_unscored,
            "comparable": self.comparable,
        }


def cluster_bootstrap_ci(
    values: list[float], clusters: list[str], iterations: int = 10000, seed: int = 0
) -> tuple[float, float]:
    """95% interval for the mean of `values`, resampling whole clusters.

    Returns (nan, nan) for an empty input, and a degenerate point interval for one cluster —
    a single cluster carries no information about between-cluster variation, and pretending
    otherwise is the error this function exists to avoid.
    """
    if not values:
        return (float("nan"), float("nan"))
    by_cluster: dict[str, list[float]] = defaultdict(list)
    for v, c in zip(values, clusters, strict=True):
        by_cluster[c].append(v)
    names = list(by_cluster)
    if len(names) == 1:
        m = float(np.mean(values))
        return (m, m)

    rng = np.random.default_rng(seed)
    pools = [np.array(by_cluster[n], dtype=float) for n in names]
    draws = rng.integers(0, len(names), size=(iterations, len(names)))
    means = np.array([np.concatenate([pools[i] for i in row]).mean() for row in draws])
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def summarise(per_task: dict[str, list[bool | None]], events: dict[str, str], runs: int) -> Summary:
    """Aggregate one arm's verdicts.

    `per_task` maps a task id to its k outcomes: `True` passed, `False` failed, `None`
    errored. A `None` is dropped before any rate is taken, so a task with two passes and one
    timeout scores 2/2 with one errored — never 3/3, and never 2/3.
    """
    n_errored = sum(1 for outs in per_task.values() for o in outs if o is None)
    known = {t: [o for o in outs if o is not None] for t, outs in per_task.items()}
    ids = sorted(t for t, outs in known.items() if outs)
    rates = [float(np.mean(known[t])) for t in ids]
    clusters = [events.get(t, t) for t in ids]
    return Summary(
        n_tasks=len(ids),
        n_events=len(set(clusters)),
        runs=runs,
        mean=float(np.mean(rates)) if rates else 0.0,
        pass_k=float(np.mean([all(known[t]) for t in ids])) if ids else 0.0,
        pass_any=float(np.mean([any(known[t]) for t in ids])) if ids else 0.0,
        ci=cluster_bootstrap_ci(rates, clusters),
        n_errored=n_errored,
        n_unscored=len(per_task) - len(ids),
    )


def mcnemar(a: dict[str, bool], b: dict[str, bool]) -> dict:
    """Exact McNemar test on the tasks two arms have in common.

    Paired, because both arms answered the same tasks. Comparing two arms by whether their
    confidence intervals overlap throws that pairing away and needs several times the sample
    to see the same difference.
    """
    shared = sorted(set(a) & set(b))
    only_a = sum(1 for t in shared if a[t] and not b[t])
    only_b = sum(1 for t in shared if b[t] and not a[t])
    n = only_a + only_b
    if n == 0:
        p = 1.0
    else:
        k = min(only_a, only_b)
        # Two-sided exact binomial at p=0.5 over the discordant pairs.
        coeff = np.array([_binom(n, i) for i in range(k + 1)], dtype=float)
        p = float(min(1.0, 2.0 * coeff.sum() / (2.0**n)))
    return {"n_shared": len(shared), "only_a": only_a, "only_b": only_b, "p_value": round(p, 6)}


def _binom(n: int, k: int) -> float:
    from math import comb

    return float(comb(n, k))
