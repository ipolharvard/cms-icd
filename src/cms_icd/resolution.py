"""Best-effort bulk resolution of historical ICD-9 GEM relationships."""

from __future__ import annotations

from concurrent.futures import Future
from datetime import date
from threading import Lock
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from .constants import ICD10_PCS_CHARACTERS
from .exceptions import ReleaseUnavailableError
from .gems import GEMKnowledgeBase
from .knowledge_base import ICD10KnowledgeBase
from .models import (
    GEMChoiceList,
    GEMEntry,
    GEMMapping,
    GEMProvenance,
    ICDCMMappingResolution,
    ICDMappingReason,
    ICDMappingStatus,
    ICDPCSMappingResolution,
    Release,
)
from .sources import CMSProvider

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from .stores import GEMStore, TabularStore

_PCS_UNKNOWN_AXIS = "?"
_PCS_CHARACTERS = frozenset(ICD10_PCS_CHARACTERS)
_resolution_lock = Lock()


class _StoreIdentityKey:
    """A hashable, identity-keyed handle for a store lacking a content fingerprint.

    The resolution cache and identity registry retain the handle, and through it the
    store, so the store's memory address cannot be reused by a distinct store while a
    cache entry exists.
    """

    __slots__ = ("store",)

    def __init__(self, store: object) -> None:
        self.store = store


_store_identity_keys: dict[int, tuple[object, _StoreIdentityKey]] = {}
_resolution_cache: dict[
    tuple[str, str | _StoreIdentityKey, str | _StoreIdentityKey | None],
    Future[Mapping[str, Any]],
] = {}


def _unmappable_cm(
    source: str,
    reason: ICDMappingReason,
    *,
    provenance: GEMProvenance | None,
) -> ICDCMMappingResolution:
    return ICDCMMappingResolution(
        source_code=source,
        target_codes=(),
        status=ICDMappingStatus.UNMAPPABLE,
        reason=reason,
        approximate=True,
        gem_provenance=provenance,
    )


def _common_ancestor(
    entries: tuple[GEMEntry, ...], tabular: TabularStore
) -> str | None:
    targets = tuple(entry.target for entry in entries if entry.target is not None)
    if not targets:
        return None
    ancestor = tabular.lowest_common_ancestor(targets)
    if ancestor is None:
        return None
    code = ancestor.name.replace(".", "")
    return code if len(code) >= 3 and code.lower() != "cm" else None


def _resolve_cm_choice_list(
    choice_list: GEMChoiceList, tabular: TabularStore
) -> str | None:
    if len(choice_list.alternatives) == 1:
        return choice_list.alternatives[0].target
    return _common_ancestor(choice_list.alternatives, tabular)


def _resolve_cm_scenario(
    choice_lists: tuple[GEMChoiceList, ...], tabular: TabularStore
) -> tuple[str, ...] | None:
    codes: list[str] = []
    for choice_list in choice_lists:
        code = _resolve_cm_choice_list(choice_list, tabular)
        if code is None:
            return None
        codes.append(code)
    return tuple(codes)


