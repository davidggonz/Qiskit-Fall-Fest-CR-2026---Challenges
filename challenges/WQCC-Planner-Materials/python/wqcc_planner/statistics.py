"""Fixed-allocation estimators and conservative sampling intervals."""
from __future__ import annotations
import math
import numpy as np


def allocate_shots(weights: list[float], budget: int, minimum: int = 2) -> list[int]:
    """Largest-remainder allocation; consumes exactly budget with no free shots."""
    if not weights:
        return []
    if budget < len(weights) * minimum:
        raise ValueError(f"need at least {len(weights) * minimum} shots for {len(weights)} experiments")
    w = np.abs(np.asarray(weights, dtype=float))
    if not np.all(np.isfinite(w)) or w.sum() <= 0:
        raise ValueError("allocation weights must be finite and have positive sum")
    remaining = budget - minimum * len(w)
    ideal = remaining * w / w.sum()
    integer = np.floor(ideal).astype(int)
    order = np.argsort(-(ideal - integer), kind="stable")
    integer[order[:remaining - int(integer.sum())]] += 1
    return (integer + minimum).tolist()


def product_variance(means: list[float], mean_variances: list[float]) -> float:
    """Exact independent-product identity with plug-in moments.

    Formula is exact for population means and true mean variances. Substituting
    empirical moments gives a NONNEGATIVE APPROXIMATION, not a coverage guarantee.
    Unlike first-order delta propagation, this retains higher-order terms.
    """
    m2 = np.square(np.asarray(means, dtype=float))
    return max(0.0, float(np.prod(m2 + mean_variances) - np.prod(m2)))


def multiply_intervals(intervals: list[tuple[float, float]]) -> tuple[float, float]:
    lo = hi = 1.0
    for a, b in intervals:
        values = (lo * a, lo * b, hi * a, hi * b)
        lo, hi = min(values), max(values)
    return lo, hi


def sampling_interval(means: list[float], shots: list[int],
                      products: list[tuple[float, list[int]]],
                      constant: float = 0.0, alpha: float = 0.05) -> tuple[float, float]:
    """Union-Hoeffding interval propagated through weighted independent products.

    Each experiment has iid observations in {-1,+1}; all allocations are fixed
    before data. The union bound does not require independence across experiments,
    but unbiased product reconstruction DOES require independent fragment data.
    Target is the noisy reconstructed estimand, not the ideal circuit expectation.
    No final clipping to [-1,1]: noisy QPD reconstruction need not be a physical
    state expectation. This valid interval can be wide and uninformative.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0,1)")
    count = len(means)
    if not count:
        return constant, constant
    intervals = []
    for mean, n in zip(means, shots):
        radius = math.sqrt(2 * math.log(2 * count / alpha) / n)
        intervals.append((max(-1.0, mean - radius), min(1.0, mean + radius)))
    lower = upper = constant
    for coefficient, indices in products:
        a, b = multiply_intervals([intervals[i] for i in indices])
        lower += min(coefficient * a, coefficient * b)
        upper += max(coefficient * a, coefficient * b)
    return float(lower), float(upper)
