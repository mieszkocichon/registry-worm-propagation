import time
import json
import requests
from pathlib import Path

import concurrent.futures
import threading
import random

from constants import is_bot
from ecosystems_rate_limiter import ecosystems_limiter

write_lock = threading.Lock()

def fetch_maintainers(package_name):
    url = f"https://packages.ecosyste.ms/api/v1/registries/npmjs.org/packages/{requests.utils.quote(package_name, safe='')}"
    max_retries = 5
    retries = 0
    while retries < max_retries:
        try:
            ecosystems_limiter.wait()
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                data = r.json()
                maintainers = data.get('maintainers', []) or []
                logins = [m.get('login') for m in maintainers if m.get('login')]
                return logins, True
            elif r.status_code == 404:
                return [], True
            elif r.status_code in (429, 500, 502, 503, 504):
                retries += 1
                time.sleep((2 ** retries) + random.random())
            else:
                break
        except requests.exceptions.RequestException:
            retries += 1
            time.sleep((2 ** retries) + random.random())
    return [], False

def process_single(pkg):
    logins, ok = fetch_maintainers(pkg)
    return pkg, logins, ok

def process_packages(npm_metadata_path, output_jsonl):
    print("Loading npm_metadata.jsonl to find empty-maintainer packages...")
    empty_pkgs = []
    with open(npm_metadata_path, 'r', encoding='utf-8') as f:
        for line in f:
            d = json.loads(line)
            if not d.get('maintainers'):
                empty_pkgs.append(d['package'])

    print(f"Found {len(empty_pkgs)} packages with empty maintainers in npm_metadata.jsonl.")

    existing = set()
    if Path(output_jsonl).exists():
        with open(output_jsonl, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    existing.add(json.loads(line)['package'])
                except Exception:
                    pass

    packages_to_fetch = [p for p in empty_pkgs if p not in existing]
    print(f"Skipping {len(empty_pkgs) - len(packages_to_fetch)} already fetched. Fetching {len(packages_to_fetch)} packages...")

    if not packages_to_fetch:
        print("Nothing to do.")
        return

    with open(output_jsonl, 'a', encoding='utf-8') as f:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_pkg = {executor.submit(process_single, pkg): pkg for pkg in packages_to_fetch}
            for i, future in enumerate(concurrent.futures.as_completed(future_to_pkg)):
                if i > 0 and i % 200 == 0:
                    print(f"Processed {i} packages...")
                pkg, logins, ok = future.result()
                if ok:
                    valid_maintainers = [m for m in logins if not is_bot(m)]
                    with write_lock:
                        f.write(json.dumps({
                            "package": pkg,
                            "maintainers": valid_maintainers,
                            "source": "ecosyste_ms"
                        }) + "\n")
                        f.flush()

    print(f"Saved ecosyste.ms maintainer backfill to {output_jsonl}")

if __name__ == "__main__":
    base = Path(__file__).parent.parent
    npm_path = base / "data" / "npm" / "npm_metadata.jsonl"
    out_dir = base / "data" / "ecosyste_ms"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "maintainers_backfill.jsonl"

    if npm_path.exists():
        process_packages(npm_path, dst)
        print("Finished ecosyste.ms maintainer backfill.")
    else:
        print(f"Input file {npm_path} not found.")
