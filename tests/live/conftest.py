from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cms_icd.models import Release
from cms_icd.sources import CMSProvider, default_cache_dir

if TYPE_CHECKING:
    from collections.abc import Iterable

    from cms_icd.sources import CatalogEntry
    from cms_icd.stores import GuidelineStore


SYSTEM_MATERIALS = tuple(
    (system, material)
    for system in ("cm", "pcs")
    for material in ("tabular", "index", "guidelines")
)


def diagnostic_dir() -> Path:
    path = Path(os.environ.get("CMS_ICD_DIAGNOSTIC_DIR", ".cms-diagnostics"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_diagnostic(name: str, value: object) -> None:
    (diagnostic_dir() / name).write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
    )


def guideline_fingerprint(store: GuidelineStore) -> str:
    """Return a compact canonical fingerprint without printing guideline text."""

    def normalize(value: str) -> str:
        return " ".join(unicodedata.normalize("NFC", value).split())

    payload = {
        "titles": {key: normalize(value) for key, value in store.titles.items()},
        "preambles": {key: normalize(value) for key, value in store.preambles.items()},
        "guidelines": {
            key: {
                "id": item.id,
                "number": item.number,
                "title": normalize(item.title),
                "content": normalize(item.content),
            }
            for key, item in store.items()
        },
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def catalog_entries() -> tuple[CatalogEntry, ...]:
    today = datetime.now(tz=UTC).date()
    return CMSProvider(Release(today.year, today))._load_catalog()


def release_dates(entries: Iterable[CatalogEntry]) -> dict[int, tuple[date, ...]]:
    result: dict[int, set[date]] = {}
    for entry in entries:
        if entry.fiscal_year >= 2016:
            result.setdefault(entry.fiscal_year, set()).add(entry.release_date)
    return {year: tuple(sorted(values)) for year, values in result.items()}


def latest_complete_release(entries: tuple[CatalogEntry, ...]) -> Release:
    for year in sorted(release_dates(entries), reverse=True):
        for effective in sorted(release_dates(entries)[year], reverse=True):
            provider = CMSProvider(Release(year, effective))
            provider._catalog = entries
            try:
                for system, material in SYSTEM_MATERIALS:
                    provider._select(system, material)
            except Exception:
                continue
            return Release(year, effective)
    raise AssertionError("CMS catalog contains no complete supported ICD release")


@pytest.fixture(scope="session")
def historical_cache() -> Path:
    return Path(
        os.environ.get(
            "CMS_ICD_LIVE_CACHE",
            default_cache_dir() / "live-tests",
        )
    ).expanduser()


@pytest.fixture(scope="session")
def fresh_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    configured = os.environ.get("CMS_ICD_FRESH_CACHE")
    return (
        Path(configured).expanduser()
        if configured
        else tmp_path_factory.mktemp("cms-current")
    )
