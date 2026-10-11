import numpy as np
import scipy.sparse as sp
from simulation_engine import BranchingProcessSimulator, estimate_R0

def test_unipartite_deterministic():
    # A simple 3-node line graph: 0-1-2
    row = [0, 1, 1, 2]
    col = [1, 0, 2, 1]
    data = [1, 1, 1, 1]
    A = sp.csr_matrix((data, (row, col)), shape=(3, 3))
    
    # Beta = 1.0 (deterministic infection), Gamma = 0.0 (no recovery until forced)
    sim = BranchingProcessSimulator(A, beta=1.0, gamma=0.0, seed=42)
    sim.set_infected([0])
    
    sim.step()
    # Node 0 infects Node 1
    assert sim.states[0] == 1
    assert sim.states[1] == 1
    assert sim.states[2] == 0
    assert sim.total_secondary == 1
    
    sim.step()
    # Node 1 infects Node 2
    assert sim.states[2] == 1
    assert sim.total_secondary == 2

    # Force recovery to test R0
    sim.states[:] = 2
    sim.total_completed_spreaders = 3
    r0 = estimate_R0(sim)
    assert r0 == 2.0 / 3.0

def test_person_time_r0_deterministic():
    # Line graph 0-1-2, beta=1.0 (deterministic infect), gamma=1.0 (deterministic recover).
    # Burns through: t0 I={0}; t1 0->1 infects, 0 recovers; t2 1->2 infects, 1 recovers;
    # t3 2 recovers, epidemic dies (i_count=0) at step_idx=2 -> early_r0 captured via fallback branch.
    # By hand: total_secondary=2, total_infectious_days=1(t0)+1(t1)+1(t2)+0(t3)=3.
    # R0 = (2/3) * (1/gamma=1) = 2/3.
    row = [0, 1, 1, 2]
    col = [1, 0, 2, 1]
    A = sp.csr_matrix((np.ones(4), (row, col)), shape=(3, 3))

    sim = BranchingProcessSimulator(A, beta=1.0, gamma=1.0, seed=42)
    sim.run(max_steps=10, initial_nodes=[0])

    assert sim.total_secondary == 2
    assert sim.total_infectious_days == 3
    assert abs(sim.early_r0 - (2.0 / 3.0)) < 1e-9
    assert abs(estimate_R0(sim) - sim.early_r0) < 1e-9

def test_bipartite_deterministic():
    # Packages: P0, P1, P2
    # Maintainers: M0, M1
    # P0 maintained by M0
    # P1 maintained by M0, M1
    # P2 maintained by M1
    row = [0, 1, 1, 2]
    col = [0, 0, 1, 1]
    B = sp.csr_matrix((np.ones(4), (row, col)), shape=(3, 2))
    
    sim = BranchingProcessSimulator(A_csr=None, beta=1.0, gamma=0.0, seed=42, B_csr=B, bipartite_mode=True)
    sim.set_infected([0]) # P0 infected
    
    # Check initialization cascade
    assert sim.states[0] == 1
    assert sim.maintainer_states[0] == 1
    assert sim.states[1] == 1 # M0 infects P1
    
    sim.step()
    # P1 tries to compromise M1 (beta=1.0) -> M1 compromised -> infects P2
    assert sim.maintainer_states[1] == 1
    assert sim.states[2] == 1

