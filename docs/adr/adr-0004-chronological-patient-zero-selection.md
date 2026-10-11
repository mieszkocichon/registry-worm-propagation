# ADR-0004: Chronological Patient-Zero Selection and Graph Validation

## Status
Accepted

## Context
Simulations start by infecting a set of initial packages ("patient zeros"). 
In early iterations:
1. Patient-zero seeds were selected based on the most frequent package names in the malware list. This did not match the chronological sequence of a historical worm outbreak.
2. In later attempts, we selected the earliest packages from the OSV dataset. However, because many early malicious packages were unpublished and purged from the npm registry, they were missing from the metadata graph. 
3. This caused the simulation to start with zero active seeds, resulting in trivial runs where the infection rate stayed at 0% and R0 calculations failed.

## Decision
We decided to implement a validated chronological selection policy:
1. Parse vulnerability publication dates (`published` string from OSV) as datetimes.
2. Sort all malware packages chronologically by their earliest publication date.
3. Filter this sorted candidate list against the packages present in the generated metadata graph (i.e. those successfully fetched and loaded into the sparse matrix representation).
4. Take the top 10 earliest *valid* packages that exist in the graph as the identical patient-zero seeds.
5. Save these seeds to `data/patient_zeros.json` so they are reused consistently across all simulations (maintainer-based, dependency-based, and counterfactuals).

## Consequences

### Positive
* **Historical Accuracy:** The simulation seeds reflect the actual chronological start of npm malware campaigns.
* **Consistency:** Reusing the exact same seeds across all simulations isolates the network topology as the sole independent variable.
* **Robustness:** Eliminates the "zero-seed" bug, guaranteeing that simulations always start with active infections.

### Negative
* **Bias:** By choosing seeds that must exist in the live graph, we exclude purged packages that were caught very early. However, this is necessary since we cannot simulate on nodes that have no metadata to build edges.
