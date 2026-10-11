"""ETAP 4: the dependency-favouring wide frame, re-run against D_ext.

results_statistical_test.txt reports the wide frame (any package with an
outgoing dependency edge, n=6,297) only against the corpus-truncated D_csr.
Once D_ext becomes the primary dependency channel, leaving the wide frame on
D_csr is an inconsistency: it would compare the paper's headline frame on one
graph against its robustness frame on another.

This reruns the identical wide frame -- same candidate set, same
np.random.default_rng(42) draw as run_stats200.py -- on B_ext, D_csr and D_ext
from the same seeds, so the two frames are stated on the same graphs.

D_csr must reproduce the published wide-frame series; the script says so either
way rather than silently reporting numbers that are not comparable.
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


def describe(label, r):
    r = np.asarray(r, float)
    s = r[r > 1]
    print(f'  {label:<8} mean {r.mean():8.1f}  median {np.median(r):7.1f}  max {r.max():7.0f}  '
          f'spread {len(s):3d}/{len(r)}  >100 pkgs {int((r > 100).sum()):3d}  '
          f'cond.mean {s.mean() if len(s) else 0:8.1f}')


def main():
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    _, pkg_list, pkg_to_idx, _, _, B_csr = build_bipartite_graph(allowed_packages=pkg_set)
    gamma = float((BASE / 'data' / 'npm' / 'gamma_param.txt').read_text().strip())
    beta, steps = 0.9, 200

    D_ext, n_ext = build_D_ext(pkg_list_univ, pkg_to_idx_univ)
    B_ext = sp.vstack([B_csr, sp.csr_matrix((n_ext, B_csr.shape[1]))]).tocsr()

    # wide frame: ANY package with an outgoing dependency edge, no maintainer
    # requirement. This is run_stats200.py's frame.
    out_deg = np.diff(D_csr.indptr)
    cand = [(pkg_list_univ[i], i) for i in np.where(out_deg > 0)[0]]
    print(f'wide frame = {len(cand)} candidates (published run reports 6,297)')

    rng = np.random.default_rng(42)
    picks = rng.choice(len(cand), size=min(200, len(cand)), replace=False)

    reach = {'B': [], 'D_csr': [], 'D_ext': []}
    for k, j in enumerate(picks):
        name, i_univ = cand[j]
        # a package with no surviving maintainer has no B row to seed from;
        # its co-maintainer reach is 1 (the seed itself) by construction.
        if name in pkg_to_idx:
            sim = BranchingProcessSimulator(A_csr=None, B_csr=B_ext, beta=beta, gamma=gamma,
                                            bipartite_mode=True, beta_p=1.0, seed=42 + k)
            h = sim.run(max_steps=steps, initial_nodes=[pkg_to_idx[name]])
            reach['B'].append(h[-1]['I'] + h[-1]['R'])
        else:
            reach['B'].append(1)
        for label, D in (('D_csr', D_csr), ('D_ext', D_ext)):
            sim = BranchingProcessSimulator(A_csr=D, B_csr=None, beta=beta, gamma=gamma,
                                            bipartite_mode=False, seed=42 + k)
            h = sim.run(max_steps=steps, initial_nodes=[i_univ])
            reach[label].append(h[-1]['I'] + h[-1]['R'])

    rb = np.array(reach['B'], float)
    print()
    for label in ('B', 'D_csr', 'D_ext'):
        describe(label, reach[label])

    print()
    for label in ('D_csr', 'D_ext'):
        rd = np.array(reach[label], float)
        up = stats.wilcoxon(rb, rd, alternative='greater', zero_method='zsplit')
        dn = stats.wilcoxon(rb, rd, alternative='less', zero_method='zsplit')
        sb, sd = rb[rb > 1], rd[rd > 1]
        mw = stats.mannwhitneyu(sb, sd, alternative='greater')
        print(f'  B vs {label}: Wilcoxon H1 B>D p={up.pvalue:.3e} | H1 B<D p={dn.pvalue:.3e}')
        print(f'      conditional on spreading: B mean {sb.mean():.1f} vs {sd.mean():.1f}, '
              f'median {np.median(sb):.1f} vs {np.median(sd):.1f}, Mann-Whitney p={mw.pvalue:.3e}')

    json.dump({'frame': 'wide (any outgoing dependency edge, no maintainer requirement)',
               'n_candidates': len(cand), 'n_seeds': len(picks),
               'beta': beta, 'gamma': gamma,
               **{f'reach_{k}_pkgs': [int(x) for x in v] for k, v in reach.items()}},
              open(BASE / 'data' / 'npm' / 'random_seed_campaigns_200_wide_extended.json', 'w'))


if __name__ == '__main__':
    main()
