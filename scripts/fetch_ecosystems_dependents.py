import time
import json
import requests
from pathlib import Path

import concurrent.futures
import threading
import random

from ecosystems_rate_limiter import ecosystems_limiter

write_lock = threading.Lock()

MAX_DEPENDENTS = 10000
PER_PACKAGE_TIME_BUDGET = 45  # seconds — hard wall-clock cap so one heavy package can't stall a worker for minutes

def fetch_dependents(package_name):
    pkg_url = f"https://packages.ecosyste.ms/api/v1/registries/npmjs.org/packages/{requests.utils.quote(package_name, safe='')}"
    base_url = pkg_url + "/dependent_packages"
    all_dependents = []
    url = base_url
    params = {"per_page": 100}
    max_retries = 5
    start_time = time.monotonic()

    # Cheap pre-check on the fast, non-paginated package endpoint: some OSV-flagged
    # packages (e.g. a hijacked version of an otherwise-legitimate popular package
    # like react) have hundreds of thousands of dependents. Paginating that full list
    # (or even a single page reply for it) can take the server long enough that
    # requests' timeout= (a per-read, not per-call, deadline) never fires — this
    # single worker then blocks for many minutes. Skip straight to a truncated
    # record instead of ever hitting the slow paginated endpoint for these.
    retries = 0
    while retries < max_retries:
        try:
            ecosystems_limiter.wait()
            r = requests.get(pkg_url, timeout=10)
            if r.status_code == 200:
                count = r.json().get('dependent_packages_count')
                if isinstance(count, int) and count > MAX_DEPENDENTS:
                    print(f"[{package_name}] dependent_packages_count={count} > {MAX_DEPENDENTS}. Skipping paginated fetch (too popular to enumerate).")
                    return [], True, count, True
                break
            elif r.status_code == 404:
                return [], False, 0, True
            elif r.status_code in (429, 500, 502, 503, 504):
                retries += 1
                time.sleep((2 ** retries) + random.random())
            else:
                break
        except requests.exceptions.RequestException:
            retries += 1
            time.sleep((2 ** retries) + random.random())

    while url:
        if time.monotonic() - start_time > PER_PACKAGE_TIME_BUDGET:
            print(f"[{package_name}] Exceeded {PER_PACKAGE_TIME_BUDGET}s time budget after {len(all_dependents)} dependents. Truncating (likely a heavily-depended-upon package).")
            return all_dependents, True, len(all_dependents), True

        retries = 0
        success = False
        while retries < max_retries:
            try:
                ecosystems_limiter.wait()
                r = requests.get(url, params=params if url == base_url else None, timeout=10)
                if r.status_code == 200:
                    nodes = r.json()
                    all_dependents.extend([n.get("name") for n in nodes if n.get("name")])

                    if len(all_dependents) > MAX_DEPENDENTS:
                        raw_c = len(all_dependents)
                        print(f"[{package_name}] Hit MAX_DEPENDENTS cap ({raw_c} > {MAX_DEPENDENTS}). Truncating.")
                        return all_dependents[:MAX_DEPENDENTS], True, raw_c, True

                    next_link = r.links.get('next', {}).get('url')
                    url = next_link
                    success = True
                    break
                elif r.status_code == 404:
                    return [], False, 0, True
                elif r.status_code in (429, 500, 502, 503, 504):
                    retries += 1
                    if time.monotonic() - start_time > PER_PACKAGE_TIME_BUDGET:
                        print(f"[{package_name}] Exceeded time budget while retrying ({r.status_code}). Truncating.")
                        return all_dependents, True, len(all_dependents), True
                    time.sleep((2 ** retries) + random.random())
                else:
                    return all_dependents, False, len(all_dependents), False
            except requests.exceptions.RequestException:
                retries += 1
                time.sleep((2 ** retries) + random.random())

        if not success:
            return all_dependents, False, len(all_dependents), False

    return all_dependents, False, len(all_dependents), True

def process_single(pkg):
    deps, truncated, raw_c, ok = fetch_dependents(pkg)
    return pkg, deps, truncated, raw_c, ok

def process_deps(npm_metadata_path, output_jsonl):
    packages = [json.loads(line)['package'] for line in open(npm_metadata_path, 'r', encoding='utf-8')]

    existing = set()
    if Path(output_jsonl).exists():
        with open(output_jsonl, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    existing.add(json.loads(line)['package'])
                except Exception:
                    pass

    packages_to_fetch = [p for p in packages if p not in existing]

    print(f"Fetching ecosyste.ms dependents for {len(packages_to_fetch)} new packages out of {len(packages)} total...")

    if not packages_to_fetch:
        print("All packages already have ecosyste.ms dependents data.")
        return

    with open(output_jsonl, 'a', encoding='utf-8') as f:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_pkg = {executor.submit(process_single, pkg): pkg for pkg in packages_to_fetch}
            for i, future in enumerate(concurrent.futures.as_completed(future_to_pkg)):
                if i > 0 and i % 500 == 0:
                    print(f"Processed {i} packages...")
                pkg, dependents, trunc, raw_c, ok = future.result()
                if ok:
                    record = {"package": pkg, "dependents": dependents, "source": "ecosyste_ms"}
                    if trunc:
                        record["truncated"] = True
                        record["raw_count"] = raw_c
                    with write_lock:
                        f.write(json.dumps(record) + "\n")
                        f.flush()

    print(f"Saved ecosyste.ms dependents data to {output_jsonl}")

if __name__ == "__main__":
    base = Path(__file__).parent.parent
    npm_path = base / "data" / "npm" / "npm_metadata.jsonl"
    out_dir = base / "data" / "ecosyste_ms"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "dependents_backfill.jsonl"

    if npm_path.exists():
        process_deps(npm_path, dst)
        print("Finished fetching ecosyste.ms dependents information.")
    else:
        print(f"Input file {npm_path} not found.")
