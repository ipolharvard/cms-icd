from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pypdf import PdfWriter

from cms_icd.exceptions import ParseError
from cms_icd.guidelines import (
    _outline_entries,
    _page_text,
    _structured_cm_guidelines,
    _text_position,
    parse_guidelines,
)
from cms_icd.knowledge_base import ICD10CMKnowledgeBase
from cms_icd.models import Code, Node
from cms_icd.parsers import parse_cm_tabular, parse_index, parse_pcs_tabular
from cms_icd.stores import TabularStore

if TYPE_CHECKING:
    from pathlib import Path

CM_XML = """\
<ICD10CM.tabular>
  <chapter>
    <name>9</name>
    <desc>Diseases of the circulatory system</desc>
    <notes><note>chapter instruction</note></notes>
    <section id="I10-I16">
      <desc>Hypertensive diseases</desc>
      <diag>
        <name>I10</name>
        <desc>Essential hypertension</desc>
        <includes><note>high blood pressure</note></includes>
      </diag>
    </section>
  </chapter>
</ICD10CM.tabular>
"""


PCS_XML = """\
<ICD10PCS>
  <pcsTable>
    <axis pos="1"><title>Section</title><label code="0">Medical</label></axis>
    <axis pos="2"><title>Body System</title><label code="A">Nervous</label></axis>
    <axis pos="3"><title>Operation</title><label code="B">Excision</label></axis>
    <pcsRow codes="2">
      <axis pos="4" values="2">
        <title>Body Part</title>
        <label code="0">Brain</label>
        <label code="1">Meninges</label>
      </axis>
    </pcsRow>
  </pcsTable>
</ICD10PCS>
"""


INDEX_XML = """\
<ICD10CM.index>
  <letter>
    <title>H</title>
    <mainTerm>
      <title>Hypertension (arterial)</title>
      <code>I10</code>
      <term><title>secondary</title><code>I15.9</code></term>
    </mainTerm>
  </letter>
</ICD10CM.index>
"""


def test_cm_parser_builds_direct_hierarchy_and_notes(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_tabular.xml"
    path.write_text(CM_XML)

    store = parse_cm_tabular(path)

    assert [node.id for node in store.children("cm")] == ["cm_9"]
    assert [node.id for node in store.children("cm_9")] == ["cm_9_I10-I16"]
    assert [node.name for node in store.leaves("cm")] == ["I10"]
    assert store["cm_9"].notes == ("chapter instruction",)
    assert store.by_code("I10").includes == ("high blood pressure",)


def test_pcs_parser_validates_and_generates_combinations(tmp_path: Path) -> None:
    path = tmp_path / "icd10pcs_tables.xml"
    path.write_text(PCS_XML)
    store = parse_pcs_tabular(path)
    assert [node.name for node in store.leaves("pcs")] == ["0AB0", "0AB1"]

    bad_path = tmp_path / "bad_icd10pcs_tables.xml"
    bad_path.write_text(PCS_XML.replace('codes="2"', 'codes="3"'))
    with pytest.raises(ParseError, match="declares 3 codes but defines 2 combinations"):
        parse_pcs_tabular(bad_path)


def test_index_parser_preserves_direct_children_and_modifiers(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_XML)
    store = parse_index((path,), system="cm")

    main = store.main_terms()[0]
    child = store.children(main.id)[0]
    assert main.title == "Hypertension"
    assert main.optional_modifiers == ("arterial",)
    assert child.path == "Hypertension, secondary"


class _MediaBox:
    height = 1_000


class _Page:
    mediabox = _MediaBox()

    def extract_text(self, *, visitor_text):
        identity = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        visitor_text(
            "Page 1 of 2",
            identity,
            (1.0, 0.0, 0.0, 1.0, 10.0, 20.0),
            None,
            10.0,
        )
        visitor_text(
            "ICD-10-CM Official Guidelines",
            identity,
            (1.0, 0.0, 0.0, 1.0, 10.0, -20.0),
            None,
            10.0,
        )
        return (
            "ICD-10-CM Official Guidelines for Coding and Reporting\n"
            "FY 2026\n"
            "Page 1 of 2\n"
            "Body cites the ICD-10-CM Official Guidelines.\n"
            "Page 1 of 2\n"
        )


class _Destination:
    def __init__(self, title: str, page: int) -> None:
        self.title = title
        self.page = page


class _Reader:
    def __init__(self) -> None:
        first = _Destination("Section I. Conventions", 0)
        child = _Destination("A. Basic conventions", 1)
        self.outline = [first, [child]]

    def get_destination_page_number(self, destination: _Destination) -> int:
        return destination.page


class _GuidelinePage:
    """A guideline page whose extracted text is fully controlled by a test."""

    mediabox = _MediaBox()

    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self, *, visitor_text):
        return self._text


