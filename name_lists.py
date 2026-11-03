"""
Shared logic for building the Dutch first name and surname lists from
open data: reading the sources, normalising names the way the detection
tokenises text, filtering, and combining counts.

Sources:
- Kiesraad candidate lists (EML, CSV or JSON, optionally inside zip
  files), from data.overheid.nl. CC0.
- Wikidata given names (P735) and family names (P734) of people with
  Dutch citizenship, fetched by fetch-wikidata.py into TSV files. CC0.
- First names only: SSA national baby names (CC0) and Statbel first
  names of the total population (CC BY 4.0), fetched by
  fetch-first-name-counts.py.

The output lists are matched by personal_info.py in
org-security-workflows. That matcher compares list entries
case-sensitively against the space-joined tokens it extracts with
`word_token`, so every entry here is normalised with the same regex
(WORD_TOKEN_RE). An entry that does not survive that tokenisation
unchanged would never match anything.
"""

import csv
import io
import json
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from typing import Iterator, NamedTuple

from wordfreq import zipf_frequency

# Mirrors `word_token` in personal_info.py (org-security-workflows):
# letter runs, joined by an internal - or '. Digits, periods and a
# leading apostrophe are never part of a token.
WORD_TOKEN_RE = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)

# Typographic apostrophes are normalised to ' so "D’Souza" and
# "D'Souza" end up as the same entry.
APOSTROPHES_RE = re.compile(r"[‘’ʼ`´]")

# Leading surname words that are written in lower case in running text
# after a first name ("Jan van der Velde"). Compared after normalisation,
# so "'t" appears as "t" and "'s" as "s".
SURNAME_PREFIXES = {
    "van", "de", "der", "den", "het", "t", "te", "ter", "ten", "in", "op",
    "aan", "bij", "uit", "onder", "over", "voor", "s",
    "la", "le", "les", "du", "da", "di", "del", "della", "dos", "das",
    "do", "von", "zu", "vom", "zum", "el", "al",
}

# Entries that occur as names but, in scanned code and text, almost
# always mean something else: place-name prefixes ("Sint Maarten", "San
# Francisco", "Costa Rica", "Den Haag"), weekday abbreviations in dates
# ("Mon May 12"), month abbreviations ("Jul", "Sep"), "Min" ("Min Max"),
# the article "The" ("The Django") and font names ("Fira Sans"). Kept
# deliberately short: the detection already requires a capitalised first
# name next to a capitalised surname.
EXCLUDED_FIRST_NAMES = {
    "Sint", "Saint", "San", "Santa", "Santo", "Las", "Costa", "Sierra",
    "Den", "The", "Mon", "Thu", "Sun", "Jun", "Jul", "Sep", "Min",
}
EXCLUDED_SURNAMES = {"Sans", "Sint", "The"}


class Person(NamedTuple):
    """One candidate as read from a Kiesraad file."""
    initials: str
    first_name: str
    prefix: str
    last_name: str


# --------------------------------------------------------------------------
# Normalisation and validation
# --------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Normalise text to the space-joined tokens the matcher would extract."""
    text = unicodedata.normalize("NFC", text or "")
    text = APOSTROPHES_RE.sub("'", text)
    return " ".join(WORD_TOKEN_RE.findall(text))


def _lowercase_prefixes(words: list[str]) -> list[str]:
    """Lower-case leading surname prefixes ("Van Der Velde" -> "van der Velde")."""
    out = list(words)
    for i, w in enumerate(out[:-1]):  # the last word is never a prefix
        if w.lower() in SURNAME_PREFIXES:
            out[i] = w.lower()
        else:
            break
    return out


# A name is a common word when its word frequency in English or Dutch is
# at least this, on the Zipf scale (3 is about once per million words).
COMMON_WORD_ZIPF = 3.5


def is_common_word(name: str, zipf: float = COMMON_WORD_ZIPF) -> bool:
    """True if the name is also a common English or Dutch word ("Even", "Trust")."""
    low = name.lower()
    return zipf_frequency(low, "en") >= zipf or zipf_frequency(low, "nl") >= zipf


def is_valid_first_name(name: str) -> bool:
    return (
        len(name) > 2
        and " " not in name
        and name[0].isupper()
        and not name.isupper()
        and name not in EXCLUDED_FIRST_NAMES
    )


def is_valid_surname(name: str) -> bool:
    words = name.split()
    return (
        len(name) > 2
        and bool(words)
        and words[-1][0].isupper()
        and words[-1].lower() not in SURNAME_PREFIXES
        and not name.isupper()
        and name not in EXCLUDED_SURNAMES
    )


def first_names_from(raw: str) -> list[str]:
    """
    Valid first names in a raw first-name field. A call name can hold
    several names ("Jan Willem"); each counts as a first name, since
    the matcher only looks at the single token next to a surname.
    """
    return [w for w in normalize(raw).split() if is_valid_first_name(w)]


def surname_from(prefix: str, last_name: str) -> str:
    """Surname in natural order with lower-case prefixes: "van der Velde"."""
    words = normalize(f"{prefix or ''} {last_name or ''}").split()
    return " ".join(_lowercase_prefixes(words)) if words else ""


