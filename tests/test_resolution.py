from __future__ import annotations

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
from cms_icd.models import Code, GEMDirection, Node, Release
from cms_icd.resolution import (
    _discover_years,
    _resolve_cm_mapping,
    _resolve_pcs_mapping,
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
        "R31": Code("R31", "R31", parent_id="cm", children_ids=("R311", "R312")),
        "R311": Code("R311", "R31.1", parent_id="R31"),
        "R312": Code("R312", "R31.2", parent_id="R31", children_ids=("R3121", "R3129")),
        "R3121": Code("R3121", "R31.21", parent_id="R312"),
        "R3129": Code("R3129", "R31.29", parent_id="R312"),
        "A70": Code("A70", "A70", parent_id="cm"),
        "J17": Code("J17", "J17", parent_id="cm"),
        "Q65": Code("Q65", "Q65", parent_id="cm", children_ids=("Q650", "Q653")),
        "Q650": Code("Q650", "Q65.0", parent_id="Q65", children_ids=("Q6501", "Q6502")),
        "Q6501": Code("Q6501", "Q65.01", parent_id="Q650"),
        "Q6502": Code("Q6502", "Q65.02", parent_id="Q650"),
        "Q653": Code("Q653", "Q65.3", parent_id="Q65", children_ids=("Q6531", "Q6532")),
        "Q6531": Code("Q6531", "Q65.31", parent_id="Q653"),
        "Q6532": Code("Q6532", "Q65.32", parent_id="Q653"),
        "S12": Code("S12", "S12", parent_id="cm"),
        "S22": Code("S22", "S22", parent_id="cm"),
    }
    lookup = {
        node.name.replace(".", ""): key for key, node in nodes.items() if key != "cm"
    }
    return TabularStore(nodes, lookup, ("cm",))


@pytest.fixture
def hierarchical_tabular() -> TabularStore:
    """Chapter/section-shaped store mirroring ``parse_cm_tabular`` output."""
    circulatory = "Diseases of the circulatory system"
    circulatory_id = f"cm_{circulatory}"
    respiratory = "Diseases of the respiratory system"
    respiratory_id = f"cm_{respiratory}"
    section_i10 = f"{circulatory_id}_I10-I15"
    section_i20 = f"{circulatory_id}_I20-I28"
    section_j10 = f"{respiratory_id}_J10-J16"
    nodes = {
        "cm": Node(
            "cm",
            "cm",
            children_ids=(circulatory_id, respiratory_id),
        ),
        circulatory_id: Node(
            circulatory_id,
            circulatory,
            parent_id="cm",
            children_ids=(section_i10, section_i20),
        ),
        respiratory_id: Node(
            respiratory_id,
            respiratory,
            parent_id="cm",
            children_ids=(section_j10,),
        ),
        section_i10: Node(
            section_i10,
            "I10-I15",
            parent_id=circulatory_id,
            children_ids=("I10", "I12", "I15"),
        ),
        section_i20: Node(
            section_i20,
            "I20-I28",
            parent_id=circulatory_id,
            children_ids=("I16", "I20"),
        ),
        section_j10: Node(
            section_j10,
            "J10-J16",
            parent_id=respiratory_id,
            children_ids=("J10",),
        ),
        "I10": Code("I10", "I10", parent_id=section_i10),
        "I12": Code(
            "I12",
            "I12",
            parent_id=section_i10,
            children_ids=("I12.0", "I12.1"),
        ),
        "I15": Code("I15", "I15", parent_id=section_i10),
        "I16": Code("I16", "I16", parent_id=section_i20),
        "I20": Code("I20", "I20", parent_id=section_i20),
        "I12.0": Code("I12.0", "I12.0", parent_id="I12"),
        "I12.1": Code("I12.1", "I12.1", parent_id="I12"),
        "J10": Code("J10", "J10", parent_id=section_j10),
    }
    lookup = {node.name: node.id for node in nodes.values() if isinstance(node, Code)}
    lookup["cm"] = "cm"
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


