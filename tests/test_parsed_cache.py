from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from cms_icd import GEMDirection, GEMEntry, GEMStore
from cms_icd.gems import _backport_corrections
from cms_icd.knowledge_base import ICD10KnowledgeBase
from cms_icd.models import Code, Guideline, Node, Release, Term
from cms_icd.parsed_cache import (
    clear_memory_cache,
    load_corrected_gem_store,
    load_gem_store,
    load_tabular_store,
)
from cms_icd.sources import CMSProvider
from cms_icd.stores import GuidelineStore, IndexStore, TabularStore

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


def test_guideline_and_index_views_share_persistent_parsed_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    tabular_path = source_dir / "icd10cm_tabular_2018.xml"
    tabular_path.write_text("tabular source", encoding="utf-8")
    index_path = source_dir / "icd10cm_index_2018.xml"
    index_path.write_text("index source", encoding="utf-8")
    guidelines_path = source_dir / "icd10cm_guidelines_2018.pdf"
    guidelines_path.write_text("guidelines source", encoding="utf-8")

    tabular = TabularStore(
        {
            "cm": Node("cm", "cm", children_ids=("A00",)),
            "A00": Code("A00", "A00", "Cholera", parent_id="cm"),
        },
        {"A00": "A00"},
        ("cm",),
    )
    index = IndexStore(
        {
            "000001": Term(id="000001", title="Cholera", children_ids=("000001.0",)),
            "000001.0": Term(
                id="000001.0",
                title="Cholera",
                parent_id="000001",
                code="A00.0",
                assignable=True,
            ),
        }
    )
    guidelines = GuidelineStore(
        {"I.A.1": Guideline("I_A_1", "I.A.1", "Section", "Body")},
        {"I": "General", "I.A": "Overview"},
        {"I.A": "Preamble"},
    )

    counts = {"tabular": 0, "index": 0, "guidelines": 0}

    def fake_parse_cm_tabular(_path):
        counts["tabular"] += 1
        return tabular

    def fake_parse_index(_paths, *, system):
        counts["index"] += 1
        return index

    def fake_parse_guidelines(_path, *, system):
        counts["guidelines"] += 1
        return guidelines

    monkeypatch.setattr("cms_icd.parsed_cache.parse_cm_tabular", fake_parse_cm_tabular)
    monkeypatch.setattr("cms_icd.parsed_cache.parse_index", fake_parse_index)
    monkeypatch.setattr("cms_icd.parsed_cache.parse_guidelines", fake_parse_guidelines)

    def make_knowledge_base() -> ICD10KnowledgeBase:
        provider = CMSProvider(
            Release(2018, date(2017, 10, 1)),
            cache_dir=tmp_path / "cache",
            offline=True,
        )

        def paths(_system: str, material: str) -> tuple[Path, ...]:
            return {
                "tabular": (tabular_path,),
                "index": (index_path,),
                "guidelines": (guidelines_path,),
            }[material]

        provider.paths = paths
        return ICD10KnowledgeBase(provider)

    first = make_knowledge_base()
    first.cm.load_all()
    assert counts == {"tabular": 1, "index": 1, "guidelines": 1}
    derived = tmp_path / "cache" / "_derived" / "v1"
    assert list((derived / "tabular").iterdir())
    assert list((derived / "index").iterdir())
    assert list((derived / "guidelines").iterdir())
    clear_memory_cache()

    second = make_knowledge_base()
    second.cm.load_all()

    assert counts == {"tabular": 1, "index": 1, "guidelines": 1}
    assert second.cm.tabular["A00"] == first.cm.tabular["A00"]
    assert second.cm.index["000001.0"] == first.cm.index["000001.0"]
    assert second.cm.guidelines["I.A.1"] == first.cm.guidelines["I.A.1"]
    assert second.cm.guidelines.titles == first.cm.guidelines.titles
    assert second.cm.guidelines.preambles == first.cm.guidelines.preambles


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
