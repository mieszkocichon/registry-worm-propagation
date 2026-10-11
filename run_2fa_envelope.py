"""How far does mandatory 2FA on the top-k accounts actually push the envelope down?

The naive evaluation -- secure the top 50, then seed from the top 50 -- is
circular: those accounts have no packages left, so it returns zero by
construction. The non-circular question is what the BEST REMAINING adversary can
still do, so for each k we secure the top k accounts and then take the maximum
reach over every account that is left.

Reported for both corpora.
"""
import json, sys
import numpy as np
import scipy.sparse as sp

sys.path.append('scripts')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from simulation_engine import BranchingProcessSimulator
from run_wcte_control import build_control

KS = (0, 1, 10, 50, 100, 500)
BETA = 0.9


def secure(B, k, order):
    """Zero the columns of the top k accounts: they are the ones put under 2FA."""
    keep = np.ones(B.shape[1], dtype=float)
    keep[order[:k]] = 0.0
    Bs = (B @ sp.diags(keep)).tocsr()
    Bs.eliminate_zeros()
    return Bs


def envelope(B, N, k, order):
    """Secure the top k accounts, then return the largest reach any remaining
    account can still achieve -- maximised over EVERY remaining account.

    An earlier version probed only the next 60 accounts in the same ranking, on
    the assumption that reach is near-monotone in portfolio size. That is the
    assumption this experiment exists to refute, so it understated the k=0
    envelope of the portfolio-size row whenever the worst account sat outside the
    window. Under beta_p = 1.0 a compromised maintainer publishes to its whole
    portfolio and the outbreak saturates the connected component it starts in, so
    reach from an account is exactly the package count of its component: one
    connected-components pass replaces one SIR run per candidate and lets us take
    the maximum over all accounts instead of a window. _selftest checks that
    identity against the simulator.
    """
    Bs = secure(B, k, order)
    _, lab = sp.csgraph.connected_components(sp.bmat([[None, Bs], [Bs.T, None]]), directed=False)
    comp_pkgs = np.bincount(lab[:N], minlength=lab.max() + 1)
    reach = comp_pkgs[lab[N:]].astype(int)
    reach[order[:k]] = -1  # a secured account is not an available starting point
    m = int(np.argmax(reach))
    return (int(reach[m]), m) if reach[m] > 0 else (0, None)


def rank_by_portfolio(B, N):
    """What deployed policy can approximate: how many packages the account owns."""
    return np.argsort(np.asarray(B.sum(axis=0)).ravel())[::-1]


def rank_by_reach(B, N):
    """Projected Co-Maintainer Degree: how many packages the account's portfolio
    reaches through co-ownership chains. With beta_p = 1.0 an outbreak saturates
    its component, so this is the size of the component the account sits in --
    computable in one pass, and the quantity the paper recommends gating on."""
    _, lab = sp.csgraph.connected_components(sp.bmat([[None, B], [B.T, None]]), directed=False)
    comp_size = np.bincount(lab[:N], minlength=lab.max() + 1)
    reach = comp_size[lab[N:]]
    deg = np.asarray(B.sum(axis=0)).ravel()
    return np.lexsort((-deg, -reach))


def onehop_degree(B, chunk=500):
    """Number of distinct packages sharing a maintainer with any package the
    account holds -- one hop in P = B B^T, not the transitive closure.

    This is the quantity the policy recommendation describes in prose. It differs
    from rank_by_reach in the way that matters for a ranking: component size is
    identical for every account in a component, so it cannot order accounts
    within one, whereas this can. Computed as the column-wise nnz of B B^T B,
    chunked over account columns so that B B^T is never materialised -- which is
    also why no hub truncation is needed here.
    """
    Bc = B.tocsc()
    deg = np.empty(B.shape[1], dtype=np.int64)
    for i in range(0, B.shape[1], chunk):
        X = B @ (B.T @ Bc[:, i:i + chunk])
        deg[i:i + chunk] = X.getnnz(axis=0)
    return deg


def rank_by_onehop(B, N):
    """Accounts by one-hop projected degree, ties broken by portfolio size."""
    return np.lexsort((-np.asarray(B.sum(axis=0)).ravel(), -onehop_degree(B)))


def report(label, B, N, m_list, out, anonymise=False):
    """anonymise: for the live-registry control these are real maintainers, and the
    paper's ethical statement forbids releasing them as a ranked target list. The
    console keeps the real names for our own auditing; only the released JSON is
    pseudonymised, C-1 being the account with the highest envelope."""
    print(f'\n=== {label} (N={N}, {B.shape[1]} accounts) ===')
    for rank_label, order in (('portfolio size', rank_by_portfolio(B, N)),
                              ('projected reach', rank_by_reach(B, N)),
                              ('onehop degree', rank_by_onehop(B, N))):
        print(f'  -- accounts secured in order of {rank_label} --')
        rows = []
        for k in KS:
            r, m = envelope(B, N, k, order)
            name = m_list[m] if m is not None else '--'
            print(f'    k={k:<5d} best remaining: {name:<24s} envelope {r:>6d} pkgs = {r / N * 100:.4f}%')
            rows.append({'k': k, 'account': name, 'reach_pkgs': int(r), 'reach_pct': r / N * 100})
        out[f'{label}::{rank_label.replace(" ", "_")}'] = rows

    if anonymise:
        pseudonymise([r for key, v in out.items() if key.startswith(f'{label}::') for r in v])


