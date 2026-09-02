from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from cms_icd import GEMDirection, GEMEntry, GEMStore, clear_memory_cache
from cms_icd.gems import _backport_corrections
from cms_icd.models import Node, Release
from cms_icd.parsed_cache import (
    _memory,
    load_corrected_gem_store,
    load_gem_store,
    load_tabular_store,
)
from cms_icd.stores import TabularStore

if TYPE_CHECKING:
    from pathlib import Path


def _provider(cache_dir: Path, paths: tuple[Path, ...]):
    return SimpleNamespace(
        cache_dir=cache_dir,
        release=Release(2018, date(2017, 10, 1)),
        paths=lambda _system, _material: paths,
    )


def test_raw_gem_store_is_loaded_from_persistent_parsed_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gem_path = tmp_path / "2018_I9gem.txt"
    gem_path.write_text("0010 A000 10000\n", encoding="ascii")
    provider = _provider(tmp_path / "cache", (gem_path,))

    first = load_gem_store(provider, "cm", GEMDirection.ICD9_TO_ICD10)
    clear_memory_cache()
    monkeypatch.setattr(
        "cms_icd.parsed_cache.parse_gems",
        lambda *_args, **_kwargs: pytest.fail("warm cache invoked GEM parser"),
    )

    second = load_gem_store(provider, "cm", GEMDirection.ICD9_TO_ICD10)

    assert second["0010"] == first["0010"]
    assert list((provider.cache_dir / "_derived" / "v1" / "gems").iterdir())


def test_parsed_cache_corruption_and_source_change_rebuild(
    tmp_path: Path,
) -> None:
    gem_path = tmp_path / "2018_I9gem.txt"
    gem_path.write_text("0010 A000 10000\n", encoding="ascii")
    provider = _provider(tmp_path / "cache", (gem_path,))
    first = load_gem_store(provider, "cm", GEMDirection.ICD9_TO_ICD10)
    cache_entries = list((provider.cache_dir / "_derived" / "v1" / "gems").iterdir())
    (cache_entries[0] / "payload.json").write_text("corrupt")
    clear_memory_cache()

    rebuilt = load_gem_store(provider, "cm", GEMDirection.ICD9_TO_ICD10)
    assert rebuilt["0010"] == first["0010"]

    gem_path.write_text("0010 A001 10000\n", encoding="ascii")
    clear_memory_cache()
    changed = load_gem_store(provider, "cm", GEMDirection.ICD9_TO_ICD10)

    assert changed["0010"][0].target == "A001"
    assert len(list((provider.cache_dir / "_derived" / "v1" / "gems").iterdir())) == 2


def test_tabular_store_is_loaded_from_persistent_parsed_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xml_path = tmp_path / "icd10cm_tabular_2018.xml"
    xml_path.write_text("source fingerprint", encoding="utf-8")
    provider = _provider(tmp_path / "cache", (xml_path,))
    expected = TabularStore(
        {
            "cm": Node("cm", "cm", children_ids=("A00",)),
            "A00": Node("A00", "A00", parent_id="cm"),
        },
        {"A00": "A00"},
        ("cm",),
    )
    monkeypatch.setattr("cms_icd.parsed_cache.parse_cm_tabular", lambda _path: expected)

    first = load_tabular_store(provider, "cm")
    clear_memory_cache()
    monkeypatch.setattr(
        "cms_icd.parsed_cache.parse_cm_tabular",
        lambda _path: pytest.fail("warm cache invoked XML parser"),
    )

    second = load_tabular_store(provider, "cm")

    assert second.roots == first.roots
    assert second["A00"] == first["A00"]


def test_corrected_store_cache_preserves_provenance(tmp_path: Path) -> None:
    releases = [Release(year, date(year - 1, 10, 1)) for year in (2017, 2018)]
    stores = [
        GEMStore(
            {"0010": (GEMEntry("0010", target, True, False, False, 0, 0),)},
            system="cm",
            direction=GEMDirection.ICD9_TO_ICD10,
            release=release,
        )
        for release, target in zip(releases, ("A000", "A001"), strict=True)
    ]
    for index, store in enumerate(stores):
        store._cache_fingerprint = f"raw-{index}"
    universes = [{"A000", "A001"}, {"A000", "A001"}]

    first = load_corrected_gem_store(
        tmp_path,
        stores,
        universes,
        build=lambda: _backport_corrections(stores, universes),
    )
    clear_memory_cache()
    second = load_corrected_gem_store(
        tmp_path,
        stores,
        universes,
        build=lambda: pytest.fail("warm cache rebuilt corrected GEMs"),
    )

    assert second["0010"] == first["0010"]
    assert second.provenance("0010") == first.provenance("0010")


def test_distinct_cache_directories_are_evictable_and_warm_reuse_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_memory_cache()
    assert len(_memory) == 0

    providers = []
    stores = []
    for index in range(3):
        gem_path = tmp_path / f"2018_I9gem_{index}.txt"
        gem_path.write_text("0010 A000 10000\n", encoding="ascii")
        provider = _provider(tmp_path / f"cache-{index}", (gem_path,))
        providers.append(provider)
        stores.append(load_gem_store(provider, "cm", GEMDirection.ICD9_TO_ICD10))

    assert len(_memory) == 3

    for entry in (providers[0].cache_dir / "_derived" / "v1" / "gems").iterdir():
        (entry / "payload.json").write_text("corrupt", encoding="utf-8")
    monkeypatch.setattr(
        "cms_icd.parsed_cache.parse_gems",
        lambda *_args, **_kwargs: pytest.fail("warm cache invoked GEM parser"),
    )

    again = load_gem_store(providers[0], "cm", GEMDirection.ICD9_TO_ICD10)
    assert again is stores[0]

    clear_memory_cache()
    assert len(_memory) == 0

    reloaded = load_gem_store(providers[1], "cm", GEMDirection.ICD9_TO_ICD10)
    assert reloaded["0010"] == stores[1]["0010"]
    assert len(_memory) == 1
