import json
import scipy.sparse as sp
import numpy as np
import matplotlib.pyplot as plt
import sys
sys.path.append('../scripts')
from simulation_engine import BranchingProcessSimulator, estimate_R0
from graph_builder import build_bipartite_graph

with open('../data/npm/gamma_param.txt', 'r') as f:
    gamma = float(f.read().strip())
    
beta = 0.9 

from data_utils import load_node_universe
pkg_set, pkg_list, pkg_to_idx, D_csr = load_node_universe()

with open('../data/npm/patient_zeros.json', 'r') as f:
    patient_zeros = json.load(f)

initial_indices = [pkg_to_idx[p] for p in patient_zeros if p in pkg_to_idx]
assert len(initial_indices) == len(patient_zeros), f"Seed mismatch: expected {len(patient_zeros)} but found {len(initial_indices)}. Node universes are not aligned!"
print(f"Using {len(initial_indices)} identical Patient-Zero seeds.")


# Reproducibility policy
master_seed = 42
rng = np.random.default_rng(master_seed)
mc_seeds = rng.integers(0, 1000000, size=50).tolist()

baseline_beta = 0.9
beta_dep_ratios = [0.05, 0.1, 0.2]
runs = 50
max_steps = 200

plt.figure(figsize=(12,8))
colors = ['blue', 'orange', 'purple']

all_r0s = {}

for idx, ratio in enumerate(beta_dep_ratios):
    b_dep = baseline_beta * ratio
    histories = []
    r0s = []
    for i in range(runs):
        sim = BranchingProcessSimulator(D_csr, b_dep, gamma, seed=mc_seeds[i])
        h = sim.run(max_steps=max_steps, initial_nodes=initial_indices)
        
        I_traj = [step['I'] for step in h]
        while len(I_traj) <= max_steps:
            I_traj.append(0)
        histories.append(I_traj[:max_steps+1])
            
        # Calculate R0 on a fresh early-phase sim
        r0s.append(estimate_R0(sim))

    hist_arr = np.array(histories)
    mean_I = np.mean(hist_arr, axis=0) / len(pkg_list) * 100  # Normalize to percentage
    std_I = np.std(hist_arr, axis=0) / len(pkg_list) * 100

    days = range(len(mean_I))
    plt.plot(days, mean_I, label=f'Ratio={ratio} (Mean % Infected)', color=colors[idx])
    plt.fill_between(days, mean_I - std_I, mean_I + std_I, color=colors[idx], alpha=0.1)
    
    all_r0s[ratio] = (np.mean(r0s), np.std(r0s))

plt.title(f'Outbreak in Dependency Network - Beta Ratio Sweep (Beta={baseline_beta}, N=50)')
plt.ylabel('% of Packages Infected')
plt.xlabel('Days')
plt.legend()
plt.savefig('../figures/dependency_vector_simulation.png')
plt.show()

print("Estimated Basic Reproduction Numbers (R0) by Beta Ratio:")
for ratio, (r0_mean, r0_std) in all_r0s.items():
    print(f"Ratio {ratio} (Beta {baseline_beta * ratio:.3f}): R0 = {r0_mean:.2f} +/- {r0_std:.2f}")


# Quantify Truncation Bias
import os
import json
dep_trunc_count = 0
total_deps_checked = 0
if os.path.exists('../data/npm/deps_dev_data.jsonl'):
    with open('../data/npm/deps_dev_data.jsonl', 'r', encoding='utf-8') as f:
        for line in f:
            total_deps_checked += 1
            if '"truncated": true' in line:
                dep_trunc_count += 1

maint_trunc_count = 0
if os.path.exists('../data/npm/truncated_maintainers.jsonl'):
    with open('../data/npm/truncated_maintainers.jsonl', 'r', encoding='utf-8') as f:
        maint_trunc_count = sum(1 for _ in f)
        
print("--- Asymmetric Truncation Bias Report ---")
print(f"Packages hitting MAX_DEPENDENTS cap: {dep_trunc_count} / {total_deps_checked} ({(dep_trunc_count/max(1, total_deps_checked))*100:.3f}%)")
print(f"Maintainers hitting MAX_PORTFOLIO cap: {maint_trunc_count}")
print("This shows the Co-Maintainer graph's upper tail is artificially deflated more heavily than the Dependency graph's tail.")

# Build Bipartite graph on exactly the same allowed_packages node universe
_, _, _, _, _, B = build_bipartite_graph(allowed_packages=pkg_set)

# Guard against projection blowup with dynamic memory budget (50M pairs)
maint_degrees = B.getnnz(axis=0).astype(np.int64)

# --- SNAPSHOT BEFORE ANY TRUNCATION ---
# These stats use the FULL untruncated B and are O(nnz) — no matmul.
# pkg_maint_degree[i] = how many (non-bot) maintainers package i has.
pkg_maint_degree_full = B.getnnz(axis=1).astype(np.int64)

