"""Parsers for CMS ICD XML and text materials.

Parser functions validate relationships before returning immutable stores. They do not
mutate public knowledge-base objects.
"""

from __future__ import annotations

import itertools
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import reduce
from operator import mul
from pathlib import Path
from typing import TYPE_CHECKING

from .exceptions import ParseError
from .models import Code, GEMDirection, GEMEntry, Node, Release, Term
from .stores import GEMStore, IndexStore, TabularStore

if TYPE_CHECKING:
    from collections.abc import Iterable


_GEM_FILENAMES: dict[tuple[str, GEMDirection], tuple[str, ...]] = {
    ("cm", GEMDirection.ICD9_TO_ICD10): ("i9gem",),
    ("cm", GEMDirection.ICD10_TO_ICD9): ("i10gem",),
    ("pcs", GEMDirection.ICD9_TO_ICD10): ("i9pcs",),
    ("pcs", GEMDirection.ICD10_TO_ICD9): ("pcsi9",),
}


def parse_gems(
    paths: Iterable[str | Path],
    *,
    system: str,
    direction: GEMDirection,
    release: Release | None = None,
) -> GEMStore:
    """Parse one official CMS General Equivalence Mapping direction.

    Codes remain strings so leading zeroes are preserved. Exactly one supplied file must
    match the requested system and direction.
    """
    if system not in {"cm", "pcs"}:
        raise ValueError(f"Unsupported GEM system: {system!r}")
    markers = _GEM_FILENAMES[(system, direction)]
    matches = [
        Path(path)
        for path in paths
        if any(marker in Path(path).name.lower() for marker in markers)
    ]
    if len(matches) != 1:
        raise ParseError(
            f"Expected one {system.upper()} {direction.value} GEM file, "
            f"found {[path.name for path in matches]}"
        )

    grouped: dict[str, list[GEMEntry]] = {}
    path = matches[0]
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ParseError(f"Unable to read GEM file {path}: {exc}") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        fields = raw_line.split()
        if len(fields) != 3 or not re.fullmatch(r"[01]{3}\d{2}", fields[-1]):
            raise ParseError(f"Invalid GEM record at {path}:{line_number}")
        source, raw_target, flags = fields
        approximate, no_map_flag, combination = (flag == "1" for flag in flags[:3])
        no_map_sentinel = (
            "noi9"
            if system == "pcs" and direction is GEMDirection.ICD10_TO_ICD9
            else ("nodx" if system == "cm" else "nopcs")
        )
        raw_target_lower = raw_target.lower()
        is_sentinel = raw_target_lower in {"nodx", "noi9", "nopcs"}
        if no_map_flag and raw_target_lower != no_map_sentinel:
            raise ParseError(
                f"GEM no-map record has an unexpected target at {path}:{line_number}"
            )
        if is_sentinel and raw_target_lower != no_map_sentinel:
            raise ParseError(f"Unexpected GEM target sentinel at {path}:{line_number}")
        if is_sentinel and not no_map_flag and no_map_sentinel != "noi9":
            raise ParseError(
                "GEM target sentinel is missing its no-map flag at "
                f"{path}:{line_number}"
            )
        # Some official reverse PCS releases encode NoI9 with 10000 rather than
        # setting the documented no-map bit. The sentinel is authoritative.
        no_map = no_map_flag or is_sentinel
        target = None if no_map else raw_target
        entry = GEMEntry(
            source=source,
            target=target,
            approximate=approximate,
            no_map=no_map,
            combination=combination,
            scenario=int(flags[3]),
            choice_list=int(flags[4]),
        )
        grouped.setdefault(source, []).append(entry)
    return GEMStore(
        {source: tuple(entries) for source, entries in grouped.items()},
        system=system,
        direction=direction,
        release=release,
    )


@dataclass(slots=True)
class _NodeDraft:
    id: str
    name: str
    description: str = ""
    parent_id: str = ""
    children_ids: list[str] = field(default_factory=list)
    assignable: bool = False
    min: str = ""
    max: str = ""
    notes: list[str] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    inclusion_term: list[str] = field(default_factory=list)
    excludes1: list[str] = field(default_factory=list)
    excludes2: list[str] = field(default_factory=list)
    use_additional_code: list[str] = field(default_factory=list)
    code_first: list[str] = field(default_factory=list)
    code_also: list[str] = field(default_factory=list)

    def freeze(self) -> Node:
        common = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parent_id": self.parent_id,
            "children_ids": tuple(self.children_ids),
            "assignable": self.assignable,
            "min": self.min,
            "max": self.max,
            "notes": tuple(self.notes),
            "includes": tuple(self.includes),
            "inclusion_term": tuple(self.inclusion_term),
            "excludes1": tuple(self.excludes1),
            "excludes2": tuple(self.excludes2),
            "use_additional_code": tuple(self.use_additional_code),
            "code_first": tuple(self.code_first),
            "code_also": tuple(self.code_also),
        }
        if self.id in {"cm", "pcs"} or not self.name or self.name != self.id:
            return Node(**common)
        return Code(
            **common,
            etiology=bool(self.use_additional_code),
            manifestation=bool(self.code_first),
        )


