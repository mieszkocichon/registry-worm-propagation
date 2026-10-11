# ADR 0004: Dynamic Hub Exclusion and Truncation Bias Mitigation

## Status
Accepted

## Context
Projecting a bipartite Package-Maintainer graph `B` (Packages x Maintainers) into a unipartite Package-Package co-maintainer graph $B B^T$ scales quadratically with maintainer degree ($O(d^2)$). A few massive organizational accounts or legacy "superhubs" (e.g., automated accounts holding tens of thousands of packages) cause $B B^T$ to explode in size, triggering memory exhaustion (OOM). 

Statically truncating these hubs (e.g., removing any maintainer with $> 10,000$ packages) avoids OOM but introduces severe measurement bias into the degree-distribution comparison plot (which is meant to prove the co-maintainer graph has a fatter tail than the dependency graph).

## Decision
1. **Dynamic Memory Budget:** Sort maintainers by degree and iteratively include them in the projection only if the cumulative sum of $d^2$ stays under a safe 50-million projected non-zero (`nnz`) limit.
2. **Measurement Bias Separation:** Compute the package degree distribution for descriptive plotting from the *full, untruncated* bipartite graph (which only takes $O(\text{nnz})$ memory, avoiding the quadratic matmul cost).
3. **Caveat Annotation:** Explicitly print the percentage of packages affected by the projection-stage hub exclusion, and annotate the final degree distribution plot with the exact count of excluded hubs to ensure transparency.

## Consequences
- **Positive:** Guarantees computation safety and avoids OOM crashes during bipartite projection.
- **Positive:** Preserves the fat-tail statistics in descriptive plots, preventing self-inflicted measurement bias from contaminating the headline comparison metric.
- **Negative:** The actual simulated propagation on the projected graph (if any projected graph is used directly) will lack connections through these superhubs, although bipartite-mode simulations use the full, untruncated `B` matrix.
