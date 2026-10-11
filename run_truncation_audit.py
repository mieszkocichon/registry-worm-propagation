"""ETAP 1a: quantify how much of each channel the corpus filter removes.

data_utils.load_node_universe() keeps only dependent edges whose TARGET is
itself in the malware corpus (data_utils.py:87). Every dependent outside the
corpus -- i.e. every legitimate package that consumes a malicious one -- is
dropped. Those are exactly the packages a real dependency-channel outbreak
would infect first, so the filter is a one-sided handicap on D_csr.

graph_builder.build_bipartite_graph(allowed_packages=pkg_set) applies the same
filter maintainer-side, so B_csr is truncated by construction too. This script
measures BOTH truncations so the paper can state whether they are comparable
in magnitude, rather than asserting symmetry it has not checked.

Reports counts only. No simulation, no inference.
"""
import json
from pathlib import Path

BASE = Path(__file__).parent
NPM = BASE / 'data' / 'npm' / 'npm_metadata.jsonl'


def main():
    corpus = set()
    records = []
    with open(NPM, 'r', encoding='utf-8') as f:
        for line in f:
            d = json.loads(line)
            corpus.add(d['package'])
            records.append((d['package'], d.get('dependents', []) or [],
                            d.get('maintainers', []) or []))

    print(f'corpus packages in npm_metadata.jsonl: {len(corpus):,}')

    # --- dependency channel -------------------------------------------------
    dep_total = dep_in = 0
    ext_targets = set()
    src_with_any = set()
    src_with_in = set()
    for pkg, deps, _ in records:
        if deps:
            src_with_any.add(pkg)
        for t in deps:
            dep_total += 1
            if t in corpus:
                dep_in += 1
                src_with_in.add(pkg)
            else:
                ext_targets.add(t)
    dep_out = dep_total - dep_in

    print('\n--- DEPENDENCY CHANNEL (edge: package -> dependent) ---')
    print(f'  total dependent edges recovered : {dep_total:,}')
    print(f'  target inside corpus  (kept)    : {dep_in:,}  ({dep_in/dep_total*100:.1f}%)')
    print(f'  target outside corpus (DROPPED) : {dep_out:,}  ({dep_out/dep_total*100:.1f}%)')
    print(f'  distinct out-of-corpus targets  : {len(ext_targets):,}')
    print(f'  source packages with >=1 edge   : {len(src_with_any):,}')
    print(f'  ... of which retain >=1 edge    : {len(src_with_in):,}')
    print(f'  ... left with NO edge by filter : {len(src_with_any) - len(src_with_in):,}')

    # --- co-maintainer channel ---------------------------------------------
    # B_csr is built over the SAME corpus node set, so a maintainer's packages
    # outside the corpus are absent. We cannot count those edges: this file only
    # contains corpus packages, so out-of-corpus portfolio entries were never
    # recorded. State that explicitly rather than guessing a number.
    m_edges = sum(len(m) for _, _, m in records)
    maints = {m for _, _, ms in records for m in ms}
    print('\n--- CO-MAINTAINER CHANNEL ---')
    print(f'  maintainer edges inside corpus  : {m_edges:,}')
    print(f'  distinct maintainers            : {len(maints):,}')
    print('  out-of-corpus portfolio edges   : NOT MEASURABLE from this file')
    print('    (npm_metadata.jsonl contains corpus packages only, so a')
    print('     maintainer\'s non-malware packages were never fetched.')
    print('     Any symmetry claim needs data/npm/extended_portfolios or a')
    print('     separate fetch -- do not assert symmetry without it.)')


if __name__ == '__main__':
    main()
