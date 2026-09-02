"""Read-only stores for parsed ICD materials."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from threading import Lock
from types import MappingProxyType
from typing import TypeVar

from .models import (
    Code,
    GEMChoiceList,
    GEMDirection,
    GEMEntry,
    GEMMapping,
    GEMProvenance,
    GEMScenario,
    Guideline,
    Node,
    Release,
    Term,
)

T = TypeVar("T")


class ReadOnlyStore[T](Mapping[str, T]):
    """A deterministic read-only mapping.

    Equality is value-based: two stores are equal when they are the same store
    class with equal items and equal store-identifying metadata (see each
    subclass), so a store is never equal to a bare mapping holding the same
    items. Value-based equality makes instances deliberately not hashable.

    Examples:
        >>> store = ReadOnlyStore({"b": 2, "a": 1})
        >>> list(store)
        ['b', 'a']
        >>> store["a"]
        1
    """

    __hash__ = None

    def __init__(self, values: Mapping[str, T]) -> None:
        self._values = MappingProxyType(dict(values))

    def __getitem__(self, key: str) -> T:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        return self._values == other._values


class GEMStore(ReadOnlyStore[tuple[GEMEntry, ...]]):
    """Immutable GEM relationships grouped by source code.

    A source may have several entries. Their order is deterministic and retains the
    official scenario and choice-list information; consumers decide how to resolve those
    alternatives.
    """

    def __init__(
        self,
        values: Mapping[str, tuple[GEMEntry, ...]],
        *,
        system: str,
        direction: GEMDirection,
        release: Release | None = None,
        provenance: Mapping[str, GEMProvenance] | None = None,
    ) -> None:
        ordered = {
            source: tuple(
                sorted(
                    entries,
                    key=lambda item: (
                        item.scenario,
                        item.choice_list,
                        item.target or "",
                    ),
                )
            )
            for source, entries in sorted(values.items())
        }
        super().__init__(ordered)
        self.system = system
        self.direction = direction
        self.release = release
        self._provenance = MappingProxyType(dict(provenance or {}))
        self._mapping_cache: dict[str, GEMMapping] = {}
        self._mapping_lock = Lock()
        self._default_provenance = (
            GEMProvenance(release, release, release) if release is not None else None
        )

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        return (
            self._values == other._values
            and self.system == other.system
            and self.direction == other.direction
            and self.release == other.release
            and self._provenance == other._provenance
        )

    def mapping(self, source: str) -> GEMMapping:
        """Return one source's rows grouped into alternatives and scenarios."""
        cached = self._mapping_cache.get(source)
        if cached is not None:
            return cached
        entries = self[source]
        simple = tuple(
            entry
            for entry in entries
            if not entry.combination and entry.target is not None
        )
        grouped: dict[int, dict[int, list[GEMEntry]]] = {}
        for entry in entries:
            if not entry.combination or entry.target is None:
                continue
            grouped.setdefault(entry.scenario, {}).setdefault(
                entry.choice_list, []
            ).append(entry)
        scenarios = tuple(
            GEMScenario(
                number=scenario,
                choice_lists=tuple(
                    GEMChoiceList(number=choice, alternatives=tuple(alternatives))
                    for choice, alternatives in sorted(choice_lists.items())
                ),
            )
            for scenario, choice_lists in sorted(grouped.items())
        )
        result = GEMMapping(
            source=source,
            simple_alternatives=simple,
            scenarios=scenarios,
            no_map=any(entry.no_map for entry in entries),
        )
        with self._mapping_lock:
            return self._mapping_cache.setdefault(source, result)

    def provenance(self, source: str) -> GEMProvenance:
        """Return release provenance for one source mapping."""
        if source not in self:
            raise KeyError(source)
        if source in self._provenance:
            return self._provenance[source]
        if self.release is None:
            raise RuntimeError("GEM provenance requires release metadata")
        if self._default_provenance is None:
            raise RuntimeError("GEM provenance requires release metadata")
        return self._default_provenance


