#!/usr/bin/env python3
"""Infection curves: bipartite (co-maintainer) vs dependency transmission, matched beta."""
import json
import numpy as np
import matplotlib.pyplot as plt
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from simulation_engine import BranchingProcessSimulator
from graph_builder import build_bipartite_graph
from data_utils import load_node_universe

base = Path(__file__).parent.parent

print("Loading graphs...")
npm_meta, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr = build_bipartite_graph()
pkg_set, pkg_list2, pkg_to_idx2, D_csr = load_node_universe()

with open(base / 'data' / 'npm' / 'gamma_param.txt') as f:
    GAMMA = float(f.read().strip())
with open(base / 'data' / 'npm' / 'patient_zeros.json') as f:
    patient_zeros = json.load(f)

BETA = 0.9
MC_RUNS = 50
MAX_STEPS = 400

initial_indices_b = np.array([pkg_to_idx[p] for p in patient_zeros if p in pkg_to_idx])
initial_indices_d = np.array([pkg_to_idx2[p] for p in patient_zeros if p in pkg_to_idx2])

print(f"beta={BETA}, gamma={GAMMA} (from survival analysis, full merged dataset)")
print(f"B_csr: {B_csr.shape}, {B_csr.nnz} edges | D_csr: {D_csr.shape}, {D_csr.nnz} edges")

def run_channel(label, initial_indices, n_nodes, **sim_kwargs):
    print(f"Running {label} ({MC_RUNS} MC runs)...")
    rng = np.random.default_rng(42)
    seeds = rng.integers(0, 1_000_000, size=MC_RUNS)
    all_pct_curves = []
    for seed in seeds:
        sim = BranchingProcessSimulator(seed=int(seed), **sim_kwargs)
        history = sim.run(max_steps=MAX_STEPS, initial_nodes=initial_indices)
        # cumulative ever-infected (I + R) as % of universe, per step
        curve = [100.0 * (step['I'] + step['R']) / n_nodes for step in history]
        while len(curve) < MAX_STEPS + 1:
            curve.append(curve[-1])
        all_pct_curves.append(curve[:MAX_STEPS + 1])
    arr = np.array(all_pct_curves)
    return arr.mean(axis=0), arr.std(axis=0)

bipartite_mean, bipartite_std = run_channel(
    "bipartite (co-maintainer)", initial_indices_b, len(pkg_list),
    A_csr=None, beta=BETA, gamma=GAMMA, B_csr=B_csr, bipartite_mode=True
)
dependency_mean, dependency_std = run_channel(
    "dependency", initial_indices_d, len(pkg_list2),
    A_csr=D_csr, beta=BETA, gamma=GAMMA
)

days = np.arange(MAX_STEPS + 1)
final_b = bipartite_mean[-1]
final_d = dependency_mean[-1]

# Two panels: (left) early-phase zoom where all the dynamics happen,
# (right) full horizon confirming the plateau. A single 0-400 day axis
# would compress the entire rise into a few pixels since gamma is small
# and the giant component saturates within ~days at beta=0.9.
zoom_days = min(30, MAX_STEPS)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

for ax, xlim, title in [(ax1, zoom_days, f'Early phase (first {zoom_days} days)'),
                         (ax2, MAX_STEPS, f'Full horizon ({MAX_STEPS} days)')]:
    ax.plot(days, bipartite_mean, label='Bipartite (co-maintainer)', color='crimson', linewidth=2)
    ax.fill_between(days, bipartite_mean - bipartite_std, bipartite_mean + bipartite_std,
                     color='crimson', alpha=0.15)
    ax.plot(days, dependency_mean, label='Dependency (direct)', color='steelblue', linewidth=2)
    ax.fill_between(days, dependency_mean - dependency_std, dependency_mean + dependency_std,
                     color='steelblue', alpha=0.15)
    ax.set_xlim(0, xlim)
    ax.set_title(title)
    ax.set_xlabel('Days')
    ax.set_ylabel('% of packages ever infected (I + R)')
    ax.grid(alpha=0.3)

ax1.legend(loc='lower right')
ax2.annotate(f'{final_b:.2f}%', xy=(days[-1], final_b), xytext=(-70, 8),
             textcoords='offset points', color='crimson', fontweight='bold')
ax2.annotate(f'{final_d:.2f}%', xy=(days[-1], final_d), xytext=(-70, -18),
             textcoords='offset points', color='steelblue', fontweight='bold')

fig.suptitle(f'Cumulative Infection Curves: Bipartite vs Dependency Transmission\n'
             f'(matched β={BETA}, γ={GAMMA:.5f}, N={MC_RUNS} MC runs, full dataset)', y=1.02)
fig.tight_layout()

out_path = base / 'figures' / 'infection_curves_bipartite_vs_dependency.png'
fig.savefig(out_path, dpi=150, bbox_inches='tight')
print(f"\nSaved: {out_path}")
print(f"Final bipartite: {final_b:.2f}% | Final dependency: {final_d:.2f}%")
