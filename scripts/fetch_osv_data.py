import json
import zipfile
import requests
import pandas as pd
from pathlib import Path

def download_osv_npm_data(dest_dir):
    url = "https://osv-vulnerabilities.storage.googleapis.com/npm/all.zip"
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "npm_all.zip"

    print(f"Downloading OSV npm data from {url}...")
    r = requests.get(url, stream=True)
    r.raise_for_status()
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    print("Extracting zip file...")
    extract_dir = dest_dir / "osv_npm"
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(extract_dir)
    print(f"Extracted OSV data to {extract_dir}")
    return extract_dir

def parse_osv_data(osv_dir):
    osv_dir = Path(osv_dir)
    records = []
    for idx, f in enumerate(osv_dir.glob("*.json")):
        if idx > 0 and idx % 1000 == 0:
            print(f"Parsed {idx} files...")
        with open(f, "r", encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError:
                continue
        osv_id = data.get("id")
        published = data.get("published")
        modified = data.get("modified")
        aliases = data.get("aliases", [])
        for affected in data.get("affected", []):
            pkg = affected.get("package", {})
            if pkg.get("ecosystem") != "npm":
                continue
            records.append({
                "osv_id": osv_id,
                "package": pkg.get("name"),
                "published": published,
                "modified": modified,
                "aliases": ",".join(aliases),
                "versions_affected": ",".join(affected.get("versions", []))
            })

    return pd.DataFrame(records)

if __name__ == "__main__":
    base = Path(__file__).parent.parent
    data_dir = base / "data" / "npm"
    extract_dir = download_osv_npm_data(data_dir)
    df = parse_osv_data(extract_dir)
    out = data_dir / "osv_npm_vulnerabilities.csv"
    df.to_csv(out, index=False)
    print(f"Saved {len(df)} records to {out}")
