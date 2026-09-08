from __future__ import annotations

import sys
import threading
from datetime import date
from typing import TYPE_CHECKING

import pytest

from cms_icd import knowledge_base
from cms_icd.knowledge_base import ICD10CMKnowledgeBase, ICD10KnowledgeBase
from cms_icd.models import Code, Guideline, Node, Release, Term
from cms_icd.sources import MaterialProvider
from cms_icd.stores import GuidelineStore, IndexStore, TabularStore

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


def test_from_cms_selects_initial_revision_from_fiscal_year() -> None:
    kb = ICD10KnowledgeBase.from_cms(fiscal_year=2026)

    assert kb.release == Release(2026, date(2025, 10, 1))


@pytest.mark.parametrize(
    ("release_date", "fiscal_year"),
    [
        (date(2025, 9, 30), 2025),
        (date(2025, 10, 1), 2026),
        (date(2026, 4, 1), 2026),
    ],
)
def test_from_cms_infers_fiscal_year_from_release_date(
    release_date: date,
    fiscal_year: int,
) -> None:
    kb = ICD10KnowledgeBase.from_cms(release_date=release_date)

    assert kb.release == Release(fiscal_year, release_date)


def test_from_cms_requires_exactly_one_selector() -> None:
    with pytest.raises(TypeError, match="exactly one"):
        ICD10KnowledgeBase.from_cms()
    with pytest.raises(TypeError, match="exactly one"):
        ICD10KnowledgeBase.from_cms(
            fiscal_year=2026,
            release_date=date(2026, 4, 1),
        )


def test_from_cms_rejects_removed_year_alias() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'year'"):
        ICD10KnowledgeBase.from_cms(year=2026)  # type: ignore[call-arg]


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


def test_membership_and_term_codes_agree_with_by_code_dot_tolerance() -> None:
    root = Node("cm", "cm", children_ids=("I20",))
    i20 = Code(
        "I20",
        "I20",
        parent_id="cm",
        assignable=False,
        children_ids=("I20.9", "I20.1"),
    )
    i20_9 = Code("I20.9", "I20.9", "Hypertension, unspecified", parent_id="I20")
    i20_1 = Code(
        "I20.1",
        "I20.1",
        "Hypertensive heart disease with heart failure",
        parent_id="I20",
        assignable=False,
        children_ids=("I20.10",),
    )
    i20_10 = Code("I20.10", "I20.10", "Acute left heart failure", parent_id="I20.1")
    nodes = (root, i20, i20_9, i20_1, i20_10)
    tabular = TabularStore(
        {node.id: node for node in nodes},
        {node.name: node.id for node in nodes if isinstance(node, Code)},
        ("cm",),
    )
    index = IndexStore(
        {
            "compact": Term("compact", "Hypertension, unspecified", code="I209"),
            "dotted": Term("dotted", "Hypertension, unspecified", code="I20.9"),
            "trailing": Term("trailing", "Hypertension, unspecified", code="I20.9."),
            "compact_category": Term("compact_category", "Heart failure", code="I201"),
            "raw_category": Term("raw_category", "Hypertension", code="I20"),
            "dangling": Term("dangling", "Unknown", code="X999"),
        }
    )
    kb = ICD10CMKnowledgeBase.from_stores(tabular=tabular, index=index)

    # by_code resolves dotted, compact, and trailing-dot forms to one Code.
    assert kb["I20.9"] is kb["I209"]
    assert kb["I20.9"] is kb["I20.9."]

    # Membership agrees with item access for every dot form.
    for member in ("I20", "I20.1", "I20.10", "I20.9", "I209", "I201", "I20.9."):
        assert member in kb
    for non_member in ("cm", "I2090", "X999"):
        assert non_member not in kb
    assert 209 not in kb

    # get_term_codes accepts the same forms and skips unresolvable values.
    assert kb.get_term_codes("compact") == ["I20.9"]
    assert kb.get_term_codes("dotted") == ["I20.9"]
    assert kb.get_term_codes("trailing") == ["I20.9"]
    assert kb.get_term_codes("compact_category") == ["I20.10"]
    assert kb.get_term_codes("raw_category") == ["I20.10", "I20.9"]
    assert kb.get_term_codes("dangling") == []
