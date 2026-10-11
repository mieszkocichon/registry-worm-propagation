# Registry ownership and dependent records (adapted from ecosyste.ms)

Licence: **CC BY-SA 4.0** (`CC-BY-SA-4.0.txt`). Source: ecosyste.ms
(https://ecosyste.ms), whose data is published under CC BY-SA 4.0
(https://ecosyste.ms/about, checked 2026-10-11).

Attribution: "Data from ecosyste.ms, CC BY-SA 4.0, adapted by Mieszko Cichon.
Changes: records merged and filtered; maintainer handles pseudonymised (see
below); registry/bot accounts left unchanged." This adapted dataset is itself
released under CC BY-SA 4.0.

Contents: `npm_metadata.jsonl`, `maintainers_backfill.jsonl`,
`dependents_backfill.jsonl`, `npm_control_maintainers.jsonl`,
`cross_ecosystem/{pypi,crates,rubygems}_maintainers.jsonl`.

Provenance caveats:
- `npm_metadata.jsonl` additionally contains publish timestamps and maintainer
  lists retrieved from the npm registry's public API (replication through the
  Public API is permitted by npm's Open-Source Terms,
  https://docs.npmjs.com/policies/open-source-terms). npm's terms continue to
  apply to that portion.
- The `is_osv_vulnerable` flag in `npm_control_maintainers.jsonl` was derived
  from the OSV records in the `osv` package, not from npm.

## Pseudonymisation

Maintainer handles are replaced by `m_<16 hex>` = first 16 hex digits of
HMAC-SHA256(secret key, handle). The mapping is deterministic, injective on this
corpus, and preserves the bipartite graph exactly (degree multisets verified).
Registry and bot accounts (those matched by `scripts/constants.py:is_bot`, e.g.
`npm`) are not natural persons and are left as plain strings so the analysis
code excludes them as before.

This is pseudonymisation, not anonymisation: package names are public and
registry pages list their maintainers, so accounts can be re-linked from a
package portfolio. The data remain personal data of third parties.

Request (not a licence condition): please use this data for research, do not
attempt to identify or contact individuals, and get in touch with the author
before any other use.
