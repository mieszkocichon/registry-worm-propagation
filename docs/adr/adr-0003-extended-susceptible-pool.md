# ADR-0003: Extended Susceptible Pool (Portfolio Expansion)

## Status
Accepted

## Context
In early phases, the simulation of worm propagation over the maintainer graph was conducted only on the subset of packages present in the filtered OSV malware list (~5,000 packages). 

This represented a severe scientific methodology flaw (Closed Ecosystem bias):
1. The graph was composed almost entirely of already-infected packages.
2. In reality, a worm spreads from compromised packages to *clean* packages sharing the same maintainers.
3. Simulating on a closed graph of malware-only packages did not represent real-world lateral movement. It was an "apples-to-oranges" comparison when compared to the dependency graph (which had a large downstream susceptible pool of clean packages).

## Decision
We decided to actively expand the susceptible pool by fetching the entire portfolio of packages for every maintainer who has ever published a package in the malware list.
1. Identify all unique maintainer accounts associated with the compromised packages in the OSV dataset.
2. Fetch the metadata (using the npm registry API) for *all* packages published/maintained by these accounts.
3. Incorporate these newly found clean packages (~3,000 additional packages) into `npm_metadata.jsonl` as the "Susceptible" pool.
4. Update the bipartite graph projection to include these clean packages, creating a realistic topology for lateral movement simulation.

## Consequences

### Positive
* **Scientific Validity:** The model now reflects true lateral movement (worms spreading from compromised packages into clean packages via shared maintainer credentials).
* **Fair Comparison:** Enables a methodologically sound comparison between the maintainer graph and the dependency graph, as both now contain a realistic mix of infected and clean packages.
* **Rich Data:** We captured a more complete picture of the compromised authors' footprint in the npm registry.

### Negative
* **API Overhead:** Fetching the extended portfolios required making thousands of API requests to the npm registry. To avoid getting rate-limited or blocked, we had to implement delays, resulting in a one-time data collection cost of several minutes.
