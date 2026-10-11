#!/usr/bin/env python3
"""Non-malware control group for the co-maintainer dominance result.

WHY THIS EXISTS
---------------
manuscript.tex (Threats to Validity / Internal Validity) concedes that this
study analyses only OSV-flagged malware packages, with no non-malware control:

    "The results therefore establish that co-maintainer transmission reaches
     further than dependency transmission once a compromise occurs, but do not
     by themselves rule out the alternative explanation that high-degree
     maintainer accounts are simply more frequent compromise targets in
     general, independent of any structural transmission advantage."

This script builds that control: an equal-sized sample of npm packages that
are NOT flagged by OSV, run through the identical bipartite-projection
pipeline, so the reported projected mean degree and Gini can be compared
directly against the malware corpus.

The comparison discriminates two hypotheses:

  H_registry  npm's co-maintainer graph is dense everywhere. Control degree
              ~= malware degree. Our dominance result is a property of the
              registry, generalises to any compromise, and the reviewer's
              objection is answered.
  H_selection Attackers preferentially land on high-degree accounts. Control
              degree << malware degree. The dominance result still holds for
              the attacked sub-population, but the paper must say so, and the
              headline must be scoped accordingly.

Either outcome is publishable. Only the absence of the measurement is not.

THREE PARITY REQUIREMENTS (each is a way to get a wrong answer)
--------------------------------------------------------------
1. EQUAL N. Projected degree under P = B @ B.T is not scale-invariant: a
   package can only share a maintainer with packages that are *in the sample*,
   so a 20k sample has systematically lower projected degree than a 213k one
   drawn from the same population. Comparing unequal N reproduces exactly the
   apples-to-oranges error ADR-0018 was written to fix. This script therefore
   defaults to N = 213,162 and refuses to emit a paper-ready baseline row at
   any other N (pilot runs still print, marked NOT COMPARABLE).

2. SAME MAINTAINER SOURCE. The malware corpus's maintainers were recovered
   from ecosyste.ms for the ~57% of packages npm had purged. If the control
   pulled maintainers from the npm registry API instead, any difference could
   be a difference between two metadata providers rather than between two
   populations. The control therefore uses ecosyste.ms for 100% of records.

3. SAME ZERO-MAINTAINER HANDLING. graph_builder.build_bipartite_graph() keeps
   every package as a row of B, so packages with no recovered maintainer sit
   in the matrix as all-zero rows and contribute degree 0 to the mean. The
   cross-ecosystem helper build_B_from_jsonl() (analyze_cross_ecosystem.py)
   instead drops them, because its defaultdict key is only created when a
   maintainer is appended. Reusing that helper here would silently inflate the
   control's mean degree relative to the treatment. build_B_control() below
   preserves the treatment's behaviour. (Note: this discrepancy also affects
   the published cross-ecosystem table -- see the module note at the bottom.)

RUNTIME
-------
The shared ecosyste.ms pacer holds the process to ~1.4 req/s regardless of
worker count, so cost is set by request count, not concurrency. Measured
against the live API (2026-08): the npm listing accepts per_page=1000, serves
deep pages without a performance guard, and returns `maintainers` inline on
937-1000 of every 1000 records. A full N = 213,162 draw is therefore a few
hundred requests -- minutes -- rather than the ~213k per-package lookups the
naive approach needs. The --frame replicate path does need those per-package
lookups (~48 h) and exists only for reviewers who insist the sampling frame be
npm's own canonical index rather than an aggregator's.

Progress is checkpointed to JSONL and flushed after every record, so an
interrupted run loses nothing and re-invoking resumes where it stopped.

Usage:
    python scripts/fetch_npm_control_baseline.py                  # full run
    python scripts/fetch_npm_control_baseline.py --limit 20000    # pilot
    python scripts/fetch_npm_control_baseline.py --analyze-only   # re-analyse
    python scripts/fetch_npm_control_baseline.py --self-check     # unit test
"""
import re
import sys
import json
import logging
from tqdm import tqdm
import random
import argparse
import threading
import concurrent.futures
from pathlib import Path

