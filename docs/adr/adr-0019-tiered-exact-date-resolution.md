# ADR 0019: Tiered Exact-Anchored Date Resolution for Epidemiological Seeding

## Status
Accepted

## Context
In early phases of this research, patient-zero malware events were chronologically filtered and sequenced using the published timestamp field from the OSV (Open Source Vulnerabilities) database. The assumption was that the vulnerability disclosure date was a reasonable proxy for the moment the malicious package entered the ecosystem. 

Subsequent rigorous testing revealed a massive **proxy-date bias** (survivorship/reporting bias). Vulnerabilities for supply chain malware are often disclosed (or backfilled in OSV) months or years after the malicious package was actually published to the registry, especially for early or less-publicized incidents. Relying on the OSV proxy date created an artificial temporal lag (median ~350 days) and allowed packages to qualify as established "patient zeros" based on a timeline that did not reflect the reality at the moment of the attacker's commit. This invalidated our temporal filter heuristics (ADR-0004, ADR-0012).

## Decision
We mandate a strictly **Tiered Exact-Anchored Date Resolution** protocol for selecting epidemiological patient zeros and calculating publish velocity:
1. **Discard OSV Proxy Dates:** The OSV published field must never be used as the anchor for when a malicious version entered the registry.
2. **Tiered Resolution:**
   - **Exact Match:** Use the 	ime dictionary from the official npm metadata. Match the precise malicious version string (e.g., 1.0.5) to its exact publication timestamp. Only packages with an exact timestamp match can be used as patient zeros in the epidemiological simulation, ensuring 100% chronological accuracy.
   - **Interpolation / Fallback:** For large-scale aggregate statistics (e.g., calculating median publish gaps across the entire corpus) where an exact version match isn't available due to registry purges, interpolate the malicious date using the closest surrounding benign versions or the package's modified timestamp. These packages are suitable for velocity analysis but are strictly excluded from patient-zero simulation seeding.
3. **Re-evaluation of Publish Lag:** All statistics regarding the gap between benign activity and malicious publication must be re-calculated using this exact-anchored ground truth. 

## Consequences
- **Positive:** Ensures our temporal patient-zero filter heuristics (requiring prior benign releases and established maintainer profiles *at the time of the attack*) are rigorously accurate.
- **Positive:** Revealed the true median malicious publish gap (13.8 days vs 350 days), firmly proving the "post-dormancy reactivation" behavior of attackers.
- **Negative:** Dramatically shrinks the pool of valid patient-zero seeds for epidemiological simulation (down to 10 highly-verified seeds), as many early malware records were purged from the registry before ecosyste.ms or npm's current 	ime API could cache their exact version timestamps.
