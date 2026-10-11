# ADR 0005: Memory-Optimized Cache Payloads for Graph Metadata

## Status
Accepted

## Context
When loading registry records from `npm_metadata.jsonl` to build bipartite graphs, the codebase traditionally pickled the full package record payload. This raw registry metadata includes heavy nested fields (e.g., full version histories, package.json configs, dependencies, engines, scripts, and readme descriptions). 

As the allowed package universe scale up, caching these full records leads to high disk usage and slow loading speeds due to heavy pickle parsing.

## Decision
Slim down the cached `npm_meta` dictionary returned by `build_bipartite_graph` to contain only the properties required for epidemiological simulations and candidate validation:
*   `'time'`: Dictionary of version publication timestamps (for temporal seed validation).
*   `'maintainers'`: List of maintainers associated with the package (to map bipartite edges).

All other unused raw JSON registry metadata fields are discarded immediately during parsing and are excluded from the pickled cache files.

## Consequences
- **Positive:** Massive reduction in memory consumption and pickled cache sizes (up to 95% reduction).
- **Positive:** Speeds up pickle loading and saving times.
- **Negative:** If new analysis steps in the notebooks require other fields (such as devDependencies or license metadata), the cache payload schema must be expanded and the cache version incremented to trigger a rebuild.
