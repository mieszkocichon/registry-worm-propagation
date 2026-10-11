#!/usr/bin/env python3
"""Recover the *actual* npm publish timestamp of each malicious version, and
re-run patient-zero selection against it.

Why this exists
---------------
ADR-0004/ADR-0012 dated every malware package by OSV's `published` field. That
field is the ADVISORY's publication date, not the date the malicious version
hit the registry. Measured on the verifiable subsample (see
analyze_publish_velocity.py): median lag 4.2 d, mean 78.2 d, 17.4% > 100 d.

The lag is one-directional (advisory always >= injection), so it is not noise:
it systematically back-dates the attack window. In patient-zero selection the
date is the cutoff for "did this package have legitimate release history
BEFORE it was hijacked?" -- so a 78-day-late cutoff lets the malicious version
itself, and any subsequent attacker republish, count as pre-hijack history.
That inflates the pool of candidates passing the "established package" filter.

Resolution ladder (per package, first tier that resolves wins)
-------------------------------------------------------------
  exact   OSV `versions_affected` names a version that is present in the
          package's own npm `time` dict -> use that version's npm timestamp.
          This is ground truth: registry-recorded, per-version.
  bounded OSV named no usable version, but npm `time` has releases at or
          before the advisory date -> use the LATEST such release. That is the
          last publish that could have been the flagged one; it is an upper
          bound on the true injection date and is always <= the OSV date, so
          it moves the cutoff in the correcting direction.
  proxy   no npm timestamps usable at all -> OSV `published`, unchanged.

`bounded` is a bound, not ground truth, and is labelled as such in the output
so the paper can report exact-only and exact+bounded coverage separately.

ponytail: the tiers are per-package; a package with several MAL- advisories is
dated by the earliest resolved one, matching the previous groupby().min().
"""
import json
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import pandas as pd

from constants import is_bot

BASE = Path(__file__).parent.parent
OSV_CSV = BASE / "data" / "npm" / "osv_npm_vulnerabilities_filtered.csv"
META_JSONL = BASE / "data" / "npm" / "npm_metadata.jsonl"


def load_malware_advisories(osv_csv=OSV_CSV):
    """MAL- advisories only, one frame, `published` parsed to UTC."""
    osv = pd.read_csv(osv_csv)
    mask = (osv["osv_id"].str.startswith("MAL-", na=False)
            | osv["aliases"].str.contains("MAL-", na=False))
    mal = osv[mask].copy()
    mal["published_dt"] = pd.to_datetime(mal["published"], utc=True, errors="coerce")
    return mal.dropna(subset=["published_dt"])


def _parse(ts):
    """
    npm serialises every timestamp as ISO-8601 with a 'Z' suffix. Calling
    pd.to_datetime per string costs ~200us of dispatch overhead, which over the
    ~1M (package, version) pairs in the corpus dominates the whole run;
    fromisoformat is ~200x faster and returns a comparable aware datetime.
    """
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _version_times(time_dict):
    """{version -> UTC timestamp}, dropping npm's 'created'/'modified' keys."""
    out = {}
    for k, ts in time_dict.items():
        if k in ("created", "modified"):
            continue
        t = _parse(ts)
        if t is not None:
            out[k] = t
    return out


