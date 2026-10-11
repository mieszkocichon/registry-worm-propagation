"""Robustness pass for the bilayer worm result (run_bilayer_evaluation.py),
matching the scrutiny already applied to the paper's other headline numbers
(beta sweep at line 797, beta_p/gamma_m sweep at line 803): before Result C
becomes a first-class finding in the paper, check it is not an artifact of
the single (beta_steal=0.9, beta_pub=1.0, gamma_m=0.0) point reported there.

Sweeps beta_steal in {0.3, 0.6, 0.9} (credential-theft probability on install
exposure) x gamma_m in {0.0, 0.05, 0.2} (token rotation) at beta_pub=1.0 fixed
(the paper's existing worst-case-ceiling convention for the publish step,
already justified at line 803: beta_p governs speed, not final size, absent
rotation). Same 200 paired seeds, same D_ext/B_ext reindexing and self-check
as run_bilayer_evaluation.py.

Output: data/npm/bilayer_sensitivity_sweep_200.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from simulation_engine import BranchingProcessSimulator
from run_stats200_fair_extended import build_extended

BASE = Path(__file__).parent
PUBLISHED = BASE / 'data' / 'npm' / 'random_seed_campaigns_200_fair_extended.json'
OUT = BASE / 'data' / 'npm' / 'bilayer_sensitivity_sweep_200.json'

BETA_STEAL_VALUES = [0.3, 0.6, 0.9]
GAMMA_M_VALUES = [0.0, 0.05, 0.2]
BETA_PUB = 1.0
STEPS = 200
N_SEEDS = 200


def main():
    t_start = time.time()
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    _, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph(allowed_packages=pkg_set)
    gamma = float((BASE / 'data' / 'npm' / 'gamma_param.txt').read_text().strip())
    ext_pkg_list, D_ext, n_ext, _ = build_extended(pkg_list_univ, pkg_to_idx_univ)

    inv_perm = np.empty(len(pkg_list_univ), dtype=np.int64)
    for name in pkg_list_univ:
        inv_perm[pkg_to_idx_univ[name]] = pkg_to_idx[name]
    B_reindexed = B_csr[inv_perm]
    B_ext = sp.vstack([B_reindexed, sp.csr_matrix((n_ext, B_csr.shape[1]))]).tocsr()

    m_deg = np.diff(B_csr.tocsr().indptr)
    out_deg = np.diff(D_csr.indptr)
    cand = [(pkg_list_univ[i], i) for i in np.where(out_deg > 0)[0]
            if pkg_list_univ[i] in pkg_to_idx and m_deg[pkg_to_idx[pkg_list_univ[i]]] > 0]
    assert len(cand) == 1183, f'candidate frame changed: {len(cand)}'
    picks = np.random.default_rng(42).choice(len(cand), size=N_SEEDS, replace=False)

    pub = json.loads(PUBLISHED.read_text())
    reach_A_ceiling = np.array(pub['reach_B_pkgs'], float)
    reach_B_dep = np.array(pub['reach_D_extended_pkgs'], float)

    grid = {}
    total = len(BETA_STEAL_VALUES) * len(GAMMA_M_VALUES)
    done = 0
    for beta_steal in BETA_STEAL_VALUES:
        for gamma_m in GAMMA_M_VALUES:
            reach_C = np.zeros(N_SEEDS)
            for k, j in enumerate(picks):
                name, i_univ = cand[j]
                sim = BranchingProcessSimulator(A_csr=D_ext, B_csr=B_ext, beta=beta_steal, gamma=gamma,
                                                 bilayer_mode=True, beta_p=BETA_PUB, gamma_m=gamma_m, seed=42 + k)
                h = sim.run(max_steps=STEPS, initial_nodes=[i_univ])
                reach_C[k] = h[-1]['I'] + h[-1]['R']

            key = f'{beta_steal}|{gamma_m}'
            grid[key] = {
                'beta_steal': beta_steal, 'gamma_m': gamma_m,
                'mean_C': float(reach_C.mean()), 'median_C': float(np.median(reach_C)), 'max_C': float(reach_C.max()),
                'ratio_vs_A_ceiling': float(reach_C.mean() / max(reach_A_ceiling.mean(), 1e-9)),
                'ratio_vs_B_dependency': float(reach_C.mean() / max(reach_B_dep.mean(), 1e-9)),
                'seeds_beyond_own': int((reach_C > 1).sum()),
            }
            done += 1
            el = time.time() - t_start
            print(f'[{done}/{total}] beta_steal={beta_steal} gamma_m={gamma_m}: '
                  f'mean {reach_C.mean():.1f}  median {np.median(reach_C):.1f}  '
                  f'C/A={grid[key]["ratio_vs_A_ceiling"]:.2f}x  C/B={grid[key]["ratio_vs_B_dependency"]:.2f}x  '
                  f'[{el / 60:.1f} min elapsed]', flush=True)

    print(f'\n{"beta_steal":>10} {"gamma_m":>8} {"mean C":>8} {"median C":>9} {"C/A":>7} {"C/B":>7}')
    for beta_steal in BETA_STEAL_VALUES:
        for gamma_m in GAMMA_M_VALUES:
            g = grid[f'{beta_steal}|{gamma_m}']
            print(f'  {beta_steal:>8} {gamma_m:>8} {g["mean_C"]:>8.1f} {g["median_C"]:>9.1f} '
                  f'{g["ratio_vs_A_ceiling"]:>6.2f}x {g["ratio_vs_B_dependency"]:>6.2f}x')

    json.dump({
        'beta_steal_values': BETA_STEAL_VALUES, 'gamma_m_values': GAMMA_M_VALUES, 'beta_pub': BETA_PUB,
        'gamma': gamma, 'steps': STEPS, 'n_seeds': N_SEEDS,
        'reach_A_ceiling_mean': float(reach_A_ceiling.mean()),
        'reach_B_dependency_mean': float(reach_B_dep.mean()),
        'grid': grid,
    }, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}   total {(time.time() - t_start) / 60:.1f} min')


if __name__ == '__main__':
    main()
