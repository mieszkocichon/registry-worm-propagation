"""Worst-Case Threat Envelope on the NON-MALWARE npm control corpus.

The treatment corpus is a malware corpus, so its maintainer accounts are
overwhelmingly the attackers' own bulk-publishing identities (noirdnv, voinza,
mipta1, ...). An envelope computed there describes spam-campaign structure, not
the ownership topology a worm would traverse in the live registry.

The control corpus (fetch_npm_control_baseline.py) is a size-matched random
sample of npm packages with every OSV-flagged and in-treatment name excluded,
so it is the graph the WCTE claim actually needs.

Same engine, same beta/gamma, same account-seeded regimes as run_wcte.py.
"""
import json, sys
import numpy as np
import scipy.sparse as sp

sys.path.append('scripts')
from constants import is_bot
from simulation_engine import BranchingProcessSimulator

CONTROL = 'data/npm/npm_control_maintainers.jsonl'


def build_control(cap=213162):
    """Same selection as fetch_npm_control_baseline.build_B_control -- dedupe by
    package, keep file order, truncate to the treatment's N for equal-N parity --
    but retaining the name lists, which that helper discards."""
    pkg_list, edges, seen = [], [], set()
    with open(CONTROL, encoding='utf-8') as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            p = rec['package']
            if p in seen:
                continue
            seen.add(p)
            i = len(pkg_list)
            pkg_list.append(p)
            for m in rec.get('maintainers') or []:
                if m and not is_bot(m):
                    edges.append((i, m))
            if len(pkg_list) >= cap:
                break

    m_list = sorted({m for _, m in edges})
    m_to_idx = {m: i for i, m in enumerate(m_list)}
    row = np.fromiter((r for r, _ in edges), dtype=np.int64, count=len(edges))
    col = np.fromiter((m_to_idx[m] for _, m in edges), dtype=np.int64, count=len(edges))
    B = sp.csr_matrix((np.ones(len(row)), (row, col)), shape=(len(pkg_list), len(m_list)))
    B.sum_duplicates()
    B.data[:] = 1.0
    return pkg_list, m_list, B


def campaign(B_csc, B, N, m_idx, gamma, beta=0.9, steps=200, seed=0):
    pkgs = B_csc[:, m_idx].nonzero()[0].tolist()
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
    pkg_list, m_list, B = build_control()
    N = len(pkg_list)
    with open('data/npm/gamma_param.txt') as f:
        gamma = float(f.read().strip())
    print(f'control B: {N} packages x {len(m_list)} maintainers, {B.nnz} edges')

    n_comp, lab = sp.csgraph.connected_components(sp.bmat([[None, B], [B.T, None]]), directed=False)
    gc = int(np.bincount(lab[:N]).max())
    print(f'ownership graph: {n_comp} components, giant = {gc} pkgs = {gc / N * 100:.4f}%')

    deg = np.asarray(B.sum(axis=0)).ravel()
    order = np.argsort(deg)[::-1]
    print('top 10 accounts:', [(m_list[i], int(deg[i])) for i in order[:10]])

    B_csc = B.tocsc()
    rng = np.random.default_rng(42)
    rand_m = rng.choice(len(m_list), size=200, replace=False)
    r_rand = np.array([campaign(B_csc, B, N, int(m), gamma, seed=42 + k)
                       for k, m in enumerate(rand_m)], dtype=float)
    p_rand = describe('Opportunistic: 200 uniformly random accounts', r_rand, N)
    print(f'  accounts reaching >1% of corpus: {int((p_rand > 1).sum())}/200')

    r_top = np.array([campaign(B_csc, B, N, int(m), gamma, seed=42 + k)
                      for k, m in enumerate(order[:50])], dtype=float)
    p_top = describe('Targeted: top 50 accounts by portfolio size', r_top, N)

    print(f'\nWCTE (single best account) = {p_top.max():.4f}% ({int(r_top.max())} pkgs), '
          f'account = {m_list[order[int(np.argmax(r_top))]]!r}')
    print(f'Targeted / opportunistic, mean: {p_top.mean() / p_rand.mean():.1f}x')

    json.dump({'random_accounts_pkgs': r_rand.tolist(), 'top50_accounts_pkgs': r_top.tolist(),
               'N': N, 'n_maintainers': len(m_list), 'edges': int(B.nnz), 'gamma': gamma,
               'beta': 0.9, 'giant_component_pkgs': gc, 'n_components': int(n_comp),
               'top50_names': [m_list[i] for i in order[:50]]},
              open('data/npm/wcte_control_account_seeded.json', 'w'))


if __name__ == '__main__':
    main()
