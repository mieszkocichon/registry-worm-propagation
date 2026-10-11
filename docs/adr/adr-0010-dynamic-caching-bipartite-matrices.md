# ADR-0010: Dynamic In-Memory Construction of Bipartite Matrices

## Status
Accepted

## Context
Running simulations requires building the bipartite package-maintainer incidence matrix $B$ and projecting it to $P = B \cdot B^T$. 
We considered two approaches for loading these graphs into the notebooks:
1. **Static Serialization:** Build the matrices once, save them to disk as SciPy `.npz` files, and load them in the notebooks.
2. **Dynamic In-Memory Construction:** Load the raw metadata JSONL files (`npm_metadata.jsonl`) at the start of each notebook and construct the sparse matrices in memory dynamically.

## Decision
We decided to use Dynamic In-Memory Construction.
1. The JSONL file `npm_metadata.jsonl` remains the single source of truth for package metadata.
2. At the start of the notebooks, the JSONL is parsed, package and maintainer index mappings are built, and the SciPy CSR matrix is instantiated.
3. We reject the use of cached `.npz` files to avoid cache invalidation bugs (e.g., modifying the metadata fetch script but forgetting to delete/re-run the matrix serialization script, leading to desynced results).

## Consequences

### Positive
* **Consistency:** The simulation always runs on the exact data present in `data/npm_metadata.jsonl`. There is zero risk of stale cache files.
* **Simplicity:** The project structure is cleaner, containing only raw data files and execution scripts, without intermediate binary graph blobs.
* **Fast Enough:** Due to SciPy's optimized CSR construction, parsing the ~8,000 package metadata records and creating the projected matrix takes less than 1 second, making disk caching unnecessary at this scale.

### Negative
* **Redundant Parse Time:** If we scale the dataset to millions of packages, parsing the JSONL file on every notebook execution will become a bottleneck. If that occurs, we will transition to a database or a structured parquet format.
