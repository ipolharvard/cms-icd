from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from cms_icd import GEMDirection, GEMKnowledgeBase
from cms_icd.exceptions import ParseError
from cms_icd.models import Release
from cms_icd.parsers import parse_gems

if TYPE_CHECKING:
    from pathlib import Path


def _write_gems(directory: Path) -> None:
    (directory / "2018_I9gem.txt").write_text(
        "0010 A000 10000\n0010 A001 10112\n0020 NoDx 11000\n",
        encoding="ascii",
    )
    (directory / "2018_I10gem.txt").write_text(
        "A000 0010 10000\n",
        encoding="ascii",
    )
    (directory / "gem_i9pcs.txt").write_text(
        "0010 0ABC0ZZ 00000\n",
        encoding="ascii",
    )
    (directory / "gem_pcsi9.txt").write_text(
        "0ABC0ZZ 0010 00000\n",
        encoding="ascii",
    )


def test_parse_gems_preserves_codes_flags_and_alternatives(tmp_path: Path) -> None:
    _write_gems(tmp_path)
    release = Release(2018, date(2017, 10, 1))

    store = parse_gems(
        tuple(tmp_path.iterdir()),
        system="cm",
        direction=GEMDirection.ICD9_TO_ICD10,
        release=release,
    )

    assert list(store) == ["0010", "0020"]
    assert [entry.target for entry in store["0010"]] == ["A000", "A001"]
    assert store["0010"][1].combination is True
    assert store["0010"][1].scenario == 1
    assert store["0010"][1].choice_list == 2
    assert store["0020"][0].target is None
    assert store["0020"][0].no_map is True
    assert store.release == release


def test_gem_knowledge_base_loads_systems_and_directions_lazily(
    tmp_path: Path,
) -> None:
    _write_gems(tmp_path)
    gems = GEMKnowledgeBase.from_directory(tmp_path, fiscal_year=2018)

    assert repr(gems).endswith("loaded=[])")
    assert gems.cm.icd9_to_icd10["0010"][0].target == "A000"
    assert "icd9_to_icd10" in repr(gems.cm)
    assert gems.pcs.icd10_to_icd9["0ABC0ZZ"][0].target == "0010"


@pytest.mark.parametrize(
    "record",
    [
        "0010 A000 0000",
        "0010 A000 20000",
        "0010 NoDx 00000",
        "0010 A000 01000",
    ],
)
def test_parse_gems_rejects_invalid_records(tmp_path: Path, record: str) -> None:
    path = tmp_path / "2018_I9gem.txt"
    path.write_text(record + "\n", encoding="ascii")

    with pytest.raises(ParseError):
        parse_gems(
            (path,),
            system="cm",
            direction=GEMDirection.ICD9_TO_ICD10,
        )
