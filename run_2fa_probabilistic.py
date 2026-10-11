"""R5: how much does 2FA actually bound reach when modelled as a probability
reduction that preserves the ownership edges of B, rather than as the
complete revocation (`secure()` in run_2fa_envelope.py, which zeroes an
account's columns outright)? Real 2FA does not delete a maintainer's
packages; it makes a compromised session less likely to complete a publish.

The theoretical answer follows directly from the persistence result already
established for the paper's other channels (sec:results, beta_p sweep,
run_betap_gammam_sweep.py): with gamma_m = 0, ANY beta_p > 0 eventually
saturates the account's full connected component, because a compromised
maintainer is re-rolled every subsequent step for as long as it stays
compromised. A probability-only 2FA -- lowering beta_p without an
accompanying token-rotation/expiry mechanism -- therefore gives the worm
unlimited retries and should leave final reach unchanged from the
uncontrolled (k=0) envelope, at ANY k. This script checks that prediction
directly by simulation rather than resting on the analogy, and then measures
what a *realistic* combined control (probability reduction + token rotation,
gamma_m > 0) actually buys.

For each ranking and k already reported in the hard-revoke table
(run_2fa_envelope.py), I do not re-run the full k-sweep by simulation (the
exhaustive per-account envelope search there is only tractable because it
uses the beta_p=1.0 connected-components shortcut, which no longer applies
once beta_p < 1). Instead I simulate directly from the single account most
consequential to that k: the highest-reach account among the top-k the
ranking would place under 2FA -- the one whose bypass, if 2FA merely slowed
rather than revoked it, would cost the most.

Output: data/npm/twofa_probabilistic_check.json
"""
import json
import sys

import numpy as np
import scipy.sparse as sp

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from simulation_engine import BranchingProcessSimulator
from run_wcte_control import build_control
from run_2fa_envelope import rank_by_reach, rank_by_onehop, KS, BETA

STEPS = 200
MC = 10
BETA_P_VALUES = [1.0, 0.6, 0.3]
GAMMA_M_VALUES = [0.0, 0.05, 0.2]


def worst_secured_account(B, N, order, k):
    """Among the top-k accounts a ranking would place under 2FA, the one with
    the largest own connected-component reach -- the account whose bypass
    matters most if 2FA merely slows rather than revokes it."""
    if k == 0:
        return None, 0
    _, lab = sp.csgraph.connected_components(sp.bmat([[None, B], [B.T, None]]), directed=False)
    comp_size = np.bincount(lab[:N], minlength=lab.max() + 1)
    reach = comp_size[lab[N:]]
    top_k = order[:k]
    best = top_k[np.argmax(reach[top_k])]
    return int(best), int(reach[best])


def simulate_account_reach(B, N, account, beta_p, gamma_m, steps=STEPS, mc=MC):
    """Mean final reach seeding directly from one account's own portfolio,
    under a probability-preserving 2FA model: the account's columns/edges in
    B are untouched, only beta_p (publish success) and gamma_m (token
    rotation) change."""
    portfolio = B.tocsc()[:, account].nonzero()[0]
    if len(portfolio) == 0:
        return 0.0
    reaches = np.zeros(mc)
    for r in range(mc):
        sim = BranchingProcessSimulator(A_csr=None, B_csr=B.tocsr(), beta=BETA, gamma=0.0,
                                         bipartite_mode=True, beta_p=beta_p, gamma_m=gamma_m, seed=1000 + r)
        h = sim.run(max_steps=steps, initial_nodes=portfolio.tolist())
        reaches[r] = h[-1]['I'] + h[-1]['R']
    return float(reaches.mean())


def run_corpus(label, B, N, out):
    print(f'\n=== {label} (N={N}) ===')
    result = {}
    for rank_label, order in (('projected reach', rank_by_reach(B, N)),
                              ('onehop degree', rank_by_onehop(B, N))):
        rows = []
        for k in KS:
            account, unsecured_reach = worst_secured_account(B, N, order, k)
            if account is None:
                rows.append({'k': k, 'unsecured_reach': None})
                continue
            cell = {'k': k, 'account_idx': account, 'unsecured_reach': unsecured_reach}
            for beta_p in BETA_P_VALUES:
                for gamma_m in GAMMA_M_VALUES:
                    r = simulate_account_reach(B, N, account, beta_p, gamma_m)
                    cell[f'reach_betap{beta_p}_gammam{gamma_m}'] = r
            print(f'  {rank_label} k={k}: worst-secured account reach(unsecured)={unsecured_reach}  '
                  f'reach(beta_p=1.0,gamma_m=0)={cell["reach_betap1.0_gammam0.0"]:.1f}  '
                  f'reach(beta_p=0.3,gamma_m=0.2)={cell["reach_betap0.3_gammam0.2"]:.1f}')
            rows.append(cell)
        result[rank_label] = rows
    out[label] = result


def main():
    out = {'beta_p_values': BETA_P_VALUES, 'gamma_m_values': GAMMA_M_VALUES, 'steps': STEPS, 'mc_replicates': MC}

    pkg_set, _, _, _ = load_node_universe()
    _, pkg_list, _, m_list, _, B = build_bipartite_graph(allowed_packages=pkg_set)
    run_corpus('treatment_malware', B, len(pkg_list), out)

    c_pkgs, c_m, Bc = build_control()
    run_corpus('control_non_malware', Bc, len(c_pkgs), out)

    json.dump(out, open('data/npm/twofa_probabilistic_check.json', 'w'), indent=1)
    print('\nwrote data/npm/twofa_probabilistic_check.json')


if __name__ == '__main__':
    main()
