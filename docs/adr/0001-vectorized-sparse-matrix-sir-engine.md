# ADR 0001: Vectorized Sparse-Matrix SIR Simulation Engine

## Status
Accepted

## Context
The project models the propagation of malicious code (worms) across the npm package dependency tree and co-maintainer networks. The target graph sizes scale to thousands of packages and maintainers (and potentially millions if scaled to the full npm registry). 

Standard graph libraries (such as NetworkX) model graphs using Python object structures. Iterating over nodes and edges in pure Python loops during stochastic simulation steps is computationally expensive ($O(N)$ or $O(E)$ overhead per step), making multi-run Monte Carlo sweeps across various parameters impractical.

## Decision
Represent all graphs and network states using pure SciPy sparse CSR matrices (`scipy.sparse.csr_matrix`) and vectorized NumPy arrays. 

All simulation steps are implemented as sparse matrix-vector products (e.g., `B_T.dot(I_vec)` where `B_T` is the transposed bipartite matrix and `I_vec` is the binary vector of infected packages). Stochastic infection probability rolls are vectorized using NumPy array operations (e.g., $1 - (1 - \beta)^W$ where $W$ is the weighted exposure vector).

## Consequences
- **Positive:** Order-of-magnitude speedups in simulation time. Monte Carlo runs (e.g., 50 runs of 200 steps across multiple parameters) execute within seconds.
- **Positive:** Eradicates the dependency on NetworkX or other heavy object-oriented graph libraries.
- **Negative:** Harder to implement complex topological operations (such as pathfinding or community detection) directly, though standard operations can be performed using `scipy.sparse.csgraph`.
