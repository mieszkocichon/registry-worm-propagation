# ADR-0012: Temporal Filter Heuristics for Patient-Zero Selection

## Status
Accepted

## Context
When running epidemiological simulations, we must select seed nodes ("patient zeros") to initiate the infection. 
If we choose these nodes randomly or solely based on their connectivity (hubs), we introduce temporal anomalies:
1. A package published in 2024 cannot historically act as the seed for an outbreak modeling malware campaigns from 2021.
2. Selecting seeds without considering their timeline violates the chronological integrity of our historical dataset.
3. We need a deterministic selection policy that aligns with the temporal flow of actual registry events.

## Decision
We decided to implement a temporal filter heuristic for selecting patient-zero seeds:
1. Extract the earliest publication date (`published`) for all malicious packages in the OSV dataset.
2. Sort all malicious packages chronologically by their earliest publication timestamp.
3. Validate each package against the set of packages currently present in the generated bipartite graph (ensuring the metadata was successfully fetched).
4. Select the top 10 earliest valid packages as our patient-zero seeds.
5. These 10 packages are saved to `data/patient_zeros.json` and loaded as the fixed starting seeds for all comparative simulations.

## Consequences

### Positive
* **Timeline Integrity:** The simulation starts from the actual historical beginning of the malware campaigns, ensuring realistic initial conditions.
* **Deterministic Baseline:** Using a saved JSON file ensures all notebooks start with the exact same initial infected nodes, facilitating fair comparisons.

### Negative
* **Purge Dependency:** Since many of the very earliest malware packages have been purged from the npm registry (as documented in ADR-0005), we must slide our chronological window forward until we find 10 packages that still exist in our graph. This means the seeds represent the earliest *surviving* packages, not the absolute earliest.
