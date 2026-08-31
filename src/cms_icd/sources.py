"""Material discovery, download, and local-directory providers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
from abc import ABC, abstractmethod
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from fnmatch import fnmatch
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse
from zipfile import BadZipFile, ZipFile

import requests
from bs4 import BeautifulSoup

from .exceptions import (
    AmbiguousReleaseError,
    DownloadError,
    MaterialUnavailableError,
    ReleaseUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import Release

logger = logging.getLogger(__name__)

CMS_CATALOG_URL = "https://www.cms.gov/medicare/coding-billing/icd-10-codes"
CMS_ARCHIVE_URL = "https://www.cms.gov/medicare/coding-billing/icd-10-codes/icd-10-cm-icd-10-pcs-gem-archive"
_PACKAGE_NAME = "cms-icd"
_CACHE_SUBDIRECTORY = Path("ipolharvard") / _PACKAGE_NAME.replace("-", "_")
_FALLBACK_LATEST_FOR_FY = "latest_for_fy"

_catalog_lock = Lock()
_catalog_cache: dict[tuple[str, bool], Future[tuple[CatalogEntry, ...]]] = {}

_PATTERNS: dict[tuple[str, str], tuple[str, ...]] = {
    ("cm", "tabular"): ("icd10cm_tabular*.xml", "tabular.xml"),
    ("cm", "index"): (
        "*icd10cm_index*.xml",
        "*icd10cm_neoplasm*.xml",
        "*icd10cm_eindex*.xml",
        "*icd10cm_drug*.xml",
        "index.xml",
        "neoplasm.xml",
        "e-index.xml",
        "drug.xml",
    ),
    ("cm", "guidelines"): ("*cm*guidelines*.pdf",),
    ("pcs", "tabular"): ("*icd10pcs_tables*.xml", "*icd10pcs_tabular*.xml"),
    ("pcs", "index"): ("*icd10pcs_index*.xml",),
    ("pcs", "guidelines"): ("*pcs*guidelines*.pdf",),
    ("cm", "gems"): ("*i9gem*.txt", "*i10gem*.txt"),
    ("pcs", "gems"): ("*i9pcs*.txt", "*pcsi9*.txt"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One downloadable material advertised by CMS."""

    system: str
    material: str
    fiscal_year: int
    release_date: date
    label: str
    url: str
    page_url: str


def _catalog_records(entries: tuple[CatalogEntry, ...]) -> list[dict[str, object]]:
    return [
        {
            "system": entry.system,
            "material": entry.material,
            "fiscal_year": entry.fiscal_year,
            "release_date": entry.release_date.isoformat(),
            "label": entry.label,
            "url": entry.url,
            "page_url": entry.page_url,
        }
        for entry in entries
    ]


