"""ETAP 4b: the ten patient-zero seeds on D_ext.

manuscript.tex claims the ten historical seeds are "isolated in D_CSR, so
person-time R_0 = 0 at every ratio". That is true of D_CSR and FALSE of the
registry: every one of the ten has 2-3 dependents, all of them outside the
malware corpus, so the corpus filter is what zeroed the channel, not the
topology. This measures what the historical dependency channel actually does
once those edges are restored, at the same beta_dep ratio band the paper
sweeps, so the caption and the R_0 discussion can be corrected to the truth.
"""
import json
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from simulation_engine import BranchingProcessSimulator

BASE = Path(__file__).parent
NPM = BASE / 'data' / 'npm' / 'npm_metadata.jsonl'
RATIOS = (0.05, 0.1, 0.2)
BETA, MC = 0.9, 50


def main():
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    corpus = set(pkg_list_univ)
    gamma = float((BASE / 'data' / 'npm' / 'gamma_param.txt').read_text().strip())

    edges, ext = [], set()
    with open(NPM, 'r', encoding='utf-8') as f:
        for line in f:
            d = json.loads(line)
            if d['package'] not in corpus:
                continue
            for t in d.get('dependents', []) or []:
                edges.append((d['package'], t))
                if t not in corpus:
                    ext.add(t)
    idx = dict(pkg_to_idx_univ)
    for i, p in enumerate(sorted(ext), start=len(pkg_list_univ)):
        idx[p] = i
    n = len(pkg_list_univ) + len(ext)
    row = np.fromiter((idx[s] for s, _ in edges), np.int64, len(edges))
    col = np.fromiter((idx[t] for _, t in edges), np.int64, len(edges))
    D_ext = sp.csr_matrix((np.ones(len(row)), (row, col)), shape=(n, n))

    pz = json.load(open(BASE / 'data' / 'npm' / 'patient_zeros.json'))
    seeds = [pkg_to_idx_univ[p] for p in pz]
    od = np.diff(D_ext.indptr)
    print(f'seeds: {len(pz)}; out-degree in D_ext = {[int(od[i]) for i in seeds]}')
    print(f'out-degree in D_csr = {[int(np.diff(D_csr.indptr)[i]) for i in seeds]}')

    # forward closure (beta=1, gamma=0) of the whole seed set
    seen = np.zeros(n, bool)
    seen[seeds] = True
    frontier = np.array(seeds)
    while len(frontier):
        nxt = np.unique(D_ext[frontier].indices)
        nxt = nxt[~seen[nxt]]
        seen[nxt] = True
        frontier = nxt
    print(f'combined forward closure on D_ext: {int(seen.sum())} packages '
          f'(seeds {len(seeds)} + {int(seen.sum()) - len(seeds)} dependents)')

    for ratio in RATIOS:
        reach, r0s = [], []
        for r in range(MC):
            sim = BranchingProcessSimulator(A_csr=D_ext, B_csr=None, beta=BETA * ratio,
                                            gamma=gamma, bipartite_mode=False, seed=1000 + r)
            h = sim.run(max_steps=200, initial_nodes=seeds)
            reach.append(h[-1]['I'] + h[-1]['R'])
            r0s.append(sim._person_time_r0() if hasattr(sim, '_person_time_r0') else np.nan)
        print(f'beta_dep ratio {ratio}: mean final reach {np.mean(reach):.2f} pkgs '
              f'(max {max(reach)}), person-time R0 {np.nanmean(r0s):.3f}')


if __name__ == '__main__':
    main()
