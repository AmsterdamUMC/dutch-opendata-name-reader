# Dutch Open-Data Name Lists

Builds the lists of Dutch first names and surnames that the GitHub security infrastructure of the Amsterdam UMC uses to detect full names (a known first name next to a known surname). The results are committed as `personal-info-lists/common-dutch-firstnames.txt` and `common-dutch-surnames.txt` in [org-security-workflows](https://github.com/AmsterdamUMC/org-security-workflows).

The lists are built only from open data:

| Source | What is used | Licence |
|---|---|---|
| Kiesraad candidate lists, via [data.overheid.nl](https://data.overheid.nl) | First name, prefix (tussenvoegsel) and last name of election candidates | CC0 1.0 |
| [Wikidata](https://www.wikidata.org) | Given names (P735) and family names (P734) of people with Dutch citizenship | CC0 1.0 |
| [SSA national baby names](https://catalog.data.gov/dataset/baby-names-from-social-security-card-applications-national-data) (US Social Security Administration) | First names given to babies in the US, with counts per year | CC0 1.0 |
| [Statbel](https://statbel.fgov.be/en/open-data/first-names-total-population-municipality-16) (Statistics Belgium) | First names of the total population of Belgium, with counts per municipality | CC BY 4.0 |

Election candidates are adults, and Wikidata mostly covers notable and older people, so on their own these sources miss first names that became popular recently. The SSA and Statbel files fill that gap: SSA for international names (Mason, Hailey, Millie), Statbel for Dutch-language names that are common in Flanders as well. They are used for first names only.

## Requirements

Python 3.10 or newer. The scripts use only the standard library; `pytest` (in `requirements-dev.txt`) is needed for the tests.

## Data setup

### Kiesraad candidate lists

```bash
python fetch-kiesraad.py          # add --list to only show what would be downloaded
```

Finds the election datasets on data.overheid.nl through its CKAN API (datasets titled "verkiezingsuitslag...") and downloads, per election, the candidate list CSV, or the candidate JSON, or else the EML zip, into `data/raw/kiesraad/<dataset>/`. Use `--dataset <id>` (repeatable) to fetch specific elections only, e.g. `--dataset verkiezingsuitslagen-gemeenteraad-2022`.

Files can also be placed in `data/raw/kiesraad/` by hand. The reader accepts:

- EML_NL files (`.xml`/`.eml`): any file with `Candidate` elements holding an `xnl:PersonName`, such as candidate lists (EML 230)
- CSV files with columns for first name and last name (`Voornaam`/`Roepnaam`, `Tussenvoegsel`, `Achternaam`, `Initialen`; `,` `;` or tab separated)
- JSON files with a list of records using the same field names
- zip files containing any of the above, including nested zips

More elections give better coverage; municipal elections contribute the most candidates.

### Wikidata

```bash
python fetch-wikidata.py
```

Writes to `data/raw/wikidata/`:

- `given-names.tsv`, `family-names.tsv`: names of people with Dutch citizenship

This queries the public Wikidata Query Service and takes a few minutes.

### SSA and Statbel first names

```bash
python fetch-first-name-counts.py
```

Downloads `data/raw/ssa/names.zip` and the Statbel men's and women's files (`data/raw/statbel/TA_POP_MALE_2026.zip`, `TA_POP_FEMALE_2026.zip`). When Statbel publishes a newer year, pass `--statbel-year <year>`.

## Building the lists

```bash
python build-name-lists.py
```

Output:
- `output/common-dutch-firstnames.txt`
- `output/common-dutch-surnames.txt`
- `data/counts-firstnames.tsv`, `data/counts-surnames.tsv`: per-name counts per source, for checking the threshold (not published)

Options: `--kiesraad DIR`, `--wikidata DIR`, `--ssa FILE`, `--statbel DIR`, `--min-persons N` (default 2), `--ssa-min-births N` (default 200), `--ssa-from-year YEAR` (default 1940), `--statbel-min-persons N` (default 10), `--out DIR`. A source whose files are missing is skipped.

## What it does

- Reads all candidates and deduplicates them on initials, first name, prefix and last name, so a person on lists in several elections counts once
- Counts, per name, how many distinct people carry it, in each source
- Keeps a name when the count summed over the Dutch sources (Kiesraad and Dutch Wikidata) is at least `--min-persons`. Neither source gives a population frequency, so this replaces the frequency threshold; it also keeps out names that only one person in the data has
- Also keeps a first name when it was given to at least `--ssa-min-births` babies in the US since `--ssa-from-year`, or when at least `--statbel-min-persons` people in Belgium carry it (summed over municipalities). These thresholds are higher because both are population-wide counts that include many rare names
- Normalises names the way the detection splits text into words (`word_token` in `personal_info.py`): letters only, internal hyphens and apostrophes kept, periods, digits and a leading apostrophe dropped; typographic apostrophes become `'`
- First names: a call name with several names ("Jan Willem") counts for each; names of one or two letters, all-caps entries and a short exclusion list (place-name prefixes such as "Sint" and "San", weekday abbreviations, "The") are dropped
- Surnames: written in natural order with lower-case prefixes ("van der Berg"). Double surnames are kept whole and also split into their parts ("Smit-van Dijk" also gives "Smit" and "van Dijk"). Entries of one or two letters, all-caps entries, bare prefixes and a short exclusion list are dropped

## Attribution

The first-name list contains data from Statbel, which requires attribution under CC BY 4.0. Wherever the list is published or copied (such as `personal-info-lists/` in org-security-workflows), include:

> First names partly derived from: Source: Statbel (Directorate-General Statistics – Statistics Belgium), "First names of the total population by municipality", licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Changes: counts summed over municipalities, names normalised and filtered, counts removed.

## Privacy

The output contains single first names and surnames, with no link between them and nothing else about the people they came from. The candidate lists name real people; they are published by the Kiesraad as open data, but reuse for another purpose should be checked against the AVG/GDPR by the institution's privacy officer. Raw source data and the per-name counts stay in the git-ignored `data/` folder.

## Using the output

Copy the two files in `output/` to `personal-info-lists/` in org-security-workflows. The normalisation must stay in step with `word_token` in that repository's `personal_info.py`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
