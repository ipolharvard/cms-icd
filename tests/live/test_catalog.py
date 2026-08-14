from __future__ import annotations

import pytest
from conftest import (
    SYSTEM_MATERIALS,
    catalog_entries,
    latest_complete_release,
    release_dates,
    write_diagnostic,
)

from cms_icd.models import Release
from cms_icd.sources import CMSProvider


@pytest.mark.live_cms
@pytest.mark.live_catalog
def test_live_catalog_resolves_supported_release_matrix() -> None:
    entries = catalog_entries()
    dates_by_year = release_dates(entries)
    latest_complete = latest_complete_release(entries)
    matrix: list[dict[str, object]] = []
    failures: list[str] = []

    assert min(dates_by_year) == 2016
    assert latest_complete.fiscal_year == max(dates_by_year) or (
        latest_complete.fiscal_year == max(dates_by_year) - 1
    )

    for year, dates in sorted(dates_by_year.items()):
        for effective in dates:
            provider = CMSProvider(Release(year, effective))
            provider._catalog = entries
            selected: dict[str, str] = {}
            unavailable: list[str] = []
            for system, material in SYSTEM_MATERIALS:
                key = f"{system}/{material}"
                try:
                    entry = provider._select(system, material)
                except Exception as exc:
                    unavailable.append(f"{key}: {type(exc).__name__}")
                else:
                    selected[key] = entry.url
            matrix.append(
                {
                    "fiscal_year": year,
                    "release_date": effective,
                    "selected": selected,
                    "unavailable": unavailable,
                }
            )
            if year <= latest_complete.fiscal_year:
                failures.extend(f"FY{year} {effective} {item}" for item in unavailable)

    write_diagnostic(
        "catalog-matrix.json",
        {
            "entry_count": len(entries),
            "latest_complete": latest_complete,
            "matrix": matrix,
        },
    )
    assert not failures, failures


@pytest.mark.live_cms
@pytest.mark.live_catalog
def test_live_catalog_keeps_october_and_april_revisions_distinct() -> None:
    dates_by_year = release_dates(catalog_entries())
    midyear_years = [
        year
        for year, dates in dates_by_year.items()
        if any(value.month == 4 for value in dates)
    ]

    assert midyear_years
    for year in midyear_years:
        dates = dates_by_year[year]
        assert any(value.month == 10 for value in dates)
        assert any(value.month == 4 for value in dates)


@pytest.mark.live_cms
@pytest.mark.live_catalog
def test_live_catalog_exposes_final_gem_releases() -> None:
    entries = catalog_entries()
    available = {
        (entry.fiscal_year, entry.system)
        for entry in entries
        if entry.material == "gems"
    }

    assert {
        (year, system) for year in range(2014, 2019) for system in ("cm", "pcs")
    } <= available
