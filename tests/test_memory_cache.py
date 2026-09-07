from __future__ import annotations

import pytest

from cms_icd import MemoryCache, clear_memory_caches


def test_clear_memory_caches_clears_every_layer_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleared: list[str] = []
    monkeypatch.setattr(
        "cms_icd.memory_cache.clear_catalog_memory_cache",
        lambda: cleared.append("catalog"),
    )
    monkeypatch.setattr(
        "cms_icd.memory_cache.clear_memory_cache", lambda: cleared.append("parsed")
    )
    monkeypatch.setattr(
        "cms_icd.memory_cache.clear_resolution_memory_cache",
        lambda: cleared.append("resolution"),
    )

    clear_memory_caches()

    assert cleared == ["catalog", "parsed", "resolution"]


def test_clear_memory_caches_accepts_enum_and_string_selectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleared: list[str] = []
    monkeypatch.setattr(
        "cms_icd.memory_cache.clear_catalog_memory_cache",
        lambda: cleared.append("catalog"),
    )
    monkeypatch.setattr(
        "cms_icd.memory_cache.clear_memory_cache", lambda: cleared.append("parsed")
    )
    monkeypatch.setattr(
        "cms_icd.memory_cache.clear_resolution_memory_cache",
        lambda: cleared.append("resolution"),
    )

    clear_memory_caches(MemoryCache.PARSED, "resolution")

    assert cleared == ["parsed", "resolution"]


def test_clear_memory_caches_rejects_an_unknown_selector() -> None:
    with pytest.raises(ValueError, match="unknown"):
        clear_memory_caches("unknown")
