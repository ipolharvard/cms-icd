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
_SECTION_START = re.compile(r"^Section\s+(IV|I{1,3})\b", re.I)
_SUBSECTION = re.compile(r"^([A-Z])\.\s")
_NUMBER = re.compile(r"^(\d+)\.\s")
_TOC_LEADER = re.compile(r"\.{3,}")
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
    # Rejoin a word-initial letter that a font split from a code, but only when the
    # result is a plausible ICD-10 code: a letter, exactly two digits, and an
    # optional decimal. Longer numerals and bare dots are prose and stay intact.
    text = re.sub(r"\b([A-Z])\s+(?=\d{2}(?:\.\d|(?![\d.])))", r"\1", text)
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
                continue
            yield level, str(item.title), page_number + 1

    yield from walk(document.outline, 1)


def _strip_header(title: str, content: str) -> str:
    """Remove a section's own heading from the start of its content.

    The heading is matched with optional whitespace between every character, mirroring
    the outline-heading position search, because PDF text extraction may insert extra
    spaces inside the heading text.
    """
    characters = "".join(title.split())
    if not characters:
        return content
    pattern = re.compile(
        r"^.*?" + r"\s*".join(re.escape(character) for character in characters),
        re.I | re.S,
    )
    return pattern.sub("", content, count=1).strip()


def _structured_cm_guidelines(document: PdfReader, path: str | Path) -> GuidelineStore:
    outline = list(_outline_entries(document))
    fixed_depth = any(
        level == 1 and _SECTION.search(title) for level, title, _ in outline
    )
    entries: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    current_section: str | None = None
    current_subsection: str | None = None
    for level, raw_title, page_number in outline:
        if fixed_depth:
            section_match = _SECTION.search(raw_title) if level == 1 else None
            subsection_match = _SUBSECTION.match(raw_title) if level == 2 else None
            # Level 2 numbers skip the lettered subsection level entirely.
            number_match = _NUMBER.match(raw_title) if level in (2, 3) else None
        else:
            if _TOC_LEADER.search(raw_title):
                continue
            section_match = _SECTION_START.match(raw_title)
            subsection_match = _SUBSECTION.match(raw_title)
            number_match = _NUMBER.match(raw_title)

        if section_match:
            match = section_match
            current_section = match.group(1).upper()
            current_subsection = None
            title = re.sub(
                r"Section\s+(?:IV|I{1,3})\.\s*", "", raw_title, count=1, flags=re.I
            ).strip()
            key = current_section
            semantic_level = 1
            if not fixed_depth and key in seen_keys:
                continue
            entries.append(
                {
                    "key": key,
                    "title": title,
                    "page": page_number,
                    "level": semantic_level,
                    "raw_title": raw_title,
                }
            )
            seen_keys.add(key)
        elif current_section and subsection_match:
            match = subsection_match
            current_subsection = f"{current_section}.{match.group(1)}"
            key = current_subsection
            semantic_level = 2
            if not fixed_depth and key in seen_keys:
                continue
            entries.append(
                {
                    "key": key,
                    "title": raw_title[match.end() :].strip(),
                    "page": page_number,
                    "level": semantic_level,
                    "raw_title": raw_title,
                }
            )
            seen_keys.add(key)
        elif current_section and number_match:
            match = number_match
            parent = current_subsection or current_section
            key = f"{parent}.{match.group(1)}"
            semantic_level = 3
            if not fixed_depth and key in seen_keys:
                continue
            entries.append(
                {
                    "key": key,
                    "title": raw_title[match.end() :].strip(),
                    "page": page_number,
                    "level": semantic_level,
                    "raw_title": raw_title,
                }
            )
            seen_keys.add(key)
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
        if match is None:
            raise ParseError(
                f"Could not locate guideline entry {entry['key']!s} "
                f"({str(entry['raw_title'])!r}) in the text of {path}"
            )
        entry["position"] = search_from + match.start()
        search_from = int(entry["position"])
    titles = {str(entry["key"]): str(entry["title"]) for entry in entries}
    guidelines: dict[str, Guideline] = {}
    preambles: dict[str, str] = {}
    for index, entry in enumerate(entries):
        position = int(entry["position"])
        later = entries[index + 1 :]
        end = int(later[0]["position"]) if later else len(full_text)
        content = full_text[position:end].strip()
        key = str(entry["key"])
        if entry["leaf"]:
            guidelines[key] = Guideline(
                id=key.replace(".", "_"),
                number=key,
                title=str(entry["title"]),
                content=_strip_header(str(entry["title"]), content),
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
