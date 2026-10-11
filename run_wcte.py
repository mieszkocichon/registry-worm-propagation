"""Worst-Case Threat Envelope under the two seed-selection regimes.

The channel comparison (run_stats200_fair.py) has to restrict seeds to packages
where BOTH channels exist, which is a small and unrepresentative slice. The WCTE
is a claim about the co-maintainer channel alone, so it takes its own frame:
seed a compromised maintainer ACCOUNT, which is what a credential theft actually
gives an attacker.

Regimes:
  opportunistic -- account drawn uniformly at random (what the historical record
                   sampled, if attackers took whatever credential was reachable)
  targeted      -- the top-k accounts by portfolio size (what an adversary that
                   ranks candidates by public co-maintainer degree would pick)
"""
import json, sys
import numpy as np
import scipy.sparse as sp

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from simulation_engine import BranchingProcessSimulator


def campaign(B, N, m_idx, gamma, beta=0.9, steps=200, seed=0):
    """Seed every package owned by maintainer m_idx -- a stolen credential
    compromises the whole portfolio at once, not one package."""
    pkgs = B.tocsc()[:, m_idx].nonzero()[0].tolist()
    sim = BranchingProcessSimulator(A_csr=None, B_csr=B, beta=beta, gamma=gamma,
                                    bipartite_mode=True, beta_p=1.0, seed=seed)
    h = sim.run(max_steps=steps, initial_nodes=pkgs)
    return h[-1]['I'] + h[-1]['R']


def describe(label, r, N):
    pct = r / N * 100
    print(f'--- {label} (n={len(r)}) ---')
    print(f'  mean   = {pct.mean():.4f}%  ({r.mean():.1f} pkgs)')
    print(f'  median = {np.median(pct):.4f}%  ({np.median(r):.1f} pkgs)')
    print(f'  max    = {pct.max():.4f}%  ({int(r.max())} pkgs)')
    return pct


def main():
    pkg_set, _, _, D_csr = load_node_universe()
    _, pkg_list, pkg_to_idx, m_list, m_to_idx, B = build_bipartite_graph(allowed_packages=pkg_set)
    with open('data/npm/gamma_param.txt') as f:
        gamma = float(f.read().strip())
    N = len(pkg_list)

    n_comp, lab = sp.csgraph.connected_components(sp.bmat([[None, B], [B.T, None]]), directed=False)
    gc = int(np.bincount(lab[:N]).max())
    print(f'ownership graph: {n_comp} components, giant = {gc} pkgs = {gc / N * 100:.4f}%')

    deg = np.asarray(B.sum(axis=0)).ravel()
    order = np.argsort(deg)[::-1]

    rng = np.random.default_rng(42)
    rand_m = rng.choice(len(m_list), size=200, replace=False)
    r_rand = np.array([campaign(B, N, int(m), gamma, seed=42 + k)
                       for k, m in enumerate(rand_m)], dtype=float)
    p_rand = describe('Opportunistic: 200 uniformly random accounts', r_rand, N)
    print(f'  accounts reaching >1% of corpus: {int((p_rand > 1).sum())}/200')

    r_top = np.array([campaign(B, N, int(m), gamma, seed=42 + k)
                      for k, m in enumerate(order[:50])], dtype=float)
    p_top = describe('Targeted: top 50 accounts by portfolio size', r_top, N)

    print(f'\nWCTE (single best account) = {p_top.max():.4f}% '
          f'({int(r_top.max())} pkgs), account = {m_list[order[int(np.argmax(r_top))]]!r}')
    print(f'Targeted / opportunistic, mean: {p_top.mean() / p_rand.mean():.1f}x')

    json.dump({'random_accounts_pkgs': r_rand.tolist(), 'top50_accounts_pkgs': r_top.tolist(),
               'N': N, 'gamma': gamma, 'beta': 0.9, 'giant_component_pkgs': gc,
               'top50_names': [m_list[i] for i in order[:50]]},
              open('data/npm/wcte_account_seeded.json', 'w'))


if __name__ == '__main__':
    main()
