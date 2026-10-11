"""R5 (akcja_naprawcza.md): staged publishing was implemented in the bilayer
engine (staged_publishing_delay) but never evaluated at corpus scale or
written into the manuscript -- the word "staged" appeared 0 times in the
text. This sweep does the missing evaluation.

Staged publishing only has a protective effect if a pending release can be
cancelled before it goes live (scripts/simulation_engine.py: a queued
republish now checks whether the account is still compromised at release
time). Delay alone, with gamma_m = 0, should reproduce the paper's
established "governs speed, not size" pattern: nothing to cancel against
because credentials never rotate. Delay combined with gamma_m > 0 should
show the delay window giving token rotation something to catch.

Sweeps staged_publishing_delay in {0, 3, 7} x gamma_m in {0, 0.05, 0.2} on
the same 200 paired seeds as run_bilayer_evaluation.py, at beta_steal=0.9,
beta_pub=1.0 (matching the bilayer headline convention).

Output: data/npm/staged_publishing_sweep_200.json
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
OUT = BASE / 'data' / 'npm' / 'staged_publishing_sweep_200.json'

BETA_STEAL = 0.9
BETA_PUB = 1.0
DELAYS = [0, 3, 7]
GAMMA_M_VALUES = [0.0, 0.05, 0.2]
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

    grid = {}
    total = len(DELAYS) * len(GAMMA_M_VALUES)
    done = 0
    for delay in DELAYS:
        for gamma_m in GAMMA_M_VALUES:
            reach = np.zeros(N_SEEDS)
            for k, j in enumerate(picks):
                name, i_univ = cand[j]
                sim = BranchingProcessSimulator(A_csr=D_ext, B_csr=B_ext, beta=BETA_STEAL, gamma=gamma,
                                                 bilayer_mode=True, beta_p=BETA_PUB, gamma_m=gamma_m,
                                                 staged_publishing_delay=delay, seed=42 + k)
                h = sim.run(max_steps=STEPS, initial_nodes=[i_univ])
                reach[k] = h[-1]['I'] + h[-1]['R']

            key = f'{delay}|{gamma_m}'
            grid[key] = {
                'delay': delay, 'gamma_m': gamma_m,
                'mean': float(reach.mean()), 'median': float(np.median(reach)), 'max': float(reach.max()),
            }
            done += 1
            el = time.time() - t_start
            print(f'[{done}/{total}] delay={delay} gamma_m={gamma_m}: '
                  f'mean {reach.mean():.1f}  median {np.median(reach):.1f}  [{el / 60:.1f} min elapsed]',
                  flush=True)

    baseline = grid['0|0.0']['mean']
    print(f'\n{"delay":>6} {"gamma_m":>8} {"mean":>8} {"median":>8} {"vs delay=0,gamma_m=0":>10}')
    for delay in DELAYS:
        for gamma_m in GAMMA_M_VALUES:
            g = grid[f'{delay}|{gamma_m}']
            print(f'  {delay:>4} {gamma_m:>8} {g["mean"]:>8.1f} {g["median"]:>8.1f} '
                  f'{g["mean"] / baseline:>9.3f}x')

    json.dump({
        'beta_steal': BETA_STEAL, 'beta_pub': BETA_PUB, 'gamma': gamma,
        'delays': DELAYS, 'gamma_m_values': GAMMA_M_VALUES, 'steps': STEPS, 'n_seeds': N_SEEDS,
        'grid': grid,
    }, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}   total {(time.time() - t_start) / 60:.1f} min')


if __name__ == '__main__':
    main()