def _resolve_cm_mapping(
    mapping: GEMMapping,
    *,
    tabular: TabularStore,
    provenance: GEMProvenance | None = None,
) -> ICDCMMappingResolution:
    source = mapping.source
    approximate = any(
        entry.approximate for entry in mapping.simple_alternatives
    ) or any(
        entry.approximate
        for scenario in mapping.scenarios
        for choice_list in scenario.choice_lists
        for entry in choice_list.alternatives
    )
    if mapping.no_map:
        return _unmappable_cm(
            source, ICDMappingReason.OFFICIAL_NO_MAP, provenance=provenance
        )

    simple_codes: tuple[str, ...] | None = None
    simple_reason = ICDMappingReason.EXACT
    if mapping.simple_alternatives:
        if len(mapping.simple_alternatives) == 1:
            target = mapping.simple_alternatives[0].target
            simple_codes = () if target is None else (target,)
            if mapping.simple_alternatives[0].approximate:
                simple_reason = ICDMappingReason.SINGLE_APPROXIMATE
        else:
            ancestor = _common_ancestor(mapping.simple_alternatives, tabular)
            if ancestor is None:
                return _unmappable_cm(
                    source,
                    ICDMappingReason.DIVERGENT_ALTERNATIVES,
                    provenance=provenance,
                )
            simple_codes = (ancestor,)
            simple_reason = ICDMappingReason.COMMON_ANCESTOR

    scenario_codes = tuple(
        _resolve_cm_scenario(scenario.choice_lists, tabular)
        for scenario in mapping.scenarios
    )
    if any(codes is None for codes in scenario_codes):
        return _unmappable_cm(
            source, ICDMappingReason.DIVERGENT_SCENARIOS, provenance=provenance
        )

    combination_codes: tuple[str, ...] | None = None
    if scenario_codes:
        resolved_scenarios = tuple(
            codes for codes in scenario_codes if codes is not None
        )
        if len(set(resolved_scenarios)) == 1:
            combination_codes = resolved_scenarios[0]
        else:
            shapes = tuple(
                tuple(choice.number for choice in scenario.choice_lists)
                for scenario in mapping.scenarios
            )
            if len(set(shapes)) != 1:
                return _unmappable_cm(
                    source,
                    ICDMappingReason.DIVERGENT_SCENARIOS,
                    provenance=provenance,
                )
            collapsed: list[str] = []
            for index in range(len(mapping.scenarios[0].choice_lists)):
                alternatives = tuple(
                    entry
                    for scenario in mapping.scenarios
                    for entry in scenario.choice_lists[index].alternatives
                )
                ancestor = _common_ancestor(alternatives, tabular)
                if ancestor is None:
                    return _unmappable_cm(
                        source,
                        ICDMappingReason.DIVERGENT_SCENARIOS,
                        provenance=provenance,
                    )
                collapsed.append(ancestor)
            combination_codes = tuple(collapsed)

    paths = tuple(
        path for path in (simple_codes, combination_codes) if path is not None
    )
    if not paths:
        return _unmappable_cm(
            source, ICDMappingReason.UNKNOWN_SOURCE, provenance=provenance
        )
    if len(set(paths)) != 1:
        return _unmappable_cm(
            source, ICDMappingReason.DIVERGENT_SCENARIOS, provenance=provenance
        )
    reason = (
        ICDMappingReason.COMBINATION if combination_codes is not None else simple_reason
    )
    return ICDCMMappingResolution(
        source_code=source,
        target_codes=paths[0],
        status=ICDMappingStatus.MAPPED,
        reason=reason,
        approximate=approximate,
        gem_provenance=provenance,
    )


def _unmappable_pcs(
    source: str,
    reason: ICDMappingReason,
    *,
    provenance: GEMProvenance | None,
) -> ICDPCSMappingResolution:
    return ICDPCSMappingResolution(
        source_code=source,
        target_patterns=(),
        status=ICDMappingStatus.UNMAPPABLE,
        reason=reason,
        approximate=True,
        gem_provenance=provenance,
    )


def _axis_consensus(entries: tuple[GEMEntry, ...]) -> tuple[str | None, bool]:
    targets = tuple(entry.target for entry in entries if entry.target is not None)
    if not targets or any(
        len(target) != 7
        or any(character not in _PCS_CHARACTERS for character in target)
        for target in targets
    ):
        return None, True
    pattern = "".join(
        values.pop()
        if len(values := {target[index] for target in targets}) == 1
        else "?"
        for index in range(7)
    )
    return (pattern if _PCS_UNKNOWN_AXIS not in pattern[:3] else None), False


def _resolve_pcs_scenario(
    choice_lists: tuple[GEMChoiceList, ...],
) -> tuple[tuple[str, ...] | None, bool]:
    patterns: list[str] = []
    for choice_list in choice_lists:
        pattern, invalid = _axis_consensus(choice_list.alternatives)
        if pattern is None:
            return None, invalid
        patterns.append(pattern)
    return tuple(patterns), False