import requests
import numpy as np
import scipy.sparse as sp

sys.path.append(str(Path(__file__).parent))
from constants import is_bot
from ecosystems_rate_limiter import ecosystems_limiter
from fetch_cross_ecosystem_metrics import http_get, fetch_osv_vulnerable_packages
from analyze_cross_ecosystem import compute_gini, compute_projected_degree_stats

BASE_DIR = Path(__file__).parent.parent
TREATMENT_JSONL = BASE_DIR / "data" / "npm" / "npm_metadata.jsonl"
CONTROL_JSONL = BASE_DIR / "data" / "npm" / "npm_control_maintainers.jsonl"
NAME_CACHE = BASE_DIR / "data" / "npm" / "npm_all_names_cache.txt"
SUMMARY_JSON = BASE_DIR / 'figures' / "non_malware_baseline.json"

ECOSYSTEMS_NPM = "https://packages.ecosyste.ms/api/v1/registries/npmjs.org"
REPLICATE_ALL_DOCS = "https://replicate.npmjs.com/_all_docs"

write_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "data" / "npm" / "fetch_npm_control.log"),
        logging.StreamHandler(sys.stdout)
    ]
)



# ---------------------------------------------------------------------------
# Exclusion set: what counts as "clean"
# ---------------------------------------------------------------------------

