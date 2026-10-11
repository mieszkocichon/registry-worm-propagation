# ADR 0020: Decoupling Topological Potential from Historical Empirical Baselines

## Status
Accepted

## Context
Our epidemiological simulations aim to prove that active supply chain worms leveraging the bipartite co-maintainer graph ({\text{CSR}}$) bypass traditional dependency chains ({\text{CSR}}$) and exhibit a vastly higher contagion reach. 

Initially, the simulation engine evaluated this hypothesis by measuring the outbreak size seeded from 10 historical "patient-zero" accounts (which yielded a 12.47% corpus reach). However, this high reach was an artifact of flawed date-proxy logic (see ADR-0019) which mistakenly included a massively connected maintainer hub in the starting seed set. Once strict exact-date anchoring was applied, the actual 10 verifiable historical seeds proved to be highly isolated peripheral accounts, resulting in an outbreak reach of only 0.03%.

Continuing to use the 10 historical seeds to claim a 12.47% topological dominance would constitute a mathematical half-truth: it conflates what the network is *capable* of with what historical attackers *actually achieved*.

## Decision
We formally decouple the measurement of the network's **Topological Potential** from the **Historical Empirical Baseline**:

1. **Topological Dominance Proofs (200 Randomized Seeds):** All claims regarding the systemic vulnerability of the registry topology (e.g., the 1,500x dominance factor, the 12.47% maximum reach) must be derived from unbiased, randomized single-seed Monte Carlo campaigns (n=200). This isolates the mathematical properties of the graphs from the idiosyncratic choices of past attackers.
2. **Historical Reality Check:** The simulations seeded from the exact-dated historical patient-zero cohort must be presented separately as a "Historical reality check". Their constrained outbreak size (0.03%) must be reported truthfully, and interpreted as empirical evidence that real-world attackers have, to date, primarily compromised isolated edge nodes rather than structural hubs.

## Consequences
- **Positive:** Resolves a major logical inconsistency and prevents the publication of a misleading statistical claim.
- **Positive:** Greatly increases the intellectual honesty of the research by openly acknowledging that the "doomsday" scenario is a structural vulnerability rather than an already-observed historical reality.
- **Positive:** Strengthens the justification for targeted defenses (ADR-0007), as it proves we still have time to secure the central maintainer hubs before attackers pivot from edge nodes to high-degree hubs.
