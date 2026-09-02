from __future__ import annotations

import weakref
from datetime import date
from types import SimpleNamespace

import pytest

from cms_icd import (
    GEMChoiceList,
    GEMEntry,
    GEMMapping,
    GEMScenario,
    GEMStore,
    ICDMappingReason,
    ICDMappingStatus,
    resolve_icd9_to_icd10_cm_mapping,
    resolve_icd9_to_icd10_cm_mappings,
    resolve_icd9_to_icd10_pcs_mapping,
)
from cms_icd.models import GEMDirection, Node, Release
from cms_icd.parsed_cache import clear_memory_cache
from cms_icd.resolution import (
    _discover_years,
    _resolution_cache,
    _resolve_cm_mapping,
    _resolve_pcs_mapping,
    clear_resolution_memory_cache,
)
from cms_icd.sources import CatalogEntry
from cms_icd.stores import TabularStore


def _entry(
    source: str,
    target: str | None,
    *,
    approximate: bool = True,
    combination: bool = False,
    scenario: int = 0,
    choice: int = 0,
) -> GEMEntry:
    return GEMEntry(
        source=source,
        target=target,
        approximate=approximate,
        no_map=target is None,
        combination=combination,
        scenario=scenario,
        choice_list=choice,
    )


@pytest.fixture
def tabular() -> TabularStore:
    nodes = {
        "cm": Node(
            "cm",
            "cm",
            children_ids=("R31", "A70", "J17", "Q65", "S12", "S22"),
        ),
        "R31": Node("R31", "R31", parent_id="cm", children_ids=("R311", "R312")),
        "R311": Node("R311", "R31.1", parent_id="R31"),
        "R312": Node("R312", "R31.2", parent_id="R31", children_ids=("R3121", "R3129")),
        "R3121": Node("R3121", "R31.21", parent_id="R312"),
        "R3129": Node("R3129", "R31.29", parent_id="R312"),
        "A70": Node("A70", "A70", parent_id="cm"),
        "J17": Node("J17", "J17", parent_id="cm"),
        "Q65": Node("Q65", "Q65", parent_id="cm", children_ids=("Q650", "Q653")),
        "Q650": Node("Q650", "Q65.0", parent_id="Q65", children_ids=("Q6501", "Q6502")),
        "Q6501": Node("Q6501", "Q65.01", parent_id="Q650"),
        "Q6502": Node("Q6502", "Q65.02", parent_id="Q650"),
        "Q653": Node("Q653", "Q65.3", parent_id="Q65", children_ids=("Q6531", "Q6532")),
        "Q6531": Node("Q6531", "Q65.31", parent_id="Q653"),
        "Q6532": Node("Q6532", "Q65.32", parent_id="Q653"),
        "S12": Node("S12", "S12", parent_id="cm"),
        "S22": Node("S22", "S22", parent_id="cm"),
    }
    lookup = {
        node.name.replace(".", ""): key for key, node in nodes.items() if key != "cm"
    }
    return TabularStore(nodes, lookup, ("cm",))


def test_cm_resolves_simple_alternatives_to_common_ancestor(
    tabular: TabularStore,
) -> None:
    mapping = GEMMapping(
        "59972",
        (
            _entry("59972", "R311"),
            _entry("59972", "R3121"),
            _entry("59972", "R3129"),
        ),
        (),
    )

    resolved = _resolve_cm_mapping(mapping, tabular=tabular)

    assert resolved.target_codes == ("R31",)
    assert resolved.reason is ICDMappingReason.COMMON_ANCESTOR


def test_cm_no_map_is_unmappable(tabular: TabularStore) -> None:
    resolved = _resolve_cm_mapping(
        GEMMapping("36570", (), (), no_map=True), tabular=tabular
    )

    assert resolved.status is ICDMappingStatus.UNMAPPABLE
    assert resolved.reason is ICDMappingReason.OFFICIAL_NO_MAP


