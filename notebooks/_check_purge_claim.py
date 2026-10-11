import pandas as pd, json, sys
sys.path.append('../scripts')
from constants import CUTOFF_DATE

osv_df = pd.read_csv('../data/npm/osv_npm_vulnerabilities_filtered.csv')
mask = osv_df['osv_id'].str.startswith('MAL-', na=False) | osv_df['aliases'].str.contains('MAL-', na=False)
osv_df = osv_df[mask].copy()
print('OSV MAL entries (rows):', len(osv_df))
print('OSV MAL unique packages:', osv_df['package'].nunique())

npm_meta = {}
with open('../data/npm/npm_metadata.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        d = json.loads(line)
        npm_meta[d['package']] = d
print('npm_meta packages:', len(npm_meta))

osv_pkgs = set(osv_df['package'])
missing = [p for p in osv_pkgs if p not in npm_meta]
print('OSV packages missing from npm_meta:', len(missing), f'({len(missing)/len(osv_pkgs)*100:.2f}%)')

# packages in npm_meta with usable version timestamps (>=1 real version time)
def nver(d):
    t = d.get('time', {})
    return sum(1 for v in t if v not in ('created', 'modified'))
nv = {p: nver(d) for p, d in npm_meta.items()}
import numpy as np
arr = np.array(list(nv.values()))
print('npm_meta packages with >=1 version timestamp:', int((arr >= 1).sum()))
print('npm_meta packages with 0 version timestamps:', int((arr == 0).sum()))

# OSV-flagged packages present in npm_meta with version timestamps
osv_with_time = sum(1 for p in osv_pkgs if p in npm_meta and nv[p] >= 1)
print('OSV packages present AND with version times:', osv_with_time, f'({osv_with_time/len(osv_pkgs)*100:.2f}%)')

# how many packages actually entered the gamma fit (approx: final_df + censored)
# final_df = packages with a matched affected version OR created-fallback
has_created = sum(1 for p, d in npm_meta.items() if isinstance(d.get('time', {}).get('created'), str))
print('npm_meta packages with created timestamp:', has_created)
