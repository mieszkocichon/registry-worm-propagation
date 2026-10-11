import sys
import json
import numpy as np
import scipy.sparse as sp
import pandas as pd
from pathlib import Path
from collections import defaultdict

sys.path.append(str(Path(__file__).parent))
from graph_builder import build_bipartite_graph


def compute_gini(array):
    """Calculates the Gini coefficient of a numpy array or list."""
    array = np.asarray(array, dtype=np.float64)
    if np.amin(array) < 0:
        array -= np.amin(array)
    array += 0.0000001
    array = np.sort(array)
    index = np.arange(1, array.shape[0] + 1)
    n = array.shape[0]
    return float((np.sum((2 * index - n - 1) * array)) / (n * np.sum(array)))


def build_B_from_jsonl(filepath):
    """
    Builds a package x maintainer sparse bipartite matrix from a cross-
    ecosystem maintainers JSONL. Maintainers are already bot-filtered at
    fetch time (fetch_cross_ecosystem_metrics.py applies is_bot() before
    writing), matching the npm pipeline's filtering.
    """
    package_to_maint = defaultdict(list)
    total_packages = 0
    osv_packages = 0
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line)
            except Exception:
                continue
            pkg = data['package']
            total_packages += 1
            if data.get('is_osv_vulnerable'):
                osv_packages += 1
            for m in data.get('maintainers', []):
                package_to_maint[pkg].append(m)

    pkgs = list(package_to_maint.keys())
    pkg_to_idx = {p: i for i, p in enumerate(pkgs)}
    maint_to_idx = {}
    rows, cols = [], []
    for pkg, maints in package_to_maint.items():
        pi = pkg_to_idx[pkg]
        for m in maints:
            mi = maint_to_idx.setdefault(m, len(maint_to_idx))
            rows.append(pi)
            cols.append(mi)
    B = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(pkgs), len(maint_to_idx)))
    return B, total_packages, osv_packages


def compute_projected_degree_stats(B):
    """
    Projects the package-maintainer bipartite graph B into a package-package
    co-maintainer graph (P = B @ B.T), using the same chunked matmul +
    dynamic nnz-budget hub exclusion as the npm B_csr projection (see
    ADR-0013 / notebook 05), so mean/max degree are directly comparable to
    npm's headline projected-graph numbers rather than raw maintainer counts.
    """
    n = B.shape[0]
    if n == 0 or B.nnz == 0:
        return None

    maint_degrees = B.getnnz(axis=0).astype(np.int64)
    sorted_degrees = np.sort(maint_degrees)
    cumulative_nnz = np.cumsum(sorted_degrees ** 2)
    budget = 50_000_000
    safe = np.where(cumulative_nnz <= budget)[0]
    threshold = sorted_degrees[safe[-1]] if len(safe) > 0 else 0

    n_excluded = 0
    if len(sorted_degrees) and sorted_degrees[-1] > threshold:
        keep_mask = maint_degrees <= threshold
        n_excluded = int((~keep_mask).sum())
        B = B[:, keep_mask]

    chunk_size = 5000
    deg = np.zeros(n, dtype=np.int64)
    B_T = B.T.tocsc()
    for i in range(0, n, chunk_size):
        end = min(i + chunk_size, n)
        chunk_proj = B[i:end, :] @ B_T
        r, c = chunk_proj.nonzero()
        diag_mask = (r + i) == c
        if np.any(diag_mask):
            chunk_proj.data[diag_mask] = 0
            chunk_proj.eliminate_zeros()
        deg[i:end] = chunk_proj.getnnz(axis=1)

    return {
        "projected_mean_degree": round(float(deg.mean()), 3),
        "projected_median_degree": float(np.median(deg)),
        "projected_max_degree": int(deg.max()),
        "projected_gini": round(compute_gini(deg.astype(np.float64)), 3),
        "hub_maintainers_excluded": n_excluded,
    }


def compute_maintainer_side_stats(B, total_packages, osv_packages):
    """
    Raw bipartite maintainer-degree stats (packages owned per maintainer).
    Kept as a secondary view -- NOT directly comparable to npm's headline
    projected-graph mean degree, since it's a different metric (maintainer
    fan-out vs. package-to-package co-maintainer reach).
    """
    maintainer_degrees = B.getnnz(axis=0)
    if len(maintainer_degrees) == 0:
        return None
    sorted_degrees = np.sort(maintainer_degrees)[::-1]
    total_maintainers = len(maintainer_degrees)
    top_1pct_count = max(1, int(np.ceil(0.01 * total_maintainers)))
    top_1pct_pkgs = sorted_degrees[:top_1pct_count].sum()
    return {
        "total_packages": total_packages,
        "osv_packages": osv_packages,
        "total_maintainers": total_maintainers,
        "maint_mean_degree": round(float(maintainer_degrees.mean()), 3),
        "maint_max_degree": int(maintainer_degrees.max()),
        "maint_gini": round(compute_gini(maintainer_degrees.astype(np.float64)), 3),
        "top_1pct_hub_ratio_pct": round(float(top_1pct_pkgs / max(1, total_packages) * 100), 2),
    }


def main():
    base_dir = Path(__file__).parent.parent
    cross_dir = base_dir / "data" / "cross_ecosystem"
    results = {}

    print("Analyzing npm primary corpus (B_csr, bot-filtered, cached)...")
    _, pkg_list, _, _, _, B_npm = build_bipartite_graph()
    stats = compute_maintainer_side_stats(B_npm, len(pkg_list), None) or {}
    stats.update(compute_projected_degree_stats(B_npm) or {})
    results["npm"] = stats

    for reg in ["pypi", "crates", "rubygems"]:
        jsonl_path = cross_dir / f"{reg}_maintainers.jsonl"
        if not jsonl_path.exists():
            continue
        print(f"Analyzing {reg} dataset...")
        B, total_packages, osv_packages = build_B_from_jsonl(jsonl_path)
        stats = compute_maintainer_side_stats(B, total_packages, osv_packages) or {}
        stats.update(compute_projected_degree_stats(B) or {})
        results[reg] = stats

    df = pd.DataFrame.from_dict(results, orient='index')
    print("\n=================== CROSS-ECOSYSTEM TOPOLOGICAL SUMMARY ===================")
    print(df.to_string())

    out_csv = base_dir / 'figures' / "cross_ecosystem_comparison_table.csv"
    df.to_csv(out_csv)
    print(f"\nSaved summary table to {out_csv}")


if __name__ == "__main__":
    main()
