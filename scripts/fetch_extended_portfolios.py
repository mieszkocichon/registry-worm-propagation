import time
import json
import urllib.request
import os
import sys
import urllib.parse
from constants import is_bot
import concurrent.futures
import threading
import random
import requests

write_lock = threading.Lock()

def fetch_json(url):
    max_retries = 5
    retries = 0
    while retries < max_retries:
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            if r.status_code == 200:
                return r.json()
            elif r.status_code in (429, 500, 502, 503, 504):
                retries += 1
                time.sleep((2 ** retries) + random.random())
            else:
                break
        except Exception:
            retries += 1
            time.sleep((2 ** retries) + random.random())
    return None

from pathlib import Path

def main():
    metadata_file = Path(__file__).parent.parent / "data" / "npm" / "npm_metadata.jsonl"
    
    if not os.path.exists(metadata_file):
        print("Metadata file not found.")
        sys.exit(1)
        
    existing_packages = set()
    maintainers = set()
    
    print("Reading existing metadata...")
    with open(metadata_file, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            existing_packages.add(data['package'])
            for m in data.get('maintainers', []):
                maintainers.add(m)
                
    print(f"Found {len(existing_packages)} packages and {len(maintainers)} unique maintainers.")
    
    # 1. Fetch all packages owned by these maintainers
    maintainer_packages = set()
    print("Fetching full portfolios for maintainers...")
    def fetch_portfolio(m):
        m_encoded = urllib.parse.quote(m)
        return fetch_json(f"https://registry.npmjs.org/-/user/{m_encoded}/package")
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_m = {executor.submit(fetch_portfolio, m): m for m in maintainers}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_m)):
            if i > 0 and i % 100 == 0:
                print(f"Processed {i}/{len(maintainers)} maintainers...")
            pkgs_data = future.result()
            m_name = future_to_m[future]
            if pkgs_data:
                pkg_keys = list(pkgs_data.keys())
                if len(pkg_keys) > 5000:
                    raw_c = len(pkg_keys)
                    print(f"[{m_name}] Hit MAX_PORTFOLIO cap ({raw_c} > 5000). Truncating.")
                    with write_lock:
                        with open(metadata_file.parent / "truncated_maintainers.jsonl", "a", encoding="utf-8") as tf:
                            tf.write(json.dumps({"maintainer": m_name, "truncated": True, "raw_count": raw_c}) + "\n")
                    pkg_keys = pkg_keys[:5000]
                for pkg_name in pkg_keys:
                    maintainer_packages.add(pkg_name)
        
    print(f"Maintainers own a total of {len(maintainer_packages)} packages.")
    
    packages_to_fetch = maintainer_packages - existing_packages
    print(f"Need to fetch metadata for {len(packages_to_fetch)} clean/susceptible packages.")
    
    if not packages_to_fetch:
        print("No new packages to fetch.")
        return
        
    print("Fetching new metadata and appending...")
    def process_pkg(pkg):
        pkg_encoded = urllib.parse.quote(pkg, safe='@/')
        return pkg, fetch_json(f"https://registry.npmjs.org/{pkg_encoded}")

    with open(metadata_file, 'a', encoding='utf-8') as f:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_pkg = {executor.submit(process_pkg, pkg): pkg for pkg in packages_to_fetch}
            for i, future in enumerate(concurrent.futures.as_completed(future_to_pkg)):
                if i > 0 and i % 100 == 0:
                    print(f"Fetched {i}/{len(packages_to_fetch)} new packages...")
                
                pkg, data = future.result()
                if data:
                    times = data.get('time', {})
                    m_list = data.get('maintainers', [])
                    valid_maintainers = []
                    for m_entry in m_list:
                        if isinstance(m_entry, dict) and 'name' in m_entry:
                            if not is_bot(m_entry['name']):
                                valid_maintainers.append(m_entry['name'])
                        elif isinstance(m_entry, str):
                            if not is_bot(m_entry):
                                valid_maintainers.append(m_entry)
                                
                    with write_lock:
                        f.write(json.dumps({
                            "package": pkg,
                            "time": times,
                            "maintainers": valid_maintainers
                        }) + "\n")
                        f.flush()
            
    print("Finished extending portfolios.")

if __name__ == "__main__":
    main()