def _texts(element: ET.Element, path: str) -> list[str]:
    return [
        " ".join(item.itertext()).strip() for item in element.findall(path) if item.text
    ]


def _int_attrib(
    element: ET.Element,
    name: str,
    *,
    default: int | None = None,
    path: str | Path,
    context: str,
) -> int:
    """Read an integer XML attribute, raising ParseError with file context."""
    raw = element.attrib.get(name)
    if raw is None:
        if default is not None:
            return default
        raise ParseError(f"Missing {name!r} attribute in {path} ({context})")
    try:
        return int(raw)
    except ValueError as exc:
        raise ParseError(
            f"Non-numeric {name!r} attribute {raw!r} in {path} ({context})"
        ) from exc


def _apply_cm_notes(draft: _NodeDraft, element: ET.Element) -> None:
    draft.notes = _texts(element, "notes/note")
    draft.includes = _texts(element, "includes/note")
    draft.inclusion_term = _texts(element, "inclusionTerm/note")
    draft.excludes1 = _texts(element, "excludes1/note")
    draft.excludes2 = _texts(element, "excludes2/note")
    draft.use_additional_code = _texts(element, "useAdditionalCode/note")
    draft.code_first = _texts(element, "codeFirst/note")
    draft.code_also = _texts(element, "codeAlso/note")


def _add_draft(drafts: dict[str, _NodeDraft], draft: _NodeDraft) -> None:
    if draft.id in drafts:
        raise ParseError(f"Duplicate tabular node identifier: {draft.id}")
    drafts[draft.id] = draft
    if draft.parent_id:
        try:
            drafts[draft.parent_id].children_ids.append(draft.id)
        except KeyError as exc:
            raise ParseError(
                f"Parent {draft.parent_id!r} is missing for tabular node {draft.id!r}"
            ) from exc


def _pad_seventh_character(code: str) -> str:
    while len(code.replace(".", "")) < 6:
        if "." not in code and len(code) == 3:
            code += "."
        code += "X"
    return code


def _insert_cm_diag(
    drafts: dict[str, _NodeDraft],
    element: ET.Element,
    parent_id: str,
    inherited_extensions: tuple[tuple[str, str, str], ...] = (),
) -> None:
    name = element.findtext("name", "").strip()
    if not name:
        raise ParseError("ICD-10-CM diagnosis element has no code name")
    children = element.findall("diag")
    local_extensions = tuple(
        (
            child.attrib.get("char", ""),
            (child.text or "").strip(),
            name,
        )
        for child in element.findall("sevenChrDef/extension")
    )
    extensions = local_extensions or inherited_extensions
    draft = _NodeDraft(
        id=name,
        name=name,
        description=element.findtext("desc", "").strip(),
        parent_id=parent_id,
        assignable=not children and not extensions,
        min=children[0].findtext("name", "") if children else "",
        max=children[-1].findtext("name", "") if children else "",
    )
    _apply_cm_notes(draft, element)
    _add_draft(drafts, draft)

    if (
        extensions
        and not children
        and any(parent_name in name for _, _, parent_name in extensions)
    ):
        for character, label, _ in extensions:
            extended = _pad_seventh_character(name) + character
            extension = _NodeDraft(
                id=extended,
                name=extended,
                description=f"{draft.description} ({label})",
                parent_id=name,
                assignable=True,
            )
            _apply_cm_notes(extension, element)
            _add_draft(drafts, extension)
        extensions = ()

    for child in children:
        _insert_cm_diag(drafts, child, name, extensions)


