# ADR 0002: Content-Aware Cache Invalidation for Graph Rebuilds

## Status
Accepted

## Context
Parsing and rebuilding graph representations (especially the bipartite package-maintainer graph `B`) from raw JSONL registry metadata files is an expensive operation. To avoid rebuilding the graph on every Jupyter Notebook run, we cache the compiled matrices using Python `pickle`. 

However, using standard file modification time (`mtime`) for cache validation is highly volatile because file modification dates are often reset during `git checkout`, `rsync` synchronizations, or repository cloning. On the other hand, simple static caching risks loading outdated matrices if the dataset content or bot filtering rules change.

## Decision
Implement a content-aware caching layer in `graph_builder.py` and `data_utils.py` using full-file MD5 hashing. 

The cache key is calculated by combining:
1. The MD5 hash of the entire JSONL data file content (avoiding `mtime`).
2. The hash of the allowed package constraints list (`allowed_packages`).
3. The current version of the bot filter regex (`BOT_REGEX_VERSION`).

Stale pickle files that do not match the current combined hash are automatically identified and cleaned up via `clean_old_caches()`.

## Consequences
- **Positive:** Cache hits are 100% safe, surviving git actions and file synchronization without false cache invalidations.
- **Positive:** Any changes to the bot regex patterns or input dataset will automatically invalidate the stale cache and trigger a rebuild.
- **Negative:** Full-file MD5 hashing reads the entire dataset file, although this overhead is negligible (milliseconds) for files under 50MB.
