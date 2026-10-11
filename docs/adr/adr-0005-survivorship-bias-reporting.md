# ADR-0005: Exposing and Quantifying Survivorship Bias in Dwell-Time Calculation

## Status
Accepted

## Context
When calculating package dwell times, we merge OSV data with npm metadata. However, npm registry policy allows the unpublishing of packages under certain conditions, and malicious packages are almost always unpublished or purged once detected.

As a result:
1. An inner join between OSV vulnerability data and npm metadata silently drops packages that no longer exist in the live registry.
2. Silently dropping these packages hides a major experimental limitation: we only calculate dwell times for packages that *survived* in the registry (i.e. those that were not purged).
3. This skews the median dwell time upward, as packages caught and deleted quickly are omitted from the sample.

## Decision
We decided to:
1. Avoid inventing synthetic timestamps (dummy data) for deleted packages, as this compromises scientific integrity.
2. Explicitly calculate and print the number of dropped packages due to missing metadata in Notebook 01 (`regen.py`).
3. Report this drop as **Survivorship Bias** in the final paper and walkthrough, framing it as a core empirical finding rather than a bug.
4. Use this quantification to caution readers about the limitations of using live registry snapshots for historical malware analysis.

## Consequences

### Positive
* **Scientific Rigor:** Exposing this bias increases the academic credibility of the research paper.
* **Empirical Insight:** We proved that out of ~215,000 OSV npm entries, over 207,000 (~96%) were completely purged. This is a significant empirical finding about npm's cleanup speed.
* **No Manufactured Data:** We do not corrupt our survival analysis with arbitrary fallback assumptions.

### Negative
* **Statistical Limitation:** Our calculated median dwell time (~546 days) and resulting recovery rate ($\gamma$) represent an upper bound (reflecting the "slow-to-detect" packages), which we must explicitly call out in our paper's limitations section.