def test_combined_deterministic():
    # A_csr: P0 -> P1 -> P2
    A_row = [0, 1]
    A_col = [1, 2]
    A = sp.csr_matrix((np.ones(2), (A_row, A_col)), shape=(4, 4))
    
    # B_csr: P0 -> M0 -> P3
    B_row = [0, 3]
    B_col = [0, 0]
    B = sp.csr_matrix((np.ones(2), (B_row, B_col)), shape=(4, 1))
    
    sim = BranchingProcessSimulator(A_csr=A, beta=1.0, gamma=0.0, seed=42, B_csr=B, combined_mode=True, beta_p=1.0, beta_dep=1.0)
    sim.set_infected([0])
    
    # At t=0, P0 is infected.
    # Day-0 bipartite cascade: P0 -> M0 -> P3
    # Note: A_csr doesn't trigger on set_infected, only on step()
    assert sim.states[0] == 1
    assert sim.states[3] == 1
    assert sim.states[1] == 0
    assert sim.states[2] == 0
    
    sim.step()
    # At t=1:
    # Bipartite: P3 -> nothing new
    # Unipartite: P0 -> P1, P3 -> nothing
    # Crucially, P1 is infected, but P2 should NOT be infected yet!
    # Because P2 is reachable from P1, and P1 is infected in THIS step.
    assert sim.states[1] == 1
    assert sim.states[2] == 0
    
    sim.step()
    # At t=2: P1 -> P2
    assert sim.states[2] == 1

def test_bilayer_install_then_steal_then_republish():
    # Packages: X(0), Y(1), Z(2). D: Y installs X (X -> Y). B: maintainer M0 owns
    # Y and Z, not X. X has no maintainer at all.
    D = sp.csr_matrix((np.ones(1), ([0], [1])), shape=(3, 3))
    B = sp.csr_matrix((np.ones(2), ([1, 2], [0, 0])), shape=(3, 1))

    sim = BranchingProcessSimulator(A_csr=D, beta=1.0, gamma=0.0, seed=42, B_csr=B,
                                     bilayer_mode=True, beta_p=1.0, gamma_m=0.0)
    sim.set_infected([0])  # X infected
    # X has no maintainer, so nothing cascades on day 0.
    assert sim.maintainer_states[0] == 0
    assert sim.states[1] == 0 and sim.states[2] == 0

    sim.step()
    # Y installs X -> Y's maintainer (M0) is exposed and compromised -> M0
    # republishes to its whole portfolio (Y and Z).
    assert sim.maintainer_states[0] == 1
    assert sim.states[1] == 1
    assert sim.states[2] == 1

def test_bilayer_ignore_scripts_blocks_propagation():
    D = sp.csr_matrix((np.ones(1), ([0], [1])), shape=(3, 3))
    B = sp.csr_matrix((np.ones(2), ([1, 2], [0, 0])), shape=(3, 1))

    sim = BranchingProcessSimulator(A_csr=D, beta=1.0, gamma=0.0, seed=42, B_csr=B,
                                     bilayer_mode=True, beta_p=1.0, gamma_m=0.0,
                                     install_scripts_enabled=False)
    sim.set_infected([0])
    sim.step()
    # No install-time exposure -> no compromise -> no republish, ever.
    assert sim.maintainer_states[0] == 0
    assert sim.states[1] == 0 and sim.states[2] == 0

def test_bilayer_2fa_preserves_edges_reduces_probability():
    # Same graph as above, but M0 is fully OIDC-enrolled: theft probability is
    # driven to 0 even though beta=1.0 and the B/D edges are untouched.
    D = sp.csr_matrix((np.ones(1), ([0], [1])), shape=(3, 3))
    B = sp.csr_matrix((np.ones(2), ([1, 2], [0, 0])), shape=(3, 1))

    sim = BranchingProcessSimulator(A_csr=D, beta=1.0, gamma=0.0, seed=42, B_csr=B,
                                     bilayer_mode=True, beta_p=1.0, gamma_m=0.0,
                                     oidc_enrolment=np.array([1.0]))
    sim.set_infected([0])
    sim.step()
    assert sim.maintainer_states[0] == 0
    assert sim.states[1] == 0 and sim.states[2] == 0
    # The edges themselves are untouched -- only the roll probability changed.
    assert sim.B[1, 0] == 1 and sim.B[2, 0] == 1