def parse_cm_tabular(path: str | Path) -> TabularStore:
    """Parse an ICD-10-CM tabular XML file.

    Args:
        path: CMS tabular XML path.

    Returns:
        A read-only tabular store with direct hierarchy relationships.
    """
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ParseError(
            f"Unable to parse ICD-10-CM tabular XML {path}: {exc}"
        ) from exc

    drafts: dict[str, _NodeDraft] = {}
    _add_draft(drafts, _NodeDraft("cm", "cm"))
    for chapter in root.findall("chapter"):
        chapter_name = chapter.findtext("name", "").strip()
        sections = chapter.findall("section")
        chapter_id = f"cm_{chapter_name}"
        chapter_draft = _NodeDraft(
            id=chapter_id,
            name=chapter_name,
            description=chapter.findtext("desc", "").strip(),
            parent_id="cm",
            min=sections[0].attrib.get("id", "").split("-")[0] if sections else "",
            max=sections[-1].attrib.get("id", "").split("-")[-1] if sections else "",
        )
        _apply_cm_notes(chapter_draft, chapter)
        _add_draft(drafts, chapter_draft)
        for section in sections:
            section_name = section.attrib.get("id", "")
            section_id = f"{chapter_id}_{section_name}"
            section_draft = _NodeDraft(
                id=section_id,
                name=section_name,
                description=section.findtext("desc", "").strip(),
                parent_id=chapter_id,
                min=section_name.split("-")[0],
                max=section_name.split("-")[-1],
            )
            _apply_cm_notes(section_draft, section)
            _add_draft(drafts, section_draft)
            for diagnosis in section.findall("diag"):
                _insert_cm_diag(drafts, diagnosis, section_id)

    values = {key: draft.freeze() for key, draft in drafts.items()}
    lookup = {
        node.name: node.id
        for node in values.values()
        if isinstance(node, Code) or node.id == "cm"
    }
    return TabularStore(values, lookup, ("cm",))


