#!/usr/bin/env python3
"""Merge npm_metadata.jsonl with ecosyste.ms recoveries, deduplicate, output unified dataset."""
import json
from pathlib import Path
from collections import defaultdict

base = Path(__file__).parent.parent

npm_meta = base / 'data' / 'npm' / 'npm_metadata.jsonl'
maint_backfill = base / 'data' / 'ecosyste_ms' / 'maintainers_backfill.jsonl'
deps_backfill = base / 'data' / 'ecosyste_ms' / 'dependents_backfill.jsonl'
output = base / 'data' / 'npm' / 'npm_metadata_merged.jsonl'

print("Loading maintainers backfill...")
maint_map = {}
with open(maint_backfill) as f:
    for line in f:
        rec = json.loads(line)
        pkg = rec['package']
        logins = rec.get('maintainers', [])
        if logins:
            maint_map[pkg] = logins

print(f"Loaded {len(maint_map)} maintainers from backfill")

print("Loading dependents backfill...")
deps_map = {}
with open(deps_backfill) as f:
    for line in f:
        rec = json.loads(line)
        pkg = rec['package']
        deps = rec.get('dependents', [])
        deps_map[pkg] = {'dependents': deps, 'truncated': rec.get('truncated', False), 'raw_count': rec.get('raw_count')}

print(f"Loaded {len(deps_map)} dependents from backfill")

print("Merging and deduplicating...")
seen = set()
dedup_count = 0
output.parent.mkdir(parents=True, exist_ok=True)

with open(output, 'w') as out:
    with open(npm_meta) as f:
        for line_num, line in enumerate(f, 1):
            rec = json.loads(line)
            pkg = rec['package']

            # Deduplicate: skip if we've already written this package
            if pkg in seen:
                dedup_count += 1
                continue
            seen.add(pkg)

            # Fill in missing maintainers from backfill
            if not rec.get('maintainers') and pkg in maint_map:
                rec['maintainers'] = maint_map[pkg]

            # Add dependents from backfill (always)
            if pkg in deps_map:
                rec['dependents'] = deps_map[pkg]['dependents']
                if deps_map[pkg]['truncated']:
                    rec['dependents_truncated'] = True
                    rec['dependents_raw_count'] = deps_map[pkg]['raw_count']
            else:
                rec['dependents'] = []

            out.write(json.dumps(rec) + '\n')

            if line_num % 50000 == 0:
                print(f"  Processed {line_num}...")

print(f"Wrote {line_num - dedup_count} unique packages to {output}")
print(f"Deduplicated {dedup_count} records")
print(f"  Maintainers recovered: {sum(1 for p in seen if p in maint_map)} packages")
print(f"  Dependents added: {sum(1 for p in seen if p in deps_map)} packages")
