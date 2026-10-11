# ADR 0006: Preventing Sequential Cascading Bias in Combined Mode

## Status
Accepted

## Context
In discrete-time epidemic simulation (specifically combined mode, where both bipartite maintainer-compromise and unipartite dependency-channel propagation run simultaneously), there is a risk of sequential order bias. If state vectors are updated in-place sequentially within a single timestep, a package infected via the dependency pathway on day $t$ could immediately transmit infection through the maintainer pathway during that same step. 

This violates discrete-time mechanics (where secondary transmissions should take a full timestep to manifest) and artificially accelerates the epidemic's velocity.

## Decision
Freeze the initial state vector of infected packages at the beginning of each step:
`I_vec_t0 = (self.states == 1).astype(np.float64)`

All propagation channels (both bipartite and unipartite) use `I_vec_t0` as their source vector for calculations. Newly infected packages are tracked in temporary boolean masks and are merged/committed to the state array only at the end of the simulation step, after both channels have fired.

## Consequences
- **Positive:** Mathematically clean discrete-time propagation, removing sequential update ordering artifacts.
- **Positive:** Consistent with deterministic cascade equations, as validated by `test_combined_deterministic` in the test suite.
- **Negative:** Slightly higher memory allocation per step due to state snapshotting, although the overhead of boolean arrays at this scale is negligible.
