# ADR-0014: Cross-Ecosystem Topological Comparative Framework & Ground-Truth Incident Integration

## Status
Accepted

## Context
1. **Journal Target Requirements (200 Points):** Submitting to top-tier security venues (*IEEE TDSC*, *IEEE TIFS*, *USENIX Security*, *ACM CCS*) requires demonstrating generalizability across open-source package manager registries to rule out single-ecosystem bias ("npm-only artifact").
2. **Empirical Ground-Truth Validation:** The emergence of the **Shai-Hulud / Mini Shai-Hulud worm campaign (2025–2026)** provided real-world empirical proof of the paper's central thesis: self-propagating supply chain worms traverse the **bipartite co-maintainership graph** ($B_{CSR}$) using stolen credentials (npm/PyPI tokens, OIDC, GitHub PATs) and native lifecycle execution hooks (`preinstall`, `setup.py`).
3. **Cross-Ecosystem Empirical Findings (corrected, see Update below):** Unbiased random sampling ($N \approx 12{,}000$–$14{,}600$ per ecosystem) from each registry's own canonical package index, cross-checked with the same $B \cdot B^T$ projected-graph methodology used for npm ($P = B \cdot B^T$, dynamic hub-exclusion budget, see ADR-0013), gives:
   - **npm:** Hyper-concentrated outlier. Projected co-maintainer mean degree $= 205.64$, $Gini = 0.890$, max hub excludes 18 maintainer-hubs from the projection (budget guard).
   - **RubyGems:** Projected mean degree $= 16.76$, $Gini = 0.877$, max degree $314$ (single-maintainer hub `awscloud`, 315 owned packages in-sample).
   - **crates.io (Rust):** Projected mean degree $= 12.42$, $Gini = 0.766$, max degree $119$.
   - **PyPI (Python):** Projected mean degree $= 4.70$, $Gini = 0.945$ (few very concentrated orgs, e.g. `OCA` with 203 packages, against a long thin tail), max degree $202$.
   - npm's projected mean degree is $\sim 12$–$44\times$ every other ecosystem's — the generalizability claim holds (all four ecosystems show heavy-tailed hub concentration), but npm remains the extreme outlier, not representative of the class.

## Decision
We decided to:
1. **Adopt a Multi-Registry Comparative Framework:** Expand the dataset and manuscript scope beyond npm to include **PyPI, crates.io, and RubyGems**, evaluating maintainer degree distributions, Gini inequality coefficients, and top 1% hub ratios across all four ecosystems.
2. **Integrate Shai-Hulud Case Study:** Incorporate a dedicated empirical case study section in the paper analyzing the 2025–2026 Shai-Hulud worm campaign across npm and PyPI as live validation of the $B_{CSR}$ propagation model.
3. **Harden Data Pipeline Infrastructure (`fetch_cross_ecosystem_metrics.py`):**
   - Implement **instant resume checkpointing** based on existing JSONL line counts to eliminate re-pagination overhead.
   - Enforce a global thread-safe rate limiter (0.7s per request) with exponential backoff retries (up to 4 attempts) to prevent HTTP 429 and socket read timeouts from `ecosyste.ms`.
   - Provide progress logging during page listing pagination.

## Consequences

### Positive
* **High Journal Impact:** Directly addresses reviewer demands for generalizability and empirical ground-truth validation for top-tier venue acceptance.
* **Novel Empirical Insights:** Proves that while PyPI, crates.io, and RubyGems possess sufficient maintainer hub density to sustain real-world worm outbreaks (explaining Shai-Hulud's success in PyPI), npm remains an extreme hyper-concentrated outlier prone to catastrophic cascade infections.
* **Resilient Infrastructure:** The data collection pipeline can be paused, resumed, and expanded without data duplication or loss.

### Negative
* **Increased Data Maintenance:** Managing JSONL datasets across four distinct package ecosystems requires ongoing schema normalization and storage upkeep.

## Update (post-correction)

The original $N=5{,}000$ figures above were superseded for two independent reasons and should not be cited:

1. **Sampling bias:** the initial sampler used `ecosyste.ms`'s `q=` search parameter, which silently falls back to the same popularity-ranked default list on unmatched queries — skewing samples toward already-popular packages. Replaced with direct sampling from each registry's own canonical name index (PyPI `/simple/`, RubyGems `/names`, crates.io `/api/v1/crates` random-page sampling within its reachable pagination window). See `fetch_registry_sample_names()` in `fetch_cross_ecosystem_metrics.py`.
2. **Metric mismatch:** the original Gini/hub-ratio numbers were computed on raw *maintainer* degree (packages owned per maintainer), not on the projected package-package co-maintainer graph ($P = B \cdot B^T$) npm's headline $205.64$ mean-degree figure actually refers to. `analyze_cross_ecosystem.py` now computes both: `maint_*` fields (raw bipartite, kept for reference, NOT comparable across the npm/cross-ecosystem split) and `projected_*` fields (the $B \cdot B^T$ metric, directly comparable to npm's number).
3. **`is_osv_vulnerable` was always `False`** in the original per-package fetch: `fetch_osv_vulnerable_packages()` called OSV's `/v1/query` with only an `ecosystem` field, which isn't a supported query mode (OSV requires a specific package name or commit); the non-200 response was silently swallowed. Fixed to use OSV's bulk per-ecosystem export (`osv-vulnerabilities.storage.googleapis.com/<ecosystem>/all.zip`, same source `fetch_osv_data.py` already used for npm), then backfilled onto the existing JSONL files without re-fetching maintainers.

### Limitation: sample, not census

All three cross-ecosystem datasets are **random samples** ($N \approx 12{,}000$–$14{,}600$ packages), not full-registry crawls — PyPI, crates.io, and RubyGems each have on the order of $150{,}000$–$500{,}000+$ total published packages. This is architecturally different from the npm study (Section 4), which analyzes the **full malware corpus** ($N = 213{,}162$, no sampling). Cross-ecosystem numbers here should be read as *qualitative, sample-based evidence that the same heavy-tailed hub-concentration structure recurs elsewhere* (supporting RQ2's generalizability claim), not as a population-level replication of the npm study's statistical test. The manuscript's Limitations section (8.2) must state this explicitly to preempt a "sample size / representativeness" reviewer objection.
