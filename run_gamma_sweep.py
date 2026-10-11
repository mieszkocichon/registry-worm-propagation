"""Recovery-rate sensitivity sweep for the co-maintainer channel, over the SAME
200 random seeds used for Table 2 (run_stats200_fair.py), so the gamma row at
0.00281 reproduces the headline mean exactly.
"""
import json, sys
import numpy as np

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from simulation_engine import BranchingProcessSimulator


def main():
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    npm_meta, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph(allowed_packages=pkg_set)

    beta = 0.9
    steps = 200
    N = len(pkg_list)

    # identical candidate pool and draw as run_stats200_fair.py
    m_deg = np.diff(B_csr.tocsr().indptr)
    out_deg = np.diff(D_csr.indptr)
    cand = [(pkg_list_univ[i], i) for i in np.where(out_deg > 0)[0]
            if pkg_list_univ[i] in pkg_to_idx and m_deg[pkg_to_idx[pkg_list_univ[i]]] > 0]
    rng = np.random.default_rng(42)
    picks = rng.choice(len(cand), size=200, replace=False)

    print(f'gamma      mean_reach%   max_reach%')
    rows = {}
    for gamma in (0.0, 0.001, 0.0028080728776521983, 0.005, 0.01):
        reach = []
        for k, j in enumerate(picks):
            name, _ = cand[j]
            sim = BranchingProcessSimulator(A_csr=None, B_csr=B_csr, beta=beta, gamma=gamma,
                                            bipartite_mode=True, beta_p=1.0, seed=42 + k)
            h = sim.run(max_steps=steps, initial_nodes=[pkg_to_idx[name]])
            reach.append(h[-1]['I'] + h[-1]['R'])
        pct = np.array(reach, dtype=float) / N * 100
        rows[gamma] = [pct.mean(), pct.max()]
        print(f'{gamma:<10.5f} {pct.mean():>10.4f}   {pct.max():>10.4f}', flush=True)

    json.dump(rows, open('data/npm/gamma_sweep_200seed.json', 'w'))


if __name__ == '__main__':
    main()
