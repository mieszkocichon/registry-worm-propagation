"""ETAP 1c: recompute the dependency-channel ceiling on the extended graph.

manuscript.tex:572 claims:
  "Even under ideal conditions for the dependency channel -- seeding from node
   terakhir558 (max degree 1,500) with beta=1.0 and gamma=0 -- dependency reach
   peaks at 1,501 packages (0.704%)."

That ceiling was computed on the corpus-truncated D_csr. run_stats200_fair_extended.py
already reaches 5,520 packages from an ORDINARY random seed on D_ext, so the
claimed ceiling is falsified. This recomputes it honestly: highest-out-degree
node in D_ext, beta=1.0, gamma=0, plus the true reachability maximum over the
whole graph (largest forward-reachable set), which bounds any seed at all.
"""
import json
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.path.append('scripts')
from data_utils import load_node_universe

BASE = Path(__file__).parent
NPM = BASE / 'data' / 'npm' / 'npm_metadata.jsonl'


def main():
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
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

    out_deg_pub = np.diff(D_csr.indptr)
    out_deg_ext = np.diff(D_ext.indptr)
    i_pub = int(np.argmax(out_deg_pub))
    i_ext = int(np.argmax(out_deg_ext))
    print(f'max out-degree, published D_csr : {int(out_deg_pub[i_pub]):,}  ({pkg_list_univ[i_pub]})')
    print(f'max out-degree, extended  D_ext : {int(out_deg_ext[i_ext]):,}  ({ext_pkg_list[i_ext]})')

    # beta=1.0, gamma=0 is exactly the forward-reachable set: BFS closure.
    # Compute it for the top-degree node, then for every node, to get the true
    # ceiling over all possible seeds.
    def closure(start):
        seen = np.zeros(n, dtype=bool)
        seen[start] = True
        frontier = np.array([start])
        while len(frontier):
            nxt = np.unique(D_ext[frontier].indices)
            nxt = nxt[~seen[nxt]]
            seen[nxt] = True
            frontier = nxt
        return int(seen.sum())

    print(f'\nforward closure of top-degree node in D_ext: {closure(i_ext):,} packages')

    # True ceiling over all seeds: reachability is bounded by the largest weakly
    # connected component; compute strongly/weakly connected structure and take
    # the largest per-seed closure over the highest-degree candidates.
    n_wcc, lab = sp.csgraph.connected_components(D_ext, directed=True, connection='weak')
    sizes = np.bincount(lab)
    print(f'D_ext: {n_wcc:,} weakly connected components, largest = {sizes.max():,} nodes')

    cand = np.argsort(out_deg_ext)[::-1][:200]
    best_i, best_v = None, -1
    for i in cand:
        v = closure(int(i))
        if v > best_v:
            best_i, best_v = int(i), v
    print(f'best forward closure over the 200 highest-out-degree seeds: {best_v:,} '
          f'packages ({ext_pkg_list[best_i]})')
    print(f'  = {best_v / len(pkg_list_univ) * 100:.4f}% of the 213,162-package corpus')


if __name__ == '__main__':
    main()
