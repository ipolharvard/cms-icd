from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from cms_icd.knowledge_base import ICD10CMKnowledgeBase, ICD10KnowledgeBase
from cms_icd.models import Guideline, Release
from cms_icd.sources import MaterialProvider
from cms_icd.stores import GuidelineStore

if TYPE_CHECKING:
    from pathlib import Path


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
