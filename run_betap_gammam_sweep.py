"""Priorytet 0 (akcja_naprawcza.md sec. 3.2): does the 2.36x/12.4x headline
dominance factor survive once the co-maintainer arm is given the same kind of
stochastic republish step (beta_p < 1) and token-rotation recovery (gamma_m > 0)
that reviewer R2 says it is missing?

The published headline (run_stats200_fair_extended.py, reused by
run_beta_sweep_paired.py) hardcodes beta_p=1.0, gamma_m=0.0 for the
co-maintainer arm: an infected package deterministically compromises its
maintainer's WHOLE portfolio in one step, with no recovery. The dependency arm
has no equivalent "free" deterministic amplification step. This script holds
beta=0.9 (the matched compromise-probability parameter) fixed and sweeps
beta_p x gamma_m on the co-maintainer arm only, re-running the identical
Wilcoxon test against the (unaffected) dependency arm at every grid point.

Same seed frame, candidate list, draw and D_ext/B_ext construction as
run_beta_sweep_paired.py. The beta_p=1.0, gamma_m=0.0 cell must reproduce the
published per-seed B-arm reach array exactly; the script refuses to report if
it does not.

Output: data/npm/betap_gammam_sweep_200.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from scipy import stats

sys.path.append('scripts')
sys.path.append('.')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from simulation_engine import BranchingProcessSimulator
from run_stats200_fair_extended import build_extended

BASE = Path(__file__).parent
PUBLISHED = BASE / 'data' / 'npm' / 'random_seed_campaigns_200_fair_extended.json'
OUT = BASE / 'data' / 'npm' / 'betap_gammam_sweep_200.json'

BETA = 0.9
BETA_P_VALUES = [1.0, 0.9, 0.6, 0.3]
GAMMA_M_VALUES = [0.0, 0.05, 0.2]
STEPS = 200
N_SEEDS = 200


def main():
    t_start = time.time()
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    _, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph(allowed_packages=pkg_set)

    gamma = float((BASE / 'data' / 'npm' / 'gamma_param.txt').read_text().strip())

    ext_pkg_list, D_ext, n_ext, _ = build_extended(pkg_list_univ, pkg_to_idx_univ)
    B_ext = sp.vstack([B_csr, sp.csr_matrix((n_ext, B_csr.shape[1]))]).tocsr()

    print(f'N_corpus={len(pkg_list):,}  N_ext={len(ext_pkg_list):,}  '
          f'D_ext nnz={D_ext.nnz:,}  B_ext nnz={B_ext.nnz:,}  gamma={gamma}', flush=True)

    # --- identical candidate frame and identical draw as the published run ---
    m_deg = np.diff(B_csr.tocsr().indptr)
    out_deg = np.diff(D_csr.indptr)
    cand = [(pkg_list_univ[i], i) for i in np.where(out_deg > 0)[0]
            if pkg_list_univ[i] in pkg_to_idx and m_deg[pkg_to_idx[pkg_list_univ[i]]] > 0]
    assert len(cand) == 1183, f'candidate frame changed: {len(cand)}'
    picks = np.random.default_rng(42).choice(len(cand), size=N_SEEDS, replace=False)

    # --- dependency arm: unaffected by beta_p/gamma_m, compute once ----------
    reach_D = np.zeros(N_SEEDS)
    for k, j in enumerate(picks):
        name, i_univ = cand[j]
        sim = BranchingProcessSimulator(A_csr=D_ext, B_csr=None, beta=BETA, gamma=gamma,
                                         bipartite_mode=False, seed=42 + k)
        h = sim.run(max_steps=STEPS, initial_nodes=[i_univ])
        reach_D[k] = h[-1]['I'] + h[-1]['R']

    pub = json.loads(PUBLISHED.read_text())
    ok_D = np.array_equal(reach_D, np.array(pub['reach_D_extended_pkgs'], float))
    print(f'\nSELF-CHECK dependency arm reproduces published array exactly: {ok_D}')
    if not ok_D:
        print('  !! MISMATCH -- refusing to report. Investigate before using any number below.')
        return

    # --- co-maintainer arm: sweep beta_p x gamma_m ----------------------------
    grid = {}
    total = len(BETA_P_VALUES) * len(GAMMA_M_VALUES)
    done = 0
    for beta_p in BETA_P_VALUES:
        for gamma_m in GAMMA_M_VALUES:
            reach_B = np.zeros(N_SEEDS)
            for k, j in enumerate(picks):
                name, i_univ = cand[j]
                sim = BranchingProcessSimulator(A_csr=None, B_csr=B_ext, beta=BETA, gamma=gamma,
                                                 bipartite_mode=True, beta_p=beta_p, gamma_m=gamma_m,
                                                 seed=42 + k)
                h = sim.run(max_steps=STEPS, initial_nodes=[pkg_to_idx[name]])
                reach_B[k] = h[-1]['I'] + h[-1]['R']

            if beta_p == 1.0 and gamma_m == 0.0:
                ok_B = np.array_equal(reach_B, np.array(pub['reach_B_pkgs'], float))
                print(f'SELF-CHECK co-maintainer arm (beta_p=1.0, gamma_m=0.0) reproduces published array exactly: {ok_B}')
                if not ok_B:
                    print('  !! MISMATCH -- refusing to report. Investigate before using any number below.')
                    return

            ratio_mean = reach_B.mean() / max(reach_D.mean(), 1e-12)
            ratio_median = float(np.median(reach_B)) / max(float(np.median(reach_D)), 1e-12)
            w = stats.wilcoxon(reach_B, reach_D, alternative='greater', zero_method='zsplit')
            bt = np.random.default_rng(7).integers(0, N_SEEDS, size=(10000, N_SEEDS))
            ratios = reach_B[bt].mean(axis=1) / np.maximum(reach_D[bt].mean(axis=1), 1e-12)

            key = f'{beta_p}|{gamma_m}'
            grid[key] = {
                'beta_p': beta_p, 'gamma_m': gamma_m,
                'mean_B': float(reach_B.mean()), 'mean_D': float(reach_D.mean()),
                'median_B': float(np.median(reach_B)), 'median_D': float(np.median(reach_D)),
                'ratio_mean': float(ratio_mean), 'ratio_median': float(ratio_median),
                'ci_lo': float(np.percentile(ratios, 2.5)), 'ci_hi': float(np.percentile(ratios, 97.5)),
                'W': float(w.statistic), 'p': float(w.pvalue),
                'B_wins': int((reach_B > reach_D).sum()), 'D_wins': int((reach_B < reach_D).sum()),
                'B_zero_reach': int((reach_B <= 1).sum()),
            }
            done += 1
            el = time.time() - t_start
            print(f'  [{done}/{total}] beta_p={beta_p} gamma_m={gamma_m}: '
                  f'mean {reach_B.mean():.1f} vs {reach_D.mean():.1f} -> {ratio_mean:.2f}x  '
                  f'median {ratio_median:.1f}x  p={w.pvalue:.2e}  [{el / 60:.1f} min elapsed]',
                  flush=True)

    print(f'\n{"beta_p":>7} {"gamma_m":>8} {"mean ratio":>11} {"median ratio":>13} {"p":>11}')
    for beta_p in BETA_P_VALUES:
        for gamma_m in GAMMA_M_VALUES:
            g = grid[f'{beta_p}|{gamma_m}']
            print(f'  {beta_p:>6} {gamma_m:>8} {g["ratio_mean"]:>10.2f}x '
                  f'{g["ratio_median"]:>12.1f}x {g["p"]:>11.2e}')

    json.dump({
        'beta': BETA, 'beta_p_values': BETA_P_VALUES, 'gamma_m_values': GAMMA_M_VALUES,
        'gamma': gamma, 'steps': STEPS, 'n_seeds': N_SEEDS,
        'self_check_D_matches_published': True,
        'self_check_B_betap1_gammam0_matches_published': True,
        'reach_D': reach_D.tolist(),
        'grid': grid,
    }, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}   total {(time.time() - t_start) / 60:.1f} min')


if __name__ == '__main__':
    main()
