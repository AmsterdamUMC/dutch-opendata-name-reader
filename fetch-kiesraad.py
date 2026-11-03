"""
Download Kiesraad candidate lists from data.overheid.nl (CC0) into
data/raw/kiesraad/<dataset>/.

Finds the election datasets through the data.overheid.nl CKAN API
(datasets whose title starts with "verkiezingsuitslag") and, per
dataset, downloads the candidate list: a candidate CSV if there is one,
otherwise a candidate JSON, otherwise the EML zip (which contains the
candidate lists as EML 230). Files already present are not downloaded
again.

Usage:
    python fetch-kiesraad.py                 # all election datasets found
    python fetch-kiesraad.py --list          # only show what would be downloaded
    python fetch-kiesraad.py --dataset verkiezingsuitslagen-gemeenteraad-2022
"""

import argparse
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://data.overheid.nl/data/api/3/action"
USER_AGENT = (
    "dutch-opendata-name-reader/1.0 "
    "(https://github.com/AmsterdamUMC/dutch-opendata-name-reader)"
)
TITLE_RE = re.compile(r"^verkiezingsuitslag", re.IGNORECASE)


def get_json(action: str, **params) -> dict:
    url = f"{API}/{action}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if not data.get("success"):
        raise RuntimeError(f"{action} failed: {data.get('error')}")
    return data["result"]


def find_datasets() -> list[dict]:
    datasets, start, rows = [], 0, 100
    while True:
        result = get_json("package_search", q="verkiezingsuitslag", rows=rows, start=start)
        datasets += result["results"]
        start += rows
        if start >= result["count"]:
            break
    return sorted(
        (d for d in datasets if TITLE_RE.match(d.get("title", ""))),
        key=lambda d: d["name"],
    )


def pick_resource(dataset: dict) -> dict | None:
    """The candidate CSV, else candidate JSON, else the EML zip."""
    resources = dataset.get("resources", [])

    def text(r):
        return f"{r.get('name', '')} {r.get('url', '')}".lower()

    def fmt(r):
        return (r.get("format") or Path(urllib.parse.urlparse(r.get("url", "")).path).suffix).lower().lstrip(".")

    for wanted in ("csv", "json"):
        for r in resources:
            if "kandidat" in text(r) and wanted in fmt(r):
                return r
    for r in resources:
        if "eml" in text(r) and ("zip" in fmt(r) or text(r).endswith(".zip")):
            return r
    return None


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp, open(tmp, "wb") as f:
        shutil.copyfileobj(resp, f)
    tmp.replace(dest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw/kiesraad")
    ap.add_argument("--dataset", action="append",
                    help="dataset id (slug) on data.overheid.nl; repeatable. "
                         "Default: all datasets titled 'verkiezingsuitslag...'")
    ap.add_argument("--list", action="store_true", help="show the files without downloading")
    args = ap.parse_args()

    if args.dataset:
        datasets = [get_json("package_show", id=d) for d in args.dataset]
    else:
        datasets = find_datasets()
    print(f"{len(datasets)} election dataset(s)")

    out = Path(args.out)
    missing = []
    for d in datasets:
        r = pick_resource(d)
        if r is None:
            missing.append(d["name"])
            print(f"  - {d['name']}: no candidate list found")
            continue
        url = r["url"]
        dest = out / d["name"] / Path(urllib.parse.urlparse(url).path).name
        if args.list:
            print(f"  {d['name']}: {r.get('name', '')} -> {url}")
        elif dest.exists():
            print(f"  {d['name']}: already present")
        else:
            print(f"  {d['name']}: downloading {dest.name}")
            try:
                download(url, dest)
            except Exception as e:  # keep going with the other datasets
                print(f"    failed: {e}", file=sys.stderr)

    if missing:
        print(f"\nNo candidate list in {len(missing)} dataset(s); these are skipped.")


if __name__ == "__main__":
    main()
