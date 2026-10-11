# ADR 0003: Temporal Heuristics for Patient Zero Selection

## Status
Accepted

## Context
When simulating the propagation of npm registry worms, the simulation must be seeded with historical malicious packages ("Patient Zeros") from OSV. However, many malware records in OSV represent "throwaway" or "typosquatting" packages, where an attacker registers a brand new account and publishes a single malicious package. 

Because these accounts do not represent compromised existing maintainers or pre-existing trust, seeding simulations with them creates misleading R0 propagation spikes. We need to isolate true "account takeover" (hijacking) mechanism seeds.

## Decision
Apply a dual-condition temporal heuristic to filter patient zero candidates from the OSV dataset:
1. **Pre-existing Legit Release History:** The package must have at least one version published *before* the malicious version's publication date (verifying it is an established package, not a new typosquat).
2. **Established Maintainer Portfolio:** At least one of the human (non-bot) maintainers of the package must have had a portfolio size $> 1$ (owned at least one other package) *before* the malicious publication date (verifying they are active ecosystem participants).

## Consequences
- **Positive:** Excludes throwaway typosquatting noise, aligning seeds with the targeted shared-maintainer compromise threat model.
- **Positive:** Leverages the parsed registry timeline metadata, ensuring temporal consistency.
- **Negative:** Reduces the usable seed set size, which could limit statistic variance. This is mitigated by aggregating outcomes across 10 distinct campaign seeds.
