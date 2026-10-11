# ADR-0001: Vectorized Pandas Processing for Dwell-Time Calculation

## Status
Accepted

## Context
In Phase 1 of the analysis, the calculation of package dwell times (time elapsed between package release and vulnerability publication in OSV) was performed using a classic Pandas anti-pattern: looping over the OSV DataFrame row-by-row using `.iterrows()`. 

For a dataset of npm packages and vulnerabilities reaching tens of thousands of rows, this loop was:
1. Extremely slow (scaling linearly $O(N)$ with high overhead per row).
2. Prone to silent indexing issues, making it difficult to maintain and debug.
3. Hard to generalize when handling version mismatches or fallback scenarios (such as fallback to package creation date).
4. Prone to crashes if datetimes contained missing or ill-formatted strings since errors were not handled at scale.

## Decision
We decided to replace the row-wise `.iterrows()` loop with fully vectorized Pandas operations. The new logic:
1. Explodes the comma-separated `versions_affected` strings into individual rows (`.explode()`).
2. Joins the exploded OSV vulnerability records with a normalized versions release time table (`pd.merge()` on `package` and `version`).
3. Computes the minimum (earliest) release time per package using group-by aggregation (`.groupby('package')['published_dt'].min()`).
4. Merges the results back to the primary vulnerability records and calculates time differences as vectorized operations.
5. Uses `pd.to_datetime(..., errors='coerce')` to gracefully handle anomalous timestamps in a vectorized fashion.

## Consequences

### Positive
* **Performance:** Execution time of the dwell-time calculation dropped from minutes to a fraction of a second, enabling fast notebook regeneration.
* **Robustness:** Eliminates the risk of `SettingWithCopyWarning` and silent indexing errors. Datetime coercion is robust to anomalous formatting.
* **Maintainability:** The code is declarative, easier to read, and aligns with standard scientific computing practices in Python.

### Negative
* **Memory usage:** Vectorized explosions and merges generate temporary intermediate DataFrames that occupy more RAM. However, at our dataset scale (<1M rows), this is negligible.
