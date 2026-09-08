from __future__ import annotations

import re
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
from cms_icd.models import Code, Node, Term
from cms_icd.parsers import parse_cm_tabular, parse_index, parse_pcs_tabular
from cms_icd.stores import IndexStore, TabularStore

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
<ICD10PCS.tabular>
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
</ICD10PCS.tabular>
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


INDEX_CELL_XML = """\
<ICD10CM.index>
  <indexHeading>
    <head col="1">Code</head>
  </indexHeading>
  <letter>
    <title>H</title>
    <mainTerm>
      <title>Hypertension (arterial)</title>
      <cell col="1">I10</cell>
    </mainTerm>
  </letter>
</ICD10CM.index>
"""


INDEX_RANGE_XML = """\
<ICD10CM.index>
  <indexHeading>
    <head col="1">Code</head>
  </indexHeading>
  <letter>
    <title>A</title>
    <mainTerm>
      <title>Code range</title>
      <code>A00-A09</code>
    </mainTerm>
  </letter>
  <letter>
    <title>E</title>
    <mainTerm>
      <title>Manifestation range</title>
      <manif>E80.0-E80.4</manif>
    </mainTerm>
  </letter>
  <letter>
    <title>I</title>
    <mainTerm>
      <title>Cell range</title>
      <cell col="1">I10-I15</cell>
    </mainTerm>
    <mainTerm>
      <title>Single code</title>
      <code>I10</code>
    </mainTerm>
    <mainTerm>
      <title>Single manifestation</title>
      <manif>I15.9</manif>
    </mainTerm>
    <mainTerm>
      <title>Single cell</title>
      <cell col="1">I10.</cell>
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


def test_pcs_parser_axis_non_numeric_values_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "icd10pcs_tables.xml"
    path.write_text(PCS_XML.replace('values="2"', 'values="abc"'))

    with pytest.raises(ParseError, match=re.escape(path.name)):
        parse_pcs_tabular(path)


def test_pcs_parser_row_non_numeric_codes_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "icd10pcs_tables.xml"
    path.write_text(PCS_XML.replace('codes="2"', 'codes="abc"'))

    with pytest.raises(ParseError, match=re.escape(path.name)):
        parse_pcs_tabular(path)


def test_index_parser_preserves_direct_children_and_modifiers(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_XML)
    store = parse_index((path,), system="cm")

    main = store.main_terms()[0]
    child = store.children(main.id)[0]
    assert main.title == "Hypertension"
    assert main.optional_modifiers == ("arterial",)
    assert child.path == "Hypertension, secondary"


def test_index_parser_reads_numbered_cells(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_CELL_XML)

    store = parse_index((path,), system="cm")
    main = store.main_terms()[0]
    cell = store.children(main.id)[0]
    assert cell.title == "Code"
    assert cell.code == "I10"


def test_index_parser_cell_missing_col_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_CELL_XML.replace('<cell col="1">', "<cell>"))

    with pytest.raises(ParseError, match=re.escape(path.name)):
        parse_index((path,), system="cm")


def test_index_parser_cell_non_numeric_col_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_CELL_XML.replace('<cell col="1">', '<cell col="abc">'))

    with pytest.raises(ParseError, match=re.escape(path.name)):
        parse_index((path,), system="cm")


def test_index_parser_cell_duplicate_col_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(
        INDEX_CELL_XML.replace(
            '<cell col="1">I10</cell>',
            '<cell col="1">I10</cell>\n      <cell col="1">I20</cell>',
        )
    )

    with pytest.raises(ParseError) as excinfo:
        parse_index((path,), system="cm")

    message = str(excinfo.value)
    assert path.name in message
    assert "Hypertension" in message


def test_index_parser_head_missing_col_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_CELL_XML.replace('<head col="1">', "<head>"))

    with pytest.raises(ParseError, match=re.escape(path.name)):
        parse_index((path,), system="cm")


def test_index_parser_head_non_numeric_col_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_CELL_XML.replace('<head col="1">', '<head col="abc">'))

    with pytest.raises(ParseError, match=re.escape(path.name)):
        parse_index((path,), system="cm")


def test_index_parser_preserves_raw_ranges_without_concatenation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_RANGE_XML)

    store = parse_index((path,), system="cm")
    terms = {term.title: term for term in store.values()}

    code_range = terms["Code range"]
    assert code_range.code == "A00-A09"
    assert code_range.assignable is False
    manifestation_range = terms["Manifestation range"]
    assert manifestation_range.code is None
    assert manifestation_range.manifestation_code == "E80.0-E80.4"
    assert manifestation_range.assignable is False
    cell = store.children(terms["Cell range"].id)[0]
    assert cell.code == "I10-I15"
    assert cell.assignable is False


def test_index_parser_single_values_keep_existing_behavior(
    tmp_path: Path,
) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_RANGE_XML)

    store = parse_index((path,), system="cm")
    terms = {term.title: term for term in store.values()}

    assert terms["Single code"].code == "I10"
    assert terms["Single code"].assignable is True
    assert terms["Single manifestation"].code is None
    assert terms["Single manifestation"].manifestation_code == "I15.9"
    assert terms["Single manifestation"].assignable is True
    cell = store.children(terms["Single cell"].id)[0]
    assert cell.code == "I10"
    assert cell.assignable is True


def test_get_assignable_terms_never_resolve_to_no_codes(
    tmp_path: Path,
) -> None:
    from cms_icd.knowledge_base import ICD10CMKnowledgeBase
    from cms_icd.models import Code, Node
    from cms_icd.stores import TabularStore

    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_RANGE_XML)
    index = parse_index((path,), system="cm")

    root = Node("cm", "cm", children_ids=("I10", "I15"))
    i10 = Code("I10", "I10", parent_id="cm")
    i15 = Node("I15", "I15", parent_id="cm", children_ids=("I15.9",))
    i15_9 = Code("I15.9", "I15.9", parent_id="I15")
    tabular = TabularStore(
        {node.id: node for node in (root, i10, i15, i15_9)},
        {"I10": "I10", "I15.9": "I15.9"},
        ("cm",),
    )
    kb = ICD10CMKnowledgeBase.from_stores(tabular=tabular, index=index)

    assert kb.get_assignable_terms()
    for term in kb.get_assignable_terms():
        assert kb.get_term_codes(term.id), term


def test_cm_tabular_rejects_pcs_tables_file(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_tabular.xml"
    path.write_text(PCS_XML)

    with pytest.raises(ParseError) as excinfo:
        parse_cm_tabular(path)

    message = str(excinfo.value)
    assert path.name in message
    assert "ICD10CM.tabular" in message
    assert "ICD10PCS.tabular" in message


def test_pcs_tabular_rejects_cm_tabular_file(tmp_path: Path) -> None:
    path = tmp_path / "icd10pcs_tables.xml"
    path.write_text(CM_XML)

    with pytest.raises(ParseError) as excinfo:
        parse_pcs_tabular(path)

    message = str(excinfo.value)
    assert path.name in message
    assert "ICD10PCS.tabular" in message
    assert "ICD10CM.tabular" in message


def test_cm_tabular_rejects_file_without_chapters(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_tabular.xml"
    path.write_text("<ICD10CM.tabular>\n</ICD10CM.tabular>\n")

    with pytest.raises(ParseError, match=re.escape(path.name)):
        parse_cm_tabular(path)


def test_pcs_tabular_rejects_file_without_tables(tmp_path: Path) -> None:
    path = tmp_path / "icd10pcs_tables.xml"
    path.write_text("<ICD10PCS.tabular>\n</ICD10PCS.tabular>\n")

    with pytest.raises(ParseError, match=re.escape(path.name)):
        parse_pcs_tabular(path)


def test_index_rejects_pcs_tables_root(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(PCS_XML)

    with pytest.raises(ParseError) as excinfo:
        parse_index((path,), system="cm")

    message = str(excinfo.value)
    assert path.name in message
    assert "ICD10CM.index" in message
    assert "ICD10PCS.tabular" in message


def test_index_rejects_cross_system_root(tmp_path: Path) -> None:
    path = tmp_path / "icd10pcs_index.xml"
    path.write_text(INDEX_XML)

    with pytest.raises(ParseError) as excinfo:
        parse_index((path,), system="pcs")

    message = str(excinfo.value)
    assert path.name in message
    assert "ICD10PCS.index" in message
    assert "ICD10CM.index" in message


def test_index_rejects_file_without_terms(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text("<ICD10CM.index>\n</ICD10CM.index>\n")

    with pytest.raises(ParseError, match=re.escape(path.name)):
        parse_index((path,), system="cm")


@pytest.mark.parametrize(
    ("filename", "source"),
    [
        ("e-index.xml", "External Cause"),
        ("E-Index.xml", "External Cause"),
        ("icd10cm_eindex_2026.xml", "External Cause"),
        ("icd10cm_index_2026.xml", ""),
        ("icd10cm_neoplasm_2026.xml", "Neoplasm"),
        ("icd10cm_drug_2026.xml", "Drug"),
    ],
)
def test_index_parser_classifies_index_source_by_filename(
    tmp_path: Path,
    filename: str,
    source: str,
) -> None:
    path = tmp_path / filename
    path.write_text(INDEX_XML)
    store = parse_index((path,), system="cm")

    assert store.main_terms()[0].source == source


INDEX_XML_WITH_CELLS = """\
<ICD10CM.index>
  <letter>
    <title>F</title>
    <mainTerm>
      <title>Fever</title>
      <cell col="1">R50.9</cell>
      <term>
        <title>with rash</title>
        <cell col="1">R05.9</cell>
        <term>
          <title>chronic</title>
          <cell col="2">R69.0</cell>
        </term>
      </term>
    </mainTerm>
  </letter>
