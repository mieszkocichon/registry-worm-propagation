# OSV npm records

Records retrieved from OSV.dev (https://osv.dev) for the npm ecosystem. OSV
aggregates advisories whose licences depend on the source database
(https://google.github.io/osv.dev/data/, checked 2026-10-11). The CSV is split
by source so each file carries exactly one licence:

| File | OSV id prefix | Source database | Licence |
|---|---|---|---|
| `osv_mal_openssf.csv` | `MAL-` | OpenSSF Malicious Packages (https://github.com/ossf/malicious-packages) | Apache-2.0 (`APACHE-2.0.txt`) |
| `osv_ghsa.csv` | `GHSA-` | GitHub Advisory Database | CC BY 4.0 (`CC-BY-4.0.txt`) |
| `osv_gsd.csv` | `GSD-` | Global Security Database | CC0 1.0 (`CC0-1.0.txt`) |

Changes made: restricted to the npm ecosystem; columns reduced to `osv_id`,
`package`, `published`, `modified`, `aliases`, `versions_affected`; one row per
affected version; rows split by source. No other modification.

Attribution: OpenSSF Malicious Packages contributors; GitHub, Inc. (GitHub
Advisory Database); Global Security Database contributors; all via OSV.dev.
Apache-2.0 notice: this is a redistribution of Apache-2.0 licensed material with
the changes listed above; the licence text is in `APACHE-2.0.txt`.

The malicious/vulnerable labels in this package come from OSV only. They are not
data provided by npm.
