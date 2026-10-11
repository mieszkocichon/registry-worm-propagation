#!/usr/bin/env python3
"""Defense 4 evidence: is the malicious-version publish anomalous relative to a
package's own prior release cadence? Self-baseline (paired, per-package)
comparison -- avoids needing an external non-malware control group, which this
study otherwise lacks (see Internal Validity, manuscript.tex).

IMPORTANT (found during a rigor pass after the first version of this script):
OSV's 'published' field is the advisory's publication date, not necessarily the
malicious npm version's actual publish date -- these can diverge substantially
(median lag ~4.2 days, but mean ~78 days and 17.4% of a verifiable subsample
lag >100 days, apparently from batched/back-dated OSV disclosure events).
This script now anchors on the EXACT malicious-version npm publish timestamp
whenever OSV's 'versions_affected' names a specific version that is present in
the package's own npm 'time' dict ('exact' method); it falls back to OSV's
'published' date only when no exact version match exists ('proxy' method,
flagged as such in the output). Results are reported for the exact-only
ground-truth subset AND for the combined exact+proxy sample, so the finding's
robustness to this confound is directly checkable.

Reuses the exact same OSV-filter logic as notebook03's patient-zero heuristic
(ADR-0004, ADR-0012) for methodological consistency.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import wilcoxon

base = Path(__file__).parent.parent

import sys
sys.path.append(str(base / "scripts"))
from resolve_malicious_dates import load_malware_advisories, resolve_malicious_dates

mal = load_malware_advisories(base / 'data' / 'npm' / 'osv_npm_vulnerabilities_filtered.csv')

npm_meta = {}
with open(base / 'data' / 'npm' / 'npm_metadata.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        d = json.loads(line)
        npm_meta[d['package']] = d

resolved = resolve_malicious_dates(mal, npm_meta)

records = []
for pkg, (mal_dt, method) in resolved.items():
    records.append((pkg, npm_meta[pkg], mal_dt, method))

def compute_gaps(records, methods_allowed):
    typical_gaps, malicious_gaps, ratios, used_methods = [], [], [], []
    n_skipped_insufficient = 0
    n_skipped_zero_gap = 0
    for pkg, d, mal_dt, method in records:
        if method not in methods_allowed:
            continue
        time_dict = d.get('time', {})
        version_times = sorted(
            t for k, ts in time_dict.items()
            if k not in ('created', 'modified') and isinstance(ts, str)
            for t in [pd.to_datetime(ts, utc=True, errors='coerce')]
            if pd.notna(t)
        )
        versions_before = [t for t in version_times if t < mal_dt]
        if len(versions_before) < 2:
            n_skipped_insufficient += 1
            continue
        gaps_days = np.diff([t.value for t in versions_before]) / 1e9 / 86400
        typical_gap = float(np.median(gaps_days))
        malicious_gap = (mal_dt - versions_before[-1]).total_seconds() / 86400
        if typical_gap <= 0:
            n_skipped_zero_gap += 1
            continue
        typical_gaps.append(typical_gap)
        malicious_gaps.append(malicious_gap)
        ratios.append(malicious_gap / typical_gap)
        used_methods.append(method)
    return (np.array(typical_gaps), np.array(malicious_gaps), np.array(ratios),
            n_skipped_insufficient, n_skipped_zero_gap)

def report(label, typical_gaps, malicious_gaps, ratios, n_skip_hist, n_skip_zero, n_candidates):
    print(f"\n=== {label} ===")
    print(f"Candidate packages: {n_candidates}")
    print(f"Skipped (<2 legit versions before malicious publish): {n_skip_hist}")
    print(f"Skipped (typical_gap == 0): {n_skip_zero}")
    n = len(ratios)
    print(f"Usable paired sample: {n}")
    if n == 0:
        return {}
    stat_fast, p_fast = wilcoxon(malicious_gaps, typical_gaps, alternative='less')
    stat_dorm, p_dorm = wilcoxon(malicious_gaps, typical_gaps, alternative='greater')
    print(f"Median typical gap (days): {np.median(typical_gaps):.3f}")
    print(f"Median malicious gap (days): {np.median(malicious_gaps):.3f}")
    print(f"Median ratio: {np.median(ratios):.4f}")
    print(f"% ratio < 1: {100*np.mean(ratios<1):.2f}%   % ratio > 5: {100*np.mean(ratios>5):.2f}%   % ratio > 100: {100*np.mean(ratios>100):.2f}%")
    print(f"Wilcoxon burst (H1 malicious<typical): p={p_fast:.3e}")
    print(f"Wilcoxon dormancy (H1 malicious>typical): p={p_dorm:.3e}")
    return {
        'n_candidates': int(n_candidates),
        'n_skipped_insufficient_history': int(n_skip_hist),
        'n_skipped_zero_typical_gap': int(n_skip_zero),
        'n_usable_paired_sample': int(n),
        'median_typical_gap_days': float(np.median(typical_gaps)),
        'median_malicious_gap_days': float(np.median(malicious_gaps)),
        'median_ratio': float(np.median(ratios)),
        'pct_ratio_lt_1': float(100*np.mean(ratios<1)),
        'pct_ratio_gt_5': float(100*np.mean(ratios>5)),
        'pct_ratio_gt_100': float(100*np.mean(ratios>100)),
        'wilcoxon_burst_p': float(p_fast),
        'wilcoxon_dormancy_p': float(p_dorm),
    }

n_exact = sum(1 for r in records if r[3] == 'exact')
n_bounded = sum(1 for r in records if r[3] == 'bounded')
n_proxy = sum(1 for r in records if r[3] == 'proxy')
print(f"Total candidate malware packages: {len(records)}")
print(f"Malicious-version date resolved via EXACT npm timestamp: {n_exact}")
print(f"Malicious-version date resolved via BOUNDED npm timestamp: {n_bounded}")
print(f"Malicious-version date resolved via OSV-published-date PROXY (fallback): {n_proxy}")

results = {}
tg, mg, r, sh, sz = compute_gaps(records, {'exact'})
results['exact_only'] = report("GROUND TRUTH (exact malicious-version npm timestamp only)", tg, mg, r, sh, sz, n_exact)

tg2, mg2, r2, sh2, sz2 = compute_gaps(records, {'exact', 'bounded', 'proxy'})
results['exact_plus_proxy'] = report("COMBINED (exact + bounded + proxy, full sample)", tg2, mg2, r2, sh2, sz2, len(records))

with open(base / 'data' / 'npm' / 'publish_velocity_anomaly.json', 'w') as f:
    json.dump({'n_exact': n_exact, 'n_proxy': n_proxy, **results}, f, indent=2)
print(f"\nSaved: data/npm/publish_velocity_anomaly.json")
