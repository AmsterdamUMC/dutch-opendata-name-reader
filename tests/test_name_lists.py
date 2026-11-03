"""
Tests for name_lists.py on small synthetic inputs. The names used here
are invented or very common; no real candidate data is included.
"""

import io
import json
import zipfile
from collections import Counter

import pytest

import name_lists as nl

EML = b"""<?xml version="1.0" encoding="UTF-8"?>
<EML xmlns="urn:oasis:names:tc:evs:schema:eml" xmlns:xnl="urn:oasis:names:tc:ciq:xsdschema:xNL:2.0" Id="230">
  <CandidateList><Election><Contest><Affiliation>
    <Candidate>
      <CandidateIdentifier Id="1"/>
      <CandidateFullName><xnl:PersonName>
        <xnl:NameLine NameType="Initials">J.W.</xnl:NameLine>
        <xnl:FirstName>Jan Willem</xnl:FirstName>
        <xnl:NamePrefix>van der</xnl:NamePrefix>
        <xnl:LastName>Berg</xnl:LastName>
      </xnl:PersonName></CandidateFullName>
    </Candidate>
    <Candidate>
      <CandidateIdentifier Id="2"/>
      <CandidateFullName><xnl:PersonName>
        <xnl:NameLine NameType="Initials">A.</xnl:NameLine>
        <xnl:FirstName>Anna</xnl:FirstName>
        <xnl:LastName>Smit-van Dijk</xnl:LastName>
      </xnl:PersonName></CandidateFullName>
    </Candidate>
  </Affiliation></Contest></Election></CandidateList>
</EML>"""

CSV = (
    "Waterschap;Partijnummer;Partijnaam;Kandidaatnummer;Initialen;Voornaam;"
    "Tussenvoegsel;Achternaam;Woonplaats;Geslacht\n"
    "X;1;P;1;A.;Anna;;Smit-van Dijk;Plaats;v\n"
    "X;1;P;2;P.;Pieter;de;Vries;Plaats;m\n"
)


@pytest.mark.parametrize("raw,expected", [
    ("’s-Gravenhage", "s-Gravenhage"),
    ("D’Souza", "D'Souza"),
    ("van 't Hof", "van t Hof"),
    ("J.W.", "J W"),
    ("Anne-Marie", "Anne-Marie"),
])
def test_normalize_matches_word_token(raw, expected):
    assert nl.normalize(raw) == expected


def test_first_names_split_and_filtered():
    assert nl.first_names_from("Jan Willem") == ["Jan", "Willem"]
    # too short, all caps, excluded, lower case
    assert nl.first_names_from("Jo") == []
    assert nl.first_names_from("JAN") == []
    assert nl.first_names_from("Sint") == []
    assert nl.first_names_from("jan") == []


def test_surname_prefixes_lowercased():
    assert nl.surname_from("Van Der", "Berg") == "van der Berg"
    assert nl.surname_from("", "Van Der Berg") == "van der Berg"
    assert nl.surname_from("van 't", "Hof") == "van t Hof"


def test_double_surname_parts():
    assert nl.surnames_from("", "Smit-van Dijk") == ["Smit-van Dijk", "Smit", "van Dijk"]


def test_invalid_surnames():
    assert nl.surnames_from("", "van") == []        # only a prefix
    assert nl.surnames_from("", "Li") == []          # too short
    assert nl.surnames_from("", "JANSEN") == []      # all caps
    assert nl.surnames_from("", "The") == []         # excluded


def test_read_eml():
    people = list(nl.read_eml(EML))
    assert people[0] == nl.Person("J.W.", "Jan Willem", "van der", "Berg")
    assert people[1].prefix == ""


def test_read_csv_semicolon_and_aliases():
    people = list(nl.read_csv(CSV.encode("utf-8")))
    assert [p.last_name for p in people] == ["Smit-van Dijk", "Vries"]
    assert people[1].prefix == "de"


def test_read_csv_without_name_columns_yields_nothing():
    assert list(nl.read_csv(b"a,b\n1,2\n")) == []


def test_read_json():
    data = json.dumps([{"voornaam": "Pieter", "tussenvoegsel": "de", "achternaam": "Vries"}])
    assert list(nl.read_json(data.encode())) == [nl.Person("", "Pieter", "de", "Vries")]


