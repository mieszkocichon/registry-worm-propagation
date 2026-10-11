# ADR-0011: Person-Time Early-Phase R0 Capture Strategy

## Status
Accepted

## Context
The Basic Reproduction Number ($R_0$) represents the average number of secondary infections caused by a single infectious node introduced into a completely susceptible population. 

In a finite network simulation, calculating $R_0$ across the entire simulation duration leads to significant underestimation due to network saturation:
1. As the infection spreads, the number of susceptible neighbors decreases.
2. Infectious nodes late in the run have fewer available targets to infect, artificially lowering their secondary infection counts.
3. If we average secondary infections across the entire run, the calculated $R_0$ will drift towards $\le 1.0$ as the outbreak runs out of susceptible nodes.

## Decision
We decided to implement an early-phase, patient-zero focused $R_0$ capture strategy in `simulation_engine.py`:
1. Track the infections caused specifically by the first generation of infectious nodes (the "Patient Zeros").
2. Calculate $R_0$ as the sum of all packages successfully infected by the initial seed nodes divided by the number of seeds.
3. This calculation is performed during the early steps of the simulation (before recovery or network saturation can deplete the local susceptible pool).
4. Nodes infected in later generations are excluded from the $R_0$ denominator, as they operate in a partially depleted network.

## Consequences

### Positive
* **Epidemiological Validity:** Matches the theoretical definition of $R_0$ (introducing infectious cases into a *completely susceptible* population).
* **Stability:** The calculated $R_0$ values (~4.4) are highly stable across multiple Monte Carlo runs and accurately reflect the initial outbreak force of the worm.

### Negative
* **Local Topology Sensitivity:** The $R_0$ value is highly sensitive to the local connectivity (degree) of the selected patient-zero seeds. If the seeds are hubs, $R_0$ will be high; if they are isolates, $R_0$ will be low. We mitigate this by using a representative set of 10 seeds.
