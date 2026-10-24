"""Statistics for the generator evaluation (plan.md section 8), in plain Python (no numpy/scipy here).

Every function takes only the observations it's given: missing values are the caller's to count and
report, and a statistic that can't be computed returns None rather than a guess.
"""
import math
import random


def binom_cdf(k, n, p):
    """P(X <= k) for X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def wilson(k, n, z=1.96):
    """Wilson score interval for k successes in n trials: (estimate, low, high), or None if n == 0."""
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return p, max(0.0, centre - half), min(1.0, centre + half)


def clopper_pearson(k, n, alpha=0.05):
    """Exact (Clopper-Pearson) interval: (low, high). With k == 0 the upper bound is about 3/n."""
    if n == 0:
        return None

    def solve(target, lo_is_zero):
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2
            if lo_is_zero:   # upper bound: largest p with P(X <= k) >= alpha/2
                lo, hi = (mid, hi) if binom_cdf(k, n, mid) > target else (lo, mid)
            else:            # lower bound: smallest p with P(X >= k) >= alpha/2
                lo, hi = (lo, mid) if 1 - binom_cdf(k - 1, n, mid) > target else (mid, hi)
        return (lo + hi) / 2
    low = 0.0 if k == 0 else solve(alpha / 2, False)
    high = 1.0 if k == n else solve(alpha / 2, True)
    return low, high


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p-value for b and c discordant pairs (None if there are none)."""
    if b + c == 0:
        return None
    return min(1.0, 2 * binom_cdf(min(b, c), b + c, 0.5))


def ranks(values):
    """Average ranks (1-based), ties sharing the mean of their positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for t in range(i, j + 1):
            out[order[t]] = (i + j) / 2 + 1
        i = j + 1
    return out


def auroc(positive, negative):
    """Area under the ROC curve: P(score of a positive > score of a negative), ties counting half."""
    if not positive or not negative:
        return None
    r = ranks(list(positive) + list(negative))
    rank_sum = sum(r[:len(positive)])
    return (rank_sum - len(positive) * (len(positive) + 1) / 2) / (len(positive) * len(negative))


def spearman(x, y):
    """Spearman correlation of paired observations (None if fewer than 3 or no variation)."""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = ranks(list(x)), ranks(list(y))
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return None if sx == 0 or sy == 0 else sxy / (sx * sy)


def fleiss_kappa(items):
    """Fleiss' kappa. items: one list of category labels per item, all with the same number of raters
    (items with a missing label should be left out by the caller and counted). None if undefined."""
    items = [i for i in items if i]
    if not items:
        return None
    n = len(items[0])
    if n < 2 or any(len(i) != n for i in items):
        return None
    cats = sorted({c for i in items for c in i})
    p_j = {c: sum(i.count(c) for i in items) / (len(items) * n) for c in cats}
    p_i = [(sum(i.count(c) ** 2 for c in cats) - n) / (n * (n - 1)) for i in items]
    p_bar = sum(p_i) / len(p_i)
    p_e = sum(v * v for v in p_j.values())
    return None if p_e == 1 else (p_bar - p_e) / (1 - p_e)


def krippendorff_alpha(units, level="ordinal"):
    """Krippendorff's alpha. units: one list of ratings per item (None = missing); items with fewer than
    two ratings are not pairable and drop out. level: "ordinal" or "nominal". None if undefined."""
    units = [[v for v in u if v is not None] for u in units]
    units = [u for u in units if len(u) >= 2]
    if not units:
        return None
    values = sorted({v for u in units for v in u})
    idx = {v: i for i, v in enumerate(values)}
    k = len(values)
    o = [[0.0] * k for _ in range(k)]   # coincidence matrix
    for u in units:
        m = len(u)
        for a in range(m):
            for b in range(m):
                if a != b:
                    o[idx[u[a]]][idx[u[b]]] += 1 / (m - 1)
    n_c = [sum(row) for row in o]
    n = sum(n_c)
    if n <= 1:
        return None

    def delta(c, e):
        if level == "nominal":
            return 0.0 if c == e else 1.0
        lo, hi = min(c, e), max(c, e)
        return (sum(n_c[g] for g in range(lo, hi + 1)) - (n_c[lo] + n_c[hi]) / 2) ** 2
    d_o = sum(o[c][e] * delta(c, e) for c in range(k) for e in range(k))
    d_e = sum(n_c[c] * n_c[e] * delta(c, e) for c in range(k) for e in range(k)) / (n - 1)
    return None if d_e == 0 else 1 - d_o / d_e


def cluster_bootstrap(clusters, statistic, resamples=10000, seed=20261023, level=0.95):
    """Percentile CI for statistic(flat list) when observations come in clusters (several drafts per
    prompt): whole clusters are resampled with replacement. Returns (estimate, low, high) or None."""
    clusters = [c for c in clusters if c]
    if not clusters:
        return None
    est = statistic([x for c in clusters for x in c])
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        sample = [x for _ in clusters for x in rng.choice(clusters)]
        value = statistic(sample)
        if value is not None:
            draws.append(value)
    if not draws:
        return None
    draws.sort()
    lo = draws[int((1 - level) / 2 * len(draws))]
    hi = draws[min(len(draws) - 1, int((1 + level) / 2 * len(draws)))]
    return est, lo, hi


def mean(xs):
    return sum(xs) / len(xs) if xs else None