def parse_pcs_tabular(path: str | Path) -> TabularStore:
    """Parse an ICD-10-PCS tables XML file."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ParseError(
            f"Unable to parse ICD-10-PCS tables XML {path}: {exc}"
        ) from exc

    drafts: dict[str, _NodeDraft] = {}
    _add_draft(drafts, _NodeDraft("pcs", "pcs"))
    for table_number, table in enumerate(root.findall("pcsTable"), start=1):
        table_axes: list[tuple[str, str, str]] = []
        for axis in table.findall("axis"):
            label = axis.find("label")
            if label is None:
                raise ParseError(
                    f"PCS table {table_number} has an axis without a label"
                )
            table_axes.append(
                (
                    label.attrib.get("code", ""),
                    axis.findtext("title", "").strip(),
                    (label.text or "").strip(),
                )
            )
        prefix = "".join(code for code, _, _ in table_axes)
        table_id = prefix or f"pcs_table_{table_number}"
        rows = table.findall("pcsRow")
        _add_draft(
            drafts,
            _NodeDraft(
                id=table_id,
                name=table_id,
                description=f"PCS table {table_number}",
                parent_id="pcs",
            ),
        )
        for row_number, row in enumerate(rows, start=1):
            row_id = f"{table_id}_{row_number}"
            _add_draft(
                drafts,
                _NodeDraft(
                    id=row_id,
                    name=f"PCS row {row_number}",
                    description=f"PCS table {table_number}, row {row_number}",
                    parent_id=table_id,
                ),
            )
            axes: list[list[tuple[str, str]]] = []
            for axis in row.findall("axis"):
                title = axis.findtext("title", "").strip()
                labels = [
                    (
                        label.attrib.get("code", ""),
                        f"{title}: {(label.text or '').strip()}",
                    )
                    for label in axis.findall("label")
                ]
                declared = _int_attrib(
                    axis,
                    "values",
                    default=len(labels),
                    path=path,
                    context=f"PCS table {table_id}, row {row_number}, axis {title!r}",
                )
                if declared != len(labels):
                    counts = f"declares {declared} values but defines {len(labels)}"
                    raise ParseError(
                        f"PCS axis {counts} in table {table_id}, row {row_number}"
                    )
                axes.append(labels)
            expected = reduce(mul, (len(axis) for axis in axes), 1)
            declared_codes = _int_attrib(
                row,
                "codes",
                default=expected,
                path=path,
                context=f"PCS table {table_id}, row {row_number}",
            )
            if declared_codes != expected:
                raise ParseError(
                    f"PCS row declares {declared_codes} codes but defines {expected} "
                    f"combinations in table {table_id}, row {row_number}"
                )
            base_description = ". ".join(
                f"{title}: {label}" for _, title, label in table_axes
            )
            for combination in itertools.product(*axes):
                code = prefix + "".join(value for value, _ in combination)
                description = ". ".join(
                    item
                    for item in (base_description, *(label for _, label in combination))
                    if item
                )
                _add_draft(
                    drafts,
                    _NodeDraft(
                        id=code,
                        name=code,
                        description=description,
                        parent_id=row_id,
                        assignable=True,
                    ),
                )
    values = {key: draft.freeze() for key, draft in drafts.items()}
    lookup = {
        node.name: node.id
        for node in values.values()
        if isinstance(node, Code) or node.id == "pcs"
    }
    return TabularStore(values, lookup, ("pcs",))


def _extract_modifiers(title: str) -> tuple[str, tuple[str, ...]]:
    modifiers: list[str] = []
    output: list[str] = []
    depth = 0
    current: list[str] = []
    for character in title:
        if character == "(":
            if depth:
                current.append(character)
            depth += 1
        elif character == ")" and depth:
            depth -= 1
            if depth:
                current.append(character)
            elif current:
                modifiers.append("".join(current).strip())
                current = []
        elif depth:
            current.append(character)
        else:
            output.append(character)
    if depth:
        output.extend(["(", *current])
    return re.sub(r"\s+", " ", "".join(output)).strip(), tuple(modifiers)


def _index_title(element: ET.Element) -> str:
    title = element.find("title")
    return " ".join(title.itertext()).strip() if title is not None else ""


def parse_index(paths: tuple[Path, ...], *, system: str) -> IndexStore:
    """Parse CM or PCS alphabetic-index XML files."""
    drafts: dict[str, dict[str, object]] = {}
    top_counter = 0

    def insert(
        element: ET.Element,
        *,
        parent_id: str,
        identifier: str,
        headings: dict[int, str],
        source: str,
        parent_path: str,
    ) -> None:
        raw_title = _index_title(element)
        title, modifiers = _extract_modifiers(raw_title)
        cells = []
        for cell in element.findall("cell"):
            value = (cell.text or "").strip()
            if value and value != "-":
                column = _int_attrib(
                    cell, "col", path=path, context=f"index term {title!r}"
                )
                cells.append((column, value))
        code = (element.findtext("code") or "").strip() or None
        manifestation = (element.findtext("manif") or "").strip() or None
        if code and "-" in code:
            code = code.replace("-", "").rstrip(".")
            assignable = False
        else:
            assignable = bool(code or manifestation)
        term_path = ", ".join(item for item in (parent_path, title) if item)
        children: list[str] = []
        drafts[identifier] = {
            "id": identifier,
            "title": title,
            "parent_id": parent_id,
            "children_ids": children,
            "path": term_path,
            "code": code,
            "manifestation_code": manifestation,
            "assignable": assignable,
            "see": (element.findtext("see") or "").strip() or None,
            "see_also": (element.findtext("seeAlso") or "").strip() or None,
            "source": source,
            "optional_modifiers": modifiers,
        }
        if parent_id:
            drafts[parent_id]["children_ids"].append(identifier)  # type: ignore[union-attr]
        if cells:
            drafts[identifier]["code"] = None
            drafts[identifier]["assignable"] = False
            for column, value in cells:
                cell_id = f"{identifier}X{column}"
                cell_assignable = "-" not in value
                cell_code = value.replace("-", "").rstrip(".")
                drafts[cell_id] = {
                    "id": cell_id,
                    "title": headings.get(column, f"Column {column}"),
                    "parent_id": identifier,
                    "children_ids": [],
                    "path": f"{term_path}, {headings.get(column, f'Column {column}')}",
                    "code": cell_code,
                    "manifestation_code": None,
                    "assignable": cell_assignable,
                    "see": None,
                    "see_also": None,
                    "source": source,
                    "optional_modifiers": (),
                }
                children.append(cell_id)
        for child_number, child in enumerate(element.findall("term")):
            insert(
                child,
                parent_id=identifier,
                identifier=f"{identifier}.{child_number}",
                headings=headings,
                source=source,
                parent_path=term_path,
            )

    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as exc:
            raise ParseError(
                f"Unable to parse ICD-10-{system.upper()} index {path}: {exc}"
            ) from exc
        headings: dict[int, str] = {}
        for item in root.findall("indexHeading/head"):
            heading = (item.text or "").strip()
            headings[
                _int_attrib(
                    item, "col", path=path, context=f"index heading {heading!r}"
                )
            ] = heading
        source_name = path.stem.lower()
        source = (
            "Neoplasm"
            if "neoplasm" in source_name
            else "External Cause"
            if "eindex" in source_name
            else "Drug"
            if "drug" in source_name
            else ""
        )
        main_terms = root.findall(".//letter/mainTerm")
        if not main_terms:
            main_terms = root.findall(".//mainTerm")
        for element in main_terms:
            top_counter += 1
            identifier = f"{top_counter:06d}"
            insert(
                element,
                parent_id="",
                identifier=identifier,
                headings=headings,
                source=source,
                parent_path="",
            )
    return IndexStore({key: Term(**values) for key, values in drafts.items()})
