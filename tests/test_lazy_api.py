from __future__ import annotations

import sys
import threading
from datetime import date
from typing import TYPE_CHECKING

import pytest

from cms_icd import knowledge_base
from cms_icd.knowledge_base import ICD10CMKnowledgeBase, ICD10KnowledgeBase
from cms_icd.models import Guideline, Release
from cms_icd.sources import MaterialProvider
from cms_icd.stores import GuidelineStore

if TYPE_CHECKING:
    from pathlib import Path

    from cms_icd.stores import TabularStore


class RecordingProvider(MaterialProvider):
    def __init__(self, files: dict[tuple[str, str], tuple[Path, ...]]) -> None:
        self.files = files
        self.release = Release(2026, date(2025, 10, 1))
        self.calls: list[tuple[str, str]] = []

    def paths(self, system: str, material: str) -> tuple[Path, ...]:
        self.calls.append((system, material))
        return self.files[(system, material)]


def test_repr_and_view_access_do_not_acquire_material() -> None:
    provider = RecordingProvider({})
    kb = ICD10KnowledgeBase(provider)
    assert "loaded=[]" in repr(kb)
    assert kb.cm.release == provider.release
    assert provider.calls == []


def test_tabular_access_loads_only_requested_system_and_material(
    tmp_path: Path,
) -> None:
    cm = tmp_path / "icd10cm_tabular.xml"
    cm.write_text(
        "<ICD10CM.tabular><chapter><name>1</name><desc>A</desc>"
        '<section id="A00-A00"><desc>B</desc><diag><name>A00</name>'
        "<desc>Cholera</desc></diag></section></chapter></ICD10CM.tabular>"
    )
    provider = RecordingProvider({("cm", "tabular"): (cm,)})
    kb = ICD10KnowledgeBase(provider)

    assert kb.cm["A00"].description == "Cholera"
    assert provider.calls == [("cm", "tabular")]
    assert kb.cm["A00"].description == "Cholera"
    assert provider.calls == [("cm", "tabular")]


def test_render_guidelines_cache_is_bounded_and_preserves_semantics() -> None:
    sections = {
        f"I.A.{number}": Guideline(
            id=f"I_A_{number}",
            number=f"I.A.{number}",
            title=f"Title {number}",
            content=f"Body {number}",
        )
        for number in range(1, 101)
    }
    cm = ICD10CMKnowledgeBase.from_stores(
        guidelines=GuidelineStore(sections, {"I": "Roman", "I.A": "Letter"})
    )

    rendered = cm.render_guidelines(["I.A.5"])
    assert rendered.id == "combined"
    assert rendered.title == "Guidelines"
    assert rendered.content == (
        "# I: Roman\n\n## I.A: Letter\n\n### I.A.5: Title 5\n\nBody 5"
    )
    assert cm.render_guidelines(["I.A.5"]) is rendered

    for number in range(1, 101):
        assert f"Body {number}" in cm.render_guidelines([f"I.A.{number}"]).content
    assert 0 < len(cm._render_cache) < 100

    with pytest.raises(KeyError, match="MISSING"):
        cm.render_guidelines(["MISSING"])


def test_cm_and_pcs_view_creation_is_race_free(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cm = tmp_path / "icd10cm_tabular.xml"
    cm.write_text(
        "<ICD10CM.tabular><chapter><name>1</name><desc>A</desc>"
        '<section id="A00-A00"><desc>B</desc><diag><name>A00</name>'
        "<desc>Cholera</desc></diag></section></chapter></ICD10CM.tabular>"
    )
    pcs = tmp_path / "icd10pcs_tables.xml"
    pcs.write_text(
        "<ICD10PCS.tabular><pcsTable>"
        '<axis><label code="0">Section</label><title>Section</title></axis>'
        '<pcsRow><axis values="1"><title>Section</title>'
        '<label code="0">Medical and Surgical</label></axis></pcsRow>'
        "</pcsTable></ICD10PCS.tabular>"
    )
    kb = ICD10KnowledgeBase.from_directory(
        tmp_path,
        fiscal_year=2026,
        release_date=date(2025, 10, 1),
    )

    cm_loads: list[Path] = []
    pcs_loads: list[Path] = []
    parse_cm_tabular = knowledge_base.parse_cm_tabular
    parse_pcs_tabular = knowledge_base.parse_pcs_tabular

    def counting_cm(path: Path) -> TabularStore:
        cm_loads.append(path)
        return parse_cm_tabular(path)

    def counting_pcs(path: Path) -> TabularStore:
        pcs_loads.append(path)
        return parse_pcs_tabular(path)

    monkeypatch.setattr(knowledge_base, "parse_cm_tabular", counting_cm)
    monkeypatch.setattr(knowledge_base, "parse_pcs_tabular", counting_pcs)

    cm_views: list[object] = []
    pcs_views: list[object] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        cm_view = kb.cm
        pcs_view = kb.pcs
        cm_views.append(cm_view)
        pcs_views.append(pcs_view)
        _ = cm_view.tabular
        _ = pcs_view.tabular

    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-4)
    try:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        sys.setswitchinterval(previous_interval)

    assert cm_views[0] is cm_views[1]
    assert pcs_views[0] is pcs_views[1]
    assert len(cm_loads) == 1
    assert len(pcs_loads) == 1