def test_cm_combination_preserves_every_required_choice(
    tabular: TabularStore,
) -> None:
    mapping = GEMMapping(
        "0730",
        (),
        (
            GEMScenario(
                1,
                (
                    GEMChoiceList(
                        1,
                        (
                            _entry(
                                "0730", "A70", combination=True, scenario=1, choice=1
                            ),
                        ),
                    ),
                    GEMChoiceList(
                        2,
                        (
                            _entry(
                                "0730", "J17", combination=True, scenario=1, choice=2
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    resolved = _resolve_cm_mapping(mapping, tabular=tabular)

    assert resolved.target_codes == ("A70", "J17")
    assert resolved.reason is ICDMappingReason.COMBINATION


def test_cm_multiple_scenarios_remove_laterality(
    tabular: TabularStore,
) -> None:
    def scenario(number: int, first: str, second: str) -> GEMScenario:
        return GEMScenario(
            number,
            (
                GEMChoiceList(
                    1,
                    (
                        _entry(
                            "75435", first, combination=True, scenario=number, choice=1
                        ),
                    ),
                ),
                GEMChoiceList(
                    2,
                    (
                        _entry(
                            "75435", second, combination=True, scenario=number, choice=2
                        ),
                    ),
                ),
            ),
        )

    mapping = GEMMapping(
        "75435",
        (),
        (scenario(1, "Q6501", "Q6532"), scenario(2, "Q6502", "Q6531")),
    )

    assert _resolve_cm_mapping(mapping, tabular=tabular).target_codes == (
        "Q650",
        "Q653",
    )


def test_cm_divergent_scenarios_are_unmappable(tabular: TabularStore) -> None:
    mapping = GEMMapping(
        "8068",
        (),
        (
            GEMScenario(
                1, (GEMChoiceList(1, (_entry("8068", "S12", combination=True),)),)
            ),
            GEMScenario(
                2, (GEMChoiceList(1, (_entry("8068", "S22", combination=True),)),)
            ),
        ),
    )

    resolved = _resolve_cm_mapping(mapping, tabular=tabular)

    assert resolved.status is ICDMappingStatus.UNMAPPABLE
    assert resolved.reason is ICDMappingReason.DIVERGENT_SCENARIOS


def test_pcs_alternatives_mask_only_disagreeing_axes() -> None:
    mapping = GEMMapping(
        "0001",
        (_entry("0001", "6A750Z4"), _entry("0001", "6A751Z4")),
        (),
    )

    resolved = _resolve_pcs_mapping(mapping)

    assert resolved.target_patterns == ("6A75?Z4",)
    assert resolved.reason is ICDMappingReason.AXIS_MASKED


def test_pcs_alternatives_require_shared_table_prefix() -> None:
    mapping = GEMMapping(
        "0009",
        (_entry("0009", "6A750ZZ"), _entry("0009", "6A930ZZ")),
        (),
    )

    resolved = _resolve_pcs_mapping(mapping)

    assert resolved.status is ICDMappingStatus.UNMAPPABLE
    assert resolved.reason is ICDMappingReason.DIVERGENT_ALTERNATIVES


def test_pcs_no_map_and_invalid_target_are_informative() -> None:
    no_map = _resolve_pcs_mapping(GEMMapping("0016", (), (), no_map=True))
    invalid = _resolve_pcs_mapping(GEMMapping("0017", (_entry("0017", "SHORT"),), ()))

    assert no_map.reason is ICDMappingReason.OFFICIAL_NO_MAP
    assert invalid.reason is ICDMappingReason.INVALID_TARGET


def test_pcs_combination_preserves_choice_order_and_multiplicity() -> None:
    mapping = GEMMapping(
        "0040",
        (),
        (
            GEMScenario(
                1,
                (
                    GEMChoiceList(
                        1,
                        (
                            _entry(
                                "0040",
                                "0WQF0ZZ",
                                combination=True,
                                scenario=1,
                                choice=1,
                            ),
                        ),
                    ),
                    GEMChoiceList(
                        2,
                        (
                            _entry(
                                "0040",
                                "0WQF0ZZ",
                                combination=True,
                                scenario=1,
                                choice=2,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    resolved = _resolve_pcs_mapping(mapping)

    assert resolved.target_patterns == ("0WQF0ZZ", "0WQF0ZZ")
    assert resolved.reason is ICDMappingReason.COMBINATION


def test_pcs_scenarios_align_choice_lists_before_masking() -> None:
    def scenario(number: int, first: str, second: str) -> GEMScenario:
        return GEMScenario(
            number,
            (
                GEMChoiceList(
                    1,
                    (
                        _entry(
                            "0041",
                            first,
                            combination=True,
                            scenario=number,
                            choice=1,
                        ),
                    ),
                ),
                GEMChoiceList(
                    2,
                    (
                        _entry(
                            "0041",
                            second,
                            combination=True,
                            scenario=number,
                            choice=2,
                        ),
                    ),
                ),
            ),
        )

    mapping = GEMMapping(
        "0041",
        (),
        (
            scenario(1, "0WQF0ZZ", "0JH60DZ"),
            scenario(2, "0WQF3ZZ", "0JH63DZ"),
        ),
    )

    assert _resolve_pcs_mapping(mapping).target_patterns == (
        "0WQF?ZZ",
        "0JH6?DZ",
    )


def test_bulk_and_single_year_cm_apis_share_resolution(
    monkeypatch: pytest.MonkeyPatch, tabular: TabularStore
) -> None:
    release = Release(2018, date(2017, 10, 1))
    store = GEMStore(
        {"0020": (_entry("0020", "A70"),)},
        system="cm",
        direction=GEMDirection.ICD9_TO_ICD10,
        release=release,
    )
    gems = SimpleNamespace(cm=SimpleNamespace(icd9_to_icd10=store))
    knowledge = SimpleNamespace(cm=SimpleNamespace(tabular=tabular))
    monkeypatch.setattr(
        "cms_icd.resolution.GEMKnowledgeBase.corrected_from_cms",
        lambda **_: gems,
    )
    monkeypatch.setattr(
        "cms_icd.resolution.ICD10KnowledgeBase.from_cms", lambda **_: knowledge
    )

    bulk = resolve_icd9_to_icd10_cm_mappings((2018, 2018))
    single = resolve_icd9_to_icd10_cm_mapping(fiscal_year=2018)

    assert list(bulk) == [2018]
    assert single is bulk[2018]
    assert single["0020"].target_codes == ("A70",)
    with pytest.raises(TypeError):
        bulk[2019] = single  # type: ignore[index]


def test_fingerprintless_store_keys_are_stable_under_object_lifetime(
    monkeypatch: pytest.MonkeyPatch, tabular: TabularStore
) -> None:
    release = Release(2018, date(2017, 10, 1))
    knowledge = SimpleNamespace(cm=SimpleNamespace(tabular=tabular))
    holder: dict[int, GEMStore] = {}
    monkeypatch.setattr(
        "cms_icd.resolution.GEMKnowledgeBase.corrected_from_cms",
        lambda **kwargs: SimpleNamespace(
            cm=SimpleNamespace(icd9_to_icd10=holder[kwargs["fiscal_year"]])
        ),
    )
    monkeypatch.setattr(
        "cms_icd.resolution.ICD10KnowledgeBase.from_cms", lambda **_: knowledge
    )
    clear_resolution_memory_cache()

    holder[2017] = GEMStore(
        {"0020": (_entry("0020", "A70"),)},
        system="cm",
        direction=GEMDirection.ICD9_TO_ICD10,
        release=release,
    )
    first = resolve_icd9_to_icd10_cm_mapping(fiscal_year=2017)
    retained = weakref.ref(holder[2017])
    del holder[2017]
    holder[2017] = GEMStore(
        {"0020": (_entry("0020", "S12"),)},
        system="cm",
        direction=GEMDirection.ICD9_TO_ICD10,
        release=release,
    )
    second = resolve_icd9_to_icd10_cm_mapping(fiscal_year=2017)

    assert first["0020"].target_codes == ("A70",)
    assert second["0020"].target_codes == ("S12",)
    assert second is not first
    assert retained() is not None
    assert len(_resolution_cache) == 2


def test_clear_memory_cache_releases_retained_resolution_entries(
    monkeypatch: pytest.MonkeyPatch, tabular: TabularStore
) -> None:
    release = Release(2018, date(2017, 10, 1))
    store = GEMStore(
        {"0020": (_entry("0020", "A70"),)},
        system="cm",
        direction=GEMDirection.ICD9_TO_ICD10,
        release=release,
    )
    gems = SimpleNamespace(cm=SimpleNamespace(icd9_to_icd10=store))
    knowledge = SimpleNamespace(cm=SimpleNamespace(tabular=tabular))
    monkeypatch.setattr(
        "cms_icd.resolution.GEMKnowledgeBase.corrected_from_cms",
        lambda **_: gems,
    )
    monkeypatch.setattr(
        "cms_icd.resolution.ICD10KnowledgeBase.from_cms", lambda **_: knowledge
    )
    clear_resolution_memory_cache()

    first = resolve_icd9_to_icd10_cm_mapping(fiscal_year=2018)
    assert first["0020"].target_codes == ("A70",)
    assert _resolution_cache

    clear_memory_cache()

    assert not _resolution_cache
    again = resolve_icd9_to_icd10_cm_mapping(fiscal_year=2018)
    assert again["0020"].target_codes == ("A70",)


def test_empty_bulk_request_does_not_load_materials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cms_icd.resolution.GEMKnowledgeBase.corrected_from_cms",
        lambda **_: pytest.fail("empty request loaded GEMs"),
    )

    assert not resolve_icd9_to_icd10_cm_mappings(())


def test_default_years_discover_complete_history_through_horizon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = tuple(
        CatalogEntry(
            system=system,
            material=material,
            fiscal_year=year,
            release_date=date(year - 1, 10, 1),
            label=f"FY{year} {system} {material}",
            url=f"https://example.test/{year}/{system}/{material}",
            page_url="https://example.test/catalog",
        )
        for year in range(2014, 2019)
        for system, material in (("cm", "gems"), ("pcs", "gems"), ("cm", "tabular"))
    )
    monkeypatch.setattr(
        "cms_icd.resolution.CMSProvider._load_catalog", lambda _self: entries
    )

    assert _discover_years(
        "cm",
        corrections_through_fiscal_year=2018,
        cache_dir=None,
        offline=False,
    ) == tuple(range(2014, 2019))
    assert _discover_years(
        "pcs",
        corrections_through_fiscal_year=2018,
        cache_dir=None,
        offline=False,
    ) == tuple(range(2014, 2019))


def test_single_year_pcs_wrapper_uses_bulk_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {"0040": object()}
    monkeypatch.setattr(
        "cms_icd.resolution.resolve_icd9_to_icd10_pcs_mappings",
        lambda years, **_: {years[0]: expected},
    )

    assert resolve_icd9_to_icd10_pcs_mapping(fiscal_year=2018) is expected