def test_bilayer_staged_publishing_delay():
    D = sp.csr_matrix((np.ones(1), ([0], [1])), shape=(3, 3))
    B = sp.csr_matrix((np.ones(2), ([1, 2], [0, 0])), shape=(3, 1))

    sim = BranchingProcessSimulator(A_csr=D, beta=1.0, gamma=0.0, seed=42, B_csr=B,
                                     bilayer_mode=True, beta_p=1.0, gamma_m=0.0,
                                     staged_publishing_delay=2)
    sim.set_infected([0])
    sim.step()  # step 1: M0 compromised, republish queued for step 3
    assert sim.maintainer_states[0] == 1
    assert sim.states[1] == 0 and sim.states[2] == 0

    sim.step()  # step 2: still queued
    assert sim.states[1] == 0 and sim.states[2] == 0

    sim.step()  # step 3: queued republish lands
    assert sim.states[1] == 1 and sim.states[2] == 1

def test_bilayer_staged_publishing_cancelled_by_rotation():
    # Same graph, but M0's credential is revoked with certainty (gamma_m=1.0)
    # in the step right after compromise -- before the staged delay elapses.
    # The queued republish must never go live.
    D = sp.csr_matrix((np.ones(1), ([0], [1])), shape=(3, 3))
    B = sp.csr_matrix((np.ones(2), ([1, 2], [0, 0])), shape=(3, 1))

    sim = BranchingProcessSimulator(A_csr=D, beta=1.0, gamma=0.0, seed=42, B_csr=B,
                                     bilayer_mode=True, beta_p=1.0, gamma_m=1.0,
                                     staged_publishing_delay=3)
    sim.set_infected([0])
    sim.step()   # step 1: M0 compromised, republish queued for step 4; M0 then revoked
    assert sim.maintainer_states[0] == 2  # revoked (gamma_m=1.0 deterministic)

    for _ in range(5):
        sim.step()

    # The queued Y/Z republish was cancelled -- M0 was no longer compromised
    # when the staged delay elapsed.
    assert sim.states[1] == 0 and sim.states[2] == 0

def test_stochastic_convergence():
    """
    Tests that the empirical Monte Carlo secondary infection rate converges
    to the theoretical probability 1 - (1 - beta)^W.
    """
    # 1 seed connected to 1000 susceptible targets
    num_targets = 1000
    N = 1 + num_targets
    
    # Adjacency: seed (0) connects to targets 1..num_targets
    row = [0] * num_targets + list(range(1, num_targets + 1))
    col = list(range(1, num_targets + 1)) + [0] * num_targets
    data = np.ones(2 * num_targets)
    A = sp.csr_matrix((data, (row, col)), shape=(N, N))
    
    beta = 0.1
    runs = 100
    
    total_infected = 0
    rng = np.random.default_rng(42)
    mc_seeds = rng.integers(0, 1000000, size=runs)
    
    for i in range(runs):
        sim = BranchingProcessSimulator(A, beta=beta, gamma=0.0, seed=mc_seeds[i])
        sim.set_infected([0])
        sim.step()
        total_infected += sim.total_secondary
        
    empirical_prob = total_infected / (runs * num_targets)
    theoretical_prob = beta # Since W=1 weight per edge
    
    # 99% CI bounds
    import math
    std_err = math.sqrt(theoretical_prob * (1 - theoretical_prob) / (runs * num_targets))
    z_score = 2.576 # 99% CI
    
    assert abs(empirical_prob - theoretical_prob) <= z_score * std_err, f"Empirical {empirical_prob} outside theoretical {theoretical_prob} CI"

if __name__ == "__main__":
    test_unipartite_deterministic()
    test_person_time_r0_deterministic()
    test_bipartite_deterministic()
    test_combined_deterministic()
    test_bilayer_install_then_steal_then_republish()
    test_bilayer_ignore_scripts_blocks_propagation()
    test_bilayer_2fa_preserves_edges_reduces_probability()
    test_bilayer_staged_publishing_delay()
    test_bilayer_staged_publishing_cancelled_by_rotation()
    test_stochastic_convergence()
    print("All simulation tests passed.")