def test_read_kiesraad_nested_zip(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("Kandidatenlijsten_GR2099_Test.eml.xml", EML)
    with zipfile.ZipFile(tmp_path / "outer.zip", "w") as z:
        z.writestr("gemeente.zip", inner.getvalue())
    (tmp_path / "kandidaten.csv").write_text(CSV, encoding="utf-8")
    people = list(nl.read_kiesraad(tmp_path))
    assert len(people) == 4


def test_count_kiesraad_deduplicates_people():
    people = list(nl.read_eml(EML)) + list(nl.read_csv(CSV.encode()))
    first, sur, n = nl.count_kiesraad(people)
    # Anna Smit-van Dijk is on both lists with the same initials: one person.
    assert n == 3
    assert first == Counter({"Jan": 1, "Willem": 1, "Anna": 1, "Pieter": 1})
    assert sur["Smit"] == 1 and sur["van Dijk"] == 1 and sur["de Vries"] == 1


def test_wikidata_tsv_and_select(tmp_path):
    tsv = tmp_path / "family-names.tsv"
    tsv.write_text("name\tpersons\titem\nVan der Berg\t5\tQ1\nJANSEN\t9\tQ2\n", encoding="utf-8")
    w_sur = nl.read_wikidata_tsv(tsv, "surname")
    assert w_sur == Counter({"van der Berg": 5})
    k_sur = Counter({"van der Berg": 1, "de Vries": 1})
    assert nl.select(k_sur, w_sur, min_persons=2) == ["van der Berg"]
    assert nl.read_wikidata_tsv(tmp_path / "missing.tsv", "first") == Counter()



def _ssa_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("yob1930.txt", "Oldname,M,500\n")
        z.writestr("yob2020.txt", "Zayn,M,150\nZayn,F,5\nRarename,F,7\n")
        z.writestr("yob2021.txt", "Zayn,M,160\n")
        z.writestr("NationalReadMe.pdf", "x")


def _statbel_zip(path):
    text = ("CD_REFNIS|tx_descr_nl|tx_descr_fr|TX_FST_NAME|MS_FREQUENCY\r\n"
            "11001|Aartselaar|Aartselaar|Lio|6\r\n"
            "11002|Antwerpen|Anvers|Lio|7\r\n"
            "11002|Antwerpen|Anvers|Fran\xe7ois|5\r\n")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("TA_POP_MALE_2026.txt", text.encode("cp1252"))


def test_read_ssa_sums_years_from(tmp_path):
    _ssa_zip(tmp_path / "names.zip")
    counts = nl.read_ssa(tmp_path / "names.zip", from_year=1940)
    assert counts == Counter({"Zayn": 315, "Rarename": 7})
    assert nl.read_ssa(tmp_path / "missing.zip") == Counter()


def test_read_statbel_sums_municipalities_cp1252(tmp_path):
    _statbel_zip(tmp_path / "TA_POP_MALE_2026.zip")
    assert nl.read_statbel(tmp_path) == Counter({"Lio": 13, "François": 5})


def test_build_combines_sources_with_thresholds(tmp_path):
    import subprocess, sys
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    w = tmp_path / "w"; w.mkdir()
    (w / "given-names.tsv").write_text("name\tpersons\titem\nAnna\t2\tQ1\n", encoding="utf-8")
    _ssa_zip(tmp_path / "names.zip")
    sb = tmp_path / "statbel"; sb.mkdir()
    _statbel_zip(sb / "TA_POP_MALE_2026.zip")
    subprocess.run(
        [sys.executable, str(repo / "build-name-lists.py"),
         "--kiesraad", str(tmp_path / "none"), "--wikidata", str(w),
         "--ssa", str(tmp_path / "names.zip"), "--statbel", str(sb),
         "--out", str(tmp_path / "out")],
        cwd=tmp_path, check=True, capture_output=True,
    )
    first = (tmp_path / "out" / "common-dutch-firstnames.txt").read_text(encoding="utf-8").split()
    # Zayn: 315 US births >= 200; Lio: 13 Belgians >= 10;
    # Rarename (7 births) and François (5 people) are below the thresholds.
    assert first == ["Anna", "Lio", "Zayn"]


def test_vote_count_files_are_skipped(tmp_path):
    # A "Telling_" file is skipped by name even if it contains candidates.
    with zipfile.ZipFile(tmp_path / "e.zip", "w") as z:
        z.writestr("Telling_GR2099_Test.eml.xml", EML)
        z.writestr("Kandidatenlijsten_GR2099_Test.eml.xml", EML)
    assert len(list(nl.read_kiesraad(tmp_path))) == 2


def test_is_common_word():
    assert nl.is_common_word("Even") and nl.is_common_word("Trust")
    assert not nl.is_common_word("Zayn") and not nl.is_common_word("Fenna")


def test_month_and_min_abbreviations_excluded():
    assert nl.first_names_from("Jul Jun Sep Sun Min") == []


def test_build_drops_ssa_only_common_words(tmp_path):
    import subprocess, sys
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    w = tmp_path / "w"; w.mkdir()
    # "Even" is also supported by Dutch sources here, "Trust" is not.
    (w / "given-names.tsv").write_text("name\tpersons\titem\nEven\t2\tQ1\n", encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "names.zip", "w") as z:
        z.writestr("yob2020.txt", "Even,M,500\nTrust,M,500\nHunter,M,400000\nZayn,M,500\n")
    subprocess.run(
        [sys.executable, str(repo / "build-name-lists.py"),
         "--kiesraad", str(tmp_path / "none"), "--wikidata", str(w),
         "--ssa", str(tmp_path / "names.zip"), "--statbel", str(tmp_path / "none"),
         "--out", str(tmp_path / "out")],
        cwd=tmp_path, check=True, capture_output=True,
    )
    first = (tmp_path / "out" / "common-dutch-firstnames.txt").read_text(encoding="utf-8").split()
    # Trust and Hunter: SSA-only common words -> dropped, however many births.
    # Even: common word but supported by a Dutch source -> kept.
    # Zayn: not a common word -> kept.
    assert first == ["Even", "Zayn"]