class _GuidelineReader:
    def __init__(self, pages: list[_GuidelinePage]) -> None:
        self.outline = [
            _Destination("Section I. Conventions", 0),
            [
                _Destination("A. Basic conventions", 1),
                [
                    _Destination("1. First rule", 1),
                    _Destination("2. Second rule", 1),
                ],
                _Destination("C. Coding rules", 1),
                [_Destination("9. Ninth rule", 1)],
            ],
        ]
        self.pages = pages

    def get_destination_page_number(self, destination: _Destination) -> int:
        return destination.page


def test_guideline_page_text_removes_only_positioned_footer() -> None:
    text = _page_text(_Page())  # type: ignore[arg-type]

    assert text == "Body cites the ICD-10-CM Official Guidelines."


def test_text_position_applies_page_transformation() -> None:
    assert _text_position(
        (1.0, 0.0, 0.0, 1.0, 4.0, 5.0),
        (2.0, 0.0, 0.0, 3.0, 10.0, 20.0),
    ) == (18.0, 35.0)


def test_guideline_outline_preserves_nested_levels_and_one_based_pages() -> None:
    assert list(_outline_entries(_Reader())) == [  # type: ignore[arg-type]
        (1, "Section I. Conventions", 1),
        (2, "A. Basic conventions", 2),
    ]


def test_cm_guideline_parser_requires_structured_outline(tmp_path: Path) -> None:
    path = tmp_path / "guidelines.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(ParseError, match="No structured CM guideline outline"):
        parse_guidelines(path, system="cm")


def test_guideline_parser_rejects_unknown_system(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported guideline system"):
        parse_guidelines(tmp_path / "unused.pdf", system="icd9")


def test_cm_guideline_leaf_content_excludes_its_own_heading() -> None:
    pages = (
        _GuidelinePage(
            "Section I. Conventions\nIntroductory text for the conventions section.\n"
        ),
        _GuidelinePage(
            "A. Basic conventions\n"
            "1. First rule\n"
            "Body of first rule.\n"
            "2. Second rule\n"
            "Body of second rule.\n"
            "C. Coding rules\n"
            "9. Ninth rule\n"
            "Body of ninth rule.\n"
        ),
    )
    reader = _GuidelineReader(list(pages))
    store = _structured_cm_guidelines(
        reader,
        "guidelines.pdf",  # type: ignore[arg-type]
    )

    assert store["I.A.1"].content == "Body of first rule."
    assert store["I.A.2"].content == "Body of second rule."
    assert store["I.C.9"].content == "Body of ninth rule."
    assert store.preambles["I"] == "Introductory text for the conventions section."

    cm = ICD10CMKnowledgeBase.from_stores(guidelines=store)
    rendered = cm.render_guidelines(["I.A.1"]).content
    assert rendered.count("### I.A.1: First rule") == 1
    assert "1. First rule" not in rendered
    assert rendered.count("First rule") == 1

    root = Node("cm", "cm", children_ids=("cm_9",))
    chapter = Node("cm_9", "9", parent_id="cm")
    code = Code("I10", "I10", "Essential hypertension", parent_id="cm_9")
    tabular = TabularStore(
        {"cm": root, "cm_9": chapter, "I10": code},
        {"I10": "I10"},
        ("cm",),
    )
    chapter_cm = ICD10CMKnowledgeBase.from_stores(tabular=tabular, guidelines=store)
    chapter_rendered = chapter_cm.get_chapter_guidelines(["I10"]).content
    assert chapter_rendered.count("### I.C.9: Ninth rule") == 1
    assert "9. Ninth rule" not in chapter_rendered
    assert chapter_rendered.count("Ninth rule") == 1