def test_cm_section_lca_is_unmappable(hierarchical_tabular: TabularStore) -> None:
    mapping = GEMMapping(
        "4019",
        (_entry("4019", "I10"), _entry("4019", "I15")),
        (),
    )

    resolved = _resolve_cm_mapping(mapping, tabular=hierarchical_tabular)

    assert resolved.status is ICDMappingStatus.UNMAPPABLE
    assert resolved.reason is ICDMappingReason.DIVERGENT_ALTERNATIVES
    assert resolved.target_codes == ()


def test_cm_chapter_lca_is_unmappable(hierarchical_tabular: TabularStore) -> None:
    mapping = GEMMapping(
        "4029",
        (_entry("4029", "I10"), _entry("4029", "I20")),
        (),
    )

    resolved = _resolve_cm_mapping(mapping, tabular=hierarchical_tabular)

    assert resolved.status is ICDMappingStatus.UNMAPPABLE
    assert resolved.reason is ICDMappingReason.DIVERGENT_ALTERNATIVES
    assert resolved.target_codes == ()


def test_cm_root_lca_is_unmappable(hierarchical_tabular: TabularStore) -> None:
    mapping = GEMMapping(
        "4039",
        (_entry("4039", "I10"), _entry("4039", "J10")),
        (),
    )

    resolved = _resolve_cm_mapping(mapping, tabular=hierarchical_tabular)

    assert resolved.status is ICDMappingStatus.UNMAPPABLE
    assert resolved.reason is ICDMappingReason.DIVERGENT_ALTERNATIVES
    assert resolved.target_codes == ()


def test_cm_scenario_choice_list_section_lca_is_unmappable(
    hierarchical_tabular: TabularStore,
) -> None:
    mapping = GEMMapping(
        "4279",
        (),
        (
            GEMScenario(
                1,
                (
                    GEMChoiceList(
                        1,
                        (
                            _entry(
                                "4279",
                                "I10",
                                combination=True,
                                scenario=1,
                                choice=1,
                            ),
                            _entry(
                                "4279",
                                "I15",
                                combination=True,
                                scenario=1,
                                choice=1,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    resolved = _resolve_cm_mapping(mapping, tabular=hierarchical_tabular)

    assert resolved.status is ICDMappingStatus.UNMAPPABLE
    assert resolved.reason is ICDMappingReason.DIVERGENT_SCENARIOS
    assert resolved.target_codes == ()


def test_cm_scenario_collapse_section_lca_is_unmappable(
    hierarchical_tabular: TabularStore,
) -> None:
    def scenario(number: int, target: str) -> GEMScenario:
        return GEMScenario(
            number,
            (
                GEMChoiceList(
                    1,
                    (
                        _entry(
                            "4119",
                            target,
                            combination=True,
                            scenario=number,
                            choice=1,
                        ),
                    ),
                ),
            ),
        )

    mapping = GEMMapping("4119", (), (scenario(1, "I10"), scenario(2, "I15")))

    resolved = _resolve_cm_mapping(mapping, tabular=hierarchical_tabular)

    assert resolved.status is ICDMappingStatus.UNMAPPABLE
    assert resolved.reason is ICDMappingReason.DIVERGENT_SCENARIOS
    assert resolved.target_codes == ()


def test_cm_single_target_under_section_resolves_exact(
    hierarchical_tabular: TabularStore,
) -> None:
    mapping = GEMMapping("4010", (_entry("4010", "I10", approximate=False),), ())

    resolved = _resolve_cm_mapping(mapping, tabular=hierarchical_tabular)

    assert resolved.target_codes == ("I10",)
    assert resolved.reason is ICDMappingReason.EXACT


def test_cm_same_category_subcodes_still_collapse(
    hierarchical_tabular: TabularStore,
) -> None:
    mapping = GEMMapping(
        "4020",
        (_entry("4020", "I120"), _entry("4020", "I121")),
        (),
    )

    resolved = _resolve_cm_mapping(mapping, tabular=hierarchical_tabular)

    assert resolved.target_codes == ("I12",)
    assert resolved.reason is ICDMappingReason.COMMON_ANCESTOR


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
