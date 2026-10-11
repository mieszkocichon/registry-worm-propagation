"""200-seed campaign on a SYMMETRIC seed frame.

run_stats200.py draws seeds from packages with >=1 outgoing dependency edge.
That frame was chosen to favour the dependency channel, but after the npm
registry account is excluded it over-favours it: 81% of those packages were
sole-owned by the takedown account, so they now have no maintainer at all and
the co-maintainer channel is unavailable to them by construction, not by
topology.

This script uses the fair frame -- packages where BOTH channels exist (>=1
outgoing dependency edge AND >=1 maintainer) -- so the comparison measures
relative propagation capability rather than relative seed availability.
Both frames are reported in the paper.
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
    _, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph(allowed_packages=pkg_set)

    with open('data/npm/gamma_param.txt', 'r') as f:
        gamma = float(f.read().strip())

    beta, steps, n_seeds = 0.9, 200, 200
    N = len(pkg_list)
    m_deg = np.diff(B_csr.tocsr().indptr)
    out_deg = np.diff(D_csr.indptr)

    cand = [(pkg_list_univ[i], i) for i in np.where(out_deg > 0)[0]
            if pkg_list_univ[i] in pkg_to_idx and m_deg[pkg_to_idx[pkg_list_univ[i]]] > 0]
    print(f'B_csr nnz={B_csr.nnz}, D_csr nnz={D_csr.nnz}, gamma={gamma}, beta={beta}')
    print(f'fair-frame candidates (>=1 dep edge AND >=1 maintainer): {len(cand)}')

    rng = np.random.default_rng(42)
    picks = rng.choice(len(cand), size=min(n_seeds, len(cand)), replace=False)

    reach_B, reach_D = [], []
    for k, j in enumerate(picks):
        name, i_univ = cand[j]
        sim_B = BranchingProcessSimulator(A_csr=None, B_csr=B_csr, beta=beta, gamma=gamma,
                                          bipartite_mode=True, beta_p=1.0, seed=42 + k)
        h = sim_B.run(max_steps=steps, initial_nodes=[pkg_to_idx[name]])
        reach_B.append(h[-1]['I'] + h[-1]['R'])

        sim_D = BranchingProcessSimulator(A_csr=D_csr, B_csr=None, beta=beta, gamma=gamma,
                                          bipartite_mode=False, seed=42 + k)
        h = sim_D.run(max_steps=steps, initial_nodes=[i_univ])
        reach_D.append(h[-1]['I'] + h[-1]['R'])

    rb, rd = np.array(reach_B, float), np.array(reach_D, float)
    pb, pd_ = rb / N * 100, rd / N * 100

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
    w = stats.wilcoxon(rb, rd, alternative='greater', zero_method='zsplit')
    print(f'Wilcoxon signed-rank (paired, H1: bipartite > dependency): W={w.statistic:.1f}, p={w.pvalue:.4e}')
    print(f'  seeds where B > D: {int((rb > rd).sum())}  B < D: {int((rb < rd).sum())}  tie: {int((rb == rd).sum())}')

    boot = rng.integers(0, len(pb), size=(10000, len(pb)))
    ratios = pb[boot].mean(axis=1) / pd_[boot].mean(axis=1)
    gaps = pb[boot].mean(axis=1) - pd_[boot].mean(axis=1)
    print(f'Bootstrap 95% CI dominance: {np.percentile(ratios, 2.5):.1f}x - {np.percentile(ratios, 97.5):.1f}x')
    print(f'Bootstrap 95% CI gap (pp):  {np.percentile(gaps, 2.5):.4f} - {np.percentile(gaps, 97.5):.4f}')

    json.dump({'reach_B_pkgs': rb.tolist(), 'reach_D_pkgs': rd.tolist(), 'N': N,
               'beta': beta, 'gamma': gamma, 'n_seeds': len(pb), 'frame': 'both-channels-available',
               'n_candidates': len(cand), 'giant_component_pkgs': gc},
              open('data/npm/random_seed_campaigns_200_fair.json', 'w'))


if __name__ == '__main__':
    main()
