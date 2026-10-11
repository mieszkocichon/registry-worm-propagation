"""ETAP 1b: does the 7.2x dominance survive giving the dependency channel its
out-of-corpus dependents back?

load_node_universe() keeps a dependent edge only when its TARGET is itself in
the malware corpus (data_utils.py:87). run_truncation_audit.py measures the
cost: 127,678 of 176,276 recovered edges (72.4%) are discarded, and 26,112 of
the 32,409 source packages lose their dependency channel entirely. The
discarded targets are legitimate packages that CONSUME a malicious one -- the
packages a real dependency-channel outbreak infects first. The published
comparison therefore runs a complete co-maintainer graph against a dependency
graph stripped of three quarters of its edges.

This script rebuilds the node universe as
    sorted(corpus)  ++  sorted(out-of-corpus dependents)
so corpus indices 0..N_corpus-1 are UNCHANGED, and:

  D_ext  carries all 176,276 edges. Out-of-corpus nodes are absorbing: we hold
         no dependents for them, so an outbreak enters and stops. That makes
         the result a one-hop LOWER bound on the dependency channel's true
         reach, not an estimate of it.

  B_ext  is the same bipartite matrix padded with zero rows. We never fetched
         the maintainers of out-of-corpus packages, so the co-maintainer
         channel cannot reach them AT ALL in this universe -- even though in
         the live registry those packages plainly have maintainers, very
         likely well-connected ones.

The asymmetry is deliberate and it runs AGAINST the paper's thesis: D_ext gains
36,288 reachable nodes, B_ext gains none. Whatever dominance survives here is a
floor.

Seeds are the exact 200 of run_stats200_fair.py (same candidate frame, same
np.random.default_rng(42) draw), so the only thing that changes between the
published run and this one is the dependency matrix.

SELF-CHECK: because the padding rows are isolated, the bipartite RNG stream and
every reachable set are untouched, so B_ext must reproduce the stored
reach_B_pkgs exactly. The script asserts this and refuses to report if it fails.
"""
import json
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from scipy import stats

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from simulation_engine import BranchingProcessSimulator

BASE = Path(__file__).parent
NPM = BASE / 'data' / 'npm' / 'npm_metadata.jsonl'
PUBLISHED = BASE / 'data' / 'npm' / 'random_seed_campaigns_200_fair.json'


def build_extended(pkg_list_univ, pkg_to_idx_univ):
    """Returns (ext_pkg_list, D_ext) over corpus ++ out-of-corpus dependents."""
    corpus = set(pkg_list_univ)
    edges, ext_targets = [], set()
    with open(NPM, 'r', encoding='utf-8') as f:
        for line in f:
            d = json.loads(line)
            src = d['package']
            if src not in corpus:
                continue
            for tgt in d.get('dependents', []) or []:
                edges.append((src, tgt))
                if tgt not in corpus:
                    ext_targets.add(tgt)

    ext_pkg_list = list(pkg_list_univ) + sorted(ext_targets)
    ext_idx = dict(pkg_to_idx_univ)
    for i, p in enumerate(sorted(ext_targets), start=len(pkg_list_univ)):
        ext_idx[p] = i

    row = np.fromiter((ext_idx[s] for s, _ in edges), dtype=np.int64, count=len(edges))
    col = np.fromiter((ext_idx[t] for _, t in edges), dtype=np.int64, count=len(edges))
    n = len(ext_pkg_list)
    D_ext = sp.csr_matrix((np.ones(len(row)), (row, col)), shape=(n, n))
    return ext_pkg_list, D_ext, len(ext_targets), len(edges)


def describe(label, reach, denom_label, denom):
    r = np.asarray(reach, dtype=float)
    print(f'--- {label} ---')
    print(f'  mean   = {r.mean():10.1f} pkgs   ({r.mean() / denom * 100:.4f}% of {denom_label})')
    print(f'  median = {np.median(r):10.1f} pkgs   ({np.median(r) / denom * 100:.4f}%)')
    print(f'  max    = {r.max():10.0f} pkgs   ({r.max() / denom * 100:.4f}%)')
    print(f'  seeds producing any spread: {int((r > 1).sum())}/{len(r)}')


