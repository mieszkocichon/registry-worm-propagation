"""R3 (akcja_naprawcza.md sec. 2/3.1): empirical delta against Zimmermann et al.
(USENIX Security 2019), who measure a maintainer's *static downstream trust*:
how many packages transitively depend on something that account maintains,
i.e. how many consumers inherit a compromise. That is a one-shot closure on
the DEPENDENCY graph (D_ext), seeded from the account's whole portfolio, at
beta=1.0/gamma=0 -- no propagation model, just "what's reachable".

This script computes that static Zimmermann-style reach for the same 200
paired seeds used by the published headline result
(random_seed_campaigns_200_fair_extended.json) and reports it next to the two
DYNAMIC reach numbers already stored there:
  - reach_B_pkgs             : co-maintainer worm reach (this paper's channel)
  - reach_D_extended_pkgs    : dependency worm reach (this paper's channel)
No new data or scraping needed -- reuses D_ext/B_ext construction identical to
run_beta_sweep_paired.py / run_dep_ceiling_extended.py.

Output: data/npm/zimmermann_baseline_comparison.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from run_stats200_fair_extended import build_extended

BASE = Path(__file__).parent
PUBLISHED = BASE / 'data' / 'npm' / 'random_seed_campaigns_200_fair_extended.json'
OUT = BASE / 'data' / 'npm' / 'zimmermann_baseline_comparison.json'


def transitive_closure(D_ext, seeds):
    """beta=1.0, gamma=0 forward closure -- the Zimmermann-style 'everything
    reachable downstream is at risk' reading, seeded from a whole portfolio
    at once rather than one package."""
    n = D_ext.shape[0]
    seen = np.zeros(n, dtype=bool)
    seen[seeds] = True
    frontier = np.array(sorted(set(seeds)))
    while len(frontier):
        nxt = np.unique(D_ext[frontier].indices)
        nxt = nxt[~seen[nxt]]
        seen[nxt] = True
        frontier = nxt
    return int(seen.sum())


def main():
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    _, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph(allowed_packages=pkg_set)
    ext_pkg_list, D_ext, n_ext, _ = build_extended(pkg_list_univ, pkg_to_idx_univ)
    B_ext = sp.vstack([B_csr, sp.csr_matrix((n_ext, B_csr.shape[1]))]).tocsr()

    pub = json.loads(PUBLISHED.read_text())
    reach_B = pub['reach_B_pkgs']
    reach_D = pub['reach_D_extended_pkgs']
    assert len(reach_B) == len(reach_D) == 200, \
        f'unexpected reach lengths: {len(reach_B)}, {len(reach_D)}'

    # Published JSON does not store the seed package names -- reconstruct the
    # identical candidate frame and draw used by run_beta_sweep_paired.py /
    # run_stats200_fair_extended.py so per-seed rows line up with reach_B/reach_D.
    m_deg = np.diff(B_csr.tocsr().indptr)
    out_deg = np.diff(D_csr.indptr)
    cand = [(pkg_list_univ[i], i) for i in np.where(out_deg > 0)[0]
            if pkg_list_univ[i] in pkg_to_idx and m_deg[pkg_to_idx[pkg_list_univ[i]]] > 0]
    assert len(cand) == 1183, f'candidate frame changed: {len(cand)}'
    picks = np.random.default_rng(42).choice(len(cand), size=200, replace=False)
    seed_names = [cand[j][0] for j in picks]

    B_csc = B_ext.tocsc()
    rows = []
    for k, name in enumerate(seed_names):
        # B_ext is indexed in the bipartite-graph's own package order (pkg_to_idx),
        # which is NOT the same index space as pkg_to_idx_univ (the D-graph order) --
        # run_beta_sweep_paired.py seeds B_ext with pkg_to_idx[name] for exactly this
        # reason. D_ext below correctly uses pkg_to_idx_univ.
        i_b = pkg_to_idx[name]
        maintainers = B_ext[i_b].indices
        portfolio_b = np.unique(B_csc[:, maintainers].indices) if len(maintainers) else np.array([i_b])
        # Translate portfolio from bipartite-graph index space to D_ext (univ) index
        # space via package name before touching D_ext -- the two spaces are not
        # interchangeable (see note above).
        portfolio = np.fromiter((pkg_to_idx_univ[pkg_list[p]] for p in portfolio_b),
                                 dtype=np.int64, count=len(portfolio_b))
        static_1hop = int(len(np.unique(D_ext[portfolio].indices))) if len(portfolio) else 0
        static_transitive = transitive_closure(D_ext, portfolio)

        rows.append({
            'seed_package': name,
            'portfolio_size': int(len(portfolio)),
            'zimmermann_static_1hop': static_1hop,
            'zimmermann_static_transitive': static_transitive,
            'this_paper_dynamic_comaintainer_reach': float(reach_B[k]),
            'this_paper_dynamic_dependency_reach': float(reach_D[k]),
        })
        if (k + 1) % 20 == 0:
            print(f'  {k + 1}/200 seeds processed', flush=True)

    portfolio_sizes = np.array([r['portfolio_size'] for r in rows], float)
    static_1hop = np.array([r['zimmermann_static_1hop'] for r in rows], float)
    static_trans = np.array([r['zimmermann_static_transitive'] for r in rows], float)
    dyn_B = np.array([r['this_paper_dynamic_comaintainer_reach'] for r in rows], float)
    dyn_D = np.array([r['this_paper_dynamic_dependency_reach'] for r in rows], float)

    def corr(a, b):
        return float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else float('nan')

    summary = {
        'n_seeds': 200,
        'mean_portfolio_size': float(portfolio_sizes.mean()),
        'mean_zimmermann_static_1hop': float(static_1hop.mean()),
        'mean_zimmermann_static_transitive': float(static_trans.mean()),
        'mean_dynamic_comaintainer_reach': float(dyn_B.mean()),
        'mean_dynamic_dependency_reach': float(dyn_D.mean()),
        'corr_static_transitive_vs_dynamic_comaintainer': corr(static_trans, dyn_B),
        'corr_static_transitive_vs_dynamic_dependency': corr(static_trans, dyn_D),
        'corr_portfolio_size_vs_dynamic_comaintainer': corr(portfolio_sizes, dyn_B),
    }

    print('\n=== Zimmermann static baseline vs. this paper\'s dynamic channels (200 paired seeds) ===')
    for k, v in summary.items():
        print(f'  {k}: {v:.4f}' if isinstance(v, float) else f'  {k}: {v}')

    json.dump({'summary': summary, 'per_seed': rows}, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
