from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from conftest import catalog_entries, latest_complete_release, write_diagnostic

if TYPE_CHECKING:
    from pathlib import Path

from cms_icd import ICD10KnowledgeBase
from cms_icd.models import Code


def _assert_tabular_integrity(store, *, system: str) -> None:
    assert len(store) > 1_000
    assert len(store.lookup) > 1_000
    assert all(identifier in store for identifier in store.lookup.values())
    assignable = [
        node for node in store.values() if isinstance(node, Code) and node.assignable
    ]
    assert assignable
    if system == "pcs":
        assert all(len(node.name) == 7 for node in assignable)
    for node in list(store.values())[:5_000]:
        if node.parent_id:
            assert node.id in store[node.parent_id].children_ids


def _manifests(cache: Path) -> list[dict[str, object]]:
    return [
        json.loads(path.read_text())
        for path in sorted(cache.glob("fy*/**/manifest.json"))
    ]


@pytest.mark.live_cms
@pytest.mark.live_current
def test_latest_complete_snapshot_fresh_download_parses_all_materials(
    fresh_cache: Path,
) -> None:
    release = latest_complete_release(catalog_entries())
    kb = ICD10KnowledgeBase.from_cms(
        release_date=release.release_date,
        cache_dir=fresh_cache,
    )

    _assert_tabular_integrity(kb.cm.tabular, system="cm")
    assert kb.cm["I10"].assignable
    assert len(kb.cm.index) > 1_000
    assert {term.source for term in kb.cm.index.values()} >= {
        "",
        "Drug",
        "External Cause",
        "Neoplasm",
    }
    assert len(kb.cm.guidelines) > 10
    assert {"I", "II", "III", "IV"} <= set(kb.cm.guidelines.titles)

    _assert_tabular_integrity(kb.pcs.tabular, system="pcs")
    assert len(kb.pcs.index) > 1_000
    assert kb.pcs.guidelines["document"].content.strip()
    assert len(kb.pcs.guidelines["document"].content) > 10_000

    manifests = _manifests(fresh_cache)
    assert {(item["system"], item["material"]) for item in manifests} == {
        ("cm", "tabular"),
        ("cm", "index"),
        ("cm", "guidelines"),
        ("pcs", "tabular"),
        ("pcs", "index"),
        ("pcs", "guidelines"),
    }
    assert all(len(str(item["sha256"])) == 64 for item in manifests)
    assert all(item["file_sha256"] for item in manifests)
    write_diagnostic(
        "current-release.json",
        {"release": release, "manifests": manifests},
    )
