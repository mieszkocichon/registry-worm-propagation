"""Projected co-maintainer degree statistics for the treatment corpus, after the
registry account exclusion. Feeds the Mean/Maximum Degree rows of Table 2 and
npm's own row of the cross-ecosystem table.

Uses analyze_cross_ecosystem.compute_projected_degree_stats so the npm numbers
are produced by exactly the same code path as the PyPI/crates.io/RubyGems ones.
"""
import json, sys
import numpy as np

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from analyze_cross_ecosystem import compute_projected_degree_stats, compute_gini


def main():
    pkg_set, _, _, D_csr = load_node_universe()
    _, pkg_list, _, m_list, _, B = build_bipartite_graph(allowed_packages=pkg_set)
    N = len(pkg_list)

    deg = B.getnnz(axis=0)
    print(f'B: {N} x {len(m_list)}, {B.nnz} edges')
    print(f'  maintainer mean degree   {deg.mean():.3f}')
    print(f'  maintainer max degree    {int(deg.max())}  ({m_list[int(deg.argmax())]})')
    print(f'  maintainer Gini          {compute_gini(deg.astype(np.float64)):.3f}')
    print(f'  packages with 0 maintainers {int((B.getnnz(axis=1) == 0).sum())}')

    s = compute_projected_degree_stats(B)
    print('  projected P = B.B^T:')
    for k, v in s.items():
        print(f'    {k:<28s} {v}')
    thr = np.sort(deg)[::-1]
    if s['hub_maintainers_excluded']:
        print(f'    truncation tau (largest retained degree) '
              f'{int(thr[s["hub_maintainers_excluded"]])}')

    d_out = np.diff(D_csr.indptr)
    print(f'D: {D_csr.nnz} edges, mean degree {D_csr.nnz / N:.4f}, '
          f'max out-degree {int(d_out.max())}')

    json.dump({'N': N, 'n_maintainers': len(m_list), 'edges': int(B.nnz),
               'maint_mean_degree': float(deg.mean()), 'maint_max_degree': int(deg.max()),
               'maint_max_account': m_list[int(deg.argmax())],
               'maint_gini': compute_gini(deg.astype(np.float64)),
               'dep_mean_degree': D_csr.nnz / N, 'dep_max_out_degree': int(d_out.max()),
               **s}, open('data/npm/projection_stats.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