def surnames_from(prefix: str, last_name: str) -> list[str]:
    """
    Valid surnames for one person: the full surname plus, for a double
    surname, each part ("Smit-van Dijk" -> "Smit-van Dijk", "Smit",
    "van Dijk"), since people are often referred to by one part.
    """
    full = surname_from(prefix, last_name)
    variants = [full]
    if "-" in full:
        for part in full.split("-"):
            words = part.split()
            if words:
                variants.append(" ".join(_lowercase_prefixes(words)))
    seen, out = set(), []
    for v in variants:
        if v and v not in seen and is_valid_surname(v):
            seen.add(v)
            out.append(v)
    return out


# --------------------------------------------------------------------------
# Kiesraad readers
# --------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(elem, name: str, attr: tuple[str, str] | None = None) -> str:
    for child in elem.iter():
        if _local(child.tag) != name:
            continue
        if attr and child.get(attr[0]) != attr[1]:
            continue
        return (child.text or "").strip()
    return ""


def read_eml(data: bytes) -> Iterator[Person]:
    """
    Candidates in an EML_NL file. Candidate lists (EML 230) and result
    files (EML 510/520) both describe candidates as
    Candidate/CandidateFullName/xnl:PersonName with xnl:NameLine
    (NameType="Initials"), xnl:FirstName, xnl:NamePrefix and
    xnl:LastName. Tags are matched by local name, so the namespace
    version does not matter. Files without such elements yield nothing.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return
    for cand in root.iter():
        if _local(cand.tag) != "Candidate":
            continue
        person = next((e for e in cand.iter() if _local(e.tag) == "PersonName"), None)
        if person is None:
            continue
        last = _child_text(person, "LastName")
        if not last:
            continue
        yield Person(
            initials=_child_text(person, "NameLine", ("NameType", "Initials")),
            first_name=_child_text(person, "FirstName"),
            prefix=_child_text(person, "NamePrefix"),
            last_name=last,
        )


# Column names seen in candidate CSV/JSON exports, compared after
# lower-casing and removing spaces, underscores and hyphens.
FIELD_ALIASES = {
    "first_name": {"voornaam", "roepnaam", "firstname", "voornamen"},
    "prefix": {"tussenvoegsel", "tussenvoegsels", "voorvoegsel", "prefix", "nameprefix"},
    "last_name": {"achternaam", "lastname", "familienaam", "geslachtsnaam"},
    "initials": {"initialen", "voorletters", "initials"},
}


def _map_fields(keys) -> dict[str, str]:
    mapping = {}
    for key in keys:
        norm = re.sub(r"[\s_\-]", "", str(key).lower())
        for field, aliases in FIELD_ALIASES.items():
            if norm in aliases and field not in mapping:
                mapping[field] = key
    return mapping


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _people_from_rows(rows, mapping) -> Iterator[Person]:
    for row in rows:
        last = (row.get(mapping["last_name"]) or "").strip()
        if not last:
            continue
        yield Person(
            initials=(row.get(mapping.get("initials", ""), "") or "").strip(),
            first_name=(row.get(mapping.get("first_name", ""), "") or "").strip(),
            prefix=(row.get(mapping.get("prefix", ""), "") or "").strip(),
            last_name=last,
        )


def read_csv(data: bytes) -> Iterator[Person]:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    mapping = _map_fields(reader.fieldnames or [])
    if "last_name" not in mapping or "first_name" not in mapping:
        return
    yield from _people_from_rows(reader, mapping)


def read_json(data: bytes) -> Iterator[Person]:
    try:
        obj = json.loads(_decode(data))
    except json.JSONDecodeError:
        return
    # Accept a list of records, or a dict holding one under some key.
    if isinstance(obj, dict):
        obj = next((v for v in obj.values() if isinstance(v, list)), [])
    rows = [r for r in obj if isinstance(r, dict)] if isinstance(obj, list) else []
    if not rows:
        return
    mapping = _map_fields(rows[0].keys())
    if "last_name" not in mapping or "first_name" not in mapping:
        return
    yield from _people_from_rows(rows, mapping)


READERS = {".xml": read_eml, ".eml": read_eml, ".csv": read_csv, ".json": read_json}


def _progress(msg: str) -> None:
    """Overwrite the current terminal line with msg (only on a terminal)."""
    if sys.stderr.isatty():
        sys.stderr.write("\r\033[K" + msg[:120])
        sys.stderr.flush()


def _skip_by_name(name: str) -> bool:
    """
    EML vote-count files (EML 510, named "Telling_..." by the Kiesraad)
    hold counts per polling station and no candidate names, but make up
    most of an election zip. Skipping them by name avoids decompressing
    and parsing them at all.
    """
    return Path(name).name.lower().startswith("telling")


def _read_blob(name: str, data: bytes, where: str = "") -> Iterator[Person]:
    suffix = Path(name).suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir() and not _skip_by_name(i.filename)]
            for n, info in enumerate(infos, 1):
                _progress(f"  {where}: {n}/{len(infos)} {Path(info.filename).name}")
                yield from _read_blob(info.filename, zf.read(info), where)
    elif suffix in (".xml", ".eml"):
        # Only parse XML that can contain candidate names; a byte search
        # is far cheaper than parsing a large file that has none.
        if b"PersonName" in data:
            yield from read_eml(data)
    elif suffix in READERS:
        yield from READERS[suffix](data)


def read_kiesraad(path: Path, verbose: bool = False) -> Iterator[Person]:
    """
    All candidates in a file, or in every supported file under a
    directory. With verbose, prints a line per file with the number of
    candidates read and the time taken.
    """
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    for i, f in enumerate(files, 1):
        where = f"[{i}/{len(files)}] {f.parent.name}/{f.name}"
        start, n = time.monotonic(), 0
        for person in _read_blob(f.name, f.read_bytes(), where):
            n += 1
            yield person
        if verbose:
            _progress("")
            print(f"  {where}: {n} candidates ({time.monotonic() - start:.1f}s)", flush=True)


def count_kiesraad(people) -> tuple[Counter, Counter, int]:
    """
    Count, per name, how many distinct candidates carry it. The same
    person appears on lists in several elections; candidates are
    deduplicated on (initials, first name, prefix, last name).
    """
    unique = {
        (normalize(p.initials).replace(" ", ""), normalize(p.first_name),
         normalize(p.prefix).lower(), normalize(p.last_name))
        for p in people
    }
    first, sur = Counter(), Counter()
    for initials, fn, prefix, last in unique:
        for name in set(first_names_from(fn)):
            first[name] += 1
        for name in surnames_from(prefix, last):
            sur[name] += 1
    return first, sur, len(unique)


# --------------------------------------------------------------------------
# Wikidata
# --------------------------------------------------------------------------

def read_wikidata_tsv(path: Path, kind: str) -> Counter:
    """
    Counts from a TSV written by fetch-wikidata.py (columns: name,
    persons, item). `kind` is "first" or "surname".
    """
    counts = Counter()
    if not path.is_file():
        return counts
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            try:
                n = int(row["persons"])
            except (KeyError, ValueError):
                continue
            label = row.get("name", "")
            if kind == "first":
                for name in set(first_names_from(label)):
                    counts[name] += n
            else:
                for name in surnames_from("", label):
                    counts[name] += n
    return counts


# --------------------------------------------------------------------------
# First-name frequency files (SSA, Statbel)
# --------------------------------------------------------------------------

def _first_name_counts(pairs) -> Counter:
    """Sum (raw name, count) pairs into counts per valid, normalised first name."""
    # Sum per raw spelling first, so each distinct spelling is normalised
    # once instead of once per year or municipality.
    raw_counts = Counter()
    for raw, n in pairs:
        raw_counts[raw] += n
    counts = Counter()
    for raw, n in raw_counts.items():
        for name in set(first_names_from(raw)):
            counts[name] += n
    return counts


def read_ssa(path: Path, from_year: int = 1940) -> Counter:
    """
    Births per first name in the SSA national baby names zip (files
    yobYYYY.txt with lines "name,sex,count"), summed over boys and girls
    and over the years from `from_year`.
    """
    if not path.is_file():
        return Counter()

    def pairs():
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                m = re.fullmatch(r"yob(\d{4})\.txt", Path(info.filename).name)
                if not m or int(m.group(1)) < from_year:
                    continue
                for line in _decode(zf.read(info)).splitlines():
                    parts = line.strip().split(",")
                    if len(parts) == 3 and parts[2].isdigit():
                        yield parts[0], int(parts[2])

    return _first_name_counts(pairs())


def read_statbel(path: Path) -> Counter:
    """
    Bearers per first name in Statbel's "first names of the total
    population by municipality" files (zip or txt, pipe-separated, with
    columns TX_FST_NAME and MS_FREQUENCY), summed over municipalities
    and over all files found (men and women).
    """
    files = [path] if path.is_file() else sorted(path.glob("*")) if path.is_dir() else []

    def texts():
        for f in files:
            if f.suffix.lower() == ".zip":
                with zipfile.ZipFile(f) as zf:
                    for info in zf.infolist():
                        if info.filename.lower().endswith(".txt"):
                            yield _decode(zf.read(info))
            elif f.suffix.lower() == ".txt":
                yield _decode(f.read_bytes())

    def pairs():
        for text in texts():
            reader = csv.DictReader(io.StringIO(text), delimiter="|")
            for row in reader:
                try:
                    yield row["TX_FST_NAME"], int(row["MS_FREQUENCY"])
                except (KeyError, TypeError, ValueError):
                    continue

    return _first_name_counts(pairs())


# --------------------------------------------------------------------------
# Combining
# --------------------------------------------------------------------------

def select(*counters: Counter, min_persons: int) -> list[str]:
    """Names whose summed count over all sources reaches min_persons, sorted."""
    total = Counter()
    for c in counters:
        total.update(c)
    return sorted(name for name, n in total.items() if n >= min_persons)
