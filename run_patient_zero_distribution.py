"""Etap 4 (A4): the 10 historical patient-zero seeds are the first 10
chronologically out of a 16,781-package exact-tier candidate pool (see
scripts/resolve_malicious_dates.py) -- an arbitrary cutoff for simulation
cost, not a claim that only 10 packages qualify. This exhausts the whole
pool and reports the co-maintainer reach as a distribution instead of the
single 0.0572% combined-seed point estimate.

At beta_p = 1.0 an outbreak saturates the connected component it starts in
(established in run_2fa_envelope.py and confirmed empirically here: the
existing 10-seed combined run in results_statistical_test.txt has std =
0.000000% across 50 Monte Carlo runs at beta = 0.9), so a single
connected-components pass gives every candidate's reach for free -- no need
to re-run the simulator once per seed.
"""
import json
import sys

import numpy as np
import scipy.sparse as sp

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from resolve_malicious_dates import (
    load_malware_advisories, resolve_malicious_dates,
    build_maintainer_timeline, select_patient_zeros,
)


def main():
    pkg_set, _, _, _ = load_node_universe()
    npm_meta, pkg_list, pkg_to_idx, m_list, m_to_idx, B = build_bipartite_graph(allowed_packages=pkg_set)
    N = len(pkg_list)

    _, lab = sp.csgraph.connected_components(sp.bmat([[None, B], [B.T, None]]), directed=False)
    comp_pkgs = np.bincount(lab[:N], minlength=lab.max() + 1)

    # sanity check against the already-published, empirically deterministic
    # 10-seed result (results_statistical_test.txt: 0.057233%, 122 pkgs, std 0)
    old_ten = json.load(open('data/npm/patient_zeros.json'))
    old_labels = set(lab[pkg_to_idx[p]] for p in old_ten)
    union_reach = int(comp_pkgs[list(old_labels)].sum())
    assert union_reach == 122, (
        f'component-size shortcut disagrees with the published 10-seed result: '
        f'got {union_reach}, expected 122')
    print('sanity check ok: shortcut reproduces the published 10-seed union reach (122 pkgs)')

    mal = load_malware_advisories()
    resolved = resolve_malicious_dates(mal, npm_meta)
    timeline = build_maintainer_timeline()

    seeds, log, rejected = select_patient_zeros(
        npm_meta, pkg_to_idx, resolved, timeline, n=len(resolved), tiers=('exact',))
    print(f'exhausted exact-tier pool: {len(seeds)} seeds admitted, {rejected} rejected')

    reach_pkgs = np.array([comp_pkgs[lab[pkg_to_idx[p]]] for p in seeds])
    reach_pct = reach_pkgs / N * 100

    print(f'n = {len(seeds)}')
    print(f'mean   {reach_pct.mean():.4f}%')
    print(f'median {np.median(reach_pct):.4f}%')
    print(f'p90    {np.percentile(reach_pct, 90):.4f}%')
    print(f'max    {reach_pct.max():.4f}% ({int(reach_pkgs.max())} pkgs)')
    print(f'isolated (component of size 1): {(reach_pkgs == 1).mean() * 100:.1f}%')

    out = {
        'n_seeds': int(len(seeds)),
        'n_rejected': int(rejected),
        'mean_pct': float(reach_pct.mean()),
        'median_pct': float(np.median(reach_pct)),
        'p90_pct': float(np.percentile(reach_pct, 90)),
        'max_pct': float(reach_pct.max()),
        'max_pkgs': int(reach_pkgs.max()),
        'frac_isolated_pct': float((reach_pkgs == 1).mean() * 100),
        'ten_seed_combined_pct': 0.057233,
        'ten_seed_combined_pkgs': 122,
    }
    json.dump(out, open('data/npm/patient_zero_distribution.json', 'w'), indent=1)
    print("\nWrote data/npm/patient_zero_distribution.json")


if __name__ == '__main__':
    main()
