import json
import scipy.sparse as sp
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys
sys.path.append('../scripts')
from simulation_engine import BranchingProcessSimulator, estimate_R0
from graph_builder import build_bipartite_graph
from data_utils import load_node_universe

# Load Gamma
with open('../data/npm/gamma_param.txt', 'r') as f:
    gamma = float(f.read().strip())
    
pkg_set, pkg_list, pkg_to_idx, D_csr = load_node_universe()
# NOTE: pkg_to_idx_B must come from build_bipartite_graph's OWN return value.
# list(set(...)) order (load_node_universe) != file-insertion order
# (build_bipartite_graph), so reusing one graph's index map on the other's
# adjacency matrix silently points at the wrong packages.
_, pkg_list_B, pkg_to_idx_B, _, _, B = build_bipartite_graph(allowed_packages=pkg_set)

# combined_mode feeds D_csr and B into ONE simulator, which reads row i of each
# as the same package -- an assumption the two orderings above violate. Permute
# D_csr into B's ordering so the two channels actually agree on what row i is.
# Both cover the identical node universe, so the permutation is a bijection.
perm = np.array([pkg_to_idx[p] for p in pkg_list_B])
assert len(perm) == D_csr.shape[0] == B.shape[0]
D_csr = D_csr[perm][:, perm]
pkg_to_idx = pkg_to_idx_B

with open('../data/npm/patient_zeros.json', 'r') as f:
    patient_zeros = json.load(f)

initial_indices = [pkg_to_idx_B[p] for p in patient_zeros if p in pkg_to_idx_B]  # shared ordering

beta = 0.9
runs = 50
max_steps = 200

master_seed = 42
rng = np.random.default_rng(master_seed)
mc_seeds = rng.integers(0, 1000000, size=runs).tolist()

all_r0s = {}
colors = ['blue', 'orange', 'red']
plt.figure(figsize=(12, 8))

# Sweep beta_dep using the same ratios as NB5 — consistent rigor for an unvalidated parameter.
# beta_dep = beta * ratio where ratio represents the relative slowness of dependency-channel adoption.
# NB5 explicitly calls this a "rough proxy not empirical fact"; NB7 must match that caveat.
beta_dep_ratios = [0.05, 0.1, 0.2]  # 20x, 10x, 5x slower adoption than co-maintainer channel

print("\n**Note on Beta_dep Ratios:** These are sensitivity sweep values, not empirically derived.")
print("Lacking edge-level timestamps on dependency uptake, no exact multiplier is available.")
print("Results show outbreak bounds across the plausible range; see NB5 for the same caveat.\n")

for idx, ratio in enumerate(beta_dep_ratios):
    b_dep = beta * ratio
    campaign_histories = []
    campaign_r0s = []

    for seed_node in initial_indices:  # combined_mode requires D/B same-index assumption; see methodology note
        r0s = []
        for i in range(runs):
            sim = BranchingProcessSimulator(A_csr=D_csr, beta=beta, gamma=gamma, seed=mc_seeds[i], B_csr=B, combined_mode=True, beta_p=1.0, beta_dep=b_dep)
            h = sim.run(max_steps=max_steps, initial_nodes=[seed_node])

            I_traj = [step['I'] for step in h]
            while len(I_traj) <= max_steps:
                I_traj.append(0)
            campaign_histories.append(I_traj[:max_steps+1])
            r0s.append(estimate_R0(sim))

        campaign_r0s.append(np.mean(r0s))

    hist_arr = np.array(campaign_histories)
    mean_I = np.mean(hist_arr, axis=0) / len(pkg_list) * 100
    std_I = np.std(hist_arr, axis=0) / len(pkg_list) * 100

    days = range(len(mean_I))
    plt.plot(days, mean_I, label=f'Beta_dep ratio={ratio} (b_dep={b_dep:.3f})', color=colors[idx])
    plt.fill_between(days, mean_I - std_I, mean_I + std_I, color=colors[idx], alpha=0.1)

    all_r0s[ratio] = (np.mean(campaign_r0s), np.std(campaign_r0s))
    print(f"Beta_dep ratio={ratio} (b_dep={b_dep:.3f}): Combined R0 = {np.mean(campaign_r0s):.2f} +/- {np.std(campaign_r0s):.2f}")

print("Combined Mode R0 sweep complete (Worst-Case Ceiling Beta_p=1.0).")

plt.title('Outbreak in Combined Network - Beta_dep Sensitivity Sweep (Worst-Case Ceiling Beta_p=1.0)')
plt.ylabel('% of Packages Infected')
plt.xlabel('Days')
plt.legend()
plt.savefig('../figures/combined_vector_simulation.png')
plt.show()

