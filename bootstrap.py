"""Is a model change bigger than the noise between seasons? Shared by the fitting scripts.

Each fitting script tests a change by holding every season out in turn, which gives one gain per season. bootstrap_report() resamples
those seasons and prints the mean gain, a 95% interval and a verdict: ADOPT when the interval excludes zero and the mean clears the
threshold a reader could notice, SMALL when it excludes zero but the gain is below that threshold, NOISE otherwise. The thresholds, per
metric: log loss 0.002, rank correlation 0.02, selections found 0.5 per season, winners found 0.1 per season."""
import numpy as np
THRESH = {'ll': 0.002, 'rho': 0.02, 'sel': 0.5, 'win': 0.1}
def bootstrap(diffs, n=20000, seed=1):
    """diffs: per-season gains (positive = better). Returns mean, lower, upper, share of resamples with no gain."""
    d = np.asarray(diffs, float); rng = np.random.default_rng(seed)
    bs = np.array([rng.choice(d, len(d), replace=True).mean() for _ in range(n)])
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)), float((bs <= 0).mean())
def verdict(mean, lo, hi, unit):
    if lo > 0 and mean >= THRESH[unit]: return 'ADOPT'
    if lo > 0: return 'SMALL'
    return 'NOISE'
def bootstrap_report(name, diffs, unit, n=20000):
    """prints one line; diffs are gains, positive = better (pass -delta for log loss)"""
    if len(diffs) < 3: print(f'{name:60s} too few seasons to judge ({len(diffs)})'); return 'NOISE'
    m, lo, hi, p = bootstrap(diffs, n); v = verdict(m, lo, hi, unit)
    fmt = '{:+.3f}' if unit in ('ll', 'rho') else '{:+.2f}'
    print(f'{name:60s} {fmt.format(m)} per season [95% {fmt.format(lo)}, {fmt.format(hi)}] over {len(diffs)} seasons: {v}')
    return v