def pseudonymise(rows):
    """Rewrite account names in place as C-1, C-2, ... ordered by descending
    envelope, so C-1 is the worst residual vector regardless of which ranking
    surfaced it and the label is stable across both ranking rows."""
    alias = {}
    for r in sorted(rows, key=lambda r: -r['reach_pkgs']):
        if r['account'] != '--':
            alias.setdefault(r['account'], f'C-{len(alias) + 1}')
    for r in rows:
        r['account'] = alias.get(r['account'], r['account'])
    return rows


def main():
    # no gamma: the envelope is a component size, and reach was already shown
    # invariant across the whole sweep gamma in [0, 0.01] including gamma = 0
    out = {}

    pkg_set, _, _, _ = load_node_universe()
    _, pkg_list, _, m_list, _, B = build_bipartite_graph(allowed_packages=pkg_set)
    report('treatment_malware', B, len(pkg_list), m_list, out)

    c_pkgs, c_m, Bc = build_control()
    report('control_non_malware', Bc, len(c_pkgs), c_m, out, anonymise=True)

    json.dump(out, open('data/npm/twofa_envelope_curve.json', 'w'), indent=1)


def _selftest():
    # same account under both rankings must get one stable alias, and the worst
    # envelope must be C-1 even when a weaker row is encountered first
    rows = [{'account': 'alice', 'reach_pkgs': 100}, {'account': 'bob', 'reach_pkgs': 300},
            {'account': 'alice', 'reach_pkgs': 100}, {'account': '--', 'reach_pkgs': 0}]
    pseudonymise(rows)
    assert [r['account'] for r in rows] == ['C-2', 'C-1', 'C-2', '--'], rows

    # p0 p1 p2 form one component via the a0-a1 chain; a2 holds p3 alone; p4 is
    # unowned and reachable by nobody. The worst account must be found even when
    # the ranking puts it last, which is what the old 60-window could miss.
    B = sp.csr_matrix(np.array([[1, 0, 0],    # p0 -- a0
                                [1, 1, 0],    # p1 -- a0, a1  (the bridge)
                                [0, 1, 0],    # p2 -- a1
                                [0, 0, 1],    # p3 -- a2
                                [0, 0, 0]], dtype=float))  # p4 unowned
    N = 5
    worst_last = np.array([2, 1, 0])
    assert envelope(B, N, 0, worst_last)[0] == 3
    assert envelope(B, N, 1, np.array([0, 1, 2]))[0] == 2   # securing a0 leaves a1 with p1,p2
    assert envelope(B, N, 2, np.array([0, 1, 2]))[0] == 1   # only a2/p3 left
    assert envelope(B, N, 3, np.array([0, 1, 2])) == (0, None)

    # the identity the analytic envelope rests on: at beta_p = 1.0 the SIR reach
    # from an account's portfolio equals the package count of its component
    _, lab = sp.csgraph.connected_components(sp.bmat([[None, B], [B.T, None]]), directed=False)
    comp_pkgs = np.bincount(lab[:N], minlength=lab.max() + 1)
    for m in range(3):
        pkgs = B.tocsc()[:, m].nonzero()[0].tolist()
        sim = BranchingProcessSimulator(A_csr=None, B_csr=B.tocsr(), beta=BETA, gamma=0.0,
                                        bipartite_mode=True, beta_p=1.0, seed=0)
        h = sim.run(max_steps=50, initial_nodes=pkgs)
        sir = h[-1]['I'] + h[-1]['R']
        assert sir == comp_pkgs[lab[N + m]], (m, sir, comp_pkgs[lab[N + m]])

    # a 4-package chain a0-p1-a1-p2-a2: one component, so component size is 4 for
    # all three accounts and cannot order them. One-hop degree must, and must put
    # the middle account first.
    C = sp.csr_matrix(np.array([[1, 0, 0],    # p0 -- a0
                                [1, 1, 0],    # p1 -- a0, a1
                                [0, 1, 1],    # p2 -- a1, a2
                                [0, 0, 1]], dtype=float))  # p3 -- a2
    _, lab_c = sp.csgraph.connected_components(sp.bmat([[None, C], [C.T, None]]), directed=False)
    assert len(set(lab_c.tolist())) == 1, 'chain must be one component'
    assert onehop_degree(C, chunk=2).tolist() == [3, 4, 3]
    assert rank_by_onehop(C, 4)[0] == 1, 'middle account must rank first'
    print('selftest ok')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        _selftest()
    else:
        main()
