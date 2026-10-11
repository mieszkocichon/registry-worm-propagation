# ADR-0002: SciPy Sparse Matrix for Graph Representations and Simulations

## Status
Accepted

## Context
Our simulations model how worms propagate across package ecosystems. To model the shared maintainer network, we require a bipartite projection where two packages are connected if they share at least one maintainer.

Initially, we used NetworkX to build the bipartite graph and run the projections. However:
1. NetworkX bipartite projections (`bipartite.weighted_projected_graph`) are extremely slow for power-law distributions. A single maintainer account owning thousands of packages (a hub) causes an edge explosion ($O(D^2)$ where $D$ is the degree).
2. Representing graphs of size $>10,000$ in NetworkX consumes substantial memory and leads to slow iteration times.
3. The simulation engine step relied on looping through neighbors, scaling as $O(\text{steps} \times \text{edges})$ in pure Python.

## Decision
We decided to replace NetworkX with SciPy Sparse Matrices, using Compressed Sparse Row (CSR) format:
1. Represent the bipartite relation as a sparse matrix $B$ of shape $\text{packages} \times \text{maintainers}$.
2. Perform the bipartite projection using high-performance sparse matrix multiplication: $P = B \cdot B^T$.
3. Zero out the diagonal ($P_{i,i} = 0$) and eliminate explicit zeros to clean up the graph.
4. Rewrite the simulation engine to propagate infection using vector-matrix multiplication (`P.dot(I_vec)`), calculating the probability of infection in a single step using vectorized numpy operations.

## Consequences

### Positive
* **Performance:** Projecting graphs and running simulations is orders of magnitude faster. Computations that once threatened to exhaust system RAM and freeze execution now complete in milliseconds.
* **Vectorized Simulation:** The propagation step uses C-optimized sparse matrix multiplication, avoiding Python loop overhead completely.
* **Scalability:** The repository no longer depends on NetworkX, simplifying dependencies and allowing the simulation of millions of packages.

### Negative
* **Mathematical Complexity:** The simulation logic shifted from intuitive graph-node traversals to abstract vector-matrix operations. This requires a stronger background in linear algebra to modify.
