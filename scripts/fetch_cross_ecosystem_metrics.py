import re
import time
import json
import random
import argparse
import requests
import threading
from pathlib import Path
import concurrent.futures

from constants import is_bot
from ecosystems_rate_limiter import ecosystems_limiter

write_lock = threading.Lock()

# requests' `timeout=` only resets on each byte received, so a connection that's
# held open and trickled (ecosyste.ms does this under load, see ecosystems_limiter
# docstring) can hang forever. Route requests through a watchdog daemon thread so
# a hung call is abandoned after a real wall-clock deadline instead of blocking
# forever. Must be `daemon=True`: a non-daemon thread stuck on a dead socket
# would keep the whole process alive indefinitely, even after the script's own
# logic finished -- ThreadPoolExecutor's workers are non-daemon, which is why a
# prior version of this using a shared pool left zombie python.exe processes
# running (and still writing) long after they appeared to have exited.
def http_get(url, timeout=10, hard_timeout=15, **kwargs):
    box = {}
    def worker():
        try:
            box['response'] = requests.get(url, timeout=timeout, **kwargs)
        except Exception as e:
            box['error'] = e
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(hard_timeout)
    if t.is_alive():
        raise requests.exceptions.Timeout(f"hard timeout ({hard_timeout}s) exceeded for {url}")
    if 'error' in box:
        raise box['error']
    return box['response']

# crates.io rejects requests with no descriptive User-Agent (403). Their
# crawler policy also asks for ~1 req/sec.
CRATES_USER_AGENT = "npm-worm-cross-ecosystem-research/1.0 (academic research script)"

# Mapping internal names to ecosyste.ms registry slugs & OSV ecosystem names
REGISTRIES = {
    "pypi": {
        "ecosystems_slug": "pypi.org",
        "osv_name": "PyPI",
        "output_file": "pypi_maintainers.jsonl"
    },
    "crates": {
        "ecosystems_slug": "crates.io",
        "osv_name": "crates.io",
        "output_file": "crates_maintainers.jsonl"
    },
    "rubygems": {
        "ecosystems_slug": "rubygems.org",
        "osv_name": "RubyGems",
        "output_file": "rubygems_maintainers.jsonl"
    }
}

def fetch_package_maintainers(registry_slug, package_name):
    """
    Queries ecosyste.ms API for package maintainers in a specific registry.
    """
    url = f"https://packages.ecosyste.ms/api/v1/registries/{registry_slug}/packages/{requests.utils.quote(package_name, safe='')}"
    max_retries = 2
    retries = 0
    while retries < max_retries:
        try:
            ecosystems_limiter.wait()
            r = http_get(url)
            if r.status_code == 200:
                data = r.json()
                maintainers = data.get('maintainers', []) or []
                logins = []
                for m in maintainers:
                    login = m.get('login') or m.get('name') or m.get('email')
                    if login:
                        logins.append(login)
                dependent_count = data.get('dependent_packages_count', 0)
                return logins, dependent_count, True
            elif r.status_code == 404:
                return [], 0, True
            elif r.status_code in (429, 500, 502, 503, 504):
                retries += 1
                time.sleep(1)
            else:
                break
        except requests.exceptions.RequestException:
            retries += 1
            time.sleep(1)
    return [], 0, False