</ICD10CM.index>
"""


def test_main_term_id_resolves_cells_at_any_depth(tmp_path: Path) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_XML_WITH_CELLS)
    store = parse_index((path,), system="cm")

    main = store.main_terms()[0]
    assert {term.id for term in store.values()} == {
        "000001",
        "000001X1",
        "000001.0",
        "000001.0X1",
        "000001.0.0",
        "000001.0.0X2",
    }
    assert all(term.main_term_id == main.id for term in store.values())


def test_index_parser_children_ids_are_tuples_equal_to_hand_built_store(
    tmp_path: Path,
) -> None:
    path = tmp_path / "icd10cm_index.xml"
    path.write_text(INDEX_XML_WITH_CELLS)

    store = parse_index((path,), system="cm")

    assert len(store) == 6
    for term in store.values():
        assert type(term.children_ids) is tuple

    expected = IndexStore(
        {
            term.id: term
            for term in (
                Term(
                    "000001",
                    "Fever",
                    children_ids=("000001X1", "000001.0"),
                    path="Fever",
                ),
                Term(
                    "000001X1",
                    "Column 1",
                    parent_id="000001",
                    path="Fever, Column 1",
                    code="R50.9",
                    assignable=True,
                ),
                Term(
                    "000001.0",
                    "with rash",
                    parent_id="000001",
                    children_ids=("000001.0X1", "000001.0.0"),
                    path="Fever, with rash",
                ),
                Term(
                    "000001.0X1",
                    "Column 1",
                    parent_id="000001.0",
                    path="Fever, with rash, Column 1",
                    code="R05.9",
                    assignable=True,
                ),
                Term(
                    "000001.0.0",
                    "chronic",
                    parent_id="000001.0",
                    children_ids=("000001.0.0X2",),
                    path="Fever, with rash, chronic",
                ),
                Term(
                    "000001.0.0X2",
                    "Column 2",
                    parent_id="000001.0.0",
                    path="Fever, with rash, chronic, Column 2",
                    code="R69.0",
                    assignable=True,
                ),
            )
        }
    )
    assert store == expected


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


class _PcsPage:
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
            "ICD-10-PCS Official Guidelines",
            identity,
            (1.0, 0.0, 0.0, 1.0, 10.0, -20.0),
            None,
            10.0,
        )
        return (
            "ICD-10-PCS Official Guidelines for Coding and Reporting\n"
            "FY 2026\n"
            "Page 1 of 2\n"
            "Body cites the ICD-10-PCS Official Guidelines for Coding and Reporting.\n"
            "Page 1 of 2\n"
        )


class _Destination:
    def __init__(self, title: str, page: int | None) -> None:
        self.title = title
        self.page = page


class _Reader:
    def __init__(self) -> None:
        container = _Destination("Structure Bookmarks", None)
        first = _Destination("Section I. Conventions", 0)
        child = _Destination("A. Basic conventions", 1)
        self.outline = [container, first, [child]]

    def get_destination_page_number(self, destination: _Destination) -> int | None:
        return destination.page


class _TaggedReader:
    def __init__(self) -> None:
        self.pages = [
            ("Section I. Conventions\nA. Basic conventions\n1. First rule\nRule body"),
            "Section II. Selection\nSelection body",
        ]
        self.outline = [
            _Destination("Structure Bookmarks", None),
            [
                _Destination("Section I. Conventions ........ 1", 0),
                _Destination("Section I. Conventions", 0),
                [
                    _Destination("A. Basic conventions", 0),
                    [_Destination("1. First rule", 0)],
                ],
                _Destination("Section I. Conventions", 0),
                [
                    _Destination("A. Basic conventions", 0),
                    [_Destination("1. First rule", 0)],
                ],
                _Destination("Section II. Selection", 1),
            ],
        ]

    def get_destination_page_number(self, destination: _Destination) -> int | None:
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


def test_guideline_page_text_removes_pcs_running_header() -> None:
    text = _page_text(_PcsPage(), "pcs")  # type: ignore[arg-type]

    assert text == (
        "Body cites the ICD-10-PCS Official Guidelines for Coding and Reporting."
    )


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


def test_cm_guidelines_accept_tagged_outline_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cms_icd.guidelines._page_text",
        lambda page: page,
    )

    store = _structured_cm_guidelines(  # type: ignore[arg-type]
        _TaggedReader(), "guidelines.pdf"
    )

    assert store.titles == {
        "I": "Conventions",
        "I.A": "Basic conventions",
        "I.A.1": "First rule",
        "II": "Selection",
    }
    assert set(store) == {"I.A.1", "II"}
    assert store["I.A.1"].content == "Rule body"
    assert store["II"].content == "Selection body"


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


def test_guideline_page_text_joins_only_plausible_code_shapes() -> None:
    page = _GuidelinePage(
        "Administer a dose of A 100 mg with water.\n"
        "See table A 10. for details.\n"
        "Vitamin E 400 IU was given.\n"
        "Code I 10.9 applies here.\n"
        "Group I 10 is referenced.\n"
    )

    text = _page_text(page)  # type: ignore[arg-type]

    assert text == (
        "Administer a dose of A 100 mg with water.\n"
        "See table A 10. for details.\n"
        "Vitamin E 400 IU was given.\n"
        "Code I10.9 applies here.\n"
        "Group I10 is referenced."
    )


class _BareSectionRuleReader:
    """A numbered rule listed directly under a section without a lettered subsection."""

    def __init__(self) -> None:
        self.pages = [
            _GuidelinePage("Section I. Conventions\n1. First rule\nRule body"),
        ]
        self.outline = [
            _Destination("Section I. Conventions", 0),
            [_Destination("1. First rule", 0)],
        ]

    def get_destination_page_number(self, destination: _Destination) -> int:
        return destination.page


def test_cm_guidelines_parse_numbered_rule_under_bare_section() -> None:
    reader = _BareSectionRuleReader()
    store = _structured_cm_guidelines(  # type: ignore[arg-type]
        reader, "guidelines.pdf"
    )

    assert store.titles == {"I": "Conventions", "I.1": "First rule"}
    assert set(store) == {"I.1"}
    assert store["I.1"].content == "Rule body"


class _MissingHeadingReader:
    """An outline leaf whose heading text is absent from the extracted page text."""

    def __init__(self) -> None:
        self.pages = [
            _GuidelinePage(
                "Section I. Conventions\n"
                "A. Basic conventions\n"
                "Orphan body of the missing rule.\n"
                "2. Second rule\n"
                "Body of second rule."
            ),
        ]
        self.outline = [
            _Destination("Section I. Conventions", 0),
            [
                _Destination("A. Basic conventions", 0),
                [
                    _Destination("1. Zephyr rule", 0),
                    _Destination("2. Second rule", 0),
                ],
            ],
        ]

    def get_destination_page_number(self, destination: _Destination) -> int:
        return destination.page


def test_cm_guidelines_reject_unlocatable_entry_heading() -> None:
    reader = _MissingHeadingReader()

    with pytest.raises(
        ParseError,
        match=re.escape("Could not locate guideline entry I.A.1"),
    ):
        _structured_cm_guidelines(reader, "guidelines.pdf")  # type: ignore[arg-type]
