"""Priorytet 1/2 (akcja_naprawcza.md sec. 3.1/3.3): does the sequential
D -> B^T -> B worm (install, then steal, then republish -- scripts/
simulation_engine.py's new bilayer_mode) actually propagate multi-hop, or does
it die at the corpus boundary as the contingency plan (3.3) anticipated?

Three arms on the same 200 paired seeds used throughout the paper:
  A. Capacity ceiling  -- existing B-only bipartite_mode (beta_p=1.0):
                          the deterministic co-maintainer connected component,
                          an upper bound on what any credential-theft worm
                          could reach, already published.
  B. Dependency-only    -- existing D_ext-only unipartite (already published).
  C. Bilayer worm       -- NEW: D_ext -> B_ext^T -> B_ext, at beta=0.9
                          (=beta_steal, matched to the rest of the paper) and
                          beta_p=1.0 (=beta_pub, matching the paper's existing
                          worst-case-ceiling convention for the publish step).

Output: data/npm/bilayer_propagation_results.json
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
OUT = BASE / 'data' / 'npm' / 'bilayer_propagation_results.json'

BETA_STEAL = 0.9
BETA_PUB = 1.0
STEPS = 200
N_SEEDS = 200


def main():
    t_start = time.time()
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    _, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph(allowed_packages=pkg_set)
    gamma = float((BASE / 'data' / 'npm' / 'gamma_param.txt').read_text().strip())

    ext_pkg_list, D_ext, n_ext, _ = build_extended(pkg_list_univ, pkg_to_idx_univ)

    # CRITICAL: build_bipartite_graph's pkg_to_idx and load_node_universe's
    # pkg_to_idx_univ are DIFFERENT orderings of the same 213,162-package corpus
    # (verified empirically: 0/213,162 rows agree). run_beta_sweep_paired.py only
    # ever uses D_ext and B_ext standalone, each seeded in its own index space, so
    # this mismatch is silent there. A coupled D->B^T->B simulation needs both
    # matrices in ONE shared index space, so B_csr's rows are reindexed here into
    # pkg_to_idx_univ order before padding for the out-of-corpus nodes.
    inv_perm = np.empty(len(pkg_list_univ), dtype=np.int64)
    for name in pkg_list_univ:
        inv_perm[pkg_to_idx_univ[name]] = pkg_to_idx[name]
    B_reindexed = B_csr[inv_perm]
    B_ext = sp.vstack([B_reindexed, sp.csr_matrix((n_ext, B_csr.shape[1]))]).tocsr()

    # Self-check: seeding the reindexed B_ext by univ index must reproduce the
    # same per-seed reach as the published (bipartite-order) B_ext run.
    m_deg = np.diff(B_csr.tocsr().indptr)
    out_deg = np.diff(D_csr.indptr)
    cand = [(pkg_list_univ[i], i) for i in np.where(out_deg > 0)[0]
            if pkg_list_univ[i] in pkg_to_idx and m_deg[pkg_to_idx[pkg_list_univ[i]]] > 0]
    assert len(cand) == 1183, f'candidate frame changed: {len(cand)}'
    picks = np.random.default_rng(42).choice(len(cand), size=N_SEEDS, replace=False)

    pub = json.loads(PUBLISHED.read_text())
    reach_A_ceiling = np.array(pub['reach_B_pkgs'], float)      # capacity ceiling, already published
    reach_B_dep = np.array(pub['reach_D_extended_pkgs'], float)  # dependency-only, already published

    print('Running self-check: reindexed B_ext (bipartite_mode, beta_p=1.0) vs published reach_B_pkgs...',
          flush=True)
    reach_check = np.zeros(N_SEEDS)
    for k, j in enumerate(picks):
        name, i_univ = cand[j]
        sim = BranchingProcessSimulator(A_csr=None, B_csr=B_ext, beta=BETA_STEAL, gamma=gamma,
                                         bipartite_mode=True, beta_p=1.0, seed=42 + k)
        h = sim.run(max_steps=STEPS, initial_nodes=[i_univ])
        reach_check[k] = h[-1]['I'] + h[-1]['R']
    ok = np.array_equal(reach_check, reach_A_ceiling)
    print(f'SELF-CHECK reindexed B_ext reproduces published reach_B_pkgs exactly: {ok}')
    if not ok:
        print('  !! MISMATCH -- reindexing is wrong, refusing to report bilayer results.')
        return

    reach_C = np.zeros(N_SEEDS)
    n_hops = np.zeros(N_SEEDS)  # steps until extinction, as a cheap multi-hop indicator
    for k, j in enumerate(picks):
        name, i_univ = cand[j]
        # Seed must be given in the D_ext (=B_ext row) index space, which the
        # extended-universe construction keeps aligned for corpus packages.
        sim = BranchingProcessSimulator(A_csr=D_ext, B_csr=B_ext, beta=BETA_STEAL, gamma=gamma,
                                         bilayer_mode=True, beta_p=BETA_PUB, gamma_m=0.0, seed=42 + k)
        h = sim.run(max_steps=STEPS, initial_nodes=[i_univ])
        reach_C[k] = h[-1]['I'] + h[-1]['R']
        n_hops[k] = len(h) - 1

        if (k + 1) % 20 == 0:
            print(f'  {k + 1}/{N_SEEDS} seeds done  [{(time.time() - t_start) / 60:.1f} min elapsed]', flush=True)

    print('\n=== Three-arm comparison on 200 paired seeds ===')
    print(f'  A. Capacity ceiling (B-only, beta_p=1.0):  mean {reach_A_ceiling.mean():.1f}  '
          f'median {np.median(reach_A_ceiling):.1f}  max {reach_A_ceiling.max():.0f}')
    print(f'  B. Dependency-only (D_ext):                 mean {reach_B_dep.mean():.1f}  '
          f'median {np.median(reach_B_dep):.1f}  max {reach_B_dep.max():.0f}')
    print(f'  C. Bilayer worm (D_ext->B_ext^T->B_ext):    mean {reach_C.mean():.1f}  '
          f'median {np.median(reach_C):.1f}  max {reach_C.max():.0f}')
    print(f'\n  C reaches beyond its own seed on {(reach_C > 1).sum()}/{N_SEEDS} seeds')
    print(f'  C / A ratio (mean): {reach_C.mean() / max(reach_A_ceiling.mean(), 1e-9):.4f}')
    print(f'  C / B ratio (mean): {reach_C.mean() / max(reach_B_dep.mean(), 1e-9):.4f}')
    print(f'  mean steps to extinction (arm C): {n_hops.mean():.2f}')

    json.dump({
        'beta_steal': BETA_STEAL, 'beta_pub': BETA_PUB, 'gamma': gamma, 'steps': STEPS, 'n_seeds': N_SEEDS,
        'reach_A_capacity_ceiling': reach_A_ceiling.tolist(),
        'reach_B_dependency_only': reach_B_dep.tolist(),
        'reach_C_bilayer_worm': reach_C.tolist(),
        'n_hops_to_extinction_C': n_hops.tolist(),
    }, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}   total {(time.time() - t_start) / 60:.1f} min')


if __name__ == '__main__':
    main()
