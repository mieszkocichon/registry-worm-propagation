"""Build the per-licence data packages and pseudonymise maintainer handles.

Handles are replaced by m_<16 hex of HMAC-SHA256(key, handle)>. Accounts matching
constants.is_bot (registry/bot accounts, not natural persons) stay literal, so
graph_builder's bot filter behaves identically on released data. This is
pseudonymisation, not anonymisation: package names remain public and link back
to accounts. The key never leaves the author.

  python scripts/build_release.py --src <dir holding original data/> \
      --key-file <secret> --out release_out [--results-out data]
"""
import argparse, csv, hmac, hashlib, json, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from constants import is_bot

ACCOUNT_KEYS = {"account", "maint_max_account", "top50_names", "maintainers"}


def make_pseudonymizer(key: bytes):
    def p(login):
        if not isinstance(login, str) or is_bot(login):
            return login
        return "m_" + hmac.new(key, login.encode(), hashlib.sha256).hexdigest()[:16]
    return p


def walk(o, p, under=False):
    if isinstance(o, dict):
        return {k: walk(v, p, k in ACCOUNT_KEYS) for k, v in o.items()}
    if isinstance(o, list):
        return [walk(v, p, under) for v in o]
    return p(o) if under and isinstance(o, str) else o


def jsonl(src, dst, p):
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8", newline="\n") as g:
        for line in f:
            d = json.loads(line)
            if "maintainers" in d:
                d["maintainers"] = [p(m) for m in d["maintainers"] or []]
            g.write(json.dumps(d, ensure_ascii=False) + "\n")


def split_osv(src, out):
    files = {"MAL": "osv_mal_openssf.csv", "GHSA": "osv_ghsa.csv", "GSD": "osv_gsd.csv"}
    out.mkdir(parents=True, exist_ok=True)
    fh = {k: open(out / v, "w", encoding="utf-8", newline="") for k, v in files.items()}
    with open(src, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        ws = {k: csv.DictWriter(h, r.fieldnames) for k, h in fh.items()}
        for w in ws.values():
            w.writeheader()
        for row in r:
            ws[row["osv_id"].split("-")[0]].writerow(row)
    for h in fh.values():
        h.close()


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--src", required=True, type=Path)
    a.add_argument("--key-file", required=True, type=Path)
    a.add_argument("--out", required=True, type=Path)
    a.add_argument("--results-out", type=Path)
    a = a.parse_args()
    p = make_pseudonymizer(a.key_file.read_text().strip().encode())
    d, o = a.src / "data", a.out

    split_osv(d / "npm" / "osv_npm_vulnerabilities_filtered.csv", o / "osv")
    for name in ("npm_metadata.jsonl", "npm_control_maintainers.jsonl"):
        jsonl(d / "npm" / name, o / "ecosyste_ms" / name, p)
    jsonl(d / "ecosyste_ms" / "maintainers_backfill.jsonl", o / "ecosyste_ms" / "maintainers_backfill.jsonl", p)
    shutil.copy(d / "ecosyste_ms" / "dependents_backfill.jsonl", o / "ecosyste_ms" / "dependents_backfill.jsonl")
    for eco in ("pypi", "crates", "rubygems"):
        jsonl(d / "cross_ecosystem" / f"{eco}_maintainers.jsonl", o / "ecosyste_ms" / "cross_ecosystem" / f"{eco}_maintainers.jsonl", p)
    (o / "deps_dev").mkdir(parents=True, exist_ok=True)
    shutil.copy(d / "npm" / "deps_dev_data.jsonl", o / "deps_dev" / "deps_dev_data.jsonl")

    if a.results_out:
        for name in ("projection_stats", "twofa_envelope_curve", "wcte_account_seeded", "wcte_control_account_seeded"):
            f = a.results_out / "npm" / f"{name}.json"
            f.write_text(json.dumps(walk(json.loads(f.read_text(encoding="utf-8")), p), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
