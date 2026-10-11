import json
import scipy.sparse as sp
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys
sys.path.append('../scripts')
from simulation_engine import BranchingProcessSimulator, estimate_R0
from graph_builder import build_bipartite_graph

# Load Gamma
with open('../data/npm/gamma_param.txt', 'r') as f:
    gamma = float(f.read().strip())
    
from data_utils import load_node_universe
pkg_set, _, _, _ = load_node_universe()
# NOTE: pkg_to_idx must come from build_bipartite_graph's OWN return value, not
# load_node_universe's. Both operate over the same package set but list(set(...))
# iteration order != file-insertion order, so reusing load_node_universe's
# pkg_to_idx to index into B silently points at the wrong packages.
npm_meta, pkg_list, pkg_to_idx, m_list, m_to_idx, B = build_bipartite_graph(allowed_packages=pkg_set)

# Load Patient Zero (Ground Truth from OSV)
osv_df = pd.read_csv('../data/npm/osv_npm_vulnerabilities_filtered.csv')
mask = osv_df['osv_id'].str.startswith('MAL-', na=False) | osv_df['aliases'].str.contains('MAL-', na=False)
mal = osv_df[mask].copy()
mal['published_dt'] = pd.to_datetime(mal['published'], utc=True)

# Build per-maintainer package timeline from raw metadata.
# - is_bot filter applied here so bot-inflated package counts don't pollute the portfolio signal.
# - For each (maintainer, package) pair we record the earliest version publish date.
#   This lets us ask: "how many packages did this maintainer have *before* the malicious version appeared?"
from collections import defaultdict
from constants import is_bot as _is_bot

# {maintainer_name -> {package_name -> earliest_published_dt (timezone-aware)}}
maint_pkg_timeline = defaultdict(dict)