def load_treatment_names():
    """Package names in the malware corpus (the treatment group, N = 213,162)."""
    names = set()
    with open(TREATMENT_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            try:
                names.add(json.loads(line)["package"])
            except Exception:
                continue
    return names


def treatment_size():
    """
    The treatment group's N, read from the corpus itself rather than taken
    from --limit. Deriving it from --limit would make the equal-N guard
    self-fulfilling: a pilot run at --limit 3000 would compare 3,000 against
    3,000, declare itself comparable, and emit a paper-ready row for numbers
    that must never sit beside the malware corpus. Observed in testing.
    """
    with open(TREATMENT_JSONL, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def build_exclusion_set():
    """
    "Clean" is defined negatively and generously: a control package must be
    absent from the treatment corpus AND absent from OSV's full npm advisory
    export. The second condition is stricter than merely "not malware" -- it
    also drops packages carrying ordinary CVEs. That is deliberate: a package
    with any OSV record has been touched by the same disclosure process that
    defines the treatment group, and excluding it removes an obvious avenue
    for a reviewer to argue the control is contaminated. The cost is a
    slightly conservative control (a few thousand packages), which biases
    against finding a difference, not toward it.
    """
    treatment = load_treatment_names()
    logging.info(f"Treatment corpus: {len(treatment):,} package names.")
    osv_all = set(fetch_osv_vulnerable_packages("npm"))
    logging.info(f"OSV npm advisory export: {len(osv_all):,} distinct package names.")
    excluded = treatment | osv_all
    logging.info(f"Exclusion set (union): {len(excluded):,} names.")
    return excluded


# ---------------------------------------------------------------------------
# Sampling frame
# ---------------------------------------------------------------------------

def fetch_all_npm_names_replicate():
    """
    npm's CouchDB replica is the canonical full name index -- the npm analogue
    of the PyPI /simple/ and RubyGems /names endpoints that ADR-0016 mandates
    for unbiased sampling. Streamed and cached: the response is one row per
    package across the whole registry (millions), too large to hold in memory
    as parsed JSON, but each row arrives on its own line so the ids can be
    pulled out with a regex as the bytes go past.

    Returns None (rather than raising) if the endpoint is unavailable, so the
    caller can fall back. npm has restricted public replication in the past.
    """
    logging.info("Fetching npm canonical name index from replicate.npmjs.com ...")
    try:
        r = http_get(REPLICATE_ALL_DOCS, timeout=120, hard_timeout=1800, stream=True)
        if r.status_code != 200:
            logging.info(f"  replicate.npmjs.com returned HTTP {r.status_code}; falling back.")
            return None
        names = []
        pattern = re.compile(r'"id":"((?:[^"\\]|\\.)*)"')
        with open(NAME_CACHE, "w", encoding="utf-8") as cache:
            for raw in r.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                for m in pattern.finditer(raw):
                    name = m.group(1)
                    if name.startswith("_design/"):
                        continue
                    names.append(name)
                    cache.write(name + "\n")
                if len(names) % 250_000 == 0 and names:
                    logging.info(f"  ... {len(names):,} names streamed")
        logging.info(f"  Cached {len(names):,} npm package names to {NAME_CACHE}")
        return names
    except Exception as e:
        logging.info(f"  replicate.npmjs.com unavailable ({e}); falling back.")
        return None


ECOSYSTEMS_PER_PAGE = 1000  # verified: the listing accepts per_page=1000 and deep pages


def _ecosystems_page(page, per_page=ECOSYSTEMS_PER_PAGE):
    ecosystems_limiter.wait()
    r = http_get(f"{ECOSYSTEMS_NPM}/packages",
                 params={"page": page, "per_page": per_page},
                 timeout=60, hard_timeout=90)
    if r.status_code != 200:
        return None
    return r.json()


def _ecosystems_total_packages():
    """
    The listing sends `current-page` and a rel="next" link but no total-pages
    header, so page count is derived from the registry summary instead of
    guessed. Verified 2026-08: packages_count = 5,687,466, deep pages (30,000+)
    are served normally -- unlike crates.io, whose performance guard rejects
    offsets beyond ~20,000 and forced the capped window in ADR-0016.
    """
    r = http_get(ECOSYSTEMS_NPM, timeout=30, hard_timeout=45)
    r.raise_for_status()
    return int(r.json().get("packages_count") or 0)


def fetch_all_npm_names_ecosystems(target_pool):
    """
    Preferred frame. Samples uniformly at random across ecosyste.ms's npm
    listing page space -- random pages, not the first K, since sequential
    pagination would correlate the sample with the listing's default ordering
    (id / insertion order) rather than drawing at random.

    This frame is preferred over npm's own _all_docs for one decisive reason:
    the listing carries `maintainers` inline. Measured coverage across three
    probe pages was 937-1000 of 1000 records populated, and the field is never
    null -- an empty list means the package genuinely has no maintainer on
    record, which build_B_control() keeps as a zero-degree row. Sampling
    213,162 packages therefore costs a few hundred requests rather than a few
    hundred thousand, i.e. minutes rather than days.

    Coverage caveat worth stating in the paper: ecosyste.ms reports ~5.69M npm
    packages against ~4.26M rows in npm's own _all_docs replica, the surplus
    being packages since unpublished or deleted. For this particular control
    that skews *toward* comparability rather than away from it, because the
    treatment corpus is itself overwhelmingly composed of packages npm has
    since purged; a frame containing only currently-live packages would be the
    less like-for-like choice.
    """
    total = _ecosystems_total_packages()
    if total <= 0:
        raise RuntimeError("ecosyste.ms did not report an npm packages_count.")
    total_pages = -(-total // ECOSYSTEMS_PER_PAGE)
    print(f"ecosyste.ms npm index: {total:,} packages "
          f"({total_pages:,} pages at per_page={ECOSYSTEMS_PER_PAGE}).")
    logging.info(f"Sampling random pages until {target_pool:,} distinct names are collected ...")

    records, tried = {}, set()
    with tqdm(total=target_pool, desc="Sampling pages", unit="names") as pbar:
        while len(records) < target_pool and len(tried) < total_pages:
            page = random.randint(1, total_pages)
            if page in tried:
                continue
            tried.add(page)
            try:
                data = _ecosystems_page(page)
            except requests.exceptions.RequestException:
                continue
            if not data:
                continue
            for entry in data:
                name = entry.get("name")
                if name and name not in records:
                    records[name] = entry.get("maintainers")
                    pbar.update(1)
                    if len(records) >= target_pool:
                        break
    return records


# ---------------------------------------------------------------------------
# Maintainer fetch
# ---------------------------------------------------------------------------

def _extract_logins(maintainers):
    """ecosyste.ms returns maintainers as dicts (login/name/email) or bare strings."""
    logins = []
    for m in maintainers or []:
        if isinstance(m, dict):
            login = m.get("login") or m.get("name") or m.get("email")
        else:
            login = m
        if login and not is_bot(login):
            logins.append(login)
    return logins


def fetch_one(package):
    """Per-package maintainer lookup. Returns (package, logins, ok)."""
    url = f"{ECOSYSTEMS_NPM}/packages/{requests.utils.quote(package, safe='')}"
    for _ in range(3):
        try:
            ecosystems_limiter.wait()
            r = http_get(url)
            if r.status_code == 200:
                return package, _extract_logins(r.json().get("maintainers")), True
            if r.status_code == 404:
                # Package is in the index but ecosyste.ms has no record. Treated as
                # a package with zero recovered maintainers, mirroring how the
                # treatment corpus handles its own 6,337 unrecovered packages
                # (missing-at-random, no imputation) rather than dropping it.
                return package, [], True
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        except requests.exceptions.RequestException:
            pass
    return package, [], False


def fetch_control_maintainers(names, inline, workers):
    """
    Writes one JSONL record per package, flushed immediately, so an interrupted
    run loses nothing and a re-invocation resumes. Packages whose maintainers
    already arrived inline with the listing skip the network entirely.
    """
    done = set()
    if CONTROL_JSONL.exists():
        with open(CONTROL_JSONL, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["package"])
                except Exception:
                    continue
        logging.info(f"Resuming: {len(done):,} control records already on disk.")

    pending = [n for n in names if n not in done]
    if not pending:
        logging.info("Nothing left to fetch.")
        return

    from_inline = [n for n in pending if inline.get(n) is not None]
    needs_http = [n for n in pending if inline.get(n) is None]
    logging.info(f"To fetch: {len(pending):,} ({len(from_inline):,} inline from listing, "
          f"{len(needs_http):,} need a per-package request)")
    if needs_http:
        print(f"  Estimated wall time for the HTTP portion at ~1.4 req/s: "
              f"{len(needs_http) / 1.4 / 3600:.1f} h")

    CONTROL_JSONL.parent.mkdir(parents=True, exist_ok=True)
    n_failed = 0
    with open(CONTROL_JSONL, "a", encoding="utf-8") as out:
        def emit(package, logins, source):
            with write_lock:
                out.write(json.dumps({
                    "package": package,
                    "registry": "npm",
                    "maintainers": logins,
                    "is_osv_vulnerable": False,
                    "group": "control",
                    "source": source,
                }) + "\n")
                out.flush()

        for name in from_inline:
            emit(name, _extract_logins(inline[name]), "ecosyste_ms_listing")

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_one, n): n for n in needs_http}
            with tqdm(total=len(needs_http), desc="Fetching missing maintainers", unit="pkg") as pbar:
                for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                    package, logins, ok = fut.result()
                    if ok:
                        emit(package, logins, "ecosyste_ms_package")
                    else:
                        n_failed += 1
                    pbar.update(1)
    if n_failed:
        print(f"WARNING: {n_failed:,} packages failed after retries and were not written. "
              f"Re-run to retry them.")


# ---------------------------------------------------------------------------
# Graph construction (parity-preserving)
# ---------------------------------------------------------------------------

def build_B_control(jsonl_path, cap=None):
    """
    Package x maintainer CSR matrix for the control group.

    Deliberately NOT analyze_cross_ecosystem.build_B_from_jsonl(): that helper
    only creates a row for a package once a maintainer is appended to it, so
    packages with zero recovered maintainers vanish from the matrix. The
    treatment's graph_builder keeps them as all-zero rows, and they pull the
    projected mean degree down. Dropping them on one side of the comparison
    only would manufacture a control-vs-treatment gap out of nothing.

    `cap` truncates to exactly the treatment's N so the two matrices are the
    same size (parity requirement 1 in the module docstring).
    """
    packages, maint_lists = [], []
    seen = set()
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            pkg = rec["package"]
            if pkg in seen:
                continue
            seen.add(pkg)
            packages.append(pkg)
            maint_lists.append([m for m in rec.get("maintainers", []) if not is_bot(m)])
            if cap is not None and len(packages) >= cap:
                break

    pkg_to_idx = {p: i for i, p in enumerate(packages)}
    maint_to_idx, rows, cols = {}, [], []
    for pkg, maints in zip(packages, maint_lists):
        pi = pkg_to_idx[pkg]
        for m in maints:
            mi = maint_to_idx.setdefault(m, len(maint_to_idx))
            rows.append(pi)
            cols.append(mi)

    B = sp.csr_matrix(
        (np.ones(len(rows)), (rows, cols)),
        shape=(len(packages), max(1, len(maint_to_idx))),
    )
    return B, len(packages), len(maint_to_idx)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse(treatment_n):
    if not CONTROL_JSONL.exists():
        logging.info(f"No control data at {CONTROL_JSONL}. Run the fetch first.")
        return None

    B, n_pkgs, n_maints = build_B_control(CONTROL_JSONL, cap=treatment_n)
    logging.info(f"\nControl B: {n_pkgs:,} packages x {n_maints:,} maintainers, {B.nnz:,} edges")

    stats = compute_projected_degree_stats(B)
    if stats is None:
        logging.info("Control graph is empty -- nothing to project.")
        return None

    maint_degrees = B.getnnz(axis=0)
    comparable = (n_pkgs == treatment_n)
    result = {
        "group": "non_malware_control",
        "sample_n": n_pkgs,
        "treatment_n": treatment_n,
        "equal_n_comparable": comparable,
        "total_maintainers": n_maints,
        "bipartite_edges": int(B.nnz),
        "packages_with_zero_maintainers": int((B.getnnz(axis=1) == 0).sum()),
        "maint_mean_degree": round(float(maint_degrees.mean()), 3) if n_maints else 0.0,
        "maint_gini": round(compute_gini(maint_degrees.astype(np.float64)), 3) if n_maints else 0.0,
        **stats,
    }

    logging.info("\n=============== NON-MALWARE BASELINE ===============")
    for k, v in result.items():
        logging.info(f"  {k:<34} {v}")

    if comparable:
        logging.info("\nPaper-ready row for Table 2 (cross-ecosystem projected metrics):")
        logging.info(f"  npm (Non-Malware Baseline) & {n_pkgs:,} & "
              f"{stats['projected_mean_degree']} & {stats['projected_gini']} & "
              f"{stats['projected_max_degree']} pkgs \\\\")
    else:
        logging.info(f"\n*** NOT COMPARABLE: control N={n_pkgs:,} != treatment N={treatment_n:,}. ***")
        logging.info("    Projected degree scales with sample size (a package can only share a maintainer with packages inside the sample), so these numbers must NOT be placed next to the malware corpus row. Pilot diagnostics only.")
        
        

    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    logging.info(f"\nSaved {SUMMARY_JSON}")
    return result


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------

def self_check():
    """Smallest thing that fails if the parity logic or the projection breaks."""
    import tempfile, os

    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    recs = [
        {"package": "a", "maintainers": ["alice"]},
        {"package": "b", "maintainers": ["alice"]},
        {"package": "c", "maintainers": ["alice"]},
        {"package": "d", "maintainers": ["dave"]},
        {"package": "e", "maintainers": []},            # zero-maintainer package
        {"package": "f", "maintainers": ["ci-bot"]},    # bot, filtered to zero
    ]
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")

    B, n_pkgs, n_maints = build_B_control(path)
    assert n_pkgs == 6, f"zero-maintainer/bot packages must stay as rows, got {n_pkgs}"
    assert n_maints == 2, f"bot must be filtered out, got {n_maints} maintainers"
    assert B.nnz == 4, f"expected 4 bipartite edges, got {B.nnz}"

    stats = compute_projected_degree_stats(B)
    # a,b,c mutually co-maintained by alice -> projected degree 2 each.
    # d (sole owner), e (none), f (bot-stripped) -> degree 0.
    assert stats["projected_max_degree"] == 2, stats
    assert abs(stats["projected_mean_degree"] - 1.0) < 1e-6, stats

    # The parity trap: dropping packages with no maintainer (e, f) shrinks the
    # denominator from 6 to 4 and inflates the mean projected degree 1.0 -> 1.5,
    # with no change whatsoever to the graph's actual edges.
    B_dropped = B[B.getnnz(axis=1) > 0]
    inflated = compute_projected_degree_stats(B_dropped)
    assert inflated["projected_mean_degree"] == 1.5, inflated

    B_capped, n_capped, _ = build_B_control(path, cap=4)
    assert n_capped == 4, f"cap must truncate to exactly N, got {n_capped}"

    os.unlink(path)
    logging.info("self-check passed: parity preserved, projection correct, cap exact.")
    print(f"  (zero-degree rows kept -> mean {stats['projected_mean_degree']}; "
          f"dropped -> {inflated['projected_mean_degree']}, the error this guards against)")


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Non-malware npm control baseline")
    ap.add_argument("--limit", type=int, default=213162,
                    help="Control sample size. Default matches the treatment corpus; "
                         "any other value produces pilot-only, non-comparable numbers.")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42, help="Sampling seed (reproducibility)")
    ap.add_argument("--frame", choices=["ecosystems", "replicate"], default="ecosystems",
                    help="Sampling frame. 'ecosystems' (default) draws random pages from "
                         "ecosyste.ms's npm listing, which returns maintainers inline -- a few "
                         "hundred requests for a full run. 'replicate' draws from npm's own "
                         "_all_docs canonical index (4.26M names, closest to ADR-0016's letter) "
                         "but then needs one request per package: days, not minutes.")
    ap.add_argument("--analyze-only", action="store_true", help="Skip fetching")
    ap.add_argument("--self-check", action="store_true", help="Run assertions and exit")
    args = ap.parse_args()

    if args.self_check:
        self_check()
        return

    random.seed(args.seed)

    if not args.analyze_only:
        excluded = build_exclusion_set()

        # Over-provision the draw: some names are excluded or fail, and the
        # analysis needs exactly N usable records to satisfy equal-N parity.
        pool = int(args.limit * 1.15)
        inline = {}
        names = None

        if args.frame == "replicate":
            if NAME_CACHE.exists():
                logging.info(f"Using cached name index {NAME_CACHE}")
                names = [l.strip() for l in open(NAME_CACHE, encoding="utf-8") if l.strip()]
            else:
                names = fetch_all_npm_names_replicate()
            if names is None:
                raise SystemExit("replicate frame requested but unavailable.")

        if names is not None:
            frame = "replicate_all_docs"
            candidates = [n for n in names if n not in excluded]
            logging.info(f"Clean candidates in frame: {len(candidates):,}")
            random.shuffle(candidates)
            sample = candidates[:pool]
        else:
            frame = "ecosystems_random_pages"
            records = fetch_all_npm_names_ecosystems(pool)
            clean = {n: m for n, m in records.items() if n not in excluded}
            logging.info(f"Clean candidates in frame: {len(clean):,} "
                  f"({len(records) - len(clean):,} dropped as OSV-flagged or in-treatment)")
            sample = list(clean.keys())
            inline = {n: m for n, m in clean.items() if m is not None}

        logging.info(f"Sampling frame: {frame}; drawing {len(sample):,} candidates "
              f"for a target of {args.limit:,} usable records.")
        fetch_control_maintainers(sample, inline, args.workers)

    analyse(treatment_n=treatment_size())


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# NOTE FOR THE CROSS-ECOSYSTEM TABLE (not fixed here -- it would change already
# published numbers, which is the authors' call):
# analyze_cross_ecosystem.build_B_from_jsonl() drops packages with zero
# maintainers, while graph_builder keeps them. The PyPI / crates.io / RubyGems
# rows of Table 2 are therefore computed over a denominator that excludes their
# own zero-maintainer packages, whereas the npm row does not. If those samples
# contain a non-trivial share of maintainer-less packages, their projected mean
# degrees are biased upward relative to npm's -- which would understate, not
# overstate, npm's reported 12-44x dominance. Worth re-running before
# submission to confirm the direction and magnitude.
# ---------------------------------------------------------------------------
