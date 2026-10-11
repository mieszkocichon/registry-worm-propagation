# ADR-0008: Node-Universe Parity Normalization for A/B Baseline Testing

## Status
Accepted

## Context
When comparing the speed and scale of worm propagation across the Maintainer network (Notebook 03) versus the Dependency network (Notebook 05), we face a "universe size" disparity. 

The Maintainer network is constructed from the extended portfolio of compromised maintainers (~7,900 nodes). The Dependency network is constructed from the downstream dependent packages fetched via deps.dev. The total number of unique packages in these two graphs differs significantly. 

Comparing raw numbers of infected packages (e.g., 2,000 packages infected) would be highly misleading, as the scale of the underlying networks is different. To test the hypothesis that the co-maintainership graph propagates worms more rapidly than the dependency graph, we need a normalized, scale-free metric.

## Decision
We decided to enforce Node-Universe Parity Normalization across all epidemiological simulations:
1. Every simulation run records the raw count of infected packages ($I$) at each time step.
2. When plotting the curves, the raw counts are divided by the total number of nodes in that specific network ($N_{universe}$) and multiplied by 100 to yield the percentage of the universe infected:
   $$\% \text{ Infected} = \frac{I}{N_{universe}} \times 100$$
3. Both Notebook 03 and Notebook 05 use this normalized metric for their primary visualization axes and summary tables.

## Consequences

### Positive
* **Fair A/B Testing:** Eliminates size-based bias, allowing a direct comparison of the propagation speed and saturation percentage between the two networks.
* **Interpretation:** Clearer presentation of results for the paper, as readers can immediately grasp the proportion of the ecosystem compromised.

### Negative
* **Loss of Absolute Scale:** The percentage normalization conceals the absolute number of affected systems. To mitigate this, the absolute size of each network ($N$) is explicitly printed in the notebook logs and the manuscript text.