def _fetch_crates_sample(target_count, existing_pkgs):
    """
    crates.io has no full-name-dump endpoint, so sample uniformly at random
    across its page space (using its own `meta.total`) instead. Hits crates.io
    directly, not ecosyste.ms's biased search.

    crates.io's own API rejects deep offsets ("Page X is unavailable for
    performance reasons") -- verified empirically: page=200 works, page=210
    doesn't, at per_page=100 (i.e. offset cap ~20,000). Random pages beyond
    that silently return nothing, so cap sampling to the reachable window
    instead of the full (mostly-unreachable) total_pages.
    """
    headers = {"User-Agent": CRATES_USER_AGENT}
    r = http_get("https://crates.io/api/v1/crates", params={"page": 1, "per_page": 1}, headers=headers)
    r.raise_for_status()
    total = r.json()["meta"]["total"]
    per_page = 100
    total_pages = -(-total // per_page)
    max_offset = 20000
    usable_pages = min(total_pages, max_offset // per_page)
    print(f"crates.io has {total} total crates; its API only allows browsing the first ~{max_offset} "
          f"(pages 1-{usable_pages} at per_page={per_page}) before its performance guard rejects requests. "
          f"Sampling random pages within that reachable range...")

    names = []
    tried_pages = set()
    page_budget = usable_pages
    while len(names) < target_count and len(tried_pages) < page_budget:
        page = random.randint(1, usable_pages)
        if page in tried_pages:
            continue
        tried_pages.add(page)
        time.sleep(1)  # crates.io crawler policy: ~1 req/sec
        try:
            r = http_get("https://crates.io/api/v1/crates", params={"page": page, "per_page": per_page}, headers=headers)
            if r.status_code != 200:
                continue
            for c in r.json().get("crates", []):
                name = c.get("name")
                if name and name not in existing_pkgs and name not in names:
                    names.append(name)
        except requests.exceptions.RequestException:
            continue
        if len(tried_pages) % 10 == 0:
            print(f"  [crates.io] sampled {len(tried_pages)}/{page_budget} pages, {len(names)}/{target_count} new names so far")

    if len(names) < target_count:
        print(f"  [crates.io] exhausted the reachable page range ({usable_pages} pages, ~{usable_pages * per_page} crates); "
              f"got {len(names)}/{target_count} new names. crates.io's API caps out here -- see https://crates.io/data-access "
              f"for the full DB dump if more are needed.")
    return names[:target_count]

def fetch_registry_sample_names(reg_key, target_count, existing_pkgs):
    """
    Samples candidate package names from each registry's own canonical index
    (not ecosyste.ms's search, which silently falls back to a popularity-
    ranked list on unmatched queries and skews samples toward already-popular
    packages -- verified: q='xk' on pypi.org returned the identical result
    set as no query at all).
    """
    if reg_key == "pypi":
        print("Fetching full PyPI simple index (all package names)...")
        r = http_get("https://pypi.org/simple/", timeout=60, hard_timeout=90)
        r.raise_for_status()
        all_names = re.findall(r'<a[^>]*>([^<]+)</a>', r.text)
    elif reg_key == "rubygems":
        print("Fetching full RubyGems name index (all gem names)...")
        r = http_get("https://index.rubygems.org/names", timeout=60, hard_timeout=90)
        r.raise_for_status()
        all_names = [l for l in r.text.splitlines() if l and not l.startswith('---')]
    elif reg_key == "crates":
        return _fetch_crates_sample(target_count, existing_pkgs)
    else:
        raise ValueError(reg_key)

    print(f"{reg_key} index has {len(all_names)} total package names.")
    candidates = [n for n in all_names if n not in existing_pkgs]
    random.shuffle(candidates)
    return candidates[:target_count]

def fetch_osv_vulnerable_packages(osv_ecosystem):
    """
    OSV's /v1/query endpoint has no "list all vulnerable packages in an
    ecosystem" mode -- it requires a specific package name or commit. The
    old ecosystem-only POST here silently returned [] on every call (non-200
    responses were swallowed with no exception raised), so is_osv_vulnerable
    was always False. Use OSV's bulk per-ecosystem export instead (same
    source fetch_osv_data.py already uses for npm).
    """
    import io
    import zipfile
    url = f"https://osv-vulnerabilities.storage.googleapis.com/{osv_ecosystem}/all.zip"
    print(f"Downloading OSV bulk export for {osv_ecosystem}...")
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        packages = set()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for name in z.namelist():
                if not name.endswith('.json'):
                    continue
                data = json.loads(z.read(name))
                for affected in data.get('affected', []):
                    pkg_name = affected.get('package', {}).get('name')
                    if pkg_name:
                        packages.add(pkg_name)
        return list(packages)
    except Exception as e:
        print(f"OSV bulk export error for {osv_ecosystem}: {e}")
        return []

def process_single(args):
    registry_slug, pkg = args
    logins, dependent_count, ok = fetch_package_maintainers(registry_slug, pkg)
    return pkg, logins, dependent_count, ok

def process_registry(reg_key, sample_limit=15000, max_workers=4):
    reg_info = REGISTRIES[reg_key]
    slug = reg_info["ecosystems_slug"]
    osv_name = reg_info["osv_name"]
    out_file = reg_info["output_file"]
    
    out_dir = Path(__file__).parent.parent / "data" / "cross_ecosystem"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst_path = out_dir / out_file
    
    # 1. Check existing downloaded packages
    existing = set()
    if dst_path.exists():
        with open(dst_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    existing.add(json.loads(line)['package'])
                except Exception:
                    pass
    
    existing_count = len(existing)
    print(f"\n[{reg_key.upper()}] Found {existing_count} packages already saved.")
    
    if existing_count >= sample_limit:
        print(f"[{reg_key.upper()}] Already reached target limit of {sample_limit} packages. Skipping.")
        return dst_path
        
    # 2. Fetch OSV packages
    osv_pkgs = fetch_osv_vulnerable_packages(osv_name)
    print(f"Found {len(osv_pkgs)} OSV vulnerable packages for {reg_key}.")
    
    # 3. Fetch registry sample packages from the registry's own canonical index (unbiased)
    remaining_limit = sample_limit - existing_count
    reg_pkgs = fetch_registry_sample_names(reg_key, target_count=remaining_limit, existing_pkgs=existing)
    print(f"Fetched {len(reg_pkgs)} new candidate package names for {reg_key}.")
    
    # Combine & deduplicate
    all_target_pkgs = [p for p in list(set(osv_pkgs + reg_pkgs)) if p not in existing][:remaining_limit]
    print(f"Total new target packages to process for {reg_key}: {len(all_target_pkgs)}")
    
    if not all_target_pkgs:
        print(f"[{reg_key.upper()}] No new packages to fetch.")
        return dst_path

    tasks = [(slug, pkg) for pkg in all_target_pkgs]
    
    with open(dst_path, 'a', encoding='utf-8') as f:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {executor.submit(process_single, t): t for t in tasks}
            for i, future in enumerate(concurrent.futures.as_completed(future_to_task)):
                if (i + 1) % 100 == 0 or (i + 1) == len(tasks):
                    print(f"[{reg_key.upper()}] Processed {i + 1}/{len(tasks)} new packages (Total saved: {existing_count + i + 1})...")
                pkg, logins, dep_count, ok = future.result()
                if ok:
                    valid_maint = [m for m in logins if not is_bot(m)]
                    is_osv = pkg in osv_pkgs
                    with write_lock:
                        f.write(json.dumps({
                            "package": pkg,
                            "registry": reg_key,
                            "maintainers": valid_maint,
                            "dependent_count": dep_count,
                            "is_osv_vulnerable": is_osv,
                            "source": "ecosyste_ms"
                        }) + "\n")
                        f.flush()
                        
    print(f"Saved {reg_key} maintainer data to {dst_path}")
    return dst_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cross-ecosystem maintainer fetcher")
    parser.add_argument("--registry", choices=["pypi", "crates", "rubygems", "all"], default="all", help="Target ecosystem")
    parser.add_argument("--limit", type=int, default=15000, help="Maximum number of packages to fetch per ecosystem")
    parser.add_argument("--workers", type=int, default=4, help="Worker threads")
    args = parser.parse_args()
    
    target_regs = ["pypi", "crates", "rubygems"] if args.registry == "all" else [args.registry]
    for r in target_regs:
        print(f"\n=================== PROCESSING {r.upper()} ===================")
        process_registry(r, sample_limit=args.limit, max_workers=args.workers)
