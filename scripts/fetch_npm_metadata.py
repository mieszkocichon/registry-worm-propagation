import time
import json
import requests
import pandas as pd
from pathlib import Path
import sys

import concurrent.futures
import threading
import random

write_lock = threading.Lock()

def fetch_package_metadata(package_name):
    url = f"https://registry.npmjs.org/{requests.utils.quote(package_name, safe='@/')}"
    max_retries = 5
    retries = 0
    while retries < max_retries:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return r.json()
            elif r.status_code in (429, 500, 502, 503, 504):
                retries += 1
                time.sleep((2 ** retries) + random.random())
            else:
                break
        except requests.exceptions.RequestException:
            retries += 1
            time.sleep((2 ** retries) + random.random())
    return None

from constants import is_bot

def process_packages(input_csv, output_jsonl, sample_size=None):
    # Process CSV to get malware packages
    print("Loading OSV CSV...")
    try:
        osv_df = pd.read_csv(input_csv)
        mask = osv_df['osv_id'].str.startswith('MAL-', na=False) | osv_df['aliases'].str.contains('MAL-', na=False)
        mal = osv_df[mask].copy()
        
        # We only care about published time
        mal['published_dt'] = pd.to_datetime(mal['published'], utc=True)
        
        # Sort chronologically to get oldest OSV entries first
        mal = mal.sort_values('published_dt', ascending=True)
        
        # The list of target malware packages
        packages = mal['package'].unique().tolist()
    except Exception as e:
        print(f"Error reading CSV: {e}")
        sys.exit(1)

    if sample_size is not None and len(packages) > sample_size:
        rng = random.Random(42) # Reproducible random sampling
        earliest_count = min(500, len(packages))
        earliest = packages[:earliest_count]
        rest = packages[earliest_count:]
        rest_sampled = rng.sample(rest, sample_size - earliest_count)
        packages = earliest + rest_sampled
    else:
        print(f"No sample cap applied — fetching full population of {len(packages)} malware-flagged packages.")

    import os
    existing_pkgs = set()
    if os.path.exists(output_jsonl):
        with open(output_jsonl, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    existing_pkgs.add(json.loads(line)['package'])
                except:
                    pass
    
    packages_to_fetch = [p for p in packages if p not in existing_pkgs]
    print(f"Skipping {len(packages) - len(packages_to_fetch)} already fetched packages.")
    packages = packages_to_fetch

    print(f"Fetching metadata for {len(packages)} structured sampled packages...")
    
    def process_single(pkg):
        data = fetch_package_metadata(pkg)
        return pkg, data

    with open(output_jsonl, 'a', encoding='utf-8') as f:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_pkg = {executor.submit(process_single, pkg): pkg for pkg in packages}
            for i, future in enumerate(concurrent.futures.as_completed(future_to_pkg)):
                if i > 0 and i % 50 == 0:
                    print(f"Processed {i} packages...")
                pkg, data = future.result()
                if data:
                    times = data.get('time', {})
                    maintainers = data.get('maintainers', [])
                    valid_maintainers = [m.get("name") for m in maintainers if not is_bot(m.get("name"))]
                    with write_lock:
                        f.write(json.dumps({
                            "package": pkg,
                            "time": times,
                            "maintainers": valid_maintainers
                        }) + "\n")
                        f.flush()

if __name__ == "__main__":
    base = Path(__file__).parent.parent
    data_dir = base / "data" / "npm"
    src = data_dir / "osv_npm_vulnerabilities_filtered.csv"
    dst = data_dir / "npm_metadata.jsonl"

    if src.exists():
        process_packages(src, dst)
        print("Finished processing npm metadata.")
    else:
        print(f"Input file {src} not found. Run filter_by_date.py first.")
