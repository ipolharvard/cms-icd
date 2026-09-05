"""Parsing for official ICD-10 coding-guideline PDFs."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pypdf import PdfReader

from .exceptions import ParseError
from .models import Guideline
from .stores import GuidelineStore

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from pypdf import PageObject
    from pypdf.generic import Destination


_SECTION = re.compile(r"Section\s+(IV|I{1,3})\b", re.I)
_SUBSECTION = re.compile(r"^([A-Z])\.\s")
_NUMBER = re.compile(r"^(\d+)\.\s")
_PAGE_FOOTER = re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.I)
_RUNNING_FOOTERS: dict[str, re.Pattern[str]] = {
    "cm": re.compile(
        r"\s*ICD\s*-\s*10\s*-\s*CM\s+Official\s+Guidelines\s+for\s+Coding\s+and"
        r"\s+Reporting\s+FY\s+\d{4}\s+Page\s+\d+\s+of\s+\d+\s*",
        re.I,
    ),
    "pcs": re.compile(
        r"\s*ICD\s*-\s*10\s*-\s*PCS\s+Official\s+Guidelines\s+for\s+Coding\s+and"
        r"\s+Reporting\s+FY\s+\d{4}\s+Page\s+\d+\s+of\s+\d+\s*",
        re.I,
    ),
}


def _text_position(
    text_matrix: Sequence[float], user_matrix: Sequence[float]
) -> tuple[float, float]:
    """Return text-space translation transformed into page coordinates."""
    x = text_matrix[4] * user_matrix[0] + text_matrix[5] * user_matrix[2]
    y = text_matrix[4] * user_matrix[1] + text_matrix[5] * user_matrix[3]
    return x + user_matrix[4], y + user_matrix[5]


def _page_text(page: PageObject, system: str = "cm") -> str:
    footer_text: set[str] = set()
    threshold = float(page.mediabox.height) * 0.08

    def visit_text(
        text: str,
        user_matrix: Sequence[float],
        text_matrix: Sequence[float],
        _font: object,
        _font_size: float,
    ) -> None:
        _, y = _text_position(text_matrix, user_matrix)
        item = text.strip()
        if item and 0 <= y <= threshold and _PAGE_FOOTER.match(item):
            footer_text.add(item)

    text = page.extract_text(visitor_text=visit_text) or ""
    text = _RUNNING_FOOTERS[system].sub("", text)
    for item in footer_text:
        text = text.replace(item, "", 1)
    text = re.sub(
        r"\bICD\s*-\s*10\s*-\s*(CM|PCS)\b",
        lambda match: f"ICD-10-{match.group(1).upper()}",
        text,
        flags=re.I,
    )
    text = re.sub(r"(?<=\d)\s+(st|nd|rd|th)\b", r"\1", text)  # codespell:ignore nd
    text = re.sub(r"\b([A-Z])\s+(?=\d{2}(?:\d|\.))", r"\1", text)
    # Some CMS fonts place artificial word boundaries inside these words.
    text = text.replace("Tabular L ist", "Tabular List")  # codespell:ignore ist
    text = re.sub(r"\bap\s+propriate\b", "appropriate", text)
    text = re.sub(r"\bW\s+hen\b", "When", text)
    text = re.sub(r"\bw\s+hen\b", "when", text)
    return re.sub(r"^(\d+\.)\s*\n\s*", r"\n\1 ", text, flags=re.M).strip()


def _outline_entries(
    document: PdfReader,
) -> Iterator[tuple[int, str, int]]:
    def walk(
        items: Sequence[Destination | list[Destination]], level: int
    ) -> Iterator[tuple[int, str, int]]:
        for item in items:
            if isinstance(item, list):
                yield from walk(item, level + 1)
                continue
            page_number = document.get_destination_page_number(item)
            if page_number is None:
                raise ParseError(f"Guideline outline destination has no page: {item!s}")
            yield level, str(item.title), page_number + 1

    yield from walk(document.outline, 1)


def _strip_header(title: str, content: str) -> str:
    words = [re.escape(word) for word in title.split()]
    if not words:
        return content
    return re.sub(
        r"^.*?" + r"\s+".join(words), "", content, count=1, flags=re.I | re.S
    ).strip()


def _structured_cm_guidelines(document: PdfReader, path: str | Path) -> GuidelineStore:
    entries: list[dict[str, object]] = []
    current_section: str | None = None
    current_subsection: str | None = None
    for level, raw_title, page_number in _outline_entries(document):
        if level == 1 and (match := _SECTION.search(raw_title)):
            current_section = match.group(1).upper()
            current_subsection = None
            title = re.sub(
                r"Section\s+(?:IV|I{1,3})\.\s*", "", raw_title, count=1, flags=re.I
            ).strip()
            entries.append(
                {
                    "key": current_section,
                    "title": title,
                    "page": page_number,
                    "level": 1,
                    "raw_title": raw_title,
                }
            )
        elif level == 2 and current_section and (match := _SUBSECTION.match(raw_title)):
            current_subsection = f"{current_section}.{match.group(1)}"
            entries.append(
                {
                    "key": current_subsection,
                    "title": raw_title[match.end() :].strip(),
                    "page": page_number,
                    "level": 2,
                    "raw_title": raw_title,
                }
            )
        elif level == 3 and current_subsection and (match := _NUMBER.match(raw_title)):
            entries.append(
                {
                    "key": f"{current_subsection}.{match.group(1)}",
                    "title": raw_title[match.end() :].strip(),
                    "page": page_number,
                    "level": 3,
                    "raw_title": raw_title,
                }
            )
    if not entries:
        raise ParseError(f"No structured CM guideline outline found in {path}")
    for index, entry in enumerate(entries):
        entry["leaf"] = index == len(entries) - 1 or int(
            entries[index + 1]["level"]
        ) <= int(entry["level"])
    first_page = int(entries[0]["page"])
    full_text = "\n".join(
        _page_text(document.pages[number])
        for number in range(first_page - 1, len(document.pages))
    )
    search_from = 0
    for entry in entries:
        words = str(entry["raw_title"]).split()[:8]
        heading = "".join(words)
        pattern = r"\s*".join(re.escape(character) for character in heading)
        match = re.search(pattern, full_text[search_from:], re.I | re.M)
        entry["position"] = search_from + match.start() if match else None
        if match:
            search_from = int(entry["position"])
    titles = {str(entry["key"]): str(entry["title"]) for entry in entries}
    guidelines: dict[str, Guideline] = {}
    preambles: dict[str, str] = {}
    for index, entry in enumerate(entries):
        position = entry["position"]
        if position is None:
            continue
        later = [item for item in entries[index + 1 :] if item["position"] is not None]
        end = int(later[0]["position"]) if later else len(full_text)
        content = full_text[int(position) : end].strip()
        key = str(entry["key"])
        if entry["leaf"]:
            guidelines[key] = Guideline(
                id=key.replace(".", "_"),
                number=key,
                title=str(entry["title"]),
                content=content,
            )
        else:
            body = _strip_header(str(entry["title"]), content)
            if body:
                preambles[key] = body
    return GuidelineStore(guidelines, titles, preambles)


def parse_guidelines(path: str | Path, *, system: str) -> GuidelineStore:
    """Parse an official coding-guidelines PDF.

    CM PDFs receive dotted section keys. PCS PDFs, whose outlines vary more by release,
    are exposed as one deterministic ``document`` guideline.
    """
    if system not in {"cm", "pcs"}:
        raise ValueError(f"Unsupported guideline system: {system!r}")
    try:
        document = PdfReader(path)
    except Exception as exc:
        raise ParseError(
            f"Unable to open ICD-10-{system.upper()} guidelines {path}: {exc}"
        ) from exc
    try:
        if system == "pcs":
            content = "\n".join(_page_text(page, system) for page in document.pages)
            guideline = Guideline(
                "document", "document", "Official Guidelines", content
            )
            return GuidelineStore(
                {"document": guideline}, {"document": guideline.title}
            )
        return _structured_cm_guidelines(document, path)
    finally:
        document.close()
