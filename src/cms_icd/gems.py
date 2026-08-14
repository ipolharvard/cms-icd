"""Lazy access to official CMS General Equivalence Mappings."""

from __future__ import annotations

from datetime import date
from threading import Lock
from typing import TYPE_CHECKING, Self

from .models import GEMDirection, Release
from .parsers import parse_gems
from .sources import CMSProvider, DirectoryProvider, MaterialProvider

if TYPE_CHECKING:
    from pathlib import Path

    from .stores import GEMStore


class GEMSystemView:
    """Lazy bidirectional GEMs for one ICD-10 system (CM or PCS)."""

    def __init__(
        self,
        provider: MaterialProvider | None,
        system: str,
        *,
        icd9_to_icd10: GEMStore | None = None,
        icd10_to_icd9: GEMStore | None = None,
    ) -> None:
        if system not in {"cm", "pcs"}:
            raise ValueError(f"Unsupported GEM system: {system!r}")
        self._provider = provider
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
                    store = parse_gems(
                        self._provider.paths(self.system, "gems"),
                        system=self.system,
                        direction=direction,
                        release=self._provider.release,
                    )
                    self._stores[direction] = store
        return store

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

    def __init__(self, provider: MaterialProvider) -> None:
        self._provider = provider
        self._cm: GEMSystemView | None = None
        self._pcs: GEMSystemView | None = None

    @classmethod
    def from_cms(
        cls,
        fiscal_year: int,
        *,
        cache_dir: str | Path | None = None,
        offline: bool = False,
    ) -> Self:
        """Create a lazy GEM selector for an official CMS fiscal year."""
        release = Release(fiscal_year, date(fiscal_year - 1, 10, 1))
        return cls(
            CMSProvider(
                release,
                cache_dir=cache_dir,
                offline=offline,
            )
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
            self._cm = GEMSystemView(self._provider, "cm")
        return self._cm

    @property
    def pcs(self) -> GEMSystemView:
        """Return the lazy procedure GEM view."""
        if self._pcs is None:
            self._pcs = GEMSystemView(self._provider, "pcs")
        return self._pcs

    def __repr__(self) -> str:
        """Return a representation without acquiring any GEM material."""
        loaded = [
            name
            for name, view in (("cm", self._cm), ("pcs", self._pcs))
            if view is not None
        ]
        return f"GEMKnowledgeBase(release={self.release!r}, loaded={loaded!r})"
