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

beta = 0.9  # Baseline beta

# Node universe must match the rest of the paper (npm_metadata.jsonl, via
# load_node_universe) -- NOT deps_dev_data.jsonl, whose 'dependents' field
# is empty for every record and silently shrinks/skews the package universe.
pkg_set, _, _, _ = load_node_universe()

npm_meta, pkg_list, pkg_to_idx, m_list, m_to_idx, B = build_bipartite_graph(allowed_packages=pkg_set)

# Load Patient Zero
with open('../data/npm/patient_zeros.json', 'r') as f:
    patient_zeros = json.load(f)
initial_indices = [pkg_to_idx[p] for p in patient_zeros if p in pkg_to_idx]

runs = 50
max_steps = 200

# Reproducibility policy
master_seed = 42
rng = np.random.default_rng(master_seed)
mc_seeds = rng.integers(0, 1000000, size=runs).tolist()

def run_sim(graph, b, g, is_bipartite=True, gm=0.0):
    histories = []
    r0s = []
    for i in range(runs):
        if is_bipartite:
            sim = BranchingProcessSimulator(A_csr=None, beta=b, gamma=g, seed=mc_seeds[i], B_csr=graph, bipartite_mode=True, gamma_m=gm, beta_p=1.0)
        else:
            sim = BranchingProcessSimulator(A_csr=graph, beta=b, gamma=g, seed=mc_seeds[i])
            
        h = sim.run(max_steps=max_steps, initial_nodes=initial_indices)
        I_traj = [step['I'] for step in h]
        while len(I_traj) <= max_steps:
            I_traj.append(0)
        histories.append(I_traj[:max_steps+1])
        
        # Calculate R0 on a fresh early-phase sim
        r0s.append(estimate_R0(sim))
    return np.mean(np.array(histories), axis=0) / len(pkg_list) * 100

# 1. Baseline
mean_I_baseline = run_sim(B, beta, gamma, is_bipartite=True)

# 2. Fast Detection (gamma * 2 -> half dwell time)
mean_I_fast = run_sim(B, beta, min(gamma * 2, 1.0), is_bipartite=True)

# 3. Targeted 2FA (Top 50 maintainers secured)
# Calculate maintainer degree
maintainer_degrees = np.array(B.sum(axis=0)).flatten()
top_50_m_idx = np.argsort(maintainer_degrees)[-50:]
B_secure = B.copy()
mask = np.ones(B.shape[1], dtype=int)
mask[top_50_m_idx] = 0
diag = sp.diags(mask)
B_secure = B_secure.dot(diag)
B_secure.eliminate_zeros()

mean_I_2fa = run_sim(B_secure, beta, gamma, is_bipartite=True)

# 4. Token Rotation (Maintainer Recovery: e.g. 5 days -> gamma_m = 0.2)
mean_I_token = run_sim(B, beta, gamma, is_bipartite=True, gm=0.2)

days = range(len(mean_I_baseline))
plt.figure(figsize=(12,8))
plt.plot(days, mean_I_baseline, label='Baseline (Beta=0.9)', color='red', linestyle='--')
plt.plot(days, mean_I_fast, label='Fast Detection (2x Gamma)', color='blue')
plt.plot(days, mean_I_2fa, label='Targeted 2FA Ceiling (Top 50 Maint Secured 100%)', color='green')
plt.plot(days, mean_I_token, label='Token Rotation (gamma_m=0.2)', color='purple')

plt.title('Counterfactual Defenses in Maintainer Network (N=50)')
plt.ylabel('% of Packages Infected')
plt.xlabel('Days')
plt.legend()
plt.savefig('../figures/targeted_2fa_simulation.png')
# Save another copy for the fast detection artifact since they are shown together
plt.savefig('../figures/fast_detection_simulation.png')
plt.show()

print(f"node universe: {len(pkg_list)} packages")
print(f"Final infected %: baseline={mean_I_baseline[-1]:.4f}  fast_detection={mean_I_fast[-1]:.4f}  "
      f"targeted_2fa={mean_I_2fa[-1]:.4f}  token_rotation={mean_I_token[-1]:.4f}")
print(f"Reduction vs baseline: fast_detection={100*(1-mean_I_fast[-1]/mean_I_baseline[-1]):.2f}%  "
      f"targeted_2fa={100*(1-mean_I_2fa[-1]/mean_I_baseline[-1]):.2f}%  "
      f"token_rotation={100*(1-mean_I_token[-1]/mean_I_baseline[-1]):.2f}%")