sorted_degrees = np.sort(maint_degrees)
cumulative_nnz = np.cumsum(sorted_degrees**2)

budget = 50_000_000
safe_indices = np.where(cumulative_nnz <= budget)[0]
if len(safe_indices) < len(sorted_degrees):
    threshold = sorted_degrees[safe_indices[-1]] if len(safe_indices) > 0 else 0
else:
    threshold = sorted_degrees[-1]

max_maint_degree = sorted_degrees[-1] if len(sorted_degrees) > 0 else 0

n_hubs_excluded = 0
pkgs_affected_by_hub_exclusion = 0
# n = rows (packages) — unchanged by column truncation (maintainers), so safe to assign here.
n = B.shape[0]

if max_maint_degree > threshold:
    hub_indices = np.where(maint_degrees > threshold)[0]
    n_hubs_excluded = len(hub_indices)
    # Any package connected to an excluded hub has its co-maintainer degree underrepresented
    # in the projected B@B.T. We count and report this explicitly.
    hub_mask = maint_degrees > threshold
    pkgs_with_hub = (B[:, hub_mask].getnnz(axis=1) > 0).sum()
    pkgs_affected_by_hub_exclusion = int(pkgs_with_hub)
    print(f"\n--- EXCLUDED TOP HUBS (DYNAMIC BUDGET) ---")
    print(f"Excluded {n_hubs_excluded} maintainer hubs with degree > {threshold} to stay under {budget} projected nnz budget.")
    print(f"Projection-Stage Truncation Bias: {pkgs_affected_by_hub_exclusion}/{n} packages ({pkgs_affected_by_hub_exclusion/max(1,n)*100:.1f}%) connected to excluded hubs have UNDERESTIMATED co-maintainer degree in the plot below.")
    print("(This is separate from raw-fetch API truncation reported above — see methodology note.)")
    # Truncate only for the matmul, not for stats
    safe_mask = maint_degrees <= threshold
    B = B[:, safe_mask]

# Project to Package-Package unipartite co-maintainership graph in chunks
# We compute row-wise degrees and total nnz to avoid full matrix materialization
# n already assigned above (rows never change on column truncation)
chunk_size = 5000
deg_comaint = np.zeros(n, dtype=np.int64)
total_proj_nnz = 0

B_T = B.T.tocsc()
for i in range(0, n, chunk_size):
    end = min(i + chunk_size, n)
    B_chunk = B[i:end, :]
    chunk_proj = B_chunk @ B_T
    
    # We must set the diagonal to 0 for the rows in this chunk
    # The diagonal of the full matrix corresponds to indices (i+k, i+k)
    # Inside chunk_proj (which is chunk_size x n), the diagonal is (k, i+k)
    rows, cols = chunk_proj.nonzero()
    diag_mask = (rows + i) == cols
    if np.any(diag_mask):
        chunk_proj.data[diag_mask] = 0
        chunk_proj.eliminate_zeros()
        
    deg_comaint[i:end] = chunk_proj.getnnz(axis=1)
    total_proj_nnz += chunk_proj.nnz

# Calculate degree distributions
deg_dep = np.array(D_csr.sum(axis=1)).flatten()

print("Topological Stats Comparison:")
print(f"Node Universe Size: {len(pkg_list)} packages")
print("\n1. Dependency Graph (D_csr)")
print(f"   Max Degree (Hub Size): {deg_dep.max()}")
print(f"   Mean Degree:           {deg_dep.mean():.2f}")
print(f"   Density:               {D_csr.nnz / (D_csr.shape[0] * D_csr.shape[1]):.6f}")

print("\n2. Co-Maintainer Projection (B @ B.T)")
print(f"   Max Degree (Hub Size): {deg_comaint.max()}")
print(f"   Mean Degree:           {deg_comaint.mean():.2f}")
print(f"   Density:               {total_proj_nnz / (n * n):.6f}")

# Plot Degree Distribution
hub_note = f" ([!] {n_hubs_excluded} hub maintainers excluded from projection, affecting {pkgs_affected_by_hub_exclusion} pkgs)" if n_hubs_excluded > 0 else ""
plt.figure(figsize=(10, 6))
plt.hist(np.log1p(deg_dep), bins=50, alpha=0.5, label='Dependency Graph', density=True)
plt.hist(np.log1p(deg_comaint), bins=50, alpha=0.5, label=f'Co-Maintainer Graph (truncated tail{hub_note})', density=True)
plt.title(f'Log-Scaled Degree Distribution Comparison{"" if not n_hubs_excluded else chr(10) + "(Co-Maintainer tail underestimated — see hub-exclusion report above)"}')
plt.xlabel('log(1 + Degree)')
plt.ylabel('Density')
plt.legend()
plt.savefig('../figures/degree_distribution.png')
plt.show()