def _read_catalog(path: Path) -> tuple[CatalogEntry, ...] | None:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        return tuple(
            CatalogEntry(
                **{
                    **record,
                    "release_date": date.fromisoformat(record["release_date"]),
                }
            )
            for record in records
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _fetch_catalog(session: requests.Session) -> tuple[CatalogEntry, ...]:
    entries: list[CatalogEntry] = []
    for url in (CMS_CATALOG_URL, CMS_ARCHIVE_URL):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DownloadError(f"Unable to read CMS ICD catalog {url}: {exc}") from exc
        entries.extend(parse_catalog(response.text, url))
    return tuple(dict.fromkeys(entries))


def _write_catalog(path: Path, entries: tuple[CatalogEntry, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix="catalog.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(_catalog_records(entries), handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def _shared_catalog(
    cache_dir: Path,
    *,
    offline: bool,
    session: requests.Session,
    refresh: bool = False,
) -> tuple[CatalogEntry, ...]:
    key = (str(cache_dir.resolve()), offline)
    with _catalog_lock:
        future = None if refresh else _catalog_cache.get(key)
        if future is None:
            future = Future()
            _catalog_cache[key] = future
            owner = True
        else:
            owner = False
    if not owner:
        return future.result()

    catalog_path = cache_dir / "catalog.json"
    try:
        entries = None if refresh else _read_catalog(catalog_path)
        if entries is None:
            if offline:
                raise DownloadError(
                    "Offline mode requires a valid cached CMS catalog at "
                    f"{catalog_path}"
                )
            with _directory_lock(catalog_path):
                entries = None if refresh else _read_catalog(catalog_path)
                if entries is None:
                    entries = _fetch_catalog(session)
                    _write_catalog(catalog_path, entries)
        future.set_result(entries)
        return entries
    except BaseException as exc:
        future.set_exception(exc)
        with _catalog_lock:
            if _catalog_cache.get(key) is future:
                _catalog_cache.pop(key, None)
        raise


def refresh_cms_catalog(*, cache_dir: str | Path | None = None) -> None:
    """Fetch and atomically replace the cached CMS material catalog.

    Normal online constructors reuse a valid cached catalog indefinitely. Call this
    function when newly advertised CMS releases should become discoverable.
    """
    selected = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    _shared_catalog(
        selected,
        offline=False,
        session=requests.Session(),
        refresh=True,
    )


def _clear_catalog_memory_cache() -> None:
    """Clear process-local catalog state for tests and diagnostics."""
    with _catalog_lock:
        _catalog_cache.clear()


def fiscal_year_for(value: date) -> int:
    """Return the CMS fiscal year containing a date.

    Examples:
        >>> fiscal_year_for(date(2025, 9, 30))
        2025
        >>> fiscal_year_for(date(2025, 10, 1))
        2026
    """
    return value.year + 1 if (value.month, value.day) >= (10, 1) else value.year


def _infer_system(label: str, href: str, section: str = "") -> str | None:
    text = f"{label} {href}".lower()
    if "pcs" in text or "procedure code" in text:
        return "pcs"
    if "cm" in text or "diagnosis code" in text:
        return "cm"
    section_text = section.lower()
    if "pcs" in section_text or "procedure code" in section_text:
        return "pcs"
    if "cm" in section_text or "diagnosis code" in section_text:
        return "cm"
    if (
        "code tables, tabular and index" in text
        or "code tables and index" in text
        or "coding guidelines" in text
    ):
        return "cm"
    return None


def _infer_material(label: str, href: str) -> str | None:
    text = f"{label} {href}".lower()
    if "reimbursement" in text or "conversion table" in text:
        return None
    if re.search(r"\bgems?\b", text) or "general equivalence" in text:
        return "gems"
    if "guideline" in text:
        return "guidelines"
    if "table" in text and "index" in text:
        return "bundle"
    return None


def _infer_year(label: str, href: str) -> int | None:
    years = re.findall(r"20\d{2}", f"{label} {href}")
    return int(years[0]) if years else None


def _infer_release_date(label: str, href: str, fiscal_year: int) -> date:
    """Infer an effective date without treating file corrections as releases."""
    text = f"{label} {href}".lower()
    if "april" in text:
        return date(fiscal_year, 4, 1)
    if (
        re.search(r"\b(?:effective[- ]+)?january[- ]+0?1\b", text)
        or "january-1" in text
    ):
        return date(fiscal_year, 1, 1)
    return date(fiscal_year - 1, 10, 1)


def parse_catalog(
    html: str, page_url: str = CMS_CATALOG_URL
) -> tuple[CatalogEntry, ...]:
    """Parse supported ICD artifacts from a CMS catalog page.

    The parser deliberately ignores unrelated code-description, conversion, and addendum
    files.
    """
    soup = BeautifulSoup(html, "html.parser")
    entries: list[CatalogEntry] = []
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = str(anchor["href"])
        heading = anchor.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
        container = anchor.find_parent(["ul", "ol", "table"])
        context = " ".join(
            text
            for text in (
                heading.get_text(" ", strip=True) if heading is not None else "",
                container.get_text(" ", strip=True) if container is not None else "",
            )
            if text
        )
        system = _infer_system(label, href, context)
        material = _infer_material(label, href)
        fiscal_year = _infer_year(label, href)
        if system is None or material is None or fiscal_year is None:
            continue
        url = urljoin(page_url, href)
        release_date = _infer_release_date(label, href, fiscal_year)
        materials = ("tabular", "index") if material == "bundle" else (material,)
        entries.extend(
            CatalogEntry(
                system=system,
                material=item,
                fiscal_year=fiscal_year,
                release_date=release_date,
                label=label,
                url=url,
                page_url=page_url,
            )
            for item in materials
        )
    return tuple(entries)


class MaterialProvider(ABC):
    """Abstract provider of local paths for individual ICD materials."""

    release: Release

    @abstractmethod
    def paths(self, system: str, material: str) -> tuple[Path, ...]:
        """Return local files needed for a system/material pair."""


class DirectoryProvider(MaterialProvider):
    """Discover CMS-format files in an existing directory."""

    def __init__(self, directory: str | Path, release: Release) -> None:
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise FileNotFoundError(
                f"ICD material directory does not exist: {self.directory}"
            )
        self.release = release

    def paths(self, system: str, material: str) -> tuple[Path, ...]:
        patterns = _PATTERNS[(system, material)]
        matches = tuple(
            sorted(
                (
                    path
                    for path in self.directory.iterdir()
                    if path.is_file()
                    and any(
                        fnmatch(path.name.lower(), pattern.lower())
                        for pattern in patterns
                    )
                ),
                key=lambda path: path.name,
            )
        )
        if not matches:
            raise MaterialUnavailableError(
                f"No {system.upper()} {material} material found in {self.directory}"
            )
        if material not in {"index", "gems"} and len(matches) != 1:
            raise AmbiguousReleaseError(
                f"Expected one {system.upper()} {material} file in {self.directory}, "
                f"found {[path.name for path in matches]}"
            )
        return matches


def default_cache_dir() -> Path:
    """Return the platform-appropriate default cache directory."""
    base = os.environ.get("XDG_CACHE_HOME")
    cache_root = Path(base) if base else Path.home() / ".cache"
    return cache_root / _CACHE_SUBDIRECTORY


_LOCK_MARKER_NAME = "pid"
_LOCK_TIMEOUT_SECONDS = 600.0
_LOCK_RETRY_SECONDS = 0.05
_LOCK_PID_REUSE_MARGIN_SECONDS = 1.0


def _pid_is_alive(pid: int) -> bool:
    """Return True when a process with this PID appears to exist."""
    if os.name != "posix":
        # Signal-based liveness probing is not portable; assume a recorded
        # holder is alive so a live lock is never reclaimed.
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _linux_process_stats(pid: int) -> tuple[str, float] | None:
    """Return (state, start time in epoch seconds) from Linux /proc, else None."""
    try:
        raw = Path("/proc", str(pid), "stat").read_bytes()
        with Path("/proc/stat").open("rb") as handle:
            btime = next(
                int(line.split()[1]) for line in handle if line.startswith(b"btime ")
            )
    except (OSError, StopIteration, ValueError, IndexError):
        return None
    try:
        # Fields after the parenthesized command name, which may itself
        # contain parentheses: field 3 (state) and field 22 (starttime).
        fields = raw.rsplit(b")", 1)[1].split()
        hertz = os.sysconf("SC_CLK_TCK")
        return fields[0].decode("ascii"), btime + int(fields[19]) / hertz
    except (IndexError, ValueError, OSError, AttributeError, UnicodeDecodeError):
        return None


def _lock_holder_pid(lock: Path) -> int | None:
    """Return the PID recorded in a lock directory, or None if absent."""
    try:
        pid = int((lock / _LOCK_MARKER_NAME).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def _lock_is_stale(lock: Path) -> bool:
    """Return True when the lock directory has no live holder."""
    try:
        raw = (lock / _LOCK_MARKER_NAME).read_text(encoding="ascii")
    except FileNotFoundError:
        return True
    except OSError:
        # An unreadable marker is not proof that the holder is gone.
        return False
    try:
        holder = int(raw.strip())
    except ValueError:
        return True
    if holder <= 0 or not _pid_is_alive(holder):
        return True
    stats = _linux_process_stats(holder)
    if stats is None:
        return False
    state, started = stats
    if state == "Z":
        # A zombie has exited and will never remove its lock.
        return True
    try:
        acquired = lock.stat().st_mtime
    except OSError:
        return False
    # The holder must have started before creating the lock. A process
    # started after the lock exists holds a reused PID, not the lock.
    return started > acquired + _LOCK_PID_REUSE_MARGIN_SECONDS


def _write_lock_holder(lock: Path, pid: int) -> None:
    """Atomically record the holder PID inside the lock directory."""
    with NamedTemporaryFile(dir=lock, prefix="pid.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(str(pid).encode("ascii"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, lock / _LOCK_MARKER_NAME)


def _reclaim_stale_lock(lock: Path) -> bool:
    """Move a holder-less lock aside and delete it.

    The staleness verdict is re-checked on the moved directory: if the holder
    completed its atomic marker write while the directory was being moved, the
    lock is restored instead of deleted, so a live holder can never lose its
    lock to an in-flight reclaim. Return True when the lock was removed.
    """
    try:
        leftover = lock.with_name(f"{lock.name}.stale.{os.getpid()}")
        lock.rename(leftover)
    except OSError:
        return False
    if not _lock_is_stale(leftover):
        try:
            leftover.rename(lock)
        except OSError:
            # The lock name was taken in the meantime; the orphaned holder
            # directory cannot be restored, so remove it.
            shutil.rmtree(leftover, ignore_errors=True)
        return False
    shutil.rmtree(leftover, ignore_errors=True)
    return True


@contextmanager
def _directory_lock(
    path: Path, timeout: float = _LOCK_TIMEOUT_SECONDS
) -> Iterable[None]:
    """Serialize cache mutations across processes with a sibling lock directory.

    The holder records its PID inside the lock directory. A lock whose marker is missing
    or whose recorded PID is dead, a zombie, or a PID reused for a newer process is
    holder-less and reclaimed immediately, so a killed process cannot permanently block
    a cache destination. A lock held by a live process is waited on for up to
    ``timeout`` seconds; the default is sized to outlast a healthy download, extraction,
    or parse. A timeout names the live holder PID (or notes that no live holder could be
    removed) so a stuck holder can be found. Release renames the whole directory aside
    atomically, so a releasing holder never leaves a marker-less window that a waiter
    could mistake for a stale lock.
    """
    lock = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir(parents=True)
        except FileExistsError:
            stale = _lock_is_stale(lock)
            reclaimed = _reclaim_stale_lock(lock) if stale else False
            if time.monotonic() >= deadline and not reclaimed:
                holder = _lock_holder_pid(lock)
                if holder is not None:
                    detail = f"; holder pid {holder} is still running"
                else:
                    detail = "; the lock has no live holder and could not be removed"
                raise DownloadError(
                    f"Timed out after {timeout:g}s waiting for cache lock: "
                    f"{lock}{detail}"
                ) from None
            time.sleep(_LOCK_RETRY_SECONDS)
            continue
        try:
            _write_lock_holder(lock, os.getpid())
        except FileNotFoundError:
            # The marker-less creation window was reclaimed while we were
            # recording the holder; retry the acquisition.
            if time.monotonic() >= deadline:
                raise DownloadError(
                    f"Timed out after {timeout:g}s waiting for cache lock: {lock}"
                ) from None
            continue
        except OSError:
            # Only remove the lock when its marker identifies this process;
            # a missing or foreign marker may belong to a concurrent holder.
            if _lock_holder_pid(lock) == os.getpid():
                shutil.rmtree(lock, ignore_errors=True)
            raise DownloadError(
                f"Unable to record holder in cache lock: {lock}"
            ) from None
        break
    try:
        yield
    finally:
        try:
            leftover = lock.with_name(f"{lock.name}.released.{os.getpid()}")
            lock.rename(leftover)
        except OSError:
            pass
        else:
            shutil.rmtree(leftover, ignore_errors=True)


class CMSProvider(MaterialProvider):
    """Lazily resolve and cache materials from official CMS catalog pages.

    Exact revisions represent snapshots: each material resolves to the latest
    artifact effective on or before the requested revision. The requested date
    must itself be a revision advertised by CMS unless an explicit fallback is
    enabled.
    """

    def __init__(
        self,
        release: Release,
        *,
        service_date: date | None = None,
        cache_dir: str | Path | None = None,
        fallback: str | None = None,
        offline: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        if fallback is not None and fallback != _FALLBACK_LATEST_FOR_FY:
            raise ValueError(f"Unsupported fallback: {fallback!r}")
        self.release = release
        self.service_date = service_date
        self.cache_dir = (
            Path(cache_dir) if cache_dir is not None else default_cache_dir()
        )
        self.fallback = fallback
        self.offline = offline
        self._session = session or requests.Session()
        self._catalog: tuple[CatalogEntry, ...] | None = None

    def _load_catalog(self) -> tuple[CatalogEntry, ...]:
        if self._catalog is None:
            self._catalog = _shared_catalog(
                self.cache_dir,
                offline=self.offline,
                session=self._session,
            )
        return self._catalog

    def _select(self, system: str, material: str) -> CatalogEntry:
        catalog = self._load_catalog()
        all_for_year = [
            entry for entry in catalog if entry.fiscal_year == self.release.fiscal_year
        ]
        candidates = [
            entry
            for entry in all_for_year
            if entry.system == system and entry.material == material
        ]
        if self.service_date is not None:
            candidates = [
                item for item in candidates if item.release_date <= self.service_date
            ]
            if candidates:
                selected_date = max(item.release_date for item in candidates)
                candidates = [
                    item for item in candidates if item.release_date == selected_date
                ]
        else:
            known_release_dates = {item.release_date for item in all_for_year}
            if self.release.release_date in known_release_dates:
                candidates = [
                    item
                    for item in candidates
                    if item.release_date <= self.release.release_date
                ]
                if candidates:
                    selected_date = max(item.release_date for item in candidates)
                    candidates = [
                        item
                        for item in candidates
                        if item.release_date == selected_date
                    ]
            else:
                candidates = []

        unique = {(item.url, item.release_date): item for item in candidates}
        candidates = list(unique.values())
        if not candidates and self.fallback == _FALLBACK_LATEST_FOR_FY:
            available = [
                entry
                for entry in all_for_year
                if entry.system == system and entry.material == material
            ]
            if available:
                selected_date = max(item.release_date for item in available)
                candidates = [
                    item for item in available if item.release_date == selected_date
                ]
        if not candidates:
            raise ReleaseUnavailableError(
                f"No CMS {system.upper()} {material} material is available for "
                f"FY {self.release.fiscal_year}, release {self.release.release_date}"
            )
        if len(candidates) != 1:
            raise AmbiguousReleaseError(
                f"Multiple CMS {system.upper()} {material} artifacts match: "
                f"{[item.label for item in candidates]}"
            )
        return candidates[0]

    def _artifact_dir(self, entry: CatalogEntry) -> Path:
        return (
            self.cache_dir
            / f"fy{entry.fiscal_year}"
            / entry.release_date.isoformat()
            / entry.system
            / entry.material
        )

    @staticmethod
    def _manifest_files(destination: Path, manifest_path: Path) -> tuple[Path, ...]:
        """Return validated extracted files, or an empty tuple for stale state."""
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            names = manifest["files"]
            checksums = manifest["file_sha256"]
            if (
                not isinstance(names, list)
                or not names
                or not isinstance(checksums, dict)
            ):
                return ()
            files = tuple(destination / name for name in names)
            if any(
                not isinstance(name, str)
                or Path(name).name != name
                or not path.is_file()
                or checksums.get(name) != _sha256(path)
                for name, path in zip(names, files, strict=True)
            ):
                return ()
            return files
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return ()

    def paths(self, system: str, material: str) -> tuple[Path, ...]:
        entry = self._select(system, material)
        return self._resolve_paths(entry, system, material)

    def _resolve_paths(
        self, entry: CatalogEntry, system: str, material: str
    ) -> tuple[Path, ...]:
        destination = self._artifact_dir(entry)
        manifest_path = destination / "manifest.json"
        if manifest_path.exists():
            files = self._manifest_files(destination, manifest_path)
            if files:
                return files

        destination.parent.mkdir(parents=True, exist_ok=True)
        with _directory_lock(destination):
            if manifest_path.exists():
                files = self._manifest_files(destination, manifest_path)
                if files:
                    return files
            staging = destination.with_name(destination.name + ".tmp")
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir()
            try:
                files, digest = self._download_and_extract(
                    entry, staging, system, material
                )
                manifest = {
                    "fiscal_year": entry.fiscal_year,
                    "release_date": entry.release_date.isoformat(),
                    "system": system,
                    "material": material,
                    "label": entry.label,
                    "url": entry.url,
                    "page_url": entry.page_url,
                    "sha256": digest,
                    "files": [path.name for path in files],
                    "file_sha256": {
                        path.name: _sha256(path)
                        for path in sorted(files, key=lambda item: item.name)
                    },
                }
                (staging / "manifest.json").write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                if destination.exists():
                    shutil.rmtree(destination)
                staging.replace(destination)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        files = self._manifest_files(destination, manifest_path)
        if not files:
            raise DownloadError(f"Generated cache manifest is invalid: {manifest_path}")
        return files

    def _download_and_extract(
        self,
        entry: CatalogEntry,
        staging: Path,
        system: str,
        material: str,
    ) -> tuple[tuple[Path, ...], str]:
        artifact, digest = self._cached_artifact(entry)

        patterns = _PATTERNS[(system, material)]
        extracted: list[Path] = []
        try:
            if artifact.suffix.lower() == ".pdf":
                with artifact.open("rb") as handle:
                    signature = handle.read(5)
                if not signature.startswith(b"%PDF-"):
                    raise DownloadError(
                        f"CMS artifact is not a valid PDF file: {entry.url}"
                    )
                target = staging / Path(entry.url).name
                shutil.copy2(artifact, target)
                extracted.append(target)
            else:
                with ZipFile(artifact) as archive:
                    extracted_names: set[str] = set()
                    for member in archive.infolist():
                        filename = Path(member.filename).name
                        if not filename or not any(
                            fnmatch(filename.lower(), pattern.lower())
                            for pattern in patterns
                        ):
                            continue
                        if filename in extracted_names:
                            raise DownloadError(
                                "CMS artifact contains duplicate filename "
                                f"{filename!r}: "
                                f"{entry.url}"
                            )
                        target = staging / filename
                        target.write_bytes(archive.read(member))
                        extracted.append(target)
                        extracted_names.add(filename)
        except BadZipFile as exc:
            raise DownloadError(
                f"CMS artifact is not a valid ZIP file: {entry.url}"
            ) from exc
        if not extracted:
            expected = f"{system.upper()} {material}"
            raise MaterialUnavailableError(
                f"{entry.label!r} did not contain expected {expected} files"
            )
        return tuple(sorted(extracted, key=lambda path: path.name)), digest

    def _cached_artifact(self, entry: CatalogEntry) -> tuple[Path, str]:
        """Download a CMS URL once, even when it supplies several lazy stores."""
        url_key = hashlib.sha256(entry.url.encode()).hexdigest()
        suffix = Path(urlparse(entry.url).path).suffix or ".bin"
        artifact_dir = self.cache_dir / "_artifacts" / url_key
        artifact = artifact_dir / f"artifact{suffix}"
        checksum = artifact_dir / "sha256"
        if artifact.is_file() and checksum.is_file():
            expected = checksum.read_text(encoding="ascii").strip()
            if expected and _sha256(artifact) == expected:
                return artifact, expected

        artifact_dir.parent.mkdir(parents=True, exist_ok=True)
        with _directory_lock(artifact_dir):
            if artifact.is_file() and checksum.is_file():
                expected = checksum.read_text(encoding="ascii").strip()
                if expected and _sha256(artifact) == expected:
                    return artifact, expected
            if artifact_dir.exists():
                shutil.rmtree(artifact_dir)
            if self.offline:
                raise DownloadError(
                    f"Offline mode requires a valid cached CMS artifact for {entry.url}"
                )
            try:
                response = self._session.get(entry.url, timeout=60, stream=True)
                response.raise_for_status()
            except requests.RequestException as exc:
                raise DownloadError(f"Unable to download {entry.url}: {exc}") from exc

            digest = hashlib.sha256()
            temporary: Path | None = None
            try:
                with NamedTemporaryFile(
                    dir=artifact_dir.parent,
                    suffix=suffix,
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                            digest.update(chunk)
                staging = artifact_dir.with_name(artifact_dir.name + ".tmp")
                shutil.rmtree(staging, ignore_errors=True)
                staging.mkdir()
                temporary.replace(staging / artifact.name)
                temporary = None
                (staging / checksum.name).write_text(
                    digest.hexdigest() + "\n", encoding="ascii"
                )
                staging.replace(artifact_dir)
            except requests.RequestException as exc:
                raise DownloadError(f"Unable to download {entry.url}: {exc}") from exc
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return artifact, checksum.read_text(encoding="ascii").strip()