def resolve_malicious_dates(mal, npm_meta):
    """
    {package -> (timestamp, tier)} for every package present in both sources.

    `npm_meta` is {package -> raw metadata record}; `mal` is the frame from
    load_malware_advisories(). Packages with no npm metadata are absent from
    the result -- they cannot seed a simulation anyway, since they are not in
    the bipartite graph.
    """
    # Versions named by OSV, per package, unioned across that package's
    # advisories. ~2.5% of rows list several comma-separated versions.
    named = defaultdict(set)
    for pkg, ver in zip(mal["package"], mal["versions_affected"]):
        if isinstance(ver, str):
            for v in ver.split(","):
                v = v.strip()
                if v:
                    named[pkg].add(v)

    osv_first = mal.groupby("package")["published_dt"].min()

    resolved = {}
    for pkg, osv_dt in osv_first.items():
        meta = npm_meta.get(pkg)
        if meta is None:
            continue
        vtimes = _version_times(meta.get("time", {}))

        hits = [vtimes[v] for v in named.get(pkg, ()) if v in vtimes]
        if hits:
            resolved[pkg] = (min(hits), "exact")
            continue

        at_or_before = [t for t in vtimes.values() if t <= osv_dt]
        if at_or_before:
            resolved[pkg] = (max(at_or_before), "bounded")
            continue

        resolved[pkg] = (osv_dt, "proxy")
    return resolved


