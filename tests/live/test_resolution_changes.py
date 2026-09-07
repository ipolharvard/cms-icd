"""Live regression coverage for ICD-9 to ICD-10-CM resolution."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from cms_icd import (
    ICD10KnowledgeBase,
    ICDMappingReason,
    ICDMappingStatus,
    resolve_icd9_to_icd10_cm_mappings,
)
from cms_icd.models import Code

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.live_cms
@pytest.mark.live_historical
def test_official_cm_resolutions_only_return_code_nodes(
    historical_cache: Path,
) -> None:
    """Reject section and chapter headings across every supported GEM year."""
    years = (2014, 2015, 2016, 2017, 2018)
    resolved = resolve_icd9_to_icd10_cm_mappings(
        years,
        corrections_through_fiscal_year=2018,
        cache_dir=historical_cache,
    )

    for year in years:
        tabular = ICD10KnowledgeBase.from_cms(
            fiscal_year=year,
            release_date=date(year - 1, 10, 1),
            cache_dir=historical_cache,
        ).cm.tabular
        for resolution in resolved[year].values():
            if resolution.status is ICDMappingStatus.MAPPED:
                assert all(
                    isinstance(tabular.by_code(target), Code)
                    for target in resolution.target_codes
                )

    for year in (2017, 2018):
        regression = resolved[year]["4019"]
        assert regression.status is ICDMappingStatus.UNMAPPABLE
        assert regression.reason in {
            ICDMappingReason.DIVERGENT_ALTERNATIVES,
            ICDMappingReason.DIVERGENT_SCENARIOS,
        }
        assert regression.target_codes == ()
