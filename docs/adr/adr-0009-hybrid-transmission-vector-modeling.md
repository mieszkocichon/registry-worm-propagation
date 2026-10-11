# ADR-0009: Hybrid Transmission Vector Modeling

## Status
Accepted

## Context
In the real npm ecosystem, a worm does not necessarily propagate via a single vector. An attacker can combine vectors:
1. **Dependency Vector:** A package is compromised, infecting downstream dependents when they install it.
2. **Maintainer Vector:** The worm steals credentials (e.g., npm tokens) from the developer's machine during install, allowing the attacker to publish malicious updates to all other packages maintained by that developer.

Simulating either vector in isolation (as done in Notebooks 03 and 05) provides useful baseline bounds but does not capture the compounded, hybrid propagation behavior of real supply-chain worms (like a potential npm-native worm).

## Decision
We decided to architect the simulation engine (`BranchingProcessSimulator` in `simulation_engine.py`) to be mathematically independent of the specific adjacency matrix format. 
1. Instead of hardcoding graph types, the engine accepts any arbitrary sparse adjacency matrix $A$.
2. To support hybrid simulations in the future, we establish the math for a hybrid transmission matrix $A_{hybrid}$:
   $$A_{hybrid} = w_m A_{maintainer} + w_d A_{dependency}$$
   where $w_m$ and $w_d$ are weights representing the relative probability/speed of credential theft vs. dependency installation.
3. For the scope of the current paper, we analyze the two vectors independently to establish clear upper and lower bounds for each topology, but document the hybrid capability in the architecture.

## Consequences

### Positive
* **Extensibility:** The simulation engine does not need to be rewritten to support hybrid worm models.
* **Theoretical Framework:** Provides a clean mathematical description of multi-vector supply chain attacks for the discussion section of the paper.

### Negative
* **Parameter Complexity:** Introducing a hybrid graph adds more free parameters ($w_m, w_d$), which increases the sensitivity sweep search space and makes empirical fitting more difficult.