with open('../data/npm/npm_metadata.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        try:
            d = json.loads(line)
            pkg_name = d['package']
            # Get the earliest version release date for this package
            time_dict = d.get('time', {})
            version_times = [
                pd.to_datetime(ts, utc=True, errors='coerce')
                for k, ts in time_dict.items()
                if k not in ('created', 'modified') and isinstance(ts, str)
            ]
            version_times = [t for t in version_times if pd.notna(t)]
            if not version_times:
                continue
            pkg_earliest = min(version_times)

            for m in d.get('maintainers', []):
                m_name = m.get('name') if isinstance(m, dict) else m
                if m_name and not _is_bot(m_name):
                    # Keep the earliest package-level date for this (maint, pkg) pair
                    existing = maint_pkg_timeline[m_name].get(pkg_name)
                    if existing is None or pkg_earliest < existing:
                        maint_pkg_timeline[m_name][pkg_name] = pkg_earliest
        except Exception:
            pass

def pre_publish_portfolio_size(maintainer_name, before_dt):
    # Count packages this maintainer owned with at least one release BEFORE before_dt.
    timeline = maint_pkg_timeline.get(maintainer_name, {})
    return sum(1 for pkg_dt in timeline.values() if pkg_dt < before_dt)

with open('../data/npm/patient_zeros.json', 'r') as f:
    patient_zeros = json.load(f)

initial_indices = [pkg_to_idx[p] for p in patient_zeros]
print(f"Loaded {len(initial_indices)} Patient-Zero seeds from patient_zeros.json (exact tier).")

betas = [0.3, 0.6, 0.9]
runs = 50
max_steps = 200

# Reproducibility policy
master_seed = 42
rng = np.random.default_rng(master_seed)
mc_seeds = rng.integers(0, 1000000, size=runs).tolist()

plt.figure(figsize=(12,8))
colors = ['blue', 'orange', 'red']

# BASELINE: 10x Single-Seed Aggregate Campaigns
all_r0s = {}

for idx, b in enumerate(betas):
    campaign_histories = []
    campaign_r0s = []
    
    for seed_node in initial_indices:
        r0s = []
        for i in range(runs):
            sim = BranchingProcessSimulator(A_csr=None, beta=b, gamma=gamma, seed=mc_seeds[i], B_csr=B, bipartite_mode=True, beta_p=1.0)
            h = sim.run(max_steps=max_steps, initial_nodes=[seed_node])
            
            # Pad history
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
    plt.plot(days, mean_I, label=f'Beta={b} (Mean % Infected)', color=colors[idx])
    plt.fill_between(days, mean_I - std_I, mean_I + std_I, color=colors[idx], alpha=0.1)
    
    all_r0s[b] = (np.mean(campaign_r0s), np.std(campaign_r0s))

plt.title('Outbreak in Maintainer Network - Worst-Case Ceiling (Beta_p=1.0) - Single-Seed Aggregate')
plt.ylabel('% of Packages Infected')
plt.xlabel('Days')
plt.legend()
plt.savefig('../figures/baseline_simulation_single_seed.png')
plt.show()

print("Estimated Basic Reproduction Numbers (R0) by Beta (Worst-Case Ceiling Beta_p=1.0, Single-Seed Mean):")
for b, (r0_mean, r0_std) in all_r0s.items():
    print(f"Beta {b}: R0 = {r0_mean:.2f} +/- {r0_std:.2f}")

# AGGREGATE RISK SURFACE: 10 Simultaneous Seeds
plt.figure(figsize=(12,8))
print("\n--- Aggregate Risk Surface (10 Simultaneous Seeds) ---")
all_r0s_simul = {}
for idx, b in enumerate(betas):
    histories = []
    r0s = []
    for i in range(runs):
        sim = BranchingProcessSimulator(A_csr=None, beta=b, gamma=gamma, seed=mc_seeds[i], B_csr=B, bipartite_mode=True, beta_p=1.0)
        h = sim.run(max_steps=max_steps, initial_nodes=initial_indices)
        
        I_traj = [step['I'] for step in h]
        while len(I_traj) <= max_steps:
            I_traj.append(0)
        histories.append(I_traj[:max_steps+1])
        r0s.append(estimate_R0(sim))
        
    hist_arr = np.array(histories)
    mean_I = np.mean(hist_arr, axis=0) / len(pkg_list) * 100
    std_I = np.std(hist_arr, axis=0) / len(pkg_list) * 100
    
    days = range(len(mean_I))
    plt.plot(days, mean_I, label=f'Beta={b} (Mean % Infected)', color=colors[idx])
    plt.fill_between(days, mean_I - std_I, mean_I + std_I, color=colors[idx], alpha=0.1)
    
    all_r0s_simul[b] = (np.mean(r0s), np.std(r0s))

plt.title('Aggregate Risk Surface - 10 Simultaneous Seeds (Worst-Case Beta_p=1.0 Sweep)')
plt.ylabel('% of Packages Infected')
plt.xlabel('Days')
plt.legend()
plt.show()

print("Estimated Basic Reproduction Numbers (R0) by Beta (Worst-Case Ceiling Beta_p=1.0, Simultaneous):")
for b, (r0_mean, r0_std) in all_r0s_simul.items():
    print(f"Beta {b}: R0 = {r0_mean:.2f} +/- {r0_std:.2f}")

# Sweep 2: Constant beta=0.9, sweeping beta_p
print("\nNote on Beta_p: The Day-0 patient zero cohort transmits malicious code deterministically (P=1.0) because the attacker already compromised their account to publish the patient zero package. The beta_p sweep governs all secondary transmissions.")
plt.figure(figsize=(12,8))
beta_p_sweep = [0.3, 0.6, 1.0]
for idx, bp in enumerate(beta_p_sweep):
    histories = []
    for i in range(runs):
        sim = BranchingProcessSimulator(A_csr=None, beta=0.9, gamma=gamma, seed=mc_seeds[i], B_csr=B, bipartite_mode=True, beta_p=bp)
        h = sim.run(max_steps=max_steps, initial_nodes=initial_indices)
        I_traj = [step['I'] for step in h]
        while len(I_traj) <= max_steps:
            I_traj.append(0)
        histories.append(I_traj[:max_steps+1])
    hist_arr = np.array(histories)
    mean_I = np.mean(hist_arr, axis=0) / len(pkg_list) * 100
    std_I = np.std(hist_arr, axis=0) / len(pkg_list) * 100
    days = range(len(mean_I))
    plt.plot(days, mean_I, label=f'Beta_p={bp} (Mean % Infected)', color=colors[idx])
    plt.fill_between(days, mean_I - std_I, mean_I + std_I, color=colors[idx], alpha=0.1)

plt.title('Outbreak in Maintainer Network - Beta_p Sensitivity Sweep (N=50)')
plt.ylabel('% of Packages Infected')
plt.xlabel('Days')
plt.legend()
plt.savefig('../figures/baseline_simulation_betap.png')
plt.show()

# Sweep 3: Gamma Sensitivity (Clamped vs Dropped)
with open('../data/npm/gamma_dropped_param.txt', 'r') as f:
    gamma_dropped = float(f.read().strip())

plt.figure(figsize=(12,8))

for idx, (g_name, g_val) in enumerate([('Clamped (Baseline)', gamma), ('Dropped (Sensitivity)', gamma_dropped)]):
    histories = []
    for i in range(runs):
        sim = BranchingProcessSimulator(A_csr=None, beta=0.9, gamma=g_val, seed=mc_seeds[i], B_csr=B, bipartite_mode=True, beta_p=1.0)
        h = sim.run(max_steps=max_steps, initial_nodes=initial_indices)
        I_traj = [step['I'] for step in h]
        while len(I_traj) <= max_steps:
            I_traj.append(0)
        histories.append(I_traj[:max_steps+1])
    hist_arr = np.array(histories)
    mean_I = np.mean(hist_arr, axis=0) / len(pkg_list) * 100
    std_I = np.std(hist_arr, axis=0) / len(pkg_list) * 100
    days = range(len(mean_I))
    plt.plot(days, mean_I, label=f'Gamma {g_name} (Mean % Infected)', color=colors[idx])
    plt.fill_between(days, mean_I - std_I, mean_I + std_I, color=colors[idx], alpha=0.1)

plt.title('Outbreak in Maintainer Network - Gamma Sensitivity Sweep (Beta=0.9, Worst-Case Ceiling Beta_p=1.0)')
plt.ylabel('% of Packages Infected')
plt.xlabel('Days')
plt.legend()
plt.savefig('../figures/baseline_simulation_gamma.png')
plt.show()