def _resolve_pcs_mapping(
    mapping: GEMMapping,
    *,
    provenance: GEMProvenance | None = None,
) -> ICDPCSMappingResolution:
    source = mapping.source
    entries = (
        *mapping.simple_alternatives,
        *(
            entry
            for scenario in mapping.scenarios
            for choice_list in scenario.choice_lists
            for entry in choice_list.alternatives
        ),
    )
    approximate = any(entry.approximate for entry in entries)
    if mapping.no_map:
        return _unmappable_pcs(
            source, ICDMappingReason.OFFICIAL_NO_MAP, provenance=provenance
        )

    simple_patterns: tuple[str, ...] | None = None
    simple_reason = ICDMappingReason.EXACT
    if mapping.simple_alternatives:
        simple_pattern, invalid = _axis_consensus(mapping.simple_alternatives)
        if invalid:
            return _unmappable_pcs(
                source, ICDMappingReason.INVALID_TARGET, provenance=provenance
            )
        if simple_pattern is None:
            return _unmappable_pcs(
                source,
                ICDMappingReason.DIVERGENT_ALTERNATIVES,
                provenance=provenance,
            )
        simple_patterns = (simple_pattern,)
        if _PCS_UNKNOWN_AXIS in simple_pattern:
            simple_reason = ICDMappingReason.AXIS_MASKED
        elif mapping.simple_alternatives[0].approximate:
            simple_reason = ICDMappingReason.SINGLE_APPROXIMATE

    scenario_patterns: list[tuple[str, ...]] = []
    for scenario in mapping.scenarios:
        patterns, invalid = _resolve_pcs_scenario(scenario.choice_lists)
        if invalid:
            return _unmappable_pcs(
                source, ICDMappingReason.INVALID_TARGET, provenance=provenance
            )
        if patterns is None:
            return _unmappable_pcs(
                source,
                ICDMappingReason.DIVERGENT_SCENARIOS,
                provenance=provenance,
            )
        scenario_patterns.append(patterns)

    combination_patterns: tuple[str, ...] | None = None
    if scenario_patterns:
        if len(set(scenario_patterns)) == 1:
            combination_patterns = scenario_patterns[0]
        else:
            shapes = tuple(
                tuple(choice.number for choice in scenario.choice_lists)
                for scenario in mapping.scenarios
            )
            if len(set(shapes)) != 1:
                return _unmappable_pcs(
                    source,
                    ICDMappingReason.DIVERGENT_SCENARIOS,
                    provenance=provenance,
                )
            collapsed: list[str] = []
            for index in range(len(mapping.scenarios[0].choice_lists)):
                alternatives = tuple(
                    entry
                    for scenario in mapping.scenarios
                    for entry in scenario.choice_lists[index].alternatives
                )
                pattern, invalid = _axis_consensus(alternatives)
                if invalid:
                    return _unmappable_pcs(
                        source,
                        ICDMappingReason.INVALID_TARGET,
                        provenance=provenance,
                    )
                if pattern is None:
                    return _unmappable_pcs(
                        source,
                        ICDMappingReason.DIVERGENT_SCENARIOS,
                        provenance=provenance,
                    )
                collapsed.append(pattern)
            combination_patterns = tuple(collapsed)

    paths = tuple(
        path for path in (simple_patterns, combination_patterns) if path is not None
    )
    if not paths:
        return _unmappable_pcs(
            source, ICDMappingReason.UNKNOWN_SOURCE, provenance=provenance
        )
    if len(set(paths)) != 1:
        return _unmappable_pcs(
            source, ICDMappingReason.DIVERGENT_SCENARIOS, provenance=provenance
        )
    reason = (
        ICDMappingReason.COMBINATION
        if combination_patterns is not None
        else simple_reason
    )
    return ICDPCSMappingResolution(
        source_code=source,
        target_patterns=paths[0],
        status=ICDMappingStatus.MAPPED,
        reason=reason,
        approximate=approximate,
        gem_provenance=provenance,
    )


