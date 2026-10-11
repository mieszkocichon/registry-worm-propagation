import time
import json
import requests
import pandas as pd
from pathlib import Path

import concurrent.futures
import threading
import random

write_lock = threading.Lock()

def fetch_dependents(package_name):
    base_url = f"https://api.deps.dev/v3/systems/npm/packages/{requests.utils.quote(package_name, safe='')}/dependents"
    all_dependents = []
    page_token = ""
    max_retries = 5
    
    while True:
        url = base_url
        if page_token:
            url += f"?pageToken={requests.utils.quote(page_token)}"
            
        retries = 0
        success = False
        while retries < max_retries:
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    nodes = data.get("nodes", [])
                    all_dependents.extend([n.get("versionKey", {}).get("name") for n in nodes if n.get("versionKey")])
                    
                    if len(all_dependents) > 10000:
                        raw_c = len(all_dependents)
                        print(f"[{package_name}] Hit MAX_DEPENDENTS cap ({raw_c} > 10000). Truncating.")
                        return all_dependents[:10000], True, raw_c
                        
                    page_token = data.get("nextPageToken")
                    success = True
                    break
                elif r.status_code in (429, 500, 502, 503, 504):
                    retries += 1
                    time.sleep((2 ** retries) + random.random())
                else:
                    break # Other error (e.g. 404), give up on this page
            except requests.exceptions.RequestException:
                retries += 1
                time.sleep((2 ** retries) + random.random())
        
        if not success or not page_token:
            break
            
    return all_dependents, False, len(all_dependents)

def process_single(pkg):
    deps, truncated, raw_c = fetch_dependents(pkg)
    return pkg, deps, truncated, raw_c

def process_deps(input_jsonl, output_jsonl):
    packages = [json.loads(line)['package'] for line in open(input_jsonl, 'r', encoding='utf-8')]
    
    existing = set()
    if Path(output_jsonl).exists():
        with open(output_jsonl, 'r', encoding='utf-8') as f:
            for line in f:
                existing.add(json.loads(line)['package'])
                
    packages_to_fetch = [p for p in packages if p not in existing]
    
    print(f"Fetching dependents for {len(packages_to_fetch)} new packages out of {len(packages)} total...")
    
    if not packages_to_fetch:
        print("All packages already have deps.dev data.")
        return
        
    with open(output_jsonl, 'a', encoding='utf-8') as f:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_pkg = {executor.submit(process_single, pkg): pkg for pkg in packages_to_fetch}
            for i, future in enumerate(concurrent.futures.as_completed(future_to_pkg)):
                if i > 0 and i % 20 == 0:
                    print(f"Processed {i} packages...")
                pkg, dependents, trunc, raw_c = future.result()
                with write_lock:
                    record = {"package": pkg, "dependents": dependents}
                    if trunc:
                        record["truncated"] = True
                        record["raw_count"] = raw_c
                    f.write(json.dumps(record) + "\n")
                    f.flush()

    print(f"Saved deps.dev data to {output_jsonl}")

if __name__ == "__main__":
    base = Path(__file__).parent.parent
    data_dir = base / "data" / "npm"
    src = data_dir / "npm_metadata.jsonl"
    dst = data_dir / "deps_dev_data.jsonl"

    if src.exists():
        process_deps(src, dst)
        print("Finished fetching deps.dev information.")
    else:
        print(f"Input file {src} not found. Run fetch_npm_metadata.py first.")
