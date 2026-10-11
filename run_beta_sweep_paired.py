"""R1 + R2: is the paired dominance factor invariant in beta, and how much
Monte Carlo noise does the dependency arm actually carry?

The published headline (run_stats200_fair_extended.py) rests on ONE realisation
per seed per arm at beta = 0.9. Two objections follow, and this script answers
both with the same 12,000 simulations:

  R1  "matched beta" holds a symbol fixed, not a mechanism. On B, beta is the
      probability an infected package yields an account takeover; on D_ext it
      is the probability a declared dependent adopts a malicious release. If
      the dominance factor moves with beta, the comparison is a statement
      about the parameter rather than about the topology. We sweep
      beta in {0.3, 0.6, 0.9} on BOTH arms and recompute the whole test at each.

  R2  the co-maintainer arm is deterministic under beta_p = 1.0 (between-run
      SD is exactly 0), which is why one realisation per seed was defensible
      there. The dependency arm is NOT: it is a genuine Bernoulli process at
      beta = 0.9, gamma > 0. We run 10 replicates per seed on both arms, report
      the per-seed SD, and re-run the Wilcoxon on per-seed replicate MEANS
      rather than on single draws.

Seed frame, candidate list and draw are byte-identical to
run_stats200_fair.py / run_stats200_fair_extended.py. Replicate 0 reuses the
published per-seed RNG seed (42 + k), so at beta = 0.9 it must reproduce the
stored reach arrays EXACTLY. The script asserts this and refuses to report if
it does not. Replicates 1..R-1 use disjoint streams (1_000_000*r + 42 + k).

Output: data/npm/beta_sweep_paired_200.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from scipy import stats

sys.path.append('scripts')
sys.path.append('.')
from data_utils import load_node_universe
from graph_builder import build_bipartite_graph
from simulation_engine import BranchingProcessSimulator
from run_stats200_fair_extended import build_extended

BASE = Path(__file__).parent
PUBLISHED = BASE / 'data' / 'npm' / 'random_seed_campaigns_200_fair_extended.json'
OUT = BASE / 'data' / 'npm' / 'beta_sweep_paired_200.json'

BETAS = [0.9, 0.6, 0.3]
N_REPLICATES = 10
STEPS = 200
N_SEEDS = 200


def rng_seed(replicate, k):
    """Replicate 0 reproduces the published stream; the rest are disjoint."""
    return 42 + k if replicate == 0 else 1_000_000 * replicate + 42 + k


def main():
    t_start = time.time()
    pkg_set, pkg_list_univ, pkg_to_idx_univ, D_csr = load_node_universe()
    _, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph(allowed_packages=pkg_set)

    gamma = float((BASE / 'data' / 'npm' / 'gamma_param.txt').read_text().strip())
    N_corpus = len(pkg_list)

    ext_pkg_list, D_ext, n_ext, _ = build_extended(pkg_list_univ, pkg_to_idx_univ)
    B_ext = sp.vstack([B_csr, sp.csr_matrix((n_ext, B_csr.shape[1]))]).tocsr()

    print(f'N_corpus={N_corpus:,}  N_ext={len(ext_pkg_list):,}  '
          f'D_ext nnz={D_ext.nnz:,}  B_ext nnz={B_ext.nnz:,}  gamma={gamma}', flush=True)

    # --- identical candidate frame and identical draw as the published run ---
    m_deg = np.diff(B_csr.tocsr().indptr)
    out_deg = np.diff(D_csr.indptr)
    cand = [(pkg_list_univ[i], i) for i in np.where(out_deg > 0)[0]
            if pkg_list_univ[i] in pkg_to_idx and m_deg[pkg_to_idx[pkg_list_univ[i]]] > 0]
    assert len(cand) == 1183, f'candidate frame changed: {len(cand)}'
    picks = np.random.default_rng(42).choice(len(cand), size=N_SEEDS, replace=False)

    # reach[beta][arm] -> array (N_REPLICATES, N_SEEDS)
    reach = {b: {'B': np.zeros((N_REPLICATES, N_SEEDS)),
                 'D': np.zeros((N_REPLICATES, N_SEEDS))} for b in BETAS}

    total = len(BETAS) * N_REPLICATES * N_SEEDS * 2
    done = 0
    for beta in BETAS:
        for r in range(N_REPLICATES):
            for k, j in enumerate(picks):
                name, i_univ = cand[j]
                s = rng_seed(r, k)

                sim = BranchingProcessSimulator(A_csr=None, B_csr=B_ext, beta=beta, gamma=gamma,
                                                bipartite_mode=True, beta_p=1.0, seed=s)
                h = sim.run(max_steps=STEPS, initial_nodes=[pkg_to_idx[name]])
                reach[beta]['B'][r, k] = h[-1]['I'] + h[-1]['R']

                sim = BranchingProcessSimulator(A_csr=D_ext, B_csr=None, beta=beta, gamma=gamma,
                                                bipartite_mode=False, seed=s)
                h = sim.run(max_steps=STEPS, initial_nodes=[i_univ])
                reach[beta]['D'][r, k] = h[-1]['I'] + h[-1]['R']

                done += 2
            el = time.time() - t_start
            print(f'  beta={beta} replicate {r + 1}/{N_REPLICATES} done '
                  f'[{done}/{total} sims, {el / 60:.1f} min elapsed]', flush=True)

    # --- SELF-CHECK: replicate 0 at beta=0.9 must equal the published arrays --
    pub = json.loads(PUBLISHED.read_text())
    ok_B = np.array_equal(reach[0.9]['B'][0], np.array(pub['reach_B_pkgs'], float))
    ok_D = np.array_equal(reach[0.9]['D'][0], np.array(pub['reach_D_extended_pkgs'], float))
    print(f'\nSELF-CHECK vs random_seed_campaigns_200_fair_extended.json')
    print(f'  co-maintainer replicate 0 reproduces exactly : {ok_B}')
    print(f'  dependency   replicate 0 reproduces exactly : {ok_D}')
    if not (ok_B and ok_D):
        print('  !! MISMATCH -- this run is not comparable to the published one.')
        print('     Refusing to report. Investigate before using any number below.')
        return

    # --- R2: Monte Carlo noise, and the test re-run on replicate means --------
    print('\n=== R2: between-replicate noise, 10 replicates per seed ===')
    summary = {}
    for beta in BETAS:
        rb_all, rd_all = reach[beta]['B'], reach[beta]['D']
        sd_B, sd_D = rb_all.std(axis=0, ddof=1), rd_all.std(axis=0, ddof=1)
        rb, rd = rb_all.mean(axis=0), rd_all.mean(axis=0)

        ratio = rb.mean() / rd.mean()
        w = stats.wilcoxon(rb, rd, alternative='greater', zero_method='zsplit')
        bt = np.random.default_rng(7).integers(0, N_SEEDS, size=(10000, N_SEEDS))
        ratios = rb[bt].mean(axis=1) / np.maximum(rd[bt].mean(axis=1), 1e-12)

        summary[beta] = {
            'mean_B': rb.mean(), 'mean_D': rd.mean(),
            'median_B': float(np.median(rb)), 'median_D': float(np.median(rd)),
            'max_B': rb.max(), 'max_D': rd.max(),
            'ratio_mean': ratio,
            'ratio_median': float(np.median(rb) / max(np.median(rd), 1e-12)),
            'ci_lo': float(np.percentile(ratios, 2.5)), 'ci_hi': float(np.percentile(ratios, 97.5)),
            'W': float(w.statistic), 'p': float(w.pvalue),
            'B_wins': int((rb > rd).sum()), 'D_wins': int((rb < rd).sum()),
            'sd_B_max': float(sd_B.max()), 'sd_B_mean': float(sd_B.mean()),
            'sd_D_max': float(sd_D.max()), 'sd_D_mean': float(sd_D.mean()),
            'sd_D_rel_mean': float((sd_D / np.maximum(rd, 1)).mean()),
            'seeds_B_zero_sd': int((sd_B == 0).sum()), 'seeds_D_zero_sd': int((sd_D == 0).sum()),
        }
        s = summary[beta]
        print(f'\n  beta = {beta}')
        print(f'    per-seed SD  B: max {s["sd_B_max"]:.3f}, mean {s["sd_B_mean"]:.3f}, '
              f'{s["seeds_B_zero_sd"]}/{N_SEEDS} seeds with SD exactly 0')
        print(f'    per-seed SD  D: max {s["sd_D_max"]:.3f}, mean {s["sd_D_mean"]:.3f}, '
              f'{s["seeds_D_zero_sd"]}/{N_SEEDS} seeds with SD exactly 0')
        print(f'    mean  {s["mean_B"]:.1f} vs {s["mean_D"]:.1f} pkgs   -> {ratio:.2f}x '
              f'[95% CI {s["ci_lo"]:.2f}-{s["ci_hi"]:.2f}]')
        print(f'    median {s["median_B"]:.1f} vs {s["median_D"]:.1f} pkgs -> '
              f'{s["ratio_median"]:.1f}x')
        print(f'    Wilcoxon W={s["W"]:.1f}, p={s["p"]:.3e};  '
              f'B>D on {s["B_wins"]}/{N_SEEDS}, D>B on {s["D_wins"]}')

    print('\n=== R1: dominance factor across beta (on replicate means) ===')
    print(f'  {"beta":>6} {"mean B":>9} {"mean D":>9} {"mean ratio":>11} '
          f'{"med B":>7} {"med D":>7} {"med ratio":>10} {"p":>11}')
    for beta in BETAS:
        s = summary[beta]
        print(f'  {beta:>6} {s["mean_B"]:>9.1f} {s["mean_D"]:>9.1f} {s["ratio_mean"]:>10.2f}x '
              f'{s["median_B"]:>7.1f} {s["median_D"]:>7.1f} {s["ratio_median"]:>9.1f}x '
              f'{s["p"]:>11.2e}')

    json.dump({
        'betas': BETAS, 'n_replicates': N_REPLICATES, 'n_seeds': N_SEEDS,
        'gamma': gamma, 'beta_p': 1.0, 'steps': STEPS,
        'N_corpus': N_corpus, 'N_ext': len(ext_pkg_list), 'D_ext_nnz': int(D_ext.nnz),
        'self_check_replicate0_matches_published': True,
        'summary': {str(b): summary[b] for b in BETAS},
        'reach': {str(b): {'B': reach[b]['B'].tolist(), 'D': reach[b]['D'].tolist()}
                  for b in BETAS},
    }, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}   total {(time.time() - t_start) / 60:.1f} min')


if __name__ == '__main__':
    main()
