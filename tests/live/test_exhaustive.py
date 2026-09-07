from __future__ import annotations

import os
from datetime import date
from typing import TYPE_CHECKING

import pytest
from conftest import (
    catalog_entries,
    guideline_fingerprint,
    latest_complete_release,
    release_dates,
    write_diagnostic,
)

if TYPE_CHECKING:
    from pathlib import Path

from cms_icd import ICD10KnowledgeBase


def _selected_release_dates(
    available: dict[int, tuple[date, ...]],
) -> dict[int, tuple[date, ...]]:
    configured = os.environ.get("CMS_ICD_EXHAUSTIVE_YEARS", "").strip()
    if not configured:
        return available
    try:
        selected = {int(item.strip()) for item in configured.split(",") if item.strip()}
    except ValueError as exc:
        raise pytest.UsageError(
            "CMS_ICD_EXHAUSTIVE_YEARS must be a comma-separated list of years"
        ) from exc
    if not selected:
        raise pytest.UsageError(
            "CMS_ICD_EXHAUSTIVE_YEARS must include at least one year"
        )
    unknown = selected - available.keys()
    if unknown:
        raise pytest.UsageError(
            "CMS_ICD_EXHAUSTIVE_YEARS contains unavailable years: "
            + ", ".join(str(year) for year in sorted(unknown))
        )
    return {year: available[year] for year in sorted(selected)}


def test_exhaustive_year_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    available = {
        2017: (date(2016, 10, 1),),
        2019: (date(2018, 10, 1),),
        2026: (date(2025, 10, 1), date(2026, 4, 1)),
    }

    monkeypatch.delenv("CMS_ICD_EXHAUSTIVE_YEARS", raising=False)
    assert _selected_release_dates(available) == available

    monkeypatch.setenv("CMS_ICD_EXHAUSTIVE_YEARS", "2017, 2026")
    assert set(_selected_release_dates(available)) == {2017, 2026}

    monkeypatch.setenv("CMS_ICD_EXHAUSTIVE_YEARS", "FY2017")
    with pytest.raises(pytest.UsageError, match="comma-separated list of years"):
        _selected_release_dates(available)

    monkeypatch.setenv("CMS_ICD_EXHAUSTIVE_YEARS", "2018")
    with pytest.raises(pytest.UsageError, match="unavailable years: 2018"):
        _selected_release_dates(available)


@pytest.mark.live_cms
@pytest.mark.live_exhaustive
def test_every_advertised_snapshot_and_material_parses(
    historical_cache: Path,
) -> None:
    entries = catalog_entries()
    latest_complete = latest_complete_release(entries)
    results: list[dict[str, object]] = []
    selected_releases = _selected_release_dates(release_dates(entries))
    for year, dates in selected_releases.items():
        for effective in dates:
            kb = ICD10KnowledgeBase.from_cms(
                fiscal_year=year,
                release_date=effective,
                cache_dir=historical_cache,
            )
            snapshot = {
                "fiscal_year": year,
                "release_date": effective,
                "materials": {},
                "guideline_fingerprints": {},
            }
            for system, material in (
                ("cm", "tabular"),
                ("cm", "index"),
                ("cm", "guidelines"),
                ("pcs", "tabular"),
                ("pcs", "index"),
                ("pcs", "guidelines"),
            ):
                name = f"{system}/{material}"
                try:
                    value = getattr(getattr(kb, system), material)
                except Exception as exc:
                    snapshot["materials"][name] = type(exc).__name__
                else:
                    snapshot["materials"][name] = len(value)
                    if material == "guidelines":
                        if system == "cm":
                            assert len(value) > 10
                            assert {"I", "II", "III", "IV"} <= set(value.titles)
                            assert all(item.content.strip() for item in value.values())
                        else:
                            assert set(value) == {"document"}
                            assert len(value["document"].content) > 10_000
                        snapshot["guideline_fingerprints"][name] = (
                            guideline_fingerprint(value)
                        )
            results.append(snapshot)
    write_diagnostic("exhaustive-results.json", results)

    supported = [
        item
        for item in results
        if int(item["fiscal_year"]) <= latest_complete.fiscal_year
    ]
    failures = [
        item
        for item in supported
        if not all(isinstance(value, int) for value in dict(item["materials"]).values())
    ]
    assert not failures, failures
