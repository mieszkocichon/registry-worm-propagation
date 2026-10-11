import pandas as pd
import numpy as np

def calculate_dwell_time(osv_df, npm_meta):
    cutoff_date = osv_df['osv_published'].max()
    
    meta_times = []
    for pkg, data in npm_meta.items():
        for v, t in data.get('time', {}).items():
            if v not in ('created', 'modified') and isinstance(t, str):
                meta_times.append({'package': pkg, 'version': v, 'published_dt': pd.to_datetime(t, utc=True, errors='coerce')})
    times_df = pd.DataFrame(meta_times)
    
    osv_df['versions_list'] = osv_df['versions_affected'].fillna('').apply(lambda x: [v.strip() for v in str(x).split(',') if v.strip()])
    pure_malware = osv_df[osv_df['versions_list'].apply(len) == 0].copy()
    osv_exploded = osv_df.explode('versions_list')
    osv_exploded['norm_version'] = osv_exploded['versions_list'].str.lstrip('vV')
    times_df['norm_version'] = times_df['version'].str.lstrip('vV')
    
    merged = pd.merge(osv_exploded, times_df, on=['package', 'norm_version'], how='inner')
    if merged.empty:
        earliest_versions = pd.DataFrame(columns=['package', 'published_dt'])
    else:
        earliest_versions = merged.groupby('package')['published_dt'].min().reset_index()
        
    pure_times = []
    for pkg in pure_malware['package']:
        if pkg in npm_meta and 'created' in npm_meta[pkg].get('time', {}):
            t = npm_meta[pkg]['time']['created']
            if isinstance(t, str):
                pure_times.append({'package': pkg, 'published_dt': pd.to_datetime(t, utc=True, errors='coerce')})
    pure_times_df = pd.DataFrame(pure_times)
    
    all_earliest = pd.concat([earliest_versions, pure_times_df])
    final_df = pd.merge(osv_df[['package', 'osv_published']], all_earliest, on='package', how='inner')
    
    final_df['dwell_days'] = (final_df['osv_published'] - final_df['published_dt']).dt.total_seconds() / 86400.0
    final_df['event_observed'] = 1
    final_df.loc[final_df['dwell_days'] < 0, 'dwell_days'] = 0.0
    
    return final_df

def test_dwell_time_logic():
    osv_df = pd.DataFrame({
        'osv_id': ['MAL-1', 'MAL-2', 'MAL-3'],
        'package': ['pkgA', 'pkgB', 'pkgC'],
        'published': ['2023-01-10T00:00:00Z', '2023-01-15T00:00:00Z', '2023-01-05T00:00:00Z'],
        'versions_affected': ['1.0.0', '', '1.0.0']
    })
    osv_df['osv_published'] = pd.to_datetime(osv_df['published'], utc=True)
    
    npm_meta = {
        'pkgA': {'package': 'pkgA', 'time': {'1.0.0': '2023-01-01T00:00:00Z'}},
        'pkgB': {'package': 'pkgB', 'time': {'created': '2023-01-05T00:00:00Z'}},
        'pkgC': {'package': 'pkgC', 'time': {'1.0.0': '2023-01-10T00:00:00Z'}} # Negative dwell time
    }
    
    res = calculate_dwell_time(osv_df, npm_meta)
    res = res.set_index('package')
    
    assert res.loc['pkgA', 'dwell_days'] == 9.0
    assert res.loc['pkgB', 'dwell_days'] == 10.0
    assert res.loc['pkgC', 'dwell_days'] == 0.0 

if __name__ == "__main__":
    test_dwell_time_logic()
    print("All dwell time logic tests passed.")
