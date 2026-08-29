"""Lazy access to official CMS General Equivalence Mappings."""

from __future__ import annotations

from datetime import date
from itertools import pairwise
from threading import Lock
from typing import TYPE_CHECKING, Self

from .models import GEMDirection, GEMProvenance, Release
from .parsers import parse_gems
from .sources import CMSProvider, DirectoryProvider, MaterialProvider
from .stores import GEMStore

if TYPE_CHECKING:
    from pathlib import Path


class GEMSystemView:
    """Lazy bidirectional GEMs for one ICD-10 system (CM or PCS)."""

    def __init__(
        self,
        provider: MaterialProvider | None,
        system: str,
        *,
        icd9_to_icd10: GEMStore | None = None,
        icd10_to_icd9: GEMStore | None = None,
        correction_providers: tuple[MaterialProvider, ...] = (),
    ) -> None:
        if system not in {"cm", "pcs"}:
            raise ValueError(f"Unsupported GEM system: {system!r}")
        self._provider = provider
        self._correction_providers = correction_providers
        self.system = system
        self._stores = {
            GEMDirection.ICD9_TO_ICD10: icd9_to_icd10,
            GEMDirection.ICD10_TO_ICD9: icd10_to_icd9,
        }
        self._locks = {direction: Lock() for direction in GEMDirection}

    @classmethod
    def from_stores(
        cls,
        system: str,
        *,
        icd9_to_icd10: GEMStore | None = None,
        icd10_to_icd9: GEMStore | None = None,
    ) -> Self:
        """Construct a view from prebuilt stores for custom sources or tests."""
        return cls(
            None,
            system,
            icd9_to_icd10=icd9_to_icd10,
            icd10_to_icd9=icd10_to_icd9,
        )

    @property
    def release(self) -> Release | None:
        """Return release metadata, if this view is provider-backed."""
        return self._provider.release if self._provider is not None else None

    def _load(self, direction: GEMDirection) -> GEMStore:
        store = self._stores[direction]
        if store is None:
            with self._locks[direction]:
                store = self._stores[direction]
                if store is None:
                    if self._provider is None:
                        raise RuntimeError(
                            f"{type(self).__name__} has no provider for unloaded GEMs"
                        )
                    store = self._load_provider(self._provider, direction)
                    if self._correction_providers:
                        stores = [store]
                        target_universes = [
                            set(
                                self._load_provider(
                                    self._provider, _opposite(direction)
                                )
                            )
                        ]
                        for provider in self._correction_providers:
                            stores.append(self._load_provider(provider, direction))
                            target_universes.append(
                                set(self._load_provider(provider, _opposite(direction)))
                            )
                        if isinstance(self._provider, CMSProvider) and all(
                            isinstance(provider, CMSProvider)
                            for provider in self._correction_providers
                        ):
                            from .parsed_cache import load_corrected_gem_store

                            store = load_corrected_gem_store(
                                self._provider.cache_dir,
                                stores,
                                target_universes,
                                build=lambda: _backport_corrections(
                                    stores, target_universes
                                ),
                            )
                        else:
                            store = _backport_corrections(stores, target_universes)
                    self._stores[direction] = store
        return store

    def _load_provider(
        self, provider: MaterialProvider, direction: GEMDirection
    ) -> GEMStore:
        if isinstance(provider, CMSProvider):
            from .parsed_cache import load_gem_store

            return load_gem_store(provider, self.system, direction)
        return parse_gems(
            provider.paths(self.system, "gems"),
            system=self.system,
            direction=direction,
            release=provider.release,
        )

    @property
    def icd9_to_icd10(self) -> GEMStore:
        """Return mappings from ICD-9-CM to ICD-10-CM or ICD-10-PCS."""
        return self._load(GEMDirection.ICD9_TO_ICD10)

    @property
    def icd10_to_icd9(self) -> GEMStore:
        """Return mappings from ICD-10-CM or ICD-10-PCS to ICD-9-CM."""
        return self._load(GEMDirection.ICD10_TO_ICD9)

    def __repr__(self) -> str:
        """Return a representation without loading mappings."""
        loaded = [
            direction.value
            for direction, store in self._stores.items()
            if store is not None
        ]
        return (
            f"GEMSystemView(system={self.system!r}, release={self.release!r}, "
            f"loaded={loaded!r})"
        )


