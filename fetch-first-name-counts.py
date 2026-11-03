"""
Download first-name frequency files:

- SSA (US Social Security Administration) national baby names, CC0:
  every first name given to at least 5 babies in a year, per year from
  1880. Covers international names that are newly popular in the
  Netherlands (Mason, Hailey, Millie).
  -> data/raw/ssa/names.zip

- Statbel (Statistics Belgium) first names of the total population by
  municipality, CC BY 4.0 ("Source: Statbel"): names with at least 5
  bearers per municipality, men and women. Covers Dutch-language names,
  including recent ones, that Dutch sources miss.
  -> data/raw/statbel/TA_POP_MALE_<year>.zip, TA_POP_FEMALE_<year>.zip

Files already present are not downloaded again.

Usage:
    python fetch-first-name-counts.py [--statbel-year 2026]
"""

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

USER_AGENT = (
    "dutch-opendata-name-reader/1.0 "
    "(https://github.com/AmsterdamUMC/dutch-opendata-name-reader)"
)
SSA_URL = "https://www.ssa.gov/oact/babynames/names.zip"
STATBEL_URL = (
    "https://statbel.fgov.be/sites/default/files/files/opendata/"
    "Voornamen%20bevolking%20per%20gemeente/TA_POP_{sex}_{year}.zip"
)


def download(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"  {dest} already present")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f)
    except Exception as e:
        print(f"    failed: {e}", file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return
    tmp.replace(dest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--statbel-year", type=int, default=2026,
                    help="year of the Statbel file (the latest one on statbel.fgov.be)")
    args = ap.parse_args()
    out = Path(args.out)

    print("SSA baby names:")
    download(SSA_URL, out / "ssa" / "names.zip")
    print(f"Statbel first names {args.statbel_year}:")
    for sex in ("MALE", "FEMALE"):
        download(STATBEL_URL.format(sex=sex, year=args.statbel_year),
                 out / "statbel" / f"TA_POP_{sex}_{args.statbel_year}.zip")


if __name__ == "__main__":
    main()
