# ADR-0018: Projected Co-Maintainer Graph as the npm-Comparable Cross-Ecosystem Metric

## Status
Accepted

## Context
An earlier version of `scripts/analyze_cross_ecosystem.py` computed
Gini-coefficient and hub-ratio statistics on **raw bipartite maintainer
degree** (packages owned per maintainer) for each cross-ecosystem sample,
and reported these alongside npm's headline "mean degree 205.64" figure as
if the two were comparable. They are not the same metric: npm's 205.64 is
the mean degree of the **projected** package-package co-maintainer graph
($P = B \cdot B^\top$, per ADR-0013) — the number of *other packages*
reachable in one hop via a shared maintainer — whereas raw maintainer
degree measures maintainer fan-out (how many packages one maintainer owns),
a related but distinct quantity. Reporting them side-by-side in the same
table risked a methodologically invalid cross-ecosystem comparison making
it into the manuscript's Section 5.2.

## Decision
Extend `analyze_cross_ecosystem.py` to compute the identical
$P = B \cdot B^\top$ projection for each cross-ecosystem sample **and** for
npm itself (reusing the existing cached
`graph_builder.build_bipartite_graph()`), via the same chunked-matmul +
dynamic nnz-budget hub-exclusion implementation already established in
ADR-0013 (copied, not reinvented). Both metric families are now reported
side-by-side and explicitly labeled:

* `projected_*` fields — the $B \cdot B^\top$ degree stats, directly
  comparable across all four ecosystems and to npm's headline figure.
* `maint_*` fields — the original raw bipartite maintainer-degree stats,
  kept for reference only, explicitly documented as **not** comparable to
  the projected figures.

Correctness was validated by confirming the recomputed npm
`projected_mean_degree` equals **205.642**, matching the previously
established value from the original notebook-based computation — i.e. the
generalized implementation reproduces the known-correct result exactly
before being trusted on the three new ecosystems.

Resulting comparable figures (`paper/cross_ecosystem_comparison_table.csv`):

| Ecosystem | N (sample) | Projected mean degree | Projected Gini | Projected max degree |
|---|---|---|---|---|
| npm (full corpus) | 213,162 | 205.64 | 0.890 | 2,924 (18 hubs excluded) |
| RubyGems | 11,940 | 16.76 | 0.877 | 314 |
| crates.io | 12,000 | 12.42 | 0.766 | 119 |
| PyPI | 14,588 | 4.70 | 0.945 | 202 |

## Consequences

### Positive
* Section 5.2's cross-ecosystem hub-concentration comparison is now
  methodologically valid — same metric, same computation path, for all
  four ecosystems.
* npm's outlier status is now quantified honestly: 12–44× every other
  ecosystem's projected mean degree, rather than resting on an
  apples-to-oranges comparison that could have overstated or understated
  the gap.

### Negative
* Projecting each ecosystem's bipartite graph on every analysis run adds
  compute cost. Currently negligible (12,000–15,000-package samples with
  small maintainer sets complete in well under a second), but the
  chunk-size and hub-exclusion budget constants would need re-tuning if
  cross-ecosystem sample sizes grow substantially (e.g. toward full
  registry crawls).
