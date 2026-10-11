"""ETAP 4c: the dependency channel at the transmission rate the paper itself
argues is realistic.

The headline comparison holds beta = 0.9 identical on both channels, which is
the right way to isolate topology. But Section 5 also argues, and sweeps, a
dependency-adoption band beta_dep = beta * ratio with ratio in {0.05, 0.1, 0.2}:
a stolen token republishes deterministically, whereas a dependency edge fires
only when a downstream maintainer voluntarily accepts a new version. That band
is applied only to the 10 historical seeds in the published work, never to the
200-seed frame the dominance factor comes from.

So the headline is measured with the dependency channel running 5-20x faster
than the paper's own model of it. This quantifies how much of the result that
concession is buying, on D_ext, over the identical 200 seeds.

beta_p < 1 is not involved here; only the dependency channel's beta moves.
The ratio = 1.0 row must reproduce the stored D_ext series exactly.
"""
import json
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from simulation_engine import BranchingProcessSimulator

BASE = Path(__file__).parent
NPM = BASE / 'data' / 'npm' / 'npm_metadata.jsonl'
EXT = BASE / 'data' / 'npm' / 'random_seed_campaigns_200_fair_extended.json'
RATIOS = (0.05, 0.1, 0.2, 1.0)
MC = 10  # beta < 1 is stochastic


def main():
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    _, pkg_list, pkg_to_idx, _, _, B_csr = build_bipartite_graph(allowed_packages=pkg_set)
    gamma = float((BASE / 'data' / 'npm' / 'gamma_param.txt').read_text().strip())
    beta = 0.9
    corpus = set(pkg_list_univ)

    edges, ext = [], set()
    with open(NPM, 'r', encoding='utf-8') as f:
        for line in f:
            d = json.loads(line)
            if d['package'] not in corpus:
                continue
            for t in d.get('dependents', []) or []:
                edges.append((d['package'], t))
                if t not in corpus:
                    ext.add(t)
    idx = dict(pkg_to_idx_univ)
    for i, p in enumerate(sorted(ext), start=len(pkg_list_univ)):
        idx[p] = i
    n = len(pkg_list_univ) + len(ext)
    D_ext = sp.csr_matrix((np.ones(len(edges)),
                           (np.fromiter((idx[s] for s, _ in edges), np.int64, len(edges)),
                            np.fromiter((idx[t] for _, t in edges), np.int64, len(edges)))),
                          shape=(n, n))

    m_deg = np.diff(B_csr.tocsr().indptr)
    out_deg = np.diff(D_csr.indptr)
    cand = [(pkg_list_univ[i], i) for i in np.where(out_deg > 0)[0]
            if pkg_list_univ[i] in pkg_to_idx and m_deg[pkg_to_idx[pkg_list_univ[i]]] > 0]
    picks = np.random.default_rng(42).choice(len(cand), size=200, replace=False)

    stored = json.loads(EXT.read_text())
    rb = np.array(stored['reach_B_pkgs'], float)
    print(f'co-maintainer reference: mean {rb.mean():.1f}, median {np.median(rb):.1f} pkgs\n')

    for ratio in RATIOS:
        runs = 1 if ratio == 1.0 else MC
        per_seed = np.zeros(len(picks))
        for k, j in enumerate(picks):
            vals = []
            for r in range(runs):
                sim = BranchingProcessSimulator(A_csr=D_ext, B_csr=None, beta=beta * ratio,
                                                gamma=gamma, bipartite_mode=False,
                                                seed=42 + k + 100000 * r)
                h = sim.run(max_steps=200, initial_nodes=[cand[j][1]])
                vals.append(h[-1]['I'] + h[-1]['R'])
            per_seed[k] = np.mean(vals)

        if ratio == 1.0:
            ok = np.array_equal(per_seed, np.array(stored['reach_D_extended_pkgs'], float))
            print(f'  [self-check] ratio=1.0 reproduces stored D_ext series: {ok}')
            if not ok:
                print('  !! MISMATCH -- aborting.')
                return

        print(f'  beta_dep ratio {ratio:<5}: D_ext mean {per_seed.mean():7.1f}  '
              f'median {np.median(per_seed):6.1f}  max {per_seed.max():7.0f}  '
              f'-> dominance {rb.mean() / per_seed.mean():5.2f}x mean, '
              f'{np.median(rb) / max(np.median(per_seed), 1e-9):5.1f}x median')


if __name__ == '__main__':
    main()
