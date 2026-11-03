"""
Build common-dutch-firstnames.txt and common-dutch-surnames.txt from
Kiesraad candidate lists and Wikidata, plus SSA and Statbel first-name
counts (see README.md for the sources).

A name is kept when the number of distinct people carrying it, summed
over the Dutch sources (Kiesraad and Dutch Wikidata), is at least
--min-persons (default 2). This replaces a population frequency, which
neither source provides, and keeps out names that only a single person
in the data has.

A first name is also kept when it was given to at least --ssa-min-births
(default 200) babies in the US since --ssa-from-year (default 1940), or
when at least --statbel-min-persons (default 10) people in Belgium carry
it. These thresholds are higher because both are population-wide counts
that include many rare names.

A first name that only the SSA supports and that is also a common
English or Dutch word ("Even", "York", "Trust", "Haven") is dropped. In
scanned code and text such names are nearly always the word ("Even
Bos", "Los Angeles", "Bank Trust"). Word frequencies come from the
wordfreq package.

Usage:
    python build-name-lists.py [--kiesraad data/raw/kiesraad]
                               [--wikidata data/raw/wikidata]
                               [--ssa data/raw/ssa/names.zip]
                               [--statbel data/raw/statbel]
                               [--min-persons 2] [--ssa-min-births 200]
                               [--ssa-from-year 1940]
                               [--statbel-min-persons 10] [--out output]
"""

import argparse
import csv
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import name_lists as nl


def write_counts(path: Path, sources: dict[str, Counter]) -> None:
    """Per-name counts per source, for checking thresholds (not published)."""
    names = sorted(set().union(*sources.values()))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["name", *sources, "total"])
        for n in names:
            row = [sources[s].get(n, 0) for s in sources]
            w.writerow([n, *row, sum(row)])


@contextmanager
def step(label: str):
    """Print a step's label before it runs and its duration after."""
    print(f"{label}...", flush=True)
    start = time.monotonic()
    yield
    print(f"  done in {time.monotonic() - start:.1f}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kiesraad", default="data/raw/kiesraad")
    ap.add_argument("--wikidata", default="data/raw/wikidata")
    ap.add_argument("--ssa", default="data/raw/ssa/names.zip")
    ap.add_argument("--statbel", default="data/raw/statbel")
    ap.add_argument("--min-persons", type=int, default=2)
    ap.add_argument("--ssa-min-births", type=int, default=200)
    ap.add_argument("--ssa-from-year", type=int, default=1940)
    ap.add_argument("--statbel-min-persons", type=int, default=10)
    ap.add_argument("--out", default="output")
    args = ap.parse_args()

    kiesraad_dir = Path(args.kiesraad)
    wikidata_dir = Path(args.wikidata)

    with step("Kiesraad"):
        if kiesraad_dir.exists():
            k_first, k_sur, n_people = nl.count_kiesraad(nl.read_kiesraad(kiesraad_dir, verbose=True))
            print(f"  {n_people} distinct candidates, "
                  f"{len(k_first)} first names, {len(k_sur)} surnames")
        else:
            k_first, k_sur = Counter(), Counter()
            print(f"  {kiesraad_dir} not found, skipped")

    with step("Wikidata"):
        w_first = nl.read_wikidata_tsv(wikidata_dir / "given-names.tsv", "first")
        w_sur = nl.read_wikidata_tsv(wikidata_dir / "family-names.tsv", "surname")
        print(f"  {len(w_first)} first names, {len(w_sur)} surnames")
    with step(f"SSA (since {args.ssa_from_year})"):
        ssa = nl.read_ssa(Path(args.ssa), from_year=args.ssa_from_year)
        print(f"  {len(ssa)} first names")
    with step("Statbel"):
        statbel = nl.read_statbel(Path(args.statbel))
        print(f"  {len(statbel)} first names")

    supported = (set(nl.select(k_first, w_first, min_persons=args.min_persons))
                 | set(nl.select(statbel, min_persons=args.statbel_min_persons)))
    ssa_only = set(nl.select(ssa, min_persons=args.ssa_min_births)) - supported
    ssa_words = {n for n in ssa_only if nl.is_common_word(n)}
    first = sorted(supported | (ssa_only - ssa_words))
    print(f"  {len(ssa_words)} SSA-only first names dropped as common words")
    sur = nl.select(k_sur, w_sur, min_persons=args.min_persons)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "common-dutch-firstnames.txt").write_text("\n".join(first) + "\n", encoding="utf-8")
    (out / "common-dutch-surnames.txt").write_text("\n".join(sur) + "\n", encoding="utf-8")
    print(f"\nWrote {len(first)} first names and {len(sur)} surnames to {out}/ "
          f"(min {args.min_persons} persons; first names also from SSA/Statbel)")

    counts_dir = Path("data")
    counts_dir.mkdir(exist_ok=True)
    write_counts(counts_dir / "counts-firstnames.tsv", {"kiesraad": k_first, "wikidata": w_first, "ssa": ssa, "statbel": statbel})
    write_counts(counts_dir / "counts-surnames.tsv", {"kiesraad": k_sur, "wikidata": w_sur})
    print(f"Per-source counts in {counts_dir}/counts-*.tsv")


if __name__ == "__main__":
    main()
