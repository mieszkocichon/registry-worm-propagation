# Data

Small result files (JSON) and the dependency matrix are in git. The large inputs
are deposited on Zenodo (DOI: to be added) as **three packages, one per licence**,
because the sources are licensed differently and must not be mixed in one file:

| Package | Contents | Licence |
|---|---|---|
| `osv/` | npm records from OSV.dev, split by source database | Apache-2.0 (`MAL-`), CC BY 4.0 (`GHSA-`), CC0 (`GSD-`) |
| `ecosyste_ms/` | ownership and dependents records adapted from ecosyste.ms | CC BY-SA 4.0 |
| `deps_dev/` | dependency records from deps.dev | CC BY 4.0 |

Each package ships its own `NOTICE.md`, licence texts and `SHA256SUMS`. Why they
are archived rather than re-fetched: npm purged the maintainer records this study
recovers from ecosyste.ms, and the crates.io sampling frame cannot be regenerated
through that registry's API.

## Layout expected by the code

Unpack the packages so that the paths match the original layout:

- `ecosyste_ms/npm_metadata.jsonl`, `npm_control_maintainers.jsonl` -> `data/npm/`
- `ecosyste_ms/maintainers_backfill.jsonl`, `dependents_backfill.jsonl` -> `data/ecosyste_ms/`
- `ecosyste_ms/cross_ecosystem/*.jsonl` -> `data/cross_ecosystem/`
- `deps_dev/deps_dev_data.jsonl` -> `data/npm/`
- `osv/*.csv`: concatenate (same header) into `data/npm/osv_npm_vulnerabilities_filtered.csv`

## Pseudonymised maintainer handles

Handles are `m_<16 hex>` (HMAC-SHA256 under a secret key held by the author).
The bipartite graph is identical to the original (degree multisets verified), so
all graph-based results reproduce. Registry/bot accounts such as `npm` stay
literal so `constants.is_bot` filters them as before. This is pseudonymisation,
not anonymisation: package names are public and link back to accounts. Please use
the data for research only, do not try to identify individuals, and contact the
author before any other use (a request, not a licence term).

Result files that named accounts (`projection_stats.json`,
`twofa_envelope_curve.json`, `wcte_*_account_seeded.json`) use the same
pseudonyms. The package-name seeds in `patient_zeros.json` are unchanged.

Do not load `*.pkl` caches from untrusted sources; `scripts/graph_builder.py`
regenerates them.

## Third-party terms

- ecosyste.ms data: CC BY-SA 4.0 (https://ecosyste.ms/about).
- OSV.dev: per-source licences (https://google.github.io/osv.dev/data/).
- deps.dev generated data: CC BY 4.0 (https://docs.deps.dev/bigquery/v1/).
- npm registry metadata: npm Open-Source Terms
  (https://docs.npmjs.com/policies/open-source-terms). Replication through the
  Public API is permitted; npm's clause on security data of packages is
  respected by taking all labels from OSV only.
