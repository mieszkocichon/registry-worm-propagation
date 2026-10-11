import json
import numpy as np
import scipy.sparse as sp
from pathlib import Path
import pandas as pd

import os
import pickle
import hashlib
from constants import is_bot, BOT_REGEX_VERSION

def build_bipartite_graph(metadata_path=Path(__file__).parent.parent / 'data' / 'npm' / 'npm_metadata.jsonl', allowed_packages=None):
    """
    Loads npm_metadata and builds the Bipartite Graph (Packages x Maintainers).
    Returns (npm_meta, pkg_list, pkg_to_idx, m_list, m_to_idx, B_csr)
    """
    cache_dir = Path(__file__).parent.parent / 'data' / 'npm'
    
    # We will import hash_file_endpoints from data_utils
    import sys
    sys.path.append(str(Path(__file__).parent))
    from data_utils import hash_file_endpoints
    
    npm_hash = hash_file_endpoints(metadata_path)
    
    if allowed_packages is not None:
        hasher = hashlib.md5()
        for p in sorted(allowed_packages):
            hasher.update(p.encode('utf-8'))
        ap_hash = hasher.hexdigest()[:8]
    else:
        ap_hash = "all"
        
    # Include bot filter version so that cache is invalidated when BOT_REGEX changes.
    combined_hash = hashlib.md5((npm_hash + ap_hash + BOT_REGEX_VERSION).encode()).hexdigest()[:8]
    cache_file = cache_dir / f'B_csr_cache_{combined_hash}.pkl'
    
    from data_utils import clean_old_caches
    clean_old_caches(cache_dir, current_b_hash=combined_hash)
    
    if cache_file.exists():
        with open(cache_file, 'rb') as f:
            return pickle.load(f)

    # Streaming line-by-line parse — avoids loading the full JSONL into memory at once.
    npm_meta = {}
    edges_list = []
    with open(metadata_path, 'r', encoding='utf-8') as f:
        for line in f:
            record = json.loads(line)
            pkg = record['package']
            if allowed_packages is None or pkg in allowed_packages:
                npm_meta[pkg] = {
                    'time': record.get('time', {}),
                    'maintainers': record.get('maintainers', [])
                }
                for m in record.get('maintainers', []):
                    # Safety net: apply is_bot at graph-build time to catch any maintainers
                    # that slipped through in legacy JSONL files fetched before the bot filter
                    # was added to the fetch scripts. Current fetch scripts (fetch_npm_metadata.py,
                    # fetch_extended_portfolios.py) already apply is_bot before writing, so for
                    # freshly-fetched data this is a no-op. Kept here so that expanding BOT_REGEX
                    # takes retroactive effect on rebuild without requiring a re-fetch.
                    m_name = m.get('name') if isinstance(m, dict) else m
                    if m_name and not is_bot(m_name):
                        edges_list.append((m_name, pkg))

    pkg_list = list(npm_meta.keys())
    pkg_to_idx = {p: i for i, p in enumerate(pkg_list)}
    
    if edges_list:
        edges_df = pd.DataFrame(edges_list, columns=['maintainer', 'package'])
        edges_df.columns = ['maintainer', 'package']
        col, m_categories = pd.factorize(edges_df['maintainer'])
        m_list = m_categories.tolist()
        m_to_idx = {m: i for i, m in enumerate(m_list)}
        
        row = edges_df['package'].map(pkg_to_idx).values
        
        B = sp.csr_matrix((np.ones(len(row)), (row, col)), shape=(len(pkg_list), len(m_list)))
    else:
        m_list = []
        m_to_idx = {}
        B = sp.csr_matrix((0, 0), shape=(len(pkg_list), 0))
    
    res = (npm_meta, pkg_list, pkg_to_idx, m_list, m_to_idx, B)
    with open(cache_file, 'wb') as f:
        pickle.dump(res, f)
    return res
