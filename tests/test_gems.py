from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from cms_icd import (
    ICD10_PCS_CHARACTERS,
    GEMDirection,
    GEMEntry,
    GEMKnowledgeBase,
    GEMStore,
)
from cms_icd.exceptions import ParseError
from cms_icd.gems import _backport_corrections
from cms_icd.models import Node, Release
from cms_icd.parsers import parse_gems
from cms_icd.stores import TabularStore

if TYPE_CHECKING:
    from pathlib import Path


def _write_gems(directory: Path) -> None:
    (directory / "2018_I9gem.txt").write_text(
        "0010 A000 10000\n0010 A001 10112\n0020 NoDx 11000\n",
        encoding="ascii",
    )
    (directory / "2018_I10gem.txt").write_text(
        "A000 0010 10000\nA001 NoDx 11000\n",
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
    assert gems.cm.icd10_to_icd9["A001"][0].target is None
    assert gems.pcs.icd10_to_icd9["0ABC0ZZ"][0].target == "0010"


def test_parse_reverse_pcs_no_map_uses_icd9_sentinel(tmp_path: Path) -> None:
    path = tmp_path / "gem_pcsi9.txt"
    path.write_text("0ABC0ZZ NoI9 10000\n", encoding="ascii")

    store = parse_gems(
        (path,),
        system="pcs",
        direction=GEMDirection.ICD10_TO_ICD9,
    )

    assert store["0ABC0ZZ"][0].target is None
    assert store["0ABC0ZZ"][0].no_map is True


def test_corrected_gems_default_to_last_cms_release() -> None:
    gems = GEMKnowledgeBase.corrected_from_cms(fiscal_year=2016)

    assert "fiscal_year=2018" in repr(gems)


def test_store_groups_simple_and_combination_entries() -> None:
    entries = (
        GEMEntry("0010", "A000", True, False, False, 0, 0),
        GEMEntry("0010", "B001", True, False, True, 1, 1),
        GEMEntry("0010", "B002", True, False, True, 1, 1),
        GEMEntry("0010", "C000", True, False, True, 1, 2),
        GEMEntry("0010", "D000", True, False, True, 2, 1),
    )
    store = GEMStore(
        {"0010": entries},
        system="cm",
        direction=GEMDirection.ICD9_TO_ICD10,
        release=Release(2018, date(2017, 10, 1)),
    )

    mapping = store.mapping("0010")

    assert [entry.target for entry in mapping.simple_alternatives] == ["A000"]
    assert [scenario.number for scenario in mapping.scenarios] == [1, 2]
    assert [
        entry.target for entry in mapping.scenarios[0].choice_lists[0].alternatives
    ] == [
        "B001",
        "B002",
    ]
    assert store.provenance("0010").selected_mapping_release.fiscal_year == 2018


def _store(
    year: int,
    values: dict[str, tuple[GEMEntry, ...]],
    *,
    system: str = "cm",
) -> GEMStore:
    return GEMStore(
        values,
        system=system,
        direction=GEMDirection.ICD9_TO_ICD10,
        release=Release(year, date(year - 1, 10, 1)),
    )


def _mapped(source: str, target: str, *, approximate: bool = True) -> GEMEntry:
    return GEMEntry(source, target, approximate, False, False, 0, 0)


def test_retrospective_corrections_apply_only_before_lifecycle_boundary() -> None:
    stores = [
        _store(
            2016,
            {
                "correction": (_mapped("correction", "A100"),),
                "lifecycle": (_mapped("lifecycle", "B100"),),
                "flags": (_mapped("flags", "C100", approximate=False),),
            },
        ),
        _store(
            2017,
            {
                "correction": (_mapped("correction", "A200"),),
                "lifecycle": (_mapped("lifecycle", "B200"),),
                "flags": (_mapped("flags", "C100"),),
            },
        ),
        _store(
            2018,
            {
                "correction": (_mapped("correction", "A300"),),
                "lifecycle": (_mapped("lifecycle", "B200"),),
                "flags": (_mapped("flags", "C100"),),
            },
        ),
    ]
    universes = [
        {"A100", "A200", "A300", "B100", "C100"},
        {"A100", "A200", "A300", "B200", "C100"},
        {"A100", "A200", "A300", "B200", "C100"},
    ]

    corrected = _backport_corrections(stores, universes)

    assert corrected["correction"][0].target == "A300"
    assert (
        corrected.provenance("correction").selected_mapping_release.fiscal_year == 2018
    )
    assert corrected["flags"][0].approximate is True
    assert corrected.provenance("flags").selected_mapping_release.fiscal_year == 2017
    assert corrected["lifecycle"][0].target == "B100"
    assert (
        corrected.provenance("lifecycle").blocked_by_code_lifecycle_release.fiscal_year
        == 2017
    )


def test_retrospective_corrections_do_not_resume_after_mixed_change() -> None:
    stores = [
        _store(2016, {"0010": (_mapped("0010", "A100"),)}),
        _store(
            2017,
            {"0010": (_mapped("0010", "A200"), _mapped("0010", "B100"))},
        ),
        _store(2018, {"0010": (_mapped("0010", "B200"),)}),
    ]
    universes = [
        {"A100", "B100", "B200"},
        {"A200", "B100", "B200"},
        {"A200", "B100", "B200"},
    ]

    corrected = _backport_corrections(stores, universes)

    assert [entry.target for entry in corrected["0010"]] == ["A100"]
    assert corrected.provenance("0010").selected_mapping_release.fiscal_year == 2016


def test_retrospective_corrections_preserve_pcs_store_metadata() -> None:
    stores = [
        _store(2017, {"0010": (_mapped("0010", "0ABC0ZZ"),)}, system="pcs"),
        _store(2018, {"0010": (_mapped("0010", "0ABC3ZZ"),)}, system="pcs"),
    ]

    corrected = _backport_corrections(
        stores,
        [{"0ABC0ZZ", "0ABC3ZZ"}, {"0ABC0ZZ", "0ABC3ZZ"}],
    )

    assert corrected.system == "pcs"
    assert corrected["0010"][0].target == "0ABC3ZZ"
    assert corrected.provenance("0010").selected_mapping_release.fiscal_year == 2018


def test_pcs_character_alphabet_is_ordered_and_omits_ambiguous_letters() -> None:
    assert "".join(ICD10_PCS_CHARACTERS) == "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def test_tabular_store_returns_lowest_common_ancestor() -> None:
    root = Node("cm", "cm", children_ids=("R31",))
    category = Node("R31", "R31", parent_id="cm", children_ids=("R311", "R312"))
    left = Node("R311", "R311", parent_id="R31")
    right = Node("R312", "R312", parent_id="R31")
    store = TabularStore(
        {node.id: node for node in (root, category, left, right)},
        {"R31": "R31", "R311": "R311", "R312": "R312"},
        ("cm",),
    )

    assert store.lowest_common_ancestor(("R311", "R312")) == category
    assert store.lowest_common_ancestor(("R311",)) == left
    assert store.lowest_common_ancestor(()) is None


def test_tabular_store_accepts_compact_cm_codes() -> None:
    root = Node("cm", "cm", children_ids=("A05",))
    category = Node("A05", "A05", parent_id="cm", children_ids=("A05.4", "A05.8"))
    left = Node("A05.4", "A05.4", parent_id="A05")
    right = Node("A05.8", "A05.8", parent_id="A05")
    store = TabularStore(
        {node.id: node for node in (root, category, left, right)},
        {"A05": "A05", "A05.4": "A05.4", "A05.8": "A05.8"},
        ("cm",),
    )

    assert store.by_code("A054") == left
    assert store.lowest_common_ancestor(("A054", "A058")) == category


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
