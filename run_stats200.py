"""Regenerate the 200-seed randomized-campaign table (manuscript Table 2)
under the CURRENT simulation_engine, so the paper's headline numbers have
reproducible provenance.

Protocol (as described in results_statistical_test.txt):
  200 single-package campaigns seeded from randomly-chosen packages that have
  at least one outgoing D_csr edge (a fair test of the dependency channel),
  run on BOTH channels from the identical seed, matched beta.
"""
import json, sys
import numpy as np
import scipy.sparse as sp
from scipy import stats

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from simulation_engine import BranchingProcessSimulator


def main():
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    npm_meta, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph(allowed_packages=pkg_set)

    with open('data/npm/gamma_param.txt', 'r') as f:
        gamma = float(f.read().strip())

    beta = 0.9
    steps = 200
    n_seeds = 200
    N = len(pkg_list)

    print(f'B_csr: {B_csr.shape}, nnz={B_csr.nnz}')
    print(f'D_csr: {D_csr.shape}, nnz={D_csr.nnz}')
    print(f'gamma={gamma}, beta={beta}, N={N}')

    # candidate seeds: outgoing dependency edge AND present in the bipartite index
    out_deg = np.diff(D_csr.indptr)
    cand_idx_univ = np.where(out_deg > 0)[0]
    cand = [(pkg_list_univ[i], i) for i in cand_idx_univ if pkg_list_univ[i] in pkg_to_idx]
    print(f'candidates with out-degree>0 and a bipartite index: {len(cand)}')

    rng = np.random.default_rng(42)
    picks = rng.choice(len(cand), size=min(n_seeds, len(cand)), replace=False)

    reach_B, reach_D = [], []
    for k, j in enumerate(picks):
        name, i_univ = cand[j]
        i_bip = pkg_to_idx[name]
        seed = 42 + k

        sim_B = BranchingProcessSimulator(A_csr=None, B_csr=B_csr, beta=beta, gamma=gamma,
                                          bipartite_mode=True, beta_p=1.0, seed=seed)
        h = sim_B.run(max_steps=steps, initial_nodes=[i_bip])
        reach_B.append(h[-1]['I'] + h[-1]['R'])

        sim_D = BranchingProcessSimulator(A_csr=D_csr, B_csr=None, beta=beta, gamma=gamma,
                                          bipartite_mode=False, seed=seed)
        h = sim_D.run(max_steps=steps, initial_nodes=[i_univ])
        reach_D.append(h[-1]['I'] + h[-1]['R'])

    rb = np.array(reach_B, dtype=float)
    rd = np.array(reach_D, dtype=float)
    pb, pd_ = rb / N * 100, rd / N * 100

    # giant component of the ownership graph, for the saturation row of Table 2
    n_comp, lab = sp.csgraph.connected_components(
        sp.bmat([[None, B_csr], [B_csr.T, None]]), directed=False)
    gc = int(np.bincount(lab[:N]).max())
    print(f'ownership graph: {n_comp} components, giant = {gc} pkgs = {gc / N * 100:.4f}%')

    for label, pct, cnt in (('Co-maintainer (bipartite)', pb, rb), ('Dependency', pd_, rd)):
        print(f'--- {label} ---')
        print(f'  mean   = {pct.mean():.4f}%  ({cnt.mean():.1f} pkgs)')
        print(f'  median = {np.median(pct):.4f}%  ({np.median(cnt):.1f} pkgs)')
        print(f'  max    = {pct.max():.4f}%  ({int(cnt.max())} pkgs)')
        print(f'  seeds producing any spread: {int((cnt > 1).sum())}/{len(cnt)}')
    print(f'  seeds saturating the giant component: {int((rb == gc).sum())}/{len(rb)}')

    print(f'Dominance factor (mean/mean): {pb.mean() / pd_.mean():.1f}x')
    print(f'Gap (pp): {pb.mean() - pd_.mean():.4f}')

    # The two channels are run from the IDENTICAL seed, so the paired test is the
    # correct one; Mann-Whitney is reported too for continuity with the earlier
    # 10-patient-zero comparison.
    w = stats.wilcoxon(rb, rd, alternative='greater', zero_method='zsplit')
    u = stats.mannwhitneyu(rb, rd, alternative='greater')
    print(f'Wilcoxon signed-rank (paired, H1: bipartite > dependency): W={w.statistic:.1f}, p={w.pvalue:.4e}')
    print(f'Mann-Whitney U (unpaired):                                 U={u.statistic:.1f}, p={u.pvalue:.4e}')

    # bootstrap CI on the dominance factor
    boot = rng.integers(0, len(pb), size=(10000, len(pb)))
    ratios = pb[boot].mean(axis=1) / pd_[boot].mean(axis=1)
    gaps = pb[boot].mean(axis=1) - pd_[boot].mean(axis=1)
    print(f'Bootstrap 95% CI dominance: {np.percentile(ratios, 2.5):.0f}x - {np.percentile(ratios, 97.5):.0f}x')
    print(f'Bootstrap 95% CI gap (pp):  {np.percentile(gaps, 2.5):.4f} - {np.percentile(gaps, 97.5):.4f}')

    json.dump({'reach_B_pkgs': rb.tolist(), 'reach_D_pkgs': rd.tolist(), 'N': N,
               'beta': beta, 'gamma': gamma, 'n_seeds': len(pb)},
              open('data/npm/random_seed_campaigns_200.json', 'w'))


if __name__ == '__main__':
    main()
