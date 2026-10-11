"""ETAP 2: sweep beta_p on the 200-seed fair frame -- the frame the headline
number actually comes from.

manuscript.tex:545 concedes that at beta_p = 1.0 a co-maintainer outbreak
saturates its connected component, so reach == component size and the SIR
machinery collapses into connected_components(). The paper answers this with
Figure fig:beta_p_sweep -- but that figure is computed on the 10 historical
patient-zero seeds (caption, manuscript.tex:562), NOT on the 200-seed frame the
7.2x / 2.36x dominance is measured on. So the headline has no beta_p sensitivity
evidence behind it at all.

This runs beta_p in {0.3, 0.6, 1.0} over the identical 200 seeds of
run_stats200_fair.py, against BOTH dependency matrices:
  D_csr  -- corpus-truncated, as published
  D_ext  -- one hop out of corpus (see run_stats200_fair_extended.py)

beta_p = 1.0 must reproduce the published bipartite series exactly; the script
asserts that before reporting anything else.
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
BETA_PS = (0.3, 0.6, 1.0)
MC_RUNS = 10  # beta_p < 1 is stochastic; beta_p = 1.0 is deterministic (std 0)


def build_D_ext(pkg_list_univ, pkg_to_idx_univ):
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
    ext_idx = dict(pkg_to_idx_univ)
    for i, p in enumerate(sorted(ext_targets), start=len(pkg_list_univ)):
        ext_idx[p] = i
    row = np.fromiter((ext_idx[s] for s, _ in edges), dtype=np.int64, count=len(edges))
    col = np.fromiter((ext_idx[t] for _, t in edges), dtype=np.int64, count=len(edges))
    n = len(pkg_list_univ) + len(ext_targets)
    return sp.csr_matrix((np.ones(len(row)), (row, col)), shape=(n, n)), len(ext_targets)


def main():
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    _, pkg_list, pkg_to_idx, _, _, B_csr = build_bipartite_graph(allowed_packages=pkg_set)
    gamma = float((BASE / 'data' / 'npm' / 'gamma_param.txt').read_text().strip())
    beta, steps = 0.9, 200
    N_corpus = len(pkg_list)

    D_ext, n_ext = build_D_ext(pkg_list_univ, pkg_to_idx_univ)
    B_ext = sp.vstack([B_csr, sp.csr_matrix((n_ext, B_csr.shape[1]))]).tocsr()

    m_deg = np.diff(B_csr.tocsr().indptr)
    out_deg = np.diff(D_csr.indptr)
    cand = [(pkg_list_univ[i], i) for i in np.where(out_deg > 0)[0]
            if pkg_list_univ[i] in pkg_to_idx and m_deg[pkg_to_idx[pkg_list_univ[i]]] > 0]
    rng = np.random.default_rng(42)
    picks = rng.choice(len(cand), size=min(200, len(cand)), replace=False)
    print(f'frame = {len(cand)} candidates, {len(picks)} seeds, beta={beta}, gamma={gamma}')
    print(f'MC runs per seed: {MC_RUNS} for beta_p < 1, 1 for beta_p = 1.0 (deterministic)\n')

    # --- dependency baselines (independent of beta_p) ------------------------
    dep = {}
    for label, D in (('D_csr', D_csr), ('D_ext', D_ext)):
        out = []
        for k, j in enumerate(picks):
            sim = BranchingProcessSimulator(A_csr=D, B_csr=None, beta=beta, gamma=gamma,
                                            bipartite_mode=False, seed=42 + k)
            h = sim.run(max_steps=steps, initial_nodes=[cand[j][1]])
            out.append(h[-1]['I'] + h[-1]['R'])
        dep[label] = np.array(out, float)
        print(f'{label}: mean {dep[label].mean():.1f} pkgs, median {np.median(dep[label]):.1f}')

    published = json.loads(PUBLISHED.read_text())
    if not np.array_equal(dep['D_csr'], np.array(published['reach_D_pkgs'], float)):
        print('!! D_csr does not reproduce the published series -- aborting.')
        return

    # --- beta_p sweep on the co-maintainer channel ---------------------------
    print()
    results = {}
    for bp in BETA_PS:
        runs = 1 if bp == 1.0 else MC_RUNS
        per_seed = np.zeros(len(picks))
        for k, j in enumerate(picks):
            name = cand[j][0]
            vals = []
            for r in range(runs):
                sim = BranchingProcessSimulator(A_csr=None, B_csr=B_ext, beta=beta, gamma=gamma,
                                                bipartite_mode=True, beta_p=bp,
                                                seed=42 + k + 100000 * r)
                h = sim.run(max_steps=steps, initial_nodes=[pkg_to_idx[name]])
                vals.append(h[-1]['I'] + h[-1]['R'])
            per_seed[k] = np.mean(vals)
        results[bp] = per_seed

        if bp == 1.0:
            ok = np.array_equal(per_seed, np.array(published['reach_B_pkgs'], float))
            print(f'  [self-check] beta_p=1.0 reproduces published bipartite series: {ok}')
            if not ok:
                print('  !! MISMATCH -- aborting.')
                return

    print(f'\n{"beta_p":>7} | {"B mean":>9} {"B median":>9} {"B max":>8} | '
          f'{"vs D_csr":>9} {"vs D_ext":>9} | {"p (D_ext)":>10}')
    print('-' * 78)
    for bp in BETA_PS:
        rb = results[bp]
        r_pub = rb.mean() / dep['D_csr'].mean()
        r_ext = rb.mean() / dep['D_ext'].mean()
        w = stats.wilcoxon(rb, dep['D_ext'], alternative='greater', zero_method='zsplit')
        print(f'{bp:>7} | {rb.mean():>9.1f} {np.median(rb):>9.1f} {rb.max():>8.0f} | '
              f'{r_pub:>8.2f}x {r_ext:>8.2f}x | {w.pvalue:>10.2e}')

    print(f'\ndependency reference: D_csr mean {dep["D_csr"].mean():.1f}, '
          f'D_ext mean {dep["D_ext"].mean():.1f} pkgs')

    json.dump({'beta': beta, 'gamma': gamma, 'n_seeds': len(picks), 'mc_runs': MC_RUNS,
               'N_corpus': N_corpus,
               'reach_D_csr_pkgs': dep['D_csr'].tolist(),
               'reach_D_ext_pkgs': dep['D_ext'].tolist(),
               'reach_B_by_beta_p': {str(bp): results[bp].tolist() for bp in BETA_PS}},
              open(BASE / 'data' / 'npm' / 'betap_sweep_200_fair.json', 'w'))


if __name__ == '__main__':
    main()
