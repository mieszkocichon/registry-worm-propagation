"""Bootstrap 99% confidence intervals for the projected Gini coefficient and
projected mean degree of each cross-ecosystem sample, plus a Hill tail-index
estimate characterising how heavy each projected degree distribution's upper
tail is. Backs the sampling-adequacy paragraph of the manuscript's
cross-ecosystem section.

compute_gini and build_B_from_jsonl are duplicated from analyze_cross_ecosystem.py
rather than imported, so this script runs without that module's pandas dependency.
Projection and hub-exclusion logic mirrors compute_projected_degree_stats() there,
so the point estimates reproduce the published table exactly.

Usage: python scripts/bootstrap_cross_ecosystem_ci.py
"""
import json
from pathlib import Path
from collections import defaultdict
import numpy as np
import scipy.sparse as sp


def compute_gini(array):
    array = np.asarray(array, dtype=np.float64)
    if np.amin(array) < 0:
        array -= np.amin(array)
    array += 0.0000001
    array = np.sort(array)
    index = np.arange(1, array.shape[0] + 1)
    n = array.shape[0]
    return float((np.sum((2 * index - n - 1) * array)) / (n * np.sum(array)))


def build_B_from_jsonl(filepath):
    package_to_maint = defaultdict(list)
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line)
            except Exception:
                continue
            for m in data.get('maintainers', []):
                package_to_maint[data['package']].append(m)
    pkgs = list(package_to_maint.keys())
    pkg_to_idx = {p: i for i, p in enumerate(pkgs)}
    maint_to_idx = {}
    rows, cols = [], []
    for pkg, maints in package_to_maint.items():
        for m in maints:
            mi = maint_to_idx.setdefault(m, len(maint_to_idx))
            rows.append(pkg_to_idx[pkg]); cols.append(mi)
    return sp.csr_matrix((np.ones(len(rows)), (rows, cols)),
                         shape=(len(pkgs), len(maint_to_idx)))


def proj_degrees(B):
    maint_deg = B.getnnz(axis=0).astype(np.int64)
    sd = np.sort(maint_deg)
    safe = np.where(np.cumsum(sd ** 2) <= 50_000_000)[0]
    thr = sd[safe[-1]] if len(safe) else 0
    if len(sd) and sd[-1] > thr:
        B = B[:, maint_deg <= thr]
    n = B.shape[0]
    deg = np.zeros(n, dtype=np.int64)
    BT = B.T.tocsc()
    for i in range(0, n, 5000):
        end = min(i + 5000, n)
        cp = B[i:end, :] @ BT
        r, c = cp.nonzero()
        dm = (r + i) == c
        if np.any(dm):
            cp.data[dm] = 0
            cp.eliminate_zeros()
        deg[i:end] = cp.getnnz(axis=1)
    return deg.astype(np.float64)


rng = np.random.default_rng(20260804)
NB = 10000
base = Path(__file__).parent.parent / "data" / "cross_ecosystem"
out = {}
for eco in ["pypi", "crates", "rubygems"]:
    deg = proj_degrees(build_B_from_jsonl(base / f"{eco}_maintainers.jsonl"))
    n = len(deg)
    g_hat, m_hat = compute_gini(deg), float(deg.mean())
    gs, ms = np.empty(NB), np.empty(NB)
    for b in range(NB):
        s = deg[rng.integers(0, n, n)]
        gs[b] = compute_gini(s); ms[b] = s.mean()
    gl, gu = np.percentile(gs, [0.5, 99.5])
    ml, mu = np.percentile(ms, [0.5, 99.5])
    d_pos = np.sort(deg[deg > 0])[::-1]
    k = max(10, int(0.05 * len(d_pos)))
    hill = 1.0 / np.mean(np.log(d_pos[:k] / d_pos[k]))
    out[eco] = dict(n=n, gini=round(g_hat, 4), gini_ci=[round(gl, 4), round(gu, 4)],
                    gini_halfwidth=round((gu - gl) / 2, 4),
                    mean=round(m_hat, 3), mean_ci=[round(ml, 3), round(mu, 3)],
                    mean_rel_pct=round((mu - ml) / 2 / m_hat * 100, 2),
                    hill_alpha=round(float(hill), 3))
    print(eco, json.dumps(out[eco]), flush=True)
(Path(__file__).parent.parent / "data" / "cross_ecosystem" /
 "bootstrap_ci.json").write_text(json.dumps(out, indent=2))