def build_maintainer_timeline(meta_jsonl=META_JSONL):
    """{maintainer -> {package -> earliest release timestamp}}, bots excluded."""
    timeline = defaultdict(dict)
    with open(meta_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            vtimes = _version_times(d.get("time", {}))
            if not vtimes:
                continue
            earliest = min(vtimes.values())
            for m in d.get("maintainers", []):
                name = m.get("name") if isinstance(m, dict) else m
                if not name or is_bot(name):
                    continue
                prev = timeline[name].get(d["package"])
                if prev is None or earliest < prev:
                    timeline[name][d["package"]] = earliest
    return timeline


def select_patient_zeros(npm_meta, pkg_to_idx, resolved, timeline, n=10,
                         tiers=("exact",)):
    """
    ADR-0012's two temporal conditions, evaluated against the RESOLVED
    malicious-version date instead of the OSV advisory date:

      1. the package has >= 1 release strictly before it was hijacked, and
      2. >= 1 non-bot maintainer already owned > 1 package at that moment
         (an established identity, not an account minted for the attack).

    Candidates are walked in chronological order of the resolved date, so the
    seeds are the earliest surviving hijacks. Returns (seeds, log, rejected).

    `tiers` defaults to exact-only, and that default is load-bearing. Condition
    1 asks whether releases predate the hijack, so it is only meaningful when
    the hijack date is the malicious version's real timestamp. Under `bounded`
    the anchor is the last release at or before the advisory -- for a package
    whose malicious version npm has since purged, that anchor is a LEGITIMATE
    release, and the chronological sort then surfaces packages that merely
    stopped releasing early rather than packages hijacked early. Measured: the
    bounded-inclusive run returns 10 seeds all sharing one 2016 date, none of
    them credible hijacks. Exact-only leaves ~16.8k candidates, which is three
    orders of magnitude more than the 10 seeds needed.
    """
    candidates = sorted(
        (p for p in resolved
         if p in pkg_to_idx and p in npm_meta and resolved[p][1] in tiers),
        key=lambda p: resolved[p][0],
    )

    seeds, log, rejected = [], [], 0
    for pkg in candidates:
        mal_dt, tier = resolved[pkg]
        vtimes = _version_times(npm_meta[pkg].get("time", {}))
        n_before = sum(1 for t in vtimes.values() if t < mal_dt)
        if n_before == 0:
            rejected += 1
            continue

        maintainers = [m.get("name") if isinstance(m, dict) else m
                       for m in npm_meta[pkg].get("maintainers", [])]
        maintainers = [m for m in maintainers if m and not is_bot(m)]
        portfolios = [sum(1 for t in timeline.get(m, {}).values() if t < mal_dt)
                      for m in maintainers]
        if not any(size > 1 for size in portfolios):
            rejected += 1
            continue

        seeds.append(pkg)
        log.append({
            "package": pkg,
            "malicious_publish": str(mal_dt),
            "date_tier": tier,
            "pre_hijack_versions": n_before,
            "human_maintainers": len(maintainers),
            "max_pre_hijack_portfolio": max(portfolios) if portfolios else 0,
        })
        if len(seeds) == n:
            break
    return seeds, log, rejected


def _self_check():
    meta = {
        # exact: OSV names 1.0.2, npm has it -> that timestamp, not the advisory's
        "exact-pkg": {"package": "exact-pkg", "maintainers": ["alice"], "time": {
            "created": "2023-01-01T00:00:00Z",
            "1.0.0": "2023-01-01T00:00:00Z",
            "1.0.1": "2023-02-01T00:00:00Z",
            "1.0.2": "2023-03-01T00:00:00Z"}},
        # bounded: no version named; latest release <= advisory date is 2.0.1
        "bounded-pkg": {"package": "bounded-pkg", "maintainers": ["alice"], "time": {
            "2.0.0": "2023-01-01T00:00:00Z",
            "2.0.1": "2023-03-01T00:00:00Z",
            "2.0.2": "2023-09-01T00:00:00Z"}},
        # proxy: every release postdates the advisory -> nothing to anchor to
        "proxy-pkg": {"package": "proxy-pkg", "maintainers": ["alice"], "time": {
            "3.0.0": "2024-01-01T00:00:00Z"}},
    }
    mal = pd.DataFrame({
        "osv_id": ["MAL-1", "MAL-2", "MAL-3"],
        "package": ["exact-pkg", "bounded-pkg", "proxy-pkg"],
        "published": ["2023-06-01T00:00:00Z"] * 3,
        "aliases": [None] * 3,
        "versions_affected": ["1.0.2", None, None],
    })
    mal["published_dt"] = pd.to_datetime(mal["published"], utc=True)

    r = resolve_malicious_dates(mal, meta)
    assert r["exact-pkg"][1] == "exact"
    assert str(r["exact-pkg"][0].date()) == "2023-03-01"
    assert r["bounded-pkg"][1] == "bounded"
    assert str(r["bounded-pkg"][0].date()) == "2023-03-01", r["bounded-pkg"]
    assert r["proxy-pkg"][1] == "proxy"
    assert str(r["proxy-pkg"][0].date()) == "2023-06-01"

    # The correction has teeth: under the OSV date (2023-06-01) bounded-pkg
    # counts 2 pre-hijack releases; under the resolved date only 1, because
    # 2.0.1 IS the malicious publish rather than legitimate history.
    vt = _version_times(meta["bounded-pkg"]["time"])
    osv_dt = pd.to_datetime("2023-06-01T00:00:00Z", utc=True)
    assert sum(1 for t in vt.values() if t < osv_dt) == 2
    assert sum(1 for t in vt.values() if t < r["bounded-pkg"][0]) == 1

    # Selection: alice owns 3 packages, so only the history condition bites.
    timeline = {"alice": {p: pd.to_datetime("2022-01-01T00:00:00Z", utc=True)
                          for p in meta}}
    idx = {p: i for i, p in enumerate(meta)}
    seeds, log, rejected = select_patient_zeros(
        meta, idx, r, timeline, n=10, tiers=("exact", "bounded"))
    assert seeds == ["bounded-pkg", "exact-pkg"], seeds  # chronological order
    assert rejected == 0, rejected  # proxy-pkg is filtered by tier, not rejected
    assert [e["date_tier"] for e in log] == ["bounded", "exact"]

    seeds_all, _, rejected_all = select_patient_zeros(
        meta, idx, r, timeline, n=10, tiers=("exact", "bounded", "proxy"))
    assert seeds_all == ["bounded-pkg", "exact-pkg"], seeds_all
    assert rejected_all == 1, rejected_all  # proxy-pkg: no release before its advisory date

    # The default seed pool is exact-only, so the bounded package is excluded.
    seeds_default, log_default, _ = select_patient_zeros(meta, idx, r, timeline, n=10)
    assert seeds_default == ["exact-pkg"], seeds_default
    assert all(e["date_tier"] == "exact" for e in log_default)
    print("self-check passed: tier ladder, correcting direction, chronological selection, exact-only default")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-seeds", type=int, default=10)
    ap.add_argument("--tiers", default="exact",
                    help="comma-separated date tiers eligible to seed "
                         "(default: exact -- see select_patient_zeros docstring)")
    ap.add_argument("--write", action="store_true",
                    help="overwrite data/npm/patient_zeros.json with the corrected seeds")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()

    if args.self_check:
        _self_check()
        return

    npm_meta = {}
    with open(META_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            npm_meta[d["package"]] = d

    mal = load_malware_advisories()
    resolved = resolve_malicious_dates(mal, npm_meta)

    tier_counts = pd.Series([t for _, t in resolved.values()]).value_counts()
    n = len(resolved)
    print(f"Resolved {n:,} malware packages present in both OSV and npm metadata.")
    for tier in ("exact", "bounded", "proxy"):
        c = int(tier_counts.get(tier, 0))
        print(f"  {tier:<8} {c:>7,}  ({100*c/n:5.2f}%)")

    osv_first = mal.groupby("package")["published_dt"].min()
    shift_by_tier = {}
    print("\nCorrection applied (advisory date minus resolved date), per tier:")
    for tier in ("exact", "bounded"):
        s = pd.Series([(osv_first[p] - dt).total_seconds() / 86400
                       for p, (dt, t) in resolved.items() if t == tier])
        if s.empty:
            continue
        shift_by_tier[tier] = s
        print(f"  {tier:<8} n={len(s):>7,}  mean {s.mean():8.1f} d  median {s.median():8.1f} d  "
              f"p90 {s.quantile(0.9):8.1f} d  >100d {100*(s > 100).mean():5.1f}%")

    from graph_builder import build_bipartite_graph
    from data_utils import load_node_universe
    pkg_set, _, _, _ = load_node_universe()
    _, pkg_list, pkg_to_idx, _, _, _ = build_bipartite_graph(allowed_packages=pkg_set)

    timeline = build_maintainer_timeline()
    tiers = tuple(args.tiers.split(","))
    seeds, log, rejected = select_patient_zeros(
        npm_meta, pkg_to_idx, resolved, timeline, n=args.n_seeds, tiers=tiers)

    print(f"\nSeed pool restricted to tier(s): {', '.join(tiers)}")
    print(f"Rejected {rejected:,} candidates (no pre-hijack history, or throwaway maintainer).")
    print(f"Selected {len(seeds)} patient-zero seeds:")
    for e in log:
        print(f"  {e['package']:<32} {e['malicious_publish'][:10]}  [{e['date_tier']:<7}] "
              f"{e['pre_hijack_versions']} pre-hijack versions, "
              f"{e['human_maintainers']} human maintainers")

    out = BASE / "data" / "npm" / "patient_zero_provenance.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "n_resolved": n,
            "tier_counts": {k: int(tier_counts.get(k, 0)) for k in ("exact", "bounded", "proxy")},
            "correction_days": {
                tier: {"n": int(len(s)), "mean": float(s.mean()),
                       "median": float(s.median()), "p90": float(s.quantile(0.9)),
                       "pct_gt_100d": float(100 * (s > 100).mean())}
                for tier, s in shift_by_tier.items()
            },
            "seed_tiers": list(tiers),
            "n_rejected": rejected,
            "seeds": log,
        }, f, indent=2)
    print(f"\nWrote {out}")

    pz = BASE / "data" / "npm" / "patient_zeros.json"
    if args.write:
        with open(pz, "w", encoding="utf-8") as f:
            json.dump(seeds, f)
        print(f"Wrote {pz}")
    else:
        with open(pz, "r", encoding="utf-8") as f:
            old = json.load(f)
        print(f"\nCurrent {pz.name}: {old}")
        print(f"Corrected:            {seeds}")
        print("Unchanged." if old == seeds else "*** SEED SET CHANGES -- rerun simulations before quoting results. ***")
        print("(pass --write to overwrite)")


if __name__ == "__main__":
    main()
