import numpy as np
import scipy.sparse as sp

class BranchingProcessSimulator:
    def __init__(self, A_csr=None, beta=0.9, gamma=0.00281, seed=42, B_csr=None, bipartite_mode=False, gamma_m=0.0, beta_p=1.0, combined_mode=False, beta_dep=None,
                 bilayer_mode=False, install_scripts_enabled=True, staged_publishing_delay=0, oidc_enrolment=None):
        """
        A_csr: scipy.sparse.csr_matrix representing adjacency (weights). In
            bilayer_mode this is the dependency graph D (package installs package).
        beta: Base infection probability per unit weight (used for bipartite beta if bipartite/combined mode).
            In bilayer_mode this is the credential-theft probability beta_steal:
            P(an exposed package's maintainer has their token stolen).
        gamma: Recovery probability per time step
        B_csr: scipy.sparse.csr_matrix representing bipartite graph (Packages x Maintainers)
        bipartite_mode: bool, whether to use the two-stage maintainer compromise model
        gamma_m: Maintainer recovery probability per time step (for Token Rotation)
        beta_p: Maintainer -> Package transmission probability per time step.
            In bilayer_mode this is beta_pub: P(a compromised maintainer's republish
            to one portfolio package succeeds).
        combined_mode: bool, whether to use both B_csr and A_csr simultaneously (D and B propagate in parallel)
        beta_dep: Base infection probability for A_csr in combined_mode. Defaults to beta if None.
        bilayer_mode: bool, sequential D -> B^T -> B worm transmission (install, then steal, then
            republish), replacing the direct ownership-implies-compromise step of bipartite_mode with
            an explicit install-exposure gate on D. Requires both A_csr (=D) and B_csr.
        install_scripts_enabled: bool, whether installing a dependency exposes the installer's
            maintainer to credential theft (bilayer_mode only; models --ignore-scripts as False).
        staged_publishing_delay: int, steps a newly-compromised republish sits in a queue before
            taking effect (bilayer_mode only; 0 = immediate, matching every other mode).
        oidc_enrolment: optional array of length num_maintainers in [0, 1], the per-maintainer
            fraction of publishing already covered by short-lived OIDC-scoped tokens rather than a
            long-lived account-wide one. Multiplies down the effective theft probability
            (bilayer_mode only). None = no OIDC adoption.
        """
        if A_csr is not None:
            self.A = A_csr
            self.A_T = self.A.T.tocsr()
        else:
            self.A = None
            self.A_T = None

        if B_csr is not None:
            self.B = B_csr
            self.B_T = self.B.T.tocsr()
        else:
            self.B = None
            self.B_T = None

        self.bipartite_mode = bipartite_mode
        self.combined_mode = combined_mode
        self.bilayer_mode = bilayer_mode
        self.beta = beta
        self.beta_dep = beta_dep if beta_dep is not None else beta
        self.gamma = gamma
        self.gamma_m = gamma_m
        self.beta_p = beta_p
        self.install_scripts_enabled = install_scripts_enabled
        self.staged_publishing_delay = staged_publishing_delay
        self.oidc_enrolment = oidc_enrolment
        self.rng = np.random.default_rng(seed)

        if self.bilayer_mode:
            assert self.A is not None and self.B is not None, 'bilayer_mode requires both A_csr (D) and B_csr'
            assert self.A.shape[0] == self.B.shape[0], 'D and B must share the same package index space'

        if (self.bipartite_mode or self.combined_mode or self.bilayer_mode) and self.B is not None:
            self.num_nodes = self.B.shape[0]
            self.num_maintainers = self.B.shape[1]
            self._comp_vec = np.zeros(self.num_maintainers, dtype=np.float64)
        elif self.A is not None:
            self.num_nodes = self.A.shape[0]
            self.num_maintainers = 0
            self._comp_vec = None
        else:
            self.num_nodes = 0
            self.num_maintainers = 0
            self._comp_vec = None
            
        self.reset()
        
    def reset(self):
        # 0=Susceptible, 1=Infected, 2=Removed
        self.states = np.zeros(self.num_nodes, dtype=np.int8)
        if self.bipartite_mode or self.combined_mode or self.bilayer_mode:
            self.maintainer_states = np.zeros(self.num_maintainers, dtype=np.int8)
        self.staged_queue = []
        self.current_step = 0

        self.history = []
        self.total_secondary = 0
        self.total_completed_spreaders = 0
        self.total_infectious_days = 0

    def set_infected(self, initial_indices):
        self.states[initial_indices] = 1
        if (self.bipartite_mode or self.combined_mode or self.bilayer_mode) and self.B is not None:
            I_vec = (self.states == 1).astype(np.float64)
            W_m = self.B_T.dot(I_vec)
            
            # Day-0 Attacker Assumption:
            # We assume the attacker *already possessed* the compromised account
            # in order to publish the patient-zero packages. Thus, the initial 
            # maintainer compromise is 100% deterministic (prob=1.0) rather than
            # subject to the stochastic beta roll used for the rest of the simulation.
            newly_comp_indices = np.where(W_m > 0)[0]
            
            self.maintainer_states[newly_comp_indices] = 1
            if len(newly_comp_indices) > 0:
                self._comp_vec[newly_comp_indices] = 1.0
                W_p = self.B.dot(self._comp_vec)
                self._comp_vec[newly_comp_indices] = 0.0
                
                # Apply stochastic beta_p roll for Day-0 package infections
                vulnerable = (W_p > 0) & (self.states == 0)
                if np.any(vulnerable):
                    W_p_vuln = W_p[vulnerable]
                    prob = 1.0 - (1.0 - self.beta_p)**W_p_vuln
                    rolls = self.rng.random(size=len(prob))
                    new_inf_mask = rolls < prob
                    
                    vulnerable_indices = np.where(vulnerable)[0]
                    actual_new_infections = vulnerable_indices[new_inf_mask]
                    
                    self.states[actual_new_infections] = 1
                    self.total_secondary += len(actual_new_infections)
                
    def step(self):
        if self.bilayer_mode:
            return self._step_bilayer()
        elif self.combined_mode:
            return self._step_combined()
        elif self.bipartite_mode:
            return self._step_bipartite()
        else:
            return self._step_unipartite()

    def _step_bilayer(self):
        """Sequential D -> B^T -> B worm transmission (install, then steal, then
        republish): a package is exposed only by installing an already-infected
        dependency, not merely by sharing a maintainer with one (Section R1)."""
        self.current_step += 1
        I_vec = (self.states == 1).astype(np.float64)
        num_infected = np.sum(I_vec)
        if num_infected == 0 and len(self.staged_queue) == 0:
            return False

        # 1. Install exposure: packages that depend on an infected package run its
        # install-time hook, if hooks are not disabled.
        if self.install_scripts_enabled:
            exposed_pkgs = (self.A_T.dot(I_vec) > 0).astype(np.float64)
        else:
            exposed_pkgs = np.zeros(self.num_nodes, dtype=np.float64)

        # 2. Credential theft: maintainers of an exposed package have their token
        # stolen with probability beta (= beta_steal), discounted by OIDC adoption.
        W_m = self.B_T.dot(exposed_pkgs)
        S_m_mask = (self.maintainer_states == 0)
        at_risk_m = S_m_mask & (W_m > 0)

        if np.any(at_risk_m):
            beta_steal_eff = self.beta
            if self.oidc_enrolment is not None:
                beta_steal_eff = self.beta * (1.0 - self.oidc_enrolment[at_risk_m])
            probs = 1.0 - np.power(1.0 - beta_steal_eff, W_m[at_risk_m])
            rolls = self.rng.random(np.sum(at_risk_m))
            at_risk_indices = np.where(at_risk_m)[0]
            newly_comp_indices = at_risk_indices[rolls < probs]
            self.maintainer_states[newly_comp_indices] = 1

        # 3. Lateral republish: every currently-compromised maintainer attempts to
        # push the payload to each susceptible package in their own portfolio,
        # with probability beta_p (= beta_pub).
        comp_m_indices = np.where(self.maintainer_states == 1)[0]
        new_infections_count = 0
        if len(comp_m_indices) > 0:
            self._comp_vec[comp_m_indices] = 1.0
            W_p = self.B.dot(self._comp_vec)
            self._comp_vec[comp_m_indices] = 0.0

            S_p_mask = (self.states == 0)
            at_risk_p = S_p_mask & (W_p > 0)
            if np.any(at_risk_p):
                probs_p = 1.0 - np.power(1.0 - self.beta_p, W_p[at_risk_p])
                rolls_p = self.rng.random(np.sum(at_risk_p))
                at_risk_indices_p = np.where(at_risk_p)[0]
                newly_infected = at_risk_indices_p[rolls_p < probs_p]

                if self.staged_publishing_delay > 0:
                    self.staged_queue.append((self.current_step + self.staged_publishing_delay, newly_infected))
                else:
                    self.states[newly_infected] = 1
                    new_infections_count += len(newly_infected)
                    self.total_secondary += len(newly_infected)

        # Release any staged republishes whose delay has elapsed. A pending release
        # only goes live if at least one of its co-maintainers is STILL compromised
        # at release time: staged publishing's protective value is that it gives a
        # revoked-in-the-meantime credential's queued payload nothing left to ride
        # on, not merely that it arrives late.
        if self.staged_publishing_delay > 0 and self.staged_queue:
            ready = [pkgs for t, pkgs in self.staged_queue if t <= self.current_step]
            self.staged_queue = [(t, pkgs) for t, pkgs in self.staged_queue if t > self.current_step]
            still_comp = (self.maintainer_states == 1).astype(np.float64)
            for pkgs in ready:
                pkgs = pkgs[self.states[pkgs] == 0]
                if len(pkgs) == 0:
                    continue
                authorised = np.asarray(self.B[pkgs].dot(still_comp)).ravel() > 0
                pkgs = pkgs[authorised]
                self.states[pkgs] = 1
                new_infections_count += len(pkgs)
                self.total_secondary += len(pkgs)

        # Token rotation: a compromised maintainer's credential is revoked with
        # probability gamma_m per step.
        if self.gamma_m > 0:
            comp_mask = (self.maintainer_states == 1)
            num_comp = int(np.sum(comp_mask))
            if num_comp > 0:
                recov_rolls = self.rng.random(num_comp)
                comp_indices = np.where(comp_mask)[0]
                self.maintainer_states[comp_indices[recov_rolls < self.gamma_m]] = 2

        return self._finalize_step(I_vec, num_infected, new_infections_count)
            
    def _step_combined(self):
        I_vec_t0 = (self.states == 1).astype(np.float64)
        num_infected = np.sum(I_vec_t0)
        if num_infected == 0:
            return False
        
        # Boolean mask union — avoids Python-set boxing of numpy ints per step
        newly_infected_mask = np.zeros(self.num_nodes, dtype=bool)
        
        # --- Bipartite (Maintainer) Pathway ---
        W_m = self.B_T.dot(I_vec_t0)
        S_m_mask = (self.maintainer_states == 0)
        at_risk_m = S_m_mask & (W_m > 0)
        
        if np.any(at_risk_m):
            probs = 1.0 - np.power(1.0 - self.beta, W_m[at_risk_m])
            rolls = self.rng.random(np.sum(at_risk_m))
            compromised_this_step = rolls < probs
            
            at_risk_indices = np.where(at_risk_m)[0]
            newly_comp_indices = at_risk_indices[compromised_this_step]
            self.maintainer_states[newly_comp_indices] = 1

        comp_m_mask = (self.maintainer_states == 1)
        comp_m_indices = np.where(comp_m_mask)[0]
        
        if len(comp_m_indices) > 0:
            self._comp_vec[comp_m_indices] = 1.0
            W_p = self.B.dot(self._comp_vec)
            self._comp_vec[comp_m_indices] = 0.0
            
            S_p_mask = (self.states == 0)
            at_risk_p = S_p_mask & (W_p > 0)
            
            if np.any(at_risk_p):
                probs_p = 1.0 - np.power(1.0 - self.beta_p, W_p[at_risk_p])
                rolls_p = self.rng.random(np.sum(at_risk_p))
                infected_this_step_p = rolls_p < probs_p
                
                at_risk_indices_p = np.where(at_risk_p)[0]
                bip_new_inf = at_risk_indices_p[infected_this_step_p]
                newly_infected_mask[bip_new_inf] = True
                    
        # Maintainer Recovery
        if self.gamma_m > 0:
            M_vec = (self.maintainer_states == 1).astype(np.float64)
            num_comp_m = np.sum(M_vec)
            if num_comp_m > 0:
                m_recovery_rolls = self.rng.random(int(num_comp_m))
                m_recovered_mask = m_recovery_rolls < self.gamma_m
                old_comp_m_indices = np.where(M_vec > 0)[0]
                m_recovered_indices = old_comp_m_indices[m_recovered_mask]
                self.maintainer_states[m_recovered_indices] = 2
                
        # --- Unipartite (Dependency) Pathway ---
        # Note: We use I_vec_t0 to prevent sequential bias!
        W_dep = self.A_T.dot(I_vec_t0)
        S_p_mask_t0 = (self.states == 0)
        at_risk_dep = S_p_mask_t0 & (W_dep > 0)
        
        if np.any(at_risk_dep):
            probs_dep = 1.0 - np.power(1.0 - self.beta_dep, W_dep[at_risk_dep])
            rolls_dep = self.rng.random(np.sum(at_risk_dep))
            infected_this_step_dep = rolls_dep < probs_dep
            
            at_risk_indices_dep = np.where(at_risk_dep)[0]
            dep_new_inf = at_risk_indices_dep[infected_this_step_dep]
            newly_infected_mask[dep_new_inf] = True
            
        # --- Merge and Commit ---
        new_inf_arr = np.where(newly_infected_mask)[0]
        self.states[new_inf_arr] = 1
        new_infections_count = len(new_inf_arr)
        self.total_secondary += new_infections_count
        
        return self._finalize_step(I_vec_t0, num_infected, new_infections_count)

    def _step_bipartite(self):
        I_vec = (self.states == 1).astype(np.float64)
        num_infected = np.sum(I_vec)
        if num_infected == 0:
            return False
            
        # 1. Infected packages attempt to compromise their susceptible maintainers
        W_m = self.B_T.dot(I_vec)
        S_m_mask = (self.maintainer_states == 0)
        at_risk_m = S_m_mask & (W_m > 0)
        
        if np.any(at_risk_m):
            probs = 1.0 - np.power(1.0 - self.beta, W_m[at_risk_m])
            rolls = self.rng.random(np.sum(at_risk_m))
            compromised_this_step = rolls < probs
            
            at_risk_indices = np.where(at_risk_m)[0]
            newly_comp_indices = at_risk_indices[compromised_this_step]
            self.maintainer_states[newly_comp_indices] = 1

        # 2. All active compromised maintainers attempt to infect susceptible packages
        comp_m_mask = (self.maintainer_states == 1)
        comp_m_indices = np.where(comp_m_mask)[0]
        
        new_infections_count = 0
        if len(comp_m_indices) > 0:
            self._comp_vec[comp_m_indices] = 1.0
            W_p = self.B.dot(self._comp_vec)
            self._comp_vec[comp_m_indices] = 0.0
            
            S_p_mask = (self.states == 0)
            at_risk_p = S_p_mask & (W_p > 0)
            
            if np.any(at_risk_p):
                probs_p = 1.0 - np.power(1.0 - self.beta_p, W_p[at_risk_p])
                rolls_p = self.rng.random(np.sum(at_risk_p))
                infected_this_step_p = rolls_p < probs_p
                
                at_risk_indices_p = np.where(at_risk_p)[0]
                newly_infected_indices = at_risk_indices_p[infected_this_step_p]
                
                self.states[newly_infected_indices] = 1
                new_infections_count = len(newly_infected_indices)
                self.total_secondary += new_infections_count
                
        # Maintainer Recovery step (Token Rotation)
        if self.gamma_m > 0:
            M_vec = (self.maintainer_states == 1).astype(np.float64)
            num_comp_m = np.sum(M_vec)
            if num_comp_m > 0:
                m_recovery_rolls = self.rng.random(int(num_comp_m))
                m_recovered_mask = m_recovery_rolls < self.gamma_m
                old_comp_m_indices = np.where(M_vec > 0)[0]
                m_recovered_indices = old_comp_m_indices[m_recovered_mask]
                self.maintainer_states[m_recovered_indices] = 2

        return self._finalize_step(I_vec, num_infected, new_infections_count)

    def _step_unipartite(self):
        I_vec = (self.states == 1).astype(np.float64)
        num_infected = np.sum(I_vec)
        if num_infected == 0:
            return False
            
        W = self.A_T.dot(I_vec)
        S_mask = (self.states == 0)
        at_risk = S_mask & (W > 0)
        
        new_infections_count = 0
        if np.any(at_risk):
            probs = 1.0 - np.power(1.0 - self.beta, W[at_risk])
            rolls = self.rng.random(np.sum(at_risk))
            infected_this_step = rolls < probs
            
            at_risk_indices = np.where(at_risk)[0]
            newly_infected_indices = at_risk_indices[infected_this_step]
            self.states[newly_infected_indices] = 1
            new_infections_count = len(newly_infected_indices)
            self.total_secondary += new_infections_count
            
        return self._finalize_step(I_vec, num_infected, new_infections_count)

    def _finalize_step(self, I_vec, num_infected, new_infections_count):
        # Recovery step
        recovery_rolls = self.rng.random(int(num_infected))
        recovered_mask = recovery_rolls < self.gamma
        old_infected_indices = np.where(I_vec > 0)[0]
        recovered_indices = old_infected_indices[recovered_mask]
        
        self.states[recovered_indices] = 2
        self.total_completed_spreaders += len(recovered_indices)
        
        s_count = np.sum(self.states == 0)
        i_count = np.sum(self.states == 1)
        r_count = np.sum(self.states == 2)

        self.total_infectious_days += i_count
        self.history.append({'S': s_count, 'I': i_count, 'R': r_count, 'new_infections': new_infections_count})
        return i_count > 0

    def run(self, max_steps=100, initial_nodes=None):
        if initial_nodes is not None:
            self.set_infected(initial_nodes)
            
        s_count = np.sum(self.states == 0)
        i_count = np.sum(self.states == 1)
        r_count = np.sum(self.states == 2)
        self.total_infectious_days += i_count
        self.history.append({'S': s_count, 'I': i_count, 'R': r_count, 'new_infections': 0})

        self.early_r0 = 0.0
        r0_captured = False

        for step_idx in range(max_steps):
            if not self.step():
                if not r0_captured:
                    self.early_r0 = self._person_time_r0()
                break
            
            if not r0_captured and step_idx == 20:
                self.early_r0 = self._person_time_r0()
                r0_captured = True

        if not r0_captured:
            self.early_r0 = self._person_time_r0()
            
        return self.history

    def _person_time_r0(self):
        """
        Person-time R0 estimator: beta_eff = secondary infections / infectious-days
        observed in the early window, R0 = beta_eff * mean infectious period (1/gamma).
        Robust at low gamma (long dwell time), where total_completed_spreaders stays
        at 0 through the whole early window and the old secondary/completed-spreaders
        ratio degenerated into a raw, unnormalized infection count.
        """
        beta_eff = self.total_secondary / max(1.0, self.total_infectious_days)
        mean_infectious_period = (1.0 / self.gamma) if self.gamma > 0 else float('inf')
        return beta_eff * mean_infectious_period

def estimate_R0(sim):
    """
    Returns the early-phase Basic Reproduction Number (R0), estimated via the
    person-time method: R0 = (secondary infections / infectious-days) * (1/gamma).
    R0 is internally captured at step 20 by BranchingProcessSimulator.run()
    to avoid doubling the Monte Carlo simulation cost.
    """
    if hasattr(sim, 'early_r0'):
        return sim.early_r0

    # Legacy fallback for manual single-stepping (no run() call, no infectious-day
    # tracking available yet) - approximate via completed-spreaders ratio.
    if sim.total_completed_spreaders == 0:
        return 0.0
    return sim.total_secondary / sim.total_completed_spreaders