class TabularStore(ReadOnlyStore[Node]):
    """Read-only ICD tabular hierarchy.

    ``children_ids`` always contains direct children. Recursive relationships
    are requested explicitly.

    Examples:
        >>> root = Node("cm", "cm", children_ids=("I10",))
        >>> code = Code("I10", "I10", "Essential hypertension", parent_id="cm")
        >>> store = TabularStore({"cm": root, "I10": code}, {"I10": "I10"}, ("cm",))
        >>> [node.id for node in store.parents("I10")]
        ['cm']
        >>> [node.name for node in store.leaves("cm")]
        ['I10']
    """

    def __init__(
        self,
        values: Mapping[str, Node],
        code_lookup: Mapping[str, str],
        roots: Iterable[str],
    ) -> None:
        super().__init__(values)
        self._code_lookup = MappingProxyType(dict(code_lookup))
        self._normalized_code_lookup = MappingProxyType(
            {code.replace(".", ""): node_id for code, node_id in code_lookup.items()}
        )
        self._roots = tuple(roots)
        self._parents_cache: dict[str, tuple[Node, ...]] = {}
        self._parents_lock = Lock()

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        return (
            self._values == other._values
            and self._code_lookup == other._code_lookup
            and self._roots == other._roots
        )

    def _node_id(self, code_or_id: str) -> str:
        if code_or_id in self._code_lookup:
            return self._code_lookup[code_or_id]
        if code_or_id in self:
            return code_or_id
        return self._normalized_code_lookup[code_or_id.replace(".", "")]

    @property
    def lookup(self) -> Mapping[str, str]:
        """Map normalized ICD code strings to tabular node identifiers."""
        return self._code_lookup

    @property
    def roots(self) -> tuple[str, ...]:
        """Return root node identifiers."""
        return self._roots

    def by_code(self, code: str) -> Node:
        """Return the node for a dotted or compact ICD code."""
        return self[self._node_id(code)]

    def parents(self, code_or_id: str) -> tuple[Node, ...]:
        """Return parents from the immediate parent to the root."""
        node_id = self._node_id(code_or_id)
        cached = self._parents_cache.get(node_id)
        if cached is not None:
            return cached
        node = self[node_id]
        result: list[Node] = []
        while node.parent_id:
            node = self[node.parent_id]
            result.append(node)
        parents = tuple(result)
        with self._parents_lock:
            return self._parents_cache.setdefault(node_id, parents)

    def children(self, code_or_id: str) -> tuple[Node, ...]:
        """Return direct children of a node."""
        node_id = self._node_id(code_or_id)
        return tuple(self[child_id] for child_id in self[node_id].children_ids)

    def descendants(self, code_or_id: str) -> tuple[Node, ...]:
        """Return all descendants in deterministic depth-first order."""
        result: list[Node] = []
        for child in self.children(code_or_id):
            result.append(child)
            result.extend(self.descendants(child.id))
        return tuple(result)

    def leaves(self, code_or_id: str) -> tuple[Code, ...]:
        """Return assignable descendant codes."""
        return tuple(
            node
            for node in self.descendants(code_or_id)
            if isinstance(node, Code) and node.assignable
        )

    def siblings(self, code_or_id: str) -> tuple[Node, ...]:
        """Return direct siblings, excluding the requested node."""
        node_id = self._node_id(code_or_id)
        node = self[node_id]
        if not node.parent_id:
            return ()
        return tuple(
            self[item] for item in self[node.parent_id].children_ids if item != node_id
        )

    def lowest_common_ancestor(self, codes_or_ids: Iterable[str]) -> Node | None:
        """Return the deepest hierarchy node shared by all supplied codes.

        The requested nodes themselves participate in the comparison. An empty input has
        no common ancestor; unknown codes retain the normal mapping ``KeyError``.
        """
        values = tuple(codes_or_ids)
        if not values:
            return None
        paths: list[tuple[Node, ...]] = []
        for value in values:
            node_id = self._node_id(value)
            node = self[node_id]
            paths.append((node, *self.parents(node_id)))
        shared = set.intersection(*({node.id for node in path} for path in paths))
        return next((node for node in paths[0] if node.id in shared), None)


class IndexStore(ReadOnlyStore[Term]):
    """Read-only alphabetic-index hierarchy."""

    def parents(self, term_id: str) -> tuple[Term, ...]:
        """Return index parents from immediate parent to main term."""
        term = self[term_id]
        result: list[Term] = []
        while term.parent_id:
            term = self[term.parent_id]
            result.append(term)
        return tuple(result)

    def children(self, term_id: str) -> tuple[Term, ...]:
        """Return direct child terms."""
        return tuple(self[item] for item in self[term_id].children_ids)

    def descendants(self, term_id: str) -> tuple[Term, ...]:
        """Return all descendant terms in depth-first order."""
        result: list[Term] = []
        for child in self.children(term_id):
            result.append(child)
            result.extend(self.descendants(child.id))
        return tuple(result)

    def main_terms(self) -> tuple[Term, ...]:
        """Return all top-level main terms."""
        return tuple(term for term in self.values() if not term.parent_id)


def _natural_sort_key(key: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", key)]


class GuidelineStore(ReadOnlyStore[Guideline]):
    """Hierarchical guideline sections keyed with dotted identifiers.

    ``key in store`` is true only for stored leaf sections that ``store[key]`` can
    return; title-only section keys are not members and raise ``KeyError`` on item
    access.

    Examples:
        >>> item = Guideline("I_A_1", "I.A.1", "Example", "Body")
        >>> titles = {"I": "Section", "I.A": "Conventions"}
        >>> store = GuidelineStore({"I.A.1": item}, titles)
        >>> store.descendants("I")
        ('I.A.1',)
        >>> store["I.A.1"].content
        'Body'
    """

    def __init__(
        self,
        values: Mapping[str, Guideline],
        titles: Mapping[str, str] | None = None,
        preambles: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(values)
        self._titles = MappingProxyType(dict(titles or {}))
        self._preambles = MappingProxyType(dict(preambles or {}))

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        return (
            self._values == other._values
            and self._titles == other._titles
            and self._preambles == other._preambles
        )

    @property
    def titles(self) -> Mapping[str, str]:
        """Return titles for both leaf and non-leaf guideline sections."""
        return self._titles

    @property
    def preambles(self) -> Mapping[str, str]:
        """Return text appearing before the first child of container sections."""
        return self._preambles

    def descendants(self, prefix: str) -> tuple[str, ...]:
        """Return naturally sorted leaf keys below a prefix."""
        return tuple(
            sorted(
                (key for key in self._values if key.startswith(prefix + ".")),
                key=_natural_sort_key,
            )
        )

    def ancestors(self, key: str) -> tuple[tuple[str, str], ...]:
        """Return titled ancestor keys from outermost to innermost."""
        parts = key.split(".")
        return tuple(
            (ancestor, self._titles[ancestor])
            for index in range(1, len(parts))
            if (ancestor := ".".join(parts[:index])) in self._titles
        )
