"""
Fetch given names (P735) and family names (P734) from Wikidata, with
the number of people per name. Wikidata is CC0.

Writes data/raw/wikidata/given-names.tsv and family-names.tsv
(columns: name, persons, item), for people with Dutch citizenship.

Two steps per list, to stay under the query service's 60-second limit:
one query counts people per name item, then labels are fetched in
batches. If a counting query times out, it is split into ten parts by
the last digit of the person's item id; the parts hold disjoint sets of
people, so their counts add up exactly.

Usage:
    python fetch-wikidata.py [--out data/raw/wikidata]
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ENDPOINT = "https://query.wikidata.org/sparql"
# The query service requires a descriptive User-Agent with a contact.
USER_AGENT = (
    "dutch-opendata-name-reader/1.0 "
    "(https://github.com/AmsterdamUMC/dutch-opendata-name-reader)"
)
# Netherlands (country) and Kingdom of the Netherlands: both are used as
# citizenship on Wikidata.
NL_COUNTRIES = ["Q55", "Q29999"]
# Partitions used when an unsplit count query times out: people by the
# last digit of their item id.
DIGIT_PARTITIONS = [f'FILTER(STRENDS(STR(?p), "{d}"))' for d in range(10)]
LABEL_BATCH = 300
# A label is used only if it is written in Latin script.
LATIN_RE = re.compile(r"^[A-Za-zÀ-ɏ' \-’]+$")


def sparql(query: str, retries: int = 4) -> list[dict]:
    body = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            ENDPOINT, data=body,
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)["results"]["bindings"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = int(e.headers.get("Retry-After", 0) or 0) or 10 * (attempt + 1)
                print(f"    HTTP {e.code}, retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                print(f"    {e}, retrying", file=sys.stderr)
                time.sleep(10 * (attempt + 1))
                continue
            raise
    return []


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def count_query(prop: str, countries: list[str], extra: str = "") -> str:
    values = " ".join(f"wd:{c}" for c in countries)
    return f"""
SELECT ?item (COUNT(DISTINCT ?p) AS ?n) WHERE {{
  VALUES ?country {{ {values} }}
  ?p wdt:P27 ?country ; wdt:{prop} ?item .
  {extra}
}} GROUP BY ?item
"""


def count_people(prop: str, countries: list[str]) -> Counter:
    try:
        rows = sparql(count_query(prop, countries), retries=1)
        return Counter({qid(r["item"]["value"]): int(r["n"]["value"]) for r in rows})
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"  count query failed ({e}); splitting into 10 parts", file=sys.stderr)
    counts = Counter()
    for i, part in enumerate(DIGIT_PARTITIONS, 1):
        rows = sparql(count_query(prop, countries, part))
        counts.update({qid(r["item"]["value"]): int(r["n"]["value"]) for r in rows})
        print(f"    part {i}/10")
    return counts


def fetch_labels(items: list[str]) -> dict[str, str]:
    """Native label (P1705) if Latin, else the Dutch, multilingual or English label."""
    labels = {}
    for i in range(0, len(items), LABEL_BATCH):
        batch = " ".join(f"wd:{q}" for q in items[i:i + LABEL_BATCH])
        rows = sparql(f"""
SELECT ?item ?native ?nl ?mul ?en WHERE {{
  VALUES ?item {{ {batch} }}
  OPTIONAL {{ ?item wdt:P1705 ?native . }}
  OPTIONAL {{ ?item rdfs:label ?nl . FILTER(LANG(?nl) = "nl") }}
  OPTIONAL {{ ?item rdfs:label ?mul . FILTER(LANG(?mul) = "mul") }}
  OPTIONAL {{ ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }}
}}""")
        for r in rows:
            q = qid(r["item"]["value"])
            for key in ("native", "nl", "mul", "en"):
                val = r.get(key, {}).get("value", "")
                if val and LATIN_RE.match(val):
                    # Prefer a native label over a language label already chosen.
                    if q not in labels or key == "native":
                        labels[q] = val
                    break
        print(f"    labels {min(i + LABEL_BATCH, len(items))}/{len(items)}")
        time.sleep(1)  # be polite to the public endpoint
    return labels


def fetch_list(out: Path, prop: str, countries: list[str]) -> None:
    """Count people per name and write the labelled names."""
    print(f"{out.name} ({prop}): counting people per name...")
    counts = count_people(prop, countries)
    print(f"  {len(counts)} name items, {sum(counts.values())} person-name pairs")
    labels = fetch_labels(sorted(counts))
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["name", "persons", "item"])
        for q, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            if q in labels:
                w.writerow([labels[q], n, q])
    print(f"  wrote {out} ({len(labels)} labelled)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw/wikidata")
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    fetch_list(out_dir / "given-names.tsv", "P735", NL_COUNTRIES)
    fetch_list(out_dir / "family-names.tsv", "P734", NL_COUNTRIES)


if __name__ == "__main__":
    main()
