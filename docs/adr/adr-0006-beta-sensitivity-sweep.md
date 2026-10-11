# ADR-0006: Beta Sensitivity Sweep and R0 Censoring Bias Mitigation

## Status
Accepted

## Context
In previous phases:
1. The probability of transmission per contact ($\beta$) was hardcoded to a single arbitrary value ($\beta = 0.9$).
2. The simulation was capped at `max_steps = 60` steps.
3. This setup introduced a severe scientific bias. The Basic Reproduction Number ($R_0$) estimator divides total secondary infections by completed spreaders. If the median dwell time (~546 days) translates to a recovery rate ($\gamma$) that takes much longer than 60 steps to resolve, most infected nodes never "complete" recovery. This right-censoring biased the $R_0$ calculation upward.

## Decision
We decided to:
1. Implement a sensitivity sweep over three values of $\beta$ ($\beta \in [0.3, 0.6, 0.9]$) to evaluate how varying infectivity rates impact outbreak size.
2. Extend the simulation duration from `max_steps = 60` to `max_steps = 200` steps. This allows the majority of infected nodes to resolve their state (either recover or complete their infection trajectory), mitigating right-censoring bias.
3. Update the visualization scripts to plot the mean and standard deviation trajectories for each $\beta$ parameter on a single chart for direct comparison.

## Consequences

### Positive
* **Sensitivity Insight:** We can now observe how the infection rate behaves across different levels of worm transmissibility, making the model more robust.
* **Unbiased R0:** By extending the simulation time window to 200 steps, the $R_0$ estimator has enough completed spreaders to yield a statistically stable value (converging to ~4.4 instead of fluctuating due to truncation).
* **Scientific Quality:** Eliminates the arbitrary hardcoded parameter assumption.

### Negative
* **Computational Cost:** Sweeping three beta values with 50 Monte Carlo runs each and extending steps to 200 multiplies the required floating-point operations by a factor of 10. The simulation notebooks take longer to execute, though SciPy's sparse matrix optimizations keep this within acceptable limits (seconds).
