import pandas as pd
from pathlib import Path
from constants import CUTOFF_DATE

def filter_dataset(cutoff_date):
    base = Path(__file__).parent.parent
    src = base / "data" / "npm" / "osv_npm_vulnerabilities.csv"
    dst = base / "data" / "npm" / "osv_npm_vulnerabilities_filtered.csv"

    if not src.exists():
        print(f"File {src} not found.")
        return

    df = pd.read_csv(src)
    n = len(df)
    df['published'] = pd.to_datetime(df['published'], format='ISO8601', errors='coerce', utc=True)
    nat_count = df['published'].isna().sum()
    if nat_count > 0:
        print(f"Warning: {nat_count} rows had unparseable dates and will be dropped.")
    df = df.dropna(subset=['published'])
    cutoff = pd.to_datetime(cutoff_date, utc=True)
    df = df[df['published'] <= cutoff]
    df.to_csv(dst, index=False)
    print(f"Filtered records from {n} down to {len(df)} using cutoff {cutoff_date}.")
    print(f"Saved to {dst}")

if __name__ == "__main__":
    filter_dataset(CUTOFF_DATE)
