# ADR-0016: Registry-Canonical-Index Sampling Instead of ecosyste.ms Search

## Status
Accepted

## Context
The first cross-ecosystem sampler queried ecosyste.ms's `packages` search
endpoint (`q=<prefix>`) across a fixed list of 59 prefix strings, aiming for
even coverage of each registry's namespace. Direct `curl` testing showed
this endpoint does not filter reliably: on unmatched query strings it
silently falls back to the **same default, popularity-ranked package list**
returned with no query at all (verified: `q='xk'` on the PyPI-backed
endpoint returned an identical result set to no query). The sampler was
therefore systematically biased toward already-popular packages regardless
of which prefix was queried, and eventually saturated — a full run across
all three registries returned 0 new candidate packages once the shared
popularity-ranked page had been exhausted by repeated queries.

## Decision
Sample directly from each registry's own canonical package-name index
instead of a search endpoint:

* **PyPI** — the full `/simple/` HTML index (one fetch, every package name
  on PyPI, hard-timeout raised to 90s given payload size).
* **RubyGems** — the `/names` plaintext index (one fetch, same rationale).
* **crates.io** — no full-name-dump endpoint exists, so sample random pages
  of its own paginated `/api/v1/crates` listing API instead of a search
  (a raw listing has no query-fallback bias to guard against).

For all three, candidate names already present in the existing output file
are filtered out before random sampling down to the remaining target count.

**crates.io pagination depth cap (discovered mid-implementation):**
`curl` testing showed crates.io's API rejects deep-offset pages —
`page=200` at `per_page=100` succeeds, `page=210` returns
`{"errors":[{"detail":"Page X is unavailable for performance reasons..."}]}`.
The initial random-page implementation sampled uniformly across the full
nominal `total_pages` (~3,047 at the time), so roughly 95% of random page
picks silently failed. Fixed by capping the sampled range to the actually
reachable window: `usable_pages = min(total_pages, max_offset // per_page)`
with `max_offset = 20_000`.

## Consequences

### Positive
* Sampling is now genuinely uniform over each registry's namespace (modulo
  crates.io's reachable-pagination-window restriction), eliminating both
  the popularity bias and the saturation failure mode.
* All three registries reached their fetch targets: PyPI 14,588,
  RubyGems 11,940, crates.io 12,000.
* The crates.io pagination fix alone took yield from ~1,090 new names per
  ~240 page attempts to ~973 new names per 10 page attempts.

### Negative
* Samples remain **partial**, not full-registry censuses — PyPI,
  crates.io, and RubyGems each host on the order of 150,000–500,000+ total
  published packages. This must be reported explicitly wherever
  cross-ecosystem numbers are compared to npm's full 213,162-package
  corpus (see ADR-0014's "sample vs. census" limitation note).
* crates.io's reachable window (~20,000 of its total crate count) means its
  sample, while now unbiased *within that window*, still cannot reach
  crates published beyond the API's own performance-guard cutoff.