def main():
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    _, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph(allowed_packages=pkg_set)

    gamma = float((BASE / 'data' / 'npm' / 'gamma_param.txt').read_text().strip())
    beta, steps, n_seeds = 0.9, 200, 200
    N_corpus = len(pkg_list)

    ext_pkg_list, D_ext, n_ext, n_edges_ext = build_extended(pkg_list_univ, pkg_to_idx_univ)
    N_ext = len(ext_pkg_list)

    B_ext = sp.vstack([B_csr, sp.csr_matrix((n_ext, B_csr.shape[1]))]).tocsr()

    print(f'corpus N            = {N_corpus:,}')
    print(f'out-of-corpus nodes = {n_ext:,}   -> extended N = {N_ext:,}')
    print(f'D_csr nnz (published) = {D_csr.nnz:,}')
    print(f'D_ext nnz             = {D_ext.nnz:,}   (from {n_edges_ext:,} raw edges)')
    print(f'B_csr nnz = {B_csr.nnz:,}   B_ext nnz = {B_ext.nnz:,}  (padding adds no edges)')
    print(f'beta={beta} gamma={gamma}\n')

    # --- identical seed frame and identical draw as run_stats200_fair.py -----
    m_deg = np.diff(B_csr.tocsr().indptr)
    out_deg = np.diff(D_csr.indptr)
    cand = [(pkg_list_univ[i], i) for i in np.where(out_deg > 0)[0]
            if pkg_list_univ[i] in pkg_to_idx and m_deg[pkg_to_idx[pkg_list_univ[i]]] > 0]
    print(f'fair-frame candidates: {len(cand)}  (published run reports 1,183)')

    rng = np.random.default_rng(42)
    picks = rng.choice(len(cand), size=min(n_seeds, len(cand)), replace=False)

    reach_B, reach_D_pub, reach_D_ext = [], [], []
    for k, j in enumerate(picks):
        name, i_univ = cand[j]

        sim = BranchingProcessSimulator(A_csr=None, B_csr=B_ext, beta=beta, gamma=gamma,
                                        bipartite_mode=True, beta_p=1.0, seed=42 + k)
        h = sim.run(max_steps=steps, initial_nodes=[pkg_to_idx[name]])
        reach_B.append(h[-1]['I'] + h[-1]['R'])

        sim = BranchingProcessSimulator(A_csr=D_csr, B_csr=None, beta=beta, gamma=gamma,
                                        bipartite_mode=False, seed=42 + k)
        h = sim.run(max_steps=steps, initial_nodes=[i_univ])
        reach_D_pub.append(h[-1]['I'] + h[-1]['R'])

        sim = BranchingProcessSimulator(A_csr=D_ext, B_csr=None, beta=beta, gamma=gamma,
                                        bipartite_mode=False, seed=42 + k)
        h = sim.run(max_steps=steps, initial_nodes=[i_univ])
        reach_D_ext.append(h[-1]['I'] + h[-1]['R'])

    rb = np.array(reach_B, float)
    rd_pub = np.array(reach_D_pub, float)
    rd_ext = np.array(reach_D_ext, float)

    # --- self-check against the published artifact --------------------------
    published = json.loads(PUBLISHED.read_text())
    pub_B = np.array(published['reach_B_pkgs'], float)
    pub_D = np.array(published['reach_D_pkgs'], float)
    ok_B = np.array_equal(rb, pub_B)
    ok_D = np.array_equal(rd_pub, pub_D)
    print(f'\nSELF-CHECK vs random_seed_campaigns_200_fair.json:')
    print(f'  co-maintainer reach reproduces exactly : {ok_B}')
    print(f'  published dependency reach reproduces  : {ok_D}')
    if not (ok_B and ok_D):
        print('  !! MISMATCH -- the rebuild is not comparable to the published run.')
        print('     Refusing to report a dominance factor. Investigate before using.')
        return

    print()
    describe('Co-maintainer B_ext (= published B_csr)', rb, 'corpus', N_corpus)
    describe('Dependency D_csr  (published, corpus-only)', rd_pub, 'corpus', N_corpus)
    describe('Dependency D_ext  (one hop out of corpus)', rd_ext, 'corpus', N_corpus)

    print('\n=== DOMINANCE, absolute packages (denominators differ, so report counts) ===')
    for label, rd in (('published D_csr', rd_pub), ('extended D_ext', rd_ext)):
        ratio = rb.mean() / rd.mean() if rd.mean() > 0 else float('inf')
        w = stats.wilcoxon(rb, rd, alternative='greater', zero_method='zsplit')
        boot = rng.integers(0, len(rb), size=(10000, len(rb)))
        ratios = rb[boot].mean(axis=1) / np.maximum(rd[boot].mean(axis=1), 1e-12)
        print(f'  vs {label}: mean/mean = {ratio:.2f}x '
              f'[bootstrap 95% CI {np.percentile(ratios, 2.5):.2f}x - {np.percentile(ratios, 97.5):.2f}x]')
        print(f'      median {np.median(rb):.1f} vs {np.median(rd):.1f} pkgs; '
              f'Wilcoxon W={w.statistic:.1f}, p={w.pvalue:.3e}; '
              f'B>D on {int((rb > rd).sum())}/{len(rb)}, B<D on {int((rb < rd).sum())}')

    gain = rd_ext.mean() / rd_pub.mean() if rd_pub.mean() > 0 else float('inf')
    print(f'\n  dependency channel gains {gain:.2f}x in mean reach from the restored edges')
    print(f'  ({rd_pub.mean():.1f} -> {rd_ext.mean():.1f} packages)')

    json.dump({'N_corpus': N_corpus, 'N_ext': N_ext, 'n_out_of_corpus': n_ext,
               'D_csr_nnz': int(D_csr.nnz), 'D_ext_nnz': int(D_ext.nnz),
               'beta': beta, 'gamma': gamma, 'n_seeds': len(rb),
               'frame': 'both-channels-available (identical to run_stats200_fair.py)',
               'reach_B_pkgs': rb.tolist(),
               'reach_D_published_pkgs': rd_pub.tolist(),
               'reach_D_extended_pkgs': rd_ext.tolist()},
              open(BASE / 'data' / 'npm' / 'random_seed_campaigns_200_fair_extended.json', 'w'))


if __name__ == '__main__':
    main()