class GEMKnowledgeBase:
    """A CMS fiscal-year GEM release with independently lazy CM and PCS views."""

    def __init__(
        self,
        provider: MaterialProvider,
        *,
        correction_providers: tuple[MaterialProvider, ...] = (),
    ) -> None:
        self._provider = provider
        self._correction_providers = correction_providers
        self._cm: GEMSystemView | None = None
        self._pcs: GEMSystemView | None = None
        self._cm_lock = Lock()
        self._pcs_lock = Lock()

    @classmethod
    def from_cms(
        cls,
        fiscal_year: int,
        *,
        cache_dir: str | Path | None = None,
        offline: bool = False,
    ) -> Self:
        """Create a lazy GEM selector for an official CMS fiscal year.

        Args:
            fiscal_year: Official CMS GEM fiscal year.
            cache_dir: Persistent artifact cache directory. ``None`` uses the
                platform default cache directory.
            offline: Require the catalog and artifacts to already be cached.
        """
        release = Release(fiscal_year, date(fiscal_year - 1, 10, 1))
        return cls(
            CMSProvider(
                release,
                cache_dir=cache_dir,
                offline=offline,
            )
        )

    @classmethod
    def corrected_from_cms(
        cls,
        fiscal_year: int,
        *,
        corrections_through_fiscal_year: int = 2018,
        cache_dir: str | Path | None = None,
        offline: bool = False,
    ) -> Self:
        """Create GEMs using historical vocabulary and later safe corrections.

        Each source remains on the requested fiscal year's vocabulary. Later complete
        row sets are adopted only until that source encounters an introduced or retired
        source/target code. Corrections are reviewed through FY2018 by default, the last
        CMS GEM release.

        Args:
            fiscal_year: Historical vocabulary fiscal year.
            corrections_through_fiscal_year: Last GEM release considered for safe
                corrections.
            cache_dir: Persistent artifact cache directory shared by all releases.
                ``None`` uses the platform default cache directory.
            offline: Require the catalog and artifacts to already be cached.
        """
        if corrections_through_fiscal_year < fiscal_year:
            raise ValueError(
                "corrections_through_fiscal_year must not precede fiscal_year"
            )

        def provider(year: int) -> CMSProvider:
            return CMSProvider(
                Release(year, date(year - 1, 10, 1)),
                cache_dir=cache_dir,
                offline=offline,
            )

        return cls(
            provider(fiscal_year),
            correction_providers=tuple(
                provider(year)
                for year in range(fiscal_year + 1, corrections_through_fiscal_year + 1)
            ),
        )

    @classmethod
    def from_directory(
        cls,
        directory: str | Path,
        *,
        fiscal_year: int,
    ) -> Self:
        """Create a knowledge base from locally supplied CMS-format GEM files."""
        release = Release(fiscal_year, date(fiscal_year - 1, 10, 1))
        return cls(DirectoryProvider(directory, release))

    @property
    def release(self) -> Release:
        """Return the selected CMS GEM release."""
        return self._provider.release

    @property
    def cm(self) -> GEMSystemView:
        """Return the lazy diagnosis GEM view."""
        if self._cm is None:
            with self._cm_lock:
                if self._cm is None:
                    self._cm = GEMSystemView(
                        self._provider,
                        "cm",
                        correction_providers=self._correction_providers,
                    )
        return self._cm

    @property
    def pcs(self) -> GEMSystemView:
        """Return the lazy procedure GEM view."""
        if self._pcs is None:
            with self._pcs_lock:
                if self._pcs is None:
                    self._pcs = GEMSystemView(
                        self._provider,
                        "pcs",
                        correction_providers=self._correction_providers,
                    )
        return self._pcs

    def __repr__(self) -> str:
        """Return a representation without acquiring any GEM material."""
        loaded = [
            name
            for name, view in (("cm", self._cm), ("pcs", self._pcs))
            if view is not None
        ]
        corrections_through = (
            self._correction_providers[-1].release
            if self._correction_providers
            else None
        )
        return (
            f"GEMKnowledgeBase(release={self.release!r}, "
            f"corrections_through={corrections_through!r}, loaded={loaded!r})"
        )


def _opposite(direction: GEMDirection) -> GEMDirection:
    if direction is GEMDirection.ICD9_TO_ICD10:
        return GEMDirection.ICD10_TO_ICD9
    return GEMDirection.ICD9_TO_ICD10


def _targets(entries: tuple) -> set[str]:
    return {entry.target for entry in entries if entry.target is not None}


def _backport_corrections(
    stores: list[GEMStore], target_universes: list[set[str]]
) -> GEMStore:
    """Backport correction-only row sets without crossing code lifecycle changes.

    A source is adopted from a later release only while it stays present in every year's
    store, unblocked, and lineage-equal: ``values`` always holds the adopted lineage,
    the unchanged-skip and adoption steps both preserve that invariant, and ``blocked``
    only grows, so a blocked source never resumes.
    """
    if len(stores) != len(target_universes) or not stores:
        raise ValueError("A target universe is required for every GEM store")
    base = stores[0]
    if base.release is None or any(store.release is None for store in stores):
        raise ValueError("Retrospective correction requires release metadata")
    base_targets = target_universes[0]
    values = dict(base.items())
    selected = dict.fromkeys(base, base.release)
    blocked: dict[str, Release] = {}

    for index, (old, new) in enumerate(pairwise(stores)):
        old_universe = target_universes[index]
        new_universe = target_universes[index + 1]
        introduced = new_universe - old_universe
        retired = old_universe - new_universe
        for source in base:
            if source in blocked:
                continue
            if source not in old or source not in new:
                blocked[source] = new.release
                continue
            old_entries = old[source]
            new_entries = new[source]
            if old_entries == new_entries:
                continue
            old_targets = _targets(old_entries)
            new_targets = _targets(new_entries)
            lifecycle = bool((old_targets | new_targets) & (introduced | retired))
            historically_compatible = new_targets <= base_targets
            if lifecycle or not historically_compatible:
                blocked[source] = new.release
                continue
            values[source] = new_entries
            selected[source] = new.release

    reviewed = stores[-1].release
    provenance = {
        source: GEMProvenance(
            vocabulary_release=base.release,
            selected_mapping_release=selected[source],
            reviewed_through_release=reviewed,
            blocked_by_code_lifecycle_release=blocked.get(source),
        )
        for source in base
    }
    return GEMStore(
        values,
        system=base.system,
        direction=base.direction,
        release=base.release,
        provenance=provenance,
    )
