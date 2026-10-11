import json
import scipy.sparse as sp
import numpy as np
from pathlib import Path
import os
import pickle

import hashlib

def hash_file_endpoints(filepath, chunk_size=1024):
    """
    Content-aware cache key: md5 of the entire file content.
    Deliberately excludes mtime — rsync/git checkout can update mtime without
    changing content, which would cause false cache invalidation.
    """
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            hasher.update(chunk)
    return hasher.hexdigest()

import glob

def clean_old_caches(data_dir, current_d_hash=None, current_b_hash=None):
    """Deletes old cache files from the given data directory to prevent disk bloat."""
    cache_files = glob.glob(str(data_dir / '*_csr_cache_*.pkl'))
    for f in cache_files:
        if current_d_hash and f"D_csr_cache_{current_d_hash}" in f:
            continue
        if current_b_hash and f"B_csr_cache_{current_b_hash}" in f:
            continue
        try:
            os.remove(f)
            print(f"Deleted old cache file: {os.path.basename(f)}")
        except Exception as e:
            print(f"Failed to delete {f}: {e}")

def load_node_universe(deps_path=None, npm_path=None):
    """
    Loads the full node universe and dependency graph edges, aligned with the npm metadata.
    Returns (pkg_set, pkg_list, pkg_to_idx, D_csr)
    """
    base = Path(__file__).parent.parent
    npm_data_dir = base / 'data' / 'npm'
    if deps_path is None:
        # npm_metadata.jsonl carries the merged, ecosyste.ms-recovered 'dependents'
        # field (see scripts/merge_and_dedup.py). The standalone deps_dev_data.jsonl
        # is the original deps.dev fetch, which returned zero populated dependents
        # for this dataset and is kept only as a raw-source artifact -- it must not
        # be used as the live dependency-graph source.
        deps_path = npm_data_dir / 'npm_metadata.jsonl'
    if npm_path is None:
        npm_path = npm_data_dir / 'npm_metadata.jsonl'

    deps_hash = hash_file_endpoints(deps_path)
    npm_hash = hash_file_endpoints(npm_path)
    combined_hash = hashlib.md5((deps_hash + npm_hash).encode()).hexdigest()[:8]

    cache_file = npm_data_dir / f'D_csr_cache_{combined_hash}.pkl'

    clean_old_caches(npm_data_dir, current_d_hash=combined_hash)
    
    cache_valid = False
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            pkg_set, pkg_list, pkg_to_idx, D_csr = pickle.load(f)
        cache_valid = True

    if not cache_valid:
        pkg_set = set()
        edges = []
        
        with open(deps_path, 'r') as f:
            for line in f:
                d = json.loads(line)
                pkg = d['package']
                pkg_set.add(pkg)
                for dep in d.get('dependents', []):
                    pkg_set.add(dep)
                    edges.append((pkg, dep))

        # Ensure perfect node-universe parity with Bipartite Graph
        npm_meta = {}
        with open(npm_path, 'r', encoding='utf-8') as f:
            for line in f:
                npm_meta[json.loads(line)['package']] = True
        pkg_set = {p for p in pkg_set if p in npm_meta}

        # sorted(), not list(): set iteration order depends on PYTHONHASHSEED, so
        # list() gives a different index assignment in every process. That does not
        # change D_csr's topology, but it does change which packages a seeded RNG
        # draws, making any randomized-seed experiment irreproducible across runs.
        # graph_builder.build_bipartite_graph() already sorts for the same reason.
        pkg_list = sorted(pkg_set)
        pkg_to_idx = {p: i for i, p in enumerate(pkg_list)}

        import pandas as pd
        if edges:
            edges_df = pd.DataFrame(edges, columns=['package', 'dependent'])
            mask = edges_df['package'].isin(pkg_set) & edges_df['dependent'].isin(pkg_set)
            edges_df = edges_df[mask]
            
            row = edges_df['package'].map(pkg_to_idx).values
            col = edges_df['dependent'].map(pkg_to_idx).values
            D_csr = sp.csr_matrix((np.ones(len(row)), (row, col)), shape=(len(pkg_list), len(pkg_list)))
        else:
            D_csr = sp.csr_matrix((len(pkg_list), len(pkg_list)))
        
        with open(cache_file, 'wb') as f:
            pickle.dump((pkg_set, pkg_list, pkg_to_idx, D_csr), f)
            
    return pkg_set, pkg_list, pkg_to_idx, D_csr
