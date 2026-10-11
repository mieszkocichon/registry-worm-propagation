import pandas as pd
import json
import numpy as np
import matplotlib.pyplot as plt
from lifelines import KaplanMeierFitter, WeibullFitter, LogNormalFitter, ExponentialFitter

import sys
sys.path.append('../scripts')
from constants import CUTOFF_DATE

# Load OSV
osv_df = pd.read_csv('../data/npm/osv_npm_vulnerabilities_filtered.csv')
mask = osv_df['osv_id'].str.startswith('MAL-', na=False) | osv_df['aliases'].str.contains('MAL-', na=False)
osv_df = osv_df[mask].copy()
osv_df['osv_published'] = pd.to_datetime(osv_df['published'], utc=True)
cutoff_date = pd.to_datetime(CUTOFF_DATE, utc=True)

# Load NPM Metadata
npm_meta = {}
with open('../data/npm/npm_metadata.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        d = json.loads(line)
        npm_meta[d['package']] = d

print("Calculating true vectorized Dwell Time with Right-Censoring...")

# Fast list of tuples construction avoids wide-matrix memory explosion
time_records = []
for pkg, d in npm_meta.items():
    if 'time' in d:
        for v, pub_time in d['time'].items():
            if v not in ('created', 'modified') and isinstance(pub_time, str):
                time_records.append({'package': pkg, 'version': v, 'published': pub_time})

times_df = pd.DataFrame.from_records(time_records)
if not times_df.empty:
    times_df['published_dt'] = pd.to_datetime(times_df['published'], utc=True, errors='coerce')

times_df['norm_version'] = times_df['version'].str.lstrip('vV')

# Explode OSV versions
osv_df['versions_list'] = osv_df['versions_affected'].fillna('').apply(lambda x: [v.strip() for v in str(x).split(',') if v.strip()])
pure_malware = osv_df[osv_df['versions_list'].apply(len) == 0].copy()
osv_exploded = osv_df.explode('versions_list')
osv_exploded['norm_version'] = osv_exploded['versions_list'].str.lstrip('vV')

# Merge versioned malware with times_df using normalized versions
merged = pd.merge(osv_exploded, times_df, on=['package', 'norm_version'], how='inner')

unmatched_versions = len(osv_exploded) - len(merged)
if len(osv_exploded) > 0:
    print(f"Versions dropped due to mismatch: {unmatched_versions} ({(unmatched_versions/len(osv_exploded))*100:.2f}%)")
    if unmatched_versions > 0:
        unmatched_df = osv_exploded[~osv_exploded.index.isin(merged.index)]
        print("Sample of dropped versions:", unmatched_df[['package', 'versions_list']].head().to_dict(orient='records'))

earliest_versions = merged.groupby('package')['published_dt'].min().reset_index()

earliest_versions['event_source'] = 'version'

# For pure malware, fallback to 'created'
pure_times = [{'package': pkg, 'published': npm_meta[pkg]['time']['created']}
              for pkg in pure_malware['package']
              if pkg in npm_meta and 'created' in npm_meta[pkg].get('time', {})
              and isinstance(npm_meta[pkg]['time']['created'], str)]
pure_times_df = pd.DataFrame.from_records(pure_times)
if not pure_times_df.empty:
    pure_times_df['published_dt'] = pd.to_datetime(pure_times_df['published'], utc=True, errors='coerce')
    pure_times_df['event_source'] = 'created_fallback'

# Combine
all_earliest = pd.concat([earliest_versions, pure_times_df])
final_df = pd.merge(osv_df[['package', 'osv_published']], all_earliest, on='package', how='inner')

# Calculate dwell time for observed events
final_df['dwell_days'] = (final_df['osv_published'] - final_df['published_dt']).dt.total_seconds() / 86400.0
final_df['event_observed'] = 1

# Investigate negative dwell times explicitly
negatives_df = final_df[final_df['dwell_days'] < 0]
if not negatives_df.empty:
    print(f"Investigating {len(negatives_df)} packages with negative dwell times (Pre-disclosure/Timezone drift):")
    print(negatives_df[['package', 'osv_published', 'published_dt', 'dwell_days']].head())

final_df_clamped = final_df.copy()
final_df_clamped.loc[final_df_clamped['dwell_days'] <= 0, 'dwell_days'] = 1e-5

final_df_dropped = final_df[final_df['dwell_days'] >= 0].copy()

# Calculate distinct sources of attrition
missing_meta_count = len([p for p in osv_df['package'].unique() if p not in npm_meta])
total_attrition = len(osv_df) - len(all_earliest)
zero_match_count = total_attrition - missing_meta_count
print(f"Total package attrition: {total_attrition} (Missing metadata completely: {missing_meta_count}, Zero version matches: {zero_match_count})")

# Right Censoring for packages in extended portfolio NOT in OSV
osv_packages = set(osv_df['package'])
censored_times = [{'package': pkg, 'published': npm_meta[pkg]['time']['created']}
                  for pkg in npm_meta
                  if pkg not in osv_packages and 'created' in npm_meta[pkg].get('time', {})
                  and isinstance(npm_meta[pkg]['time']['created'], str)]
censored_df = pd.DataFrame.from_records(censored_times)
if not censored_df.empty:
    censored_df['pub_dt'] = pd.to_datetime(censored_df['published'], utc=True, errors='coerce')
    censored_df['dwell_days'] = (cutoff_date - censored_df['pub_dt']).dt.total_seconds() / 86400.0
    pre_drop_count = len(censored_df)
    censored_df = censored_df[censored_df['dwell_days'] >= 0].copy()
    if pre_drop_count > len(censored_df):
        print(f"Warning: Dropped {pre_drop_count - len(censored_df)} right-censored packages due to negative dwell times (created > cutoff_date).")
    censored_df['event_observed'] = 0

combined_clamped = pd.concat([final_df_clamped[['package', 'dwell_days', 'event_observed']], censored_df[['package', 'dwell_days', 'event_observed']]])
combined_dropped = pd.concat([final_df_dropped[['package', 'dwell_days', 'event_observed']], censored_df[['package', 'dwell_days', 'event_observed']]])

print(f"Total OSV entries starting: {len(osv_df)}")
print(f"Dropped due to missing metadata: {missing_meta_count}")

if len(combined_clamped) == 0:
    raise ValueError("CRITICAL ERROR: No valid dwell times found! Cannot compute survival curve.")

def fit_and_compare(df, label):
    dwell = df['dwell_days'].values
    events = df['event_observed'].values

    ef = ExponentialFitter().fit(dwell, events)
    wf = WeibullFitter().fit(dwell, events)
    lnf = LogNormalFitter().fit(dwell, events)
    scores = {
        'Exponential': (ef, ef.AIC_),
        'Weibull': (wf, wf.AIC_),
        'LogNormal': (lnf, lnf.AIC_)
    }

    best_name = min(scores.keys(), key=lambda k: scores[k][1])

    print(f"\n[{label}] AIC Scores:")
    print(f"  Exponential: {ef.AIC_:.2f}")
    print(f"  Weibull:     {wf.AIC_:.2f}")
    print(f"  LogNormal:   {lnf.AIC_:.2f}")
    print(f"  -> Best fit by AIC: {best_name}")

    # Structural constraint: the branching-process SIR simulator (simulation_engine.py)
    # models recovery as a memoryless per-step Bernoulli draw, i.e. a constant hazard
    # rate. That is only a faithful reduction of the Exponential fit. If Weibull or
    # LogNormal wins on AIC (time-varying hazard), collapsing it to a single scalar
    # gamma = 1/median_survival would silently reintroduce the memoryless assumption
    # the AIC comparison was meant to test against - so gamma is always taken from the
    # Exponential fit regardless of which model wins. The AIC table above is reported
    # for descriptive/diagnostic purposes only; it does not feed the simulation.
    gamma_val = 1.0 / ef.lambda_
    if best_name != 'Exponential':
        print(f"  -> NOTE: {best_name} beat Exponential on AIC (time-varying hazard), "
              f"but gamma is still taken from the Exponential fit (constant-hazard "
              f"constraint of the memoryless SIR simulator).")
    print(f"  -> Derived Gamma for SIR (Exponential only): {gamma_val}")
    return gamma_val

gamma_clamped = fit_and_compare(combined_clamped.dropna(subset=['dwell_days']), 'Clamped')
gamma_dropped = fit_and_compare(combined_dropped.dropna(subset=['dwell_days']), 'Dropped')
print(f"Gamma Delta (Clamped - Dropped): {gamma_clamped - gamma_dropped}")

dwell_times = combined_clamped['dwell_days'].dropna().values
events = combined_clamped.dropna(subset=['dwell_days'])['event_observed'].values

kmf = KaplanMeierFitter()
kmf.fit(durations=dwell_times, event_observed=events)
plt.figure(figsize=(10, 6))
kmf.plot_survival_function()
plt.title('Kaplan-Meier Survival Curve (With Right-Censoring)')
plt.savefig('../figures/survival_curve.png')
plt.show()

with open('../data/npm/gamma_param.txt', 'w') as f:
    f.write(str(gamma_clamped))
with open('../data/npm/gamma_dropped_param.txt', 'w') as f:
    f.write(str(gamma_dropped))

