"""Immutable public records used by :mod:`cms_icd`.

The records use slotted dataclasses because a complete ICD release contains many
thousands of code and index objects. They intentionally retain a small ``model_dump``
compatibility method for consumers migrating from Pydantic models.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import date


def _serialized(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_serialized(item) for item in value]
    if isinstance(value, list):
        return [_serialized(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialized(item) for key, item in value.items()}
    return value


class Record:
    """Serialization helpers shared by immutable public records."""

    def to_dict(self, *, exclude_none: bool = False) -> dict[str, Any]:
        """Return a recursively serialized dictionary.

        Examples:
            >>> Code(id="I10", name="I10", description="Hypertension").to_dict()
            {'id': 'I10', 'name': 'I10', 'description': 'Hypertension', ...}
        """
        result = _serialized(asdict(self))
        if exclude_none:
            return {key: value for key, value in result.items() if value is not None}
        return result

    def model_dump(self, *, exclude_none: bool = False, **_: Any) -> dict[str, Any]:
        """Compatibility alias for Pydantic's ``model_dump`` method."""
        return self.to_dict(exclude_none=exclude_none)


@dataclass(frozen=True, slots=True)
class Release(Record):
    """A CMS ICD release selector.

    Args:
        fiscal_year: CMS fiscal year.
        release_date: Date on which this revision became effective.
    """

    fiscal_year: int
    release_date: date


class GEMDirection(StrEnum):
    """Direction of an ICD-9/ICD-10 General Equivalence Mapping."""

    ICD9_TO_ICD10 = "icd9_to_icd10"
    ICD10_TO_ICD9 = "icd10_to_icd9"


@dataclass(frozen=True, slots=True)
class GEMEntry(Record):
    """One official CMS General Equivalence Mapping relationship.

    ``target`` is ``None`` when CMS marks the source code as having no mapping. The
    remaining fields expose the five flags from the official GEM layout without applying
    a consumer-specific choice policy.
    """

    source: str
    target: str | None
    approximate: bool
    no_map: bool
    combination: bool
    scenario: int
    choice_list: int


@dataclass(frozen=True, slots=True)
class GEMChoiceList(Record):
    """Alternative target rows occupying one required slot in a GEM scenario."""

    number: int
    alternatives: tuple[GEMEntry, ...]


@dataclass(frozen=True, slots=True)
class GEMScenario(Record):
    """One complete combination-mapping alternative."""

    number: int
    choice_lists: tuple[GEMChoiceList, ...]


@dataclass(frozen=True, slots=True)
class GEMMapping(Record):
    """Structured interpretation of every official row for one source code.

    Simple alternatives and combination scenarios may both be populated because a small
    number of official GEM entries contain both forms.
    """

    source: str
    simple_alternatives: tuple[GEMEntry, ...]
    scenarios: tuple[GEMScenario, ...]
    no_map: bool = False


@dataclass(frozen=True, slots=True)
class GEMProvenance(Record):
    """Release lineage for an exact or retrospectively corrected source mapping."""

    vocabulary_release: Release
    selected_mapping_release: Release
    reviewed_through_release: Release
    blocked_by_code_lifecycle_release: Release | None = None


class ICDMappingStatus(StrEnum):
    """Whether a best-effort ICD-9 mapping produced a usable ICD-10 result."""

    MAPPED = "mapped"
    UNMAPPABLE = "unmappable"


class ICDMappingReason(StrEnum):
    """Deterministic reason for a best-effort ICD-9 mapping resolution."""

    EXACT = "exact"
    SINGLE_APPROXIMATE = "single_approximate"
    COMMON_ANCESTOR = "common_ancestor"
    AXIS_MASKED = "axis_masked"
    COMBINATION = "combination"
    OFFICIAL_NO_MAP = "official_no_map"
    DIVERGENT_ALTERNATIVES = "divergent_alternatives"
    DIVERGENT_SCENARIOS = "divergent_scenarios"
    INVALID_TARGET = "invalid_target"
    UNKNOWN_SOURCE = "unknown_source"


@dataclass(frozen=True, slots=True)
class ICDCMMappingResolution(Record):
    """Best-effort ICD-9-CM diagnosis resolution for one source code."""

    source_code: str
    target_codes: tuple[str, ...]
    status: ICDMappingStatus
    reason: ICDMappingReason
    approximate: bool
    gem_provenance: GEMProvenance | None = None


@dataclass(frozen=True, slots=True)
class ICDPCSMappingResolution(Record):
    """Best-effort ICD-9-CM procedure resolution for one source code.

    A ``?`` in a target pattern marks an ICD-10-PCS axis on which the official
    alternatives disagree.
    """

    source_code: str
    target_patterns: tuple[str, ...]
    status: ICDMappingStatus
    reason: ICDMappingReason
    approximate: bool
    gem_provenance: GEMProvenance | None = None


@dataclass(frozen=True, slots=True)
class Node(Record):
    """A node in an ICD tabular hierarchy."""

    id: str
    name: str
    description: str = ""
    parent_id: str = ""
    children_ids: tuple[str, ...] = ()
    assignable: bool = False
    min: str = ""
    max: str = ""
    notes: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()
    inclusion_term: tuple[str, ...] = ()
    excludes1: tuple[str, ...] = ()
    excludes2: tuple[str, ...] = ()
    use_additional_code: tuple[str, ...] = ()
    code_first: tuple[str, ...] = ()
    code_also: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Code(Node):
    """An ICD code or non-assignable code-category node."""

    assignable: bool = True
    etiology: bool = False
    manifestation: bool = False


@dataclass(frozen=True, slots=True)
class InstructionalNote(Record):
    """Instructional notes associated with a tabular node."""

    name: str
    assignable: bool
    notes: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()
    inclusion_term: tuple[str, ...] = ()
    excludes1: tuple[str, ...] = ()
    excludes2: tuple[str, ...] = ()
    use_additional_code: tuple[str, ...] = ()
    code_first: tuple[str, ...] = ()
    code_also: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        """Return whether the record contains no instructional content.

        Examples:
            >>> note = InstructionalNote("I10", True, includes=("high blood pressure",))
            >>> note.to_dict()["includes"]
            ['high blood pressure']
        """
        return not any(
            getattr(self, field.name)
            for field in fields(self)
            if field.name not in {"name", "assignable"}
        )


@dataclass(frozen=True, slots=True)
class Term(Record):
    """A term in an ICD alphabetic index."""

    id: str
    title: str
    parent_id: str = ""
    children_ids: tuple[str, ...] = ()
    path: str = ""
    code: str | None = None
    manifestation_code: str | None = None
    assignable: bool = False
    see: str | None = None
    see_also: str | None = None
    source: str = ""
    optional_modifiers: tuple[str, ...] = ()

    @property
    def main_term_id(self) -> str:
        """Return the identifier of this term's top-level main term."""
        return self.id.split(".", maxsplit=1)[0]


@dataclass(frozen=True, slots=True)
class Guideline(Record):
    """A coding-guideline section."""

    id: str
    number: str
    title: str
    content: str