def _discover_years(
    kind: Literal["cm", "pcs"],
    *,
    corrections_through_fiscal_year: int,
    cache_dir: str | Path | None,
    offline: bool,
) -> tuple[int, ...]:
    provider = CMSProvider(
        Release(
            corrections_through_fiscal_year,
            date(corrections_through_fiscal_year - 1, 10, 1),
        ),
        cache_dir=cache_dir,
        offline=offline,
    )
    catalog = provider._load_catalog()
    gem_years = {
        entry.fiscal_year
        for entry in catalog
        if entry.system == kind
        and entry.material == "gems"
        and entry.fiscal_year <= corrections_through_fiscal_year
    }
    tabular_years = {
        entry.fiscal_year
        for entry in catalog
        if entry.system == "cm" and entry.material == "tabular"
    }
    compatible = [
        year
        for year in gem_years
        if set(range(year, corrections_through_fiscal_year + 1)) <= gem_years
        and (kind == "pcs" or year in tabular_years)
    ]
    if not compatible:
        raise ReleaseUnavailableError(
            f"No compatible ICD-{kind.upper()} GEM fiscal years are available through "
            f"FY {corrections_through_fiscal_year}"
        )
    return tuple(sorted(compatible))


def _normalize_years(
    fiscal_years: Iterable[int] | None,
    *,
    kind: Literal["cm", "pcs"],
    corrections_through_fiscal_year: int,
    cache_dir: str | Path | None,
    offline: bool,
) -> tuple[int, ...]:
    if fiscal_years is None:
        return _discover_years(
            kind,
            corrections_through_fiscal_year=corrections_through_fiscal_year,
            cache_dir=cache_dir,
            offline=offline,
        )
    requested = tuple(fiscal_years)
    if any(isinstance(year, bool) or not isinstance(year, int) for year in requested):
        raise TypeError("fiscal_years must contain integers")
    years = tuple(sorted(set(requested)))
    if any(year > corrections_through_fiscal_year for year in years):
        raise ValueError("fiscal_years must not exceed corrections_through_fiscal_year")
    return years


def _key_component(store: object) -> str | _StoreIdentityKey:
    """Return the cache key component for one store.

    A content fingerprint, when present, is the key; otherwise a stable identity handle
    is used so that two distinct stores can never share an entry.
    """
    fingerprint = getattr(store, "_cache_fingerprint", None)
    if fingerprint is not None:
        return str(fingerprint)
    candidate = _store_identity_keys.get(id(store))
    if candidate is not None and candidate[0] is store:
        return candidate[1]
    handle = _StoreIdentityKey(store)
    _store_identity_keys[id(store)] = (store, handle)
    return handle


def _resolved_year(
    kind: Literal["cm", "pcs"],
    store: GEMStore,
    tabular: TabularStore | None,
) -> Mapping[str, ICDCMMappingResolution] | Mapping[str, ICDPCSMappingResolution]:
    with _resolution_lock:
        store_key = _key_component(store)
        tabular_key = None if tabular is None else _key_component(tabular)
        key = (kind, store_key, tabular_key)
        future = _resolution_cache.get(key)
        if future is None:
            future = Future()
            _resolution_cache[key] = future
            owner = True
        else:
            owner = False
    if not owner:
        return future.result()
    try:
        if kind == "cm":
            if tabular is None:
                raise RuntimeError("CM resolution requires a tabular hierarchy")
            result = MappingProxyType(
                {
                    source: _resolve_cm_mapping(
                        store.mapping(source),
                        tabular=tabular,
                        provenance=store.provenance(source),
                    )
                    for source in store
                }
            )
        else:
            result = MappingProxyType(
                {
                    source: _resolve_pcs_mapping(
                        store.mapping(source),
                        provenance=store.provenance(source),
                    )
                    for source in store
                }
            )
        future.set_result(result)
        return result
    except BaseException as exc:
        future.set_exception(exc)
        with _resolution_lock:
            _resolution_cache.pop(key, None)
        raise


