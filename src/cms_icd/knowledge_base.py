"""Lazy public knowledge-base interfaces."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import date
from threading import Lock
from typing import TYPE_CHECKING, Self

from .guidelines import parse_guidelines
from .models import Code, Guideline, InstructionalNote, Node, Release, Term
from .parsers import parse_cm_tabular, parse_index, parse_pcs_tabular
from .sources import CMSProvider, DirectoryProvider, MaterialProvider, fiscal_year_for
from .stores import GuidelineStore, IndexStore, TabularStore, _natural_sort_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

logger = logging.getLogger(__name__)

_RENDER_CACHE_MAX = 32


class _SystemKnowledgeBase:
    """Shared lazy-loading behavior for one ICD-10 code system."""

    system: str

    def __init__(
        self,
        provider: MaterialProvider | None,
        *,
        tabular: TabularStore | None = None,
        index: IndexStore | None = None,
        guidelines: GuidelineStore | None = None,
    ) -> None:
        self._provider = provider
        self._tabular = tabular
        self._index = index
        self._guidelines = guidelines
        self._tabular_lock = Lock()
        self._index_lock = Lock()
        self._guidelines_lock = Lock()
        self._render_cache: OrderedDict[tuple[str, ...], Guideline] = OrderedDict()

    @property
    def release(self) -> Release | None:
        """Return release metadata, if this view is provider-backed."""
        return self._provider.release if self._provider is not None else None

    @property
    def tabular(self) -> TabularStore:
        """Return the tabular hierarchy, parsing it on first access."""
        if self._tabular is None:
            with self._tabular_lock:
                if self._tabular is None:
                    self._tabular = self._load_tabular()
        return self._tabular

    @property
    def lookup(self) -> Mapping[str, str]:
        """Map ICD codes to their tabular node identifiers."""
        return self.tabular.lookup

    @property
    def roots(self) -> tuple[str, ...]:
        """Return tabular root identifiers."""
        return self.tabular.roots

    @property
    def index(self) -> IndexStore:
        """Return the alphabetic index, parsing it on first access."""
        if self._index is None:
            with self._index_lock:
                if self._index is None:
                    self._index = self._load_index()
        return self._index

    @property
    def guidelines(self) -> GuidelineStore:
        """Return official coding guidelines, parsing them on first access."""
        if self._guidelines is None:
            with self._guidelines_lock:
                if self._guidelines is None:
                    self._guidelines = self._load_guidelines()
        return self._guidelines

    def _require_provider(self) -> MaterialProvider:
        if self._provider is None:
            raise RuntimeError(
                f"{type(self).__name__} has no provider for unloaded material"
            )
        return self._provider

    def _load_tabular(self) -> TabularStore:
        provider = self._require_provider()
        if isinstance(provider, CMSProvider):
            from .parsed_cache import load_tabular_store

            return load_tabular_store(provider, self.system)
        path = provider.paths(self.system, "tabular")[0]
        if self.system == "cm":
            return parse_cm_tabular(path)
        return parse_pcs_tabular(path)

    def _load_index(self) -> IndexStore:
        provider = self._require_provider()
        if isinstance(provider, CMSProvider):
            from .parsed_cache import load_index_store

            return load_index_store(provider, self.system)
        return parse_index(provider.paths(self.system, "index"), system=self.system)

    def _load_guidelines(self) -> GuidelineStore:
        provider = self._require_provider()
        if isinstance(provider, CMSProvider):
            from .parsed_cache import load_guideline_store

            return load_guideline_store(provider, self.system)
        path = provider.paths(self.system, "guidelines")[0]
        return parse_guidelines(path, system=self.system)

    def __getitem__(self, code: str) -> Code:
        """Return an ICD code.

        Raises:
            KeyError: If the code does not exist in this release.
        """
        node = self.tabular.by_code(code)
        if not isinstance(node, Code):
            raise KeyError(code)
        return node

    def __contains__(self, code: object) -> bool:
        """Return whether a code exists in the tabular list."""
        return isinstance(code, str) and code in self.lookup

    def __repr__(self) -> str:
        """Return a representation without loading any material."""
        loaded = [
            name
            for name, value in (
                ("tabular", self._tabular),
                ("index", self._index),
                ("guidelines", self._guidelines),
            )
            if value is not None
        ]
        return f"{type(self).__name__}(loaded={loaded!r}, release={self.release!r})"

    def load_tabular(self) -> None:
        """Eagerly load only the tabular hierarchy."""
        _ = self.tabular

    def load_index(self) -> None:
        """Eagerly load only the alphabetic index."""
        _ = self.index

    def load_guidelines(self) -> None:
        """Eagerly load only official coding guidelines."""
        _ = self.guidelines

    def load_all(self) -> None:
        """Eagerly load all materials for this code system."""
        self.load_tabular()
        self.load_index()
        self.load_guidelines()

    def get_all_tabular_parents(self, code_or_id: str) -> list[Node]:
        """Return all tabular parents, immediate parent first.

        This compatibility method returns a list. New code may use
        :meth:`cms_icd.stores.TabularStore.parents` directly.
        """
        return list(self.tabular.parents(code_or_id))

    def get_all_tabular_children(self, code_or_id: str) -> list[str]:
        """Return descendant identifiers in depth-first order."""
        return [node.id for node in self.tabular.descendants(code_or_id)]

    def get_leaves(self, code_or_id: str) -> list[str]:
        """Return assignable descendant code strings."""
        return [node.name for node in self.tabular.leaves(code_or_id)]

    def get_all_index_parents(self, term_id: str) -> list[Term]:
        """Return index parents, immediate parent first."""
        return list(self.index.parents(term_id))

    def get_all_main_terms(self) -> list[Term]:
        """Return top-level alphabetic-index terms."""
        return list(self.index.main_terms())

    def get_all_term_children(self, term_id: str) -> list[Term]:
        """Return all descendant index terms."""
        return list(self.index.descendants(term_id))

    def get_assignable_terms(self) -> list[Term]:
        """Return index terms that point to assignable codes."""
        return [term for term in self.index.values() if term.assignable]

    def get_term_codes(self, term_id: str, subterms: bool = False) -> list[str]:
        """Resolve an index term to deterministic ICD code strings.

        Args:
            term_id: Alphabetic-index term identifier.
            subterms: Include codes reachable from descendant terms.
        """
        terms = (self.index[term_id],)
        if subterms:
            terms += self.index.descendants(term_id)
        codes: set[str] = set()
        for term in terms:
            for value in (term.code, term.manifestation_code):
                if not value:
                    continue
                if value in self.lookup and self.tabular.by_code(value).assignable:
                    codes.add(value)
                elif value in self.lookup:
                    codes.update(node.name for node in self.tabular.leaves(value))
        return sorted(codes)

    def get_instructional_notes(self, codes: list[str]) -> list[dict[str, object]]:
        """Return deduplicated instructional notes inherited by codes."""
        included: set[str] = set()
        result: list[dict[str, object]] = []
        for code in codes:
            node = self[code]
            lineage = [*reversed(self.tabular.parents(code)), node]
            for item in lineage:
                if item.id in included:
                    continue
                note = InstructionalNote(
                    name=item.name,
                    assignable=item.assignable,
                    notes=item.notes,
                    includes=item.includes,
                    inclusion_term=item.inclusion_term,
                    excludes1=item.excludes1,
                    excludes2=item.excludes2,
                    use_additional_code=item.use_additional_code,
                    code_first=item.code_first,
                    code_also=item.code_also,
                )
                if note.is_empty():
                    continue
                result.append(note.to_dict(exclude_none=True))
                included.add(item.id)
        return result

    def render_guidelines(self, keys: Iterable[str]) -> Guideline:
        """Render selected guideline sections with shared ancestors once."""
        cache_key = tuple(sorted(set(keys), key=_natural_sort_key))
        cached = self._render_cache.get(cache_key)
        if cached is not None:
            self._render_cache.move_to_end(cache_key)
            return cached
        expanded: list[str] = []
        for key in cache_key:
            if key in self.guidelines.keys():
                expanded.append(key)
            else:
                descendants = self.guidelines.descendants(key)
                if not descendants:
                    raise KeyError(f"Guideline key {key!r} does not exist")
                expanded.extend(descendants)
        parts: list[str] = []
        rendered_ancestors: set[str] = set()
        sorted_keys = sorted(set(expanded), key=_natural_sort_key)
        for key in sorted_keys:
            guideline = self.guidelines[key]
            for ancestor, title in self.guidelines.ancestors(key):
                if ancestor in rendered_ancestors:
                    continue
                parts.append(f"{'#' * (ancestor.count('.') + 1)} {ancestor}: {title}")
                if ancestor in self.guidelines.preambles:
                    parts.append(self.guidelines.preambles[ancestor])
                rendered_ancestors.add(ancestor)
            header = f"{'#' * (key.count('.') + 1)} {key}: {guideline.title}"
            parts.append(f"{header}\n\n{guideline.content}")
        result = Guideline(
            id="combined",
            number=", ".join(sorted_keys),
            title="Guidelines",
            content="\n\n".join(parts).strip(),
        )
        self._render_cache[cache_key] = result
        while len(self._render_cache) > _RENDER_CACHE_MAX:
            self._render_cache.popitem(last=False)
        return result


class ICD10CMKnowledgeBase(_SystemKnowledgeBase):
    """Lazy structured access to ICD-10-CM materials.

    Instances are normally obtained from :attr:`ICD10KnowledgeBase.cm`.

    Examples:
        >>> from cms_icd.models import Code, Node
        >>> from cms_icd.stores import IndexStore, TabularStore
        >>> root = Node("cm", "cm", children_ids=("I10",))
        >>> code = Code("I10", "I10", "Essential hypertension", parent_id="cm")
        >>> tabular = TabularStore({"cm": root, "I10": code}, {"I10": "I10"}, ("cm",))
        >>> cm = ICD10CMKnowledgeBase.from_stores(tabular=tabular)
        >>> cm["I10"].description
        'Essential hypertension'
        >>> cm.get_all_tabular_parents("I10")[0].id
        'cm'
    """

    system = "cm"

    @classmethod
    def from_stores(
        cls,
        *,
        tabular: TabularStore | None = None,
        index: IndexStore | None = None,
        guidelines: GuidelineStore | None = None,
    ) -> Self:
        """Construct a CM view from prebuilt stores for custom sources or tests."""
        return cls(None, tabular=tabular, index=index, guidelines=guidelines)

    def get_chapter_guidelines(self, codes: list[str]) -> Guideline:
        """Render chapter-specific CM guidelines for a list of codes."""
        keys: set[str] = set()
        for code in codes:
            parents = [
                item
                for item in self.tabular.parents(code)
                if item.id not in self.tabular.roots
            ]
            if not parents:
                continue
            chapter = parents[-1]
            keys.add(f"I.C.{chapter.name}")
        return self.render_guidelines(keys)


class ICD10PCSKnowledgeBase(_SystemKnowledgeBase):
    """Lazy structured access to ICD-10-PCS materials."""

    system = "pcs"

    @classmethod
    def from_stores(
        cls,
        *,
        tabular: TabularStore | None = None,
        index: IndexStore | None = None,
        guidelines: GuidelineStore | None = None,
    ) -> Self:
        """Construct a PCS view from prebuilt stores for custom sources or tests."""
        return cls(None, tabular=tabular, index=index, guidelines=guidelines)


class ICD10KnowledgeBase:
    """A CMS ICD-10 release with independently lazy CM and PCS views.

    Construction records how materials should be found but performs no network
    request, download, or parsing. Accessing a view is also cheap; material is
    acquired only when ``tabular``, ``index``, or ``guidelines`` is accessed.

    Examples:
        >>> kb = ICD10KnowledgeBase.from_directory(
        ...     ".", fiscal_year=2026, release_date=date(2025, 10, 1)
        ... )
        >>> repr(kb)
        'ICD10KnowledgeBase(...loaded=[])'
    """

    def __init__(self, provider: MaterialProvider) -> None:
        self._provider = provider
        self._cm: ICD10CMKnowledgeBase | None = None
        self._pcs: ICD10PCSKnowledgeBase | None = None

    @classmethod
    def from_cms(
        cls,
        fiscal_year: int | None = None,
        *,
        year: int | None = None,
        release_date: date | None = None,
        cache_dir: str | Path | None = None,
        fallback: str | None = None,
        offline: bool = False,
    ) -> Self:
        """Create a lazy selector for an exact CMS fiscal-year snapshot.

        ``year`` is accepted as a compatibility alias for ``fiscal_year``.
        Materials unchanged in the requested revision are inherited from the
        latest earlier revision in the same fiscal year.

        Args:
            fiscal_year: CMS fiscal year.
            year: Compatibility alias for ``fiscal_year``.
            release_date: Effective date of the requested revision. Defaults to
                October 1 preceding the fiscal year.
            cache_dir: Persistent artifact cache directory. ``None`` uses the
                platform default cache directory.
            fallback: Set to ``"latest_for_fy"`` to permit an explicit fallback.
            offline: Require the catalog and artifacts to already be cached.
        """
        selected_year = fiscal_year if fiscal_year is not None else year
        if selected_year is None:
            raise TypeError("fiscal_year is required")
        if fiscal_year is not None and year is not None and fiscal_year != year:
            raise ValueError("fiscal_year and year disagree")
        selected_date = release_date or date(selected_year - 1, 10, 1)
        release = Release(selected_year, selected_date)
        return cls(
            CMSProvider(
                release,
                cache_dir=cache_dir,
                fallback=fallback,
                offline=offline,
            ),
        )

    @classmethod
    def for_date(
        cls,
        service_date: date,
        *,
        cache_dir: str | Path | None = None,
        fallback: str | None = None,
        offline: bool = False,
    ) -> Self:
        """Create a lazy selector for materials applicable on a coding date.

        Use the discharge date for inpatient ICD-10-CM and ICD-10-PCS. Use the
        encounter or date of service for other ICD-10-CM coding.

        Args:
            service_date: Date that controls coding for the record.
            cache_dir: Persistent artifact cache directory. ``None`` uses the
                platform default cache directory.
            fallback: Set to ``"latest_for_fy"`` to permit an explicit fallback.
            offline: Require the catalog and artifacts to already be cached.
        """
        release = Release(fiscal_year_for(service_date), service_date)
        return cls(
            CMSProvider(
                release,
                service_date=service_date,
                cache_dir=cache_dir,
                fallback=fallback,
                offline=offline,
            )
        )

    @classmethod
    def from_directory(
        cls,
        directory: str | Path,
        *,
        fiscal_year: int,
        release_date: date,
    ) -> Self:
        """Create an offline knowledge base from CMS-format files."""
        return cls(DirectoryProvider(directory, Release(fiscal_year, release_date)))

    @property
    def release(self) -> Release:
        """Return requested release metadata."""
        return self._provider.release

    @property
    def cm(self) -> ICD10CMKnowledgeBase:
        """Return the lazy ICD-10-CM view."""
        if self._cm is None:
            self._cm = ICD10CMKnowledgeBase(self._provider)
        return self._cm

    @property
    def pcs(self) -> ICD10PCSKnowledgeBase:
        """Return the lazy ICD-10-PCS view."""
        if self._pcs is None:
            self._pcs = ICD10PCSKnowledgeBase(self._provider)
        return self._pcs

    def load_all(self) -> None:
        """Eagerly load every CM and PCS material."""
        self.cm.load_all()
        self.pcs.load_all()

    def __repr__(self) -> str:
        """Return a representation without acquiring any material."""
        loaded = [
            name
            for name, view in (("cm", self._cm), ("pcs", self._pcs))
            if view is not None
        ]
        return f"ICD10KnowledgeBase(release={self.release!r}, loaded={loaded!r})"