def resolve_icd9_to_icd10_cm_mappings(
    fiscal_years: Iterable[int] | None = None,
    *,
    corrections_through_fiscal_year: int = 2018,
    cache_dir: str | Path | None = None,
    offline: bool = False,
) -> Mapping[int, Mapping[str, ICDCMMappingResolution]]:
    """Resolve corrected ICD-9-CM diagnosis GEMs for several fiscal years.

    The result is a best-effort interpretation of every official source mapping, not a
    one-to-one clinical conversion table. ``None`` selects every compatible advertised
    GEM year through the correction horizon (currently FY2014--FY2018).
    """
    years = _normalize_years(
        fiscal_years,
        kind="cm",
        corrections_through_fiscal_year=corrections_through_fiscal_year,
        cache_dir=cache_dir,
        offline=offline,
    )
    result: dict[int, Mapping[str, ICDCMMappingResolution]] = {}
    for year in years:
        store = GEMKnowledgeBase.corrected_from_cms(
            fiscal_year=year,
            corrections_through_fiscal_year=corrections_through_fiscal_year,
            cache_dir=cache_dir,
            offline=offline,
        ).cm.icd9_to_icd10
        tabular = ICD10KnowledgeBase.from_cms(
            fiscal_year=year,
            release_date=date(year - 1, 10, 1),
            cache_dir=cache_dir,
            offline=offline,
        ).cm.tabular
        result[year] = _resolved_year("cm", store, tabular)  # type: ignore[assignment]
    return MappingProxyType(result)


def resolve_icd9_to_icd10_pcs_mappings(
    fiscal_years: Iterable[int] | None = None,
    *,
    corrections_through_fiscal_year: int = 2018,
    cache_dir: str | Path | None = None,
    offline: bool = False,
) -> Mapping[int, Mapping[str, ICDPCSMappingResolution]]:
    """Resolve corrected ICD-9-CM procedure GEMs for several fiscal years.

    The result is a best-effort interpretation. A ``?`` in a target pattern marks an
    ICD-10-PCS axis on which official alternatives disagree.
    """
    years = _normalize_years(
        fiscal_years,
        kind="pcs",
        corrections_through_fiscal_year=corrections_through_fiscal_year,
        cache_dir=cache_dir,
        offline=offline,
    )
    result: dict[int, Mapping[str, ICDPCSMappingResolution]] = {}
    for year in years:
        store = GEMKnowledgeBase.corrected_from_cms(
            fiscal_year=year,
            corrections_through_fiscal_year=corrections_through_fiscal_year,
            cache_dir=cache_dir,
            offline=offline,
        ).pcs.icd9_to_icd10
        result[year] = _resolved_year("pcs", store, None)  # type: ignore[assignment]
    return MappingProxyType(result)


def resolve_icd9_to_icd10_cm_mapping(
    *,
    fiscal_year: int,
    corrections_through_fiscal_year: int = 2018,
    cache_dir: str | Path | None = None,
    offline: bool = False,
) -> Mapping[str, ICDCMMappingResolution]:
    """Resolve corrected diagnosis mappings for one historical fiscal year."""
    return resolve_icd9_to_icd10_cm_mappings(
        (fiscal_year,),
        corrections_through_fiscal_year=corrections_through_fiscal_year,
        cache_dir=cache_dir,
        offline=offline,
    )[fiscal_year]


def resolve_icd9_to_icd10_pcs_mapping(
    *,
    fiscal_year: int,
    corrections_through_fiscal_year: int = 2018,
    cache_dir: str | Path | None = None,
    offline: bool = False,
) -> Mapping[str, ICDPCSMappingResolution]:
    """Resolve corrected procedure mappings for one historical fiscal year."""
    return resolve_icd9_to_icd10_pcs_mappings(
        (fiscal_year,),
        corrections_through_fiscal_year=corrections_through_fiscal_year,
        cache_dir=cache_dir,
        offline=offline,
    )[fiscal_year]


def clear_resolution_memory_cache() -> None:
    """Clear process-local resolution state for tests and diagnostics."""
    with _resolution_lock:
        _resolution_cache.clear()
        _store_identity_keys.clear()
