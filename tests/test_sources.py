from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Event, Thread
from zipfile import ZipFile

import pytest
import requests

from cms_icd import ICD10KnowledgeBase
from cms_icd.exceptions import (
    AmbiguousReleaseError,
    DownloadError,
    MaterialUnavailableError,
    ReleaseUnavailableError,
)
from cms_icd.models import Release
from cms_icd.sources import (
    _LOCK_MARKER_NAME,
    CMSProvider,
    DirectoryProvider,
    _clear_catalog_memory_cache,
    _directory_lock,
    _reclaim_stale_lock,
    default_cache_dir,
    parse_catalog,
    refresh_cms_catalog,
)

CATALOG_HTML = """
<html><body>
  <a href="/files/zip/2026-code-tables-tabular-and-index.zip">
    2026 Code Tables, Tabular and Index (ZIP)
  </a>
  <a href="/files/zip/april-1-2026-code-tables-tabular-index.zip">
    April 1, 2026 Code Tables, Tabular and Index (ZIP)
  </a>
  <a href="/files/zip/2025-code-tables-tabular-and-index-april.zip">
    2025 Code Tables, Tabular and Index (ZIP)
  </a>
  <a href="/files/zip/2026-pcs-tables-index.zip">
    2026 ICD-10-PCS Code Tables and Index (ZIP)
  </a>
  <a href="/files/document/fy-2026-icd-10-cm-coding-guidelines.pdf">
    FY 2026 ICD-10-CM Coding Guidelines (PDF)
  </a>
  <a href="/downloads/2020-coding-guidelines.pdf">
    2020 Coding Guidelines (PDF)
  </a>
  <a href="/downloads/2017-icd10-code-tables-index.zip">
    2017 Code Tables and Index (ZIP)
  </a>
  <a href="/files/zip/2024-code-tables-updated-04/01/2024.zip">
    2024 Code Tables and Index (ZIP) - Updated 04/01/2024
  </a>
  <a href="/files/zip/2026-conversion-table.zip">2026 Conversion Table</a>
</body></html>
"""

GEM_CATALOG_HTML = """
<html><body>
  <h3>Diagnosis Code Set General Equivalence Mappings</h3>
  <a href="/files/zip/2018-gems.zip">2018 General Equivalence Mappings</a>
  <a href="/files/zip/2018-reimbursement-mappings.zip">
    2018 Reimbursement Mappings
  </a>
  <h3>Procedure Coding System (ICD-10-PCS)</h3>
  <a href="/files/zip/2018-pcs-gems.zip">2018 GEMs</a>
  <a href="/files/zip/2016-gems-dx.zip">
    2016 General Equivalence Mappings - Diagnosis Codes
  </a>
  <a href="/files/zip/2016-gems-proc.zip">
    2016 General Equivalence Mappings - Procedure Codes
  </a>
</body></html>
"""

LEGACY_TABLE_CATALOG_HTML = """
<html><body>
  <h3>ICD-10 Files</h3>
  <ul>
    <li><a href="/files/zip/2014-icd10-code-tables-and-index.zip">
      2014 Code Tables and Index (ZIP)
    </a></li>
    <li>2014 ICD-10-CM Present On Admission Exempt List</li>
  </ul>
  <ul>
    <li><a href="/files/zip/2014-code-tables-and-index.zip">
      2014 Code Tables and Index (ZIP)
    </a></li>
    <li>2014 Official ICD-10-PCS Coding Guidelines</li>
  </ul>
</body></html>
"""


def test_default_cache_uses_namespaced_home_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", "/tmp/example-home")

    assert default_cache_dir() == Path("/tmp/example-home/.cache/ipolharvard/cms_icd")


def test_default_cache_honors_xdg_cache_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/example-cache")

    assert default_cache_dir() == Path("/tmp/example-cache/ipolharvard/cms_icd")


def test_provider_accepts_path_and_string_cache_directories(tmp_path: Path) -> None:
    path_cache = tmp_path / "path-cache"
    string_cache = tmp_path / "string-cache"

    path_provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=path_cache,
    )
    string_provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=str(string_cache),
    )

    assert path_provider.cache_dir == path_cache
    assert string_provider.cache_dir == string_cache
    assert not path_cache.exists()
    assert not string_cache.exists()


def test_parse_catalog_distinguishes_initial_and_april_revisions() -> None:
    entries = parse_catalog(CATALOG_HTML)
    cm_tabular = {
        entry.url: entry.release_date
        for entry in entries
        if entry.system == "cm" and entry.material == "tabular"
    }
    assert cm_tabular[
        "https://www.cms.gov/files/zip/2026-code-tables-tabular-and-index.zip"
    ] == date(2025, 10, 1)
    assert cm_tabular[
        "https://www.cms.gov/files/zip/april-1-2026-code-tables-tabular-index.zip"
    ] == date(2026, 4, 1)
    assert cm_tabular[
        "https://www.cms.gov/files/zip/2025-code-tables-tabular-and-index-april.zip"
    ] == date(2025, 4, 1)
    assert cm_tabular[
        "https://www.cms.gov/downloads/2017-icd10-code-tables-index.zip"
    ] == date(2016, 10, 1)
    assert any(
        entry.system == "cm"
        and entry.material == "guidelines"
        and entry.fiscal_year == 2020
        for entry in entries
    )
    assert cm_tabular[
        "https://www.cms.gov/files/zip/2024-code-tables-updated-04/01/2024.zip"
    ] == date(2023, 10, 1)
    assert {entry.material for entry in entries} == {"tabular", "index", "guidelines"}


def test_parse_catalog_discovers_cm_and_pcs_gems_from_section_context() -> None:
    entries = parse_catalog(GEM_CATALOG_HTML)

    assert [(entry.system, entry.material, entry.fiscal_year) for entry in entries] == [
        ("cm", "gems", 2018),
        ("pcs", "gems", 2018),
        ("cm", "gems", 2016),
        ("pcs", "gems", 2016),
    ]


def test_parse_catalog_uses_section_for_ambiguous_legacy_table_labels() -> None:
    entries = parse_catalog(LEGACY_TABLE_CATALOG_HTML)

    assert [(entry.system, entry.material) for entry in entries] == [
        ("cm", "tabular"),
        ("cm", "index"),
        ("pcs", "tabular"),
        ("pcs", "index"),
    ]


def test_exact_revision_inherits_unchanged_material() -> None:
    entries = parse_catalog(CATALOG_HTML)
    provider = CMSProvider(Release(2026, date(2026, 4, 1)))
    provider._catalog = entries

    assert provider._select("cm", "tabular").release_date == date(2026, 4, 1)
    assert provider._select("cm", "guidelines").release_date == date(2025, 10, 1)


def test_service_date_selects_latest_effective_material() -> None:
    entries = parse_catalog(CATALOG_HTML)
    before = CMSProvider(
        Release(2026, date(2026, 3, 31)),
        service_date=date(2026, 3, 31),
    )
    before._catalog = entries
    after = CMSProvider(
        Release(2026, date(2026, 4, 1)),
        service_date=date(2026, 4, 1),
    )
    after._catalog = entries

    assert before._select("cm", "tabular").release_date == date(2025, 10, 1)
    assert after._select("cm", "tabular").release_date == date(2026, 4, 1)


def test_exact_unknown_revision_remains_strict() -> None:
    provider = CMSProvider(Release(2026, date(2026, 2, 1)))
    provider._catalog = parse_catalog(CATALOG_HTML)

    with pytest.raises(ReleaseUnavailableError):
        provider._select("cm", "tabular")


def test_latest_for_fy_fallback_is_explicit() -> None:
    provider = CMSProvider(
        Release(2026, date(2026, 2, 1)),
        fallback="latest_for_fy",
    )
    provider._catalog = parse_catalog(CATALOG_HTML)

    assert provider._select("cm", "tabular").release_date == date(2026, 4, 1)


def test_distinct_matching_urls_are_ambiguous() -> None:
    provider = CMSProvider(Release(2026, date(2025, 10, 1)))
    provider._catalog = parse_catalog(
        CATALOG_HTML.replace(
            "</body>",
            '<a href="/other/2026-code-tables-and-index.zip">'
            "2026 Code Tables and Index (ZIP)</a></body>",
        )
    )

    with pytest.raises(AmbiguousReleaseError):
        provider._select("cm", "tabular")


class FakeResponse:
    def __init__(
        self,
        *,
        text: str = "",
        content: bytes = b"",
        error: Exception | None = None,
    ) -> None:
        self.text = text
        self.content = content
        self.error = error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self.content


class FakeSession:
    def __init__(self, archive: bytes) -> None:
        self.archive = archive
        self.downloads = 0
        self.catalog_reads = 0

    def get(self, url: str, **kwargs):
        del kwargs
        if "coding-billing/icd-10-codes" in url:
            self.catalog_reads += 1
            return FakeResponse(text=CATALOG_HTML)
        self.downloads += 1
        return FakeResponse(content=self.archive)


class InterruptedResponse(FakeResponse):
    def iter_content(self, chunk_size: int):
        del chunk_size
        yield b"partial"
        raise requests.ConnectionError("connection interrupted")


class InterruptedSession(FakeSession):
    def get(self, url: str, **kwargs):
        del kwargs
        if "coding-billing/icd-10-codes" in url:
            return FakeResponse(text=CATALOG_HTML)
        self.downloads += 1
        return InterruptedResponse()


def _cm_archive() -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("icd10cm_tabular_2026.xml", "<ICD10CM.tabular/>")
        archive.writestr("icd10cm_index_2026.xml", "<ICD10CM.index/>")
        archive.writestr("icd10cm_neoplasm_2026.xml", "<ICD10CM.index/>")
        archive.writestr("icd10cm_eindex_2026.xml", "<ICD10CM.index/>")
        archive.writestr("icd10cm_drug_2026.xml", "<ICD10CM.index/>")
    return buffer.getvalue()


def _legacy_cm_archive() -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("Tabular.xml", "<ICD10CM.tabular/>")
        archive.writestr("Index.xml", "<ICD10CM.index/>")
        archive.writestr("Neoplasm.xml", "<ICD10CM.index/>")
        archive.writestr("E-Index.xml", "<ICD10CM.index/>")
        archive.writestr("Drug.xml", "<ICD10CM.index/>")
    return buffer.getvalue()


def test_one_archive_download_supplies_tabular_and_index(tmp_path: Path) -> None:
    session = FakeSession(_cm_archive())
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
    )

    tabular = provider.paths("cm", "tabular")
    index = provider.paths("cm", "index")

    assert session.downloads == 1
    assert [path.name for path in tabular] == ["icd10cm_tabular_2026.xml"]
    assert len(index) == 4
    manifest = json.loads(
        (
            tmp_path / "fy2026" / "2025-10-01" / "cm" / "tabular" / "manifest.json"
        ).read_text()
    )
    assert manifest["release_date"] == "2025-10-01"
    assert len(manifest["sha256"]) == 64
    assert set(manifest["file_sha256"]) == {"icd10cm_tabular_2026.xml"}


def test_legacy_archive_names_supply_tabular_and_index(tmp_path: Path) -> None:
    session = FakeSession(_legacy_cm_archive())
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
    )

    assert [path.name for path in provider.paths("cm", "tabular")] == ["Tabular.xml"]
    assert {path.name for path in provider.paths("cm", "index")} == {
        "Drug.xml",
        "E-Index.xml",
        "Index.xml",
        "Neoplasm.xml",
    }


def test_corrupt_extracted_file_is_rebuilt_from_cached_artifact(
    tmp_path: Path,
) -> None:
    session = FakeSession(_cm_archive())
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
    )
    path = provider.paths("cm", "tabular")[0]
    path.write_text("corrupt")

    rebuilt = provider.paths("cm", "tabular")[0]

    assert rebuilt.read_text() == "<ICD10CM.tabular/>"
    assert session.downloads == 1


def test_corrupt_downloaded_artifact_is_downloaded_again(tmp_path: Path) -> None:
    session = FakeSession(_cm_archive())
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
    )
    provider.paths("cm", "tabular")
    artifact = next((tmp_path / "_artifacts").glob("*/artifact.zip"))
    artifact.write_bytes(b"corrupt")
    extracted = (
        tmp_path
        / "fy2026"
        / "2025-10-01"
        / "cm"
        / "tabular"
        / "icd10cm_tabular_2026.xml"
    )
    extracted.write_text("corrupt")

    provider.paths("cm", "tabular")

    assert session.downloads == 2


def test_malformed_manifest_is_rebuilt(tmp_path: Path) -> None:
    session = FakeSession(_cm_archive())
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
    )
    provider.paths("cm", "tabular")
    manifest = tmp_path / "fy2026" / "2025-10-01" / "cm" / "tabular" / "manifest.json"
    manifest.write_text("{")

    paths = provider.paths("cm", "tabular")

    assert paths[0].name == "icd10cm_tabular_2026.xml"
    assert json.loads(manifest.read_text())["system"] == "cm"
    assert session.downloads == 1


def test_invalid_zip_payload_is_rejected(tmp_path: Path) -> None:
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=FakeSession(b"<html>not a zip</html>"),  # type: ignore[arg-type]
    )

    with pytest.raises(DownloadError, match="not a valid ZIP"):
        provider.paths("cm", "tabular")


def test_invalid_direct_pdf_payload_is_rejected(tmp_path: Path) -> None:
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=FakeSession(b"<html>not a pdf</html>"),  # type: ignore[arg-type]
    )

    with pytest.raises(DownloadError, match="not a valid PDF"):
        provider.paths("cm", "guidelines")


def test_interrupted_download_cleans_temporary_file(tmp_path: Path) -> None:
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=InterruptedSession(b""),  # type: ignore[arg-type]
    )

    with pytest.raises(DownloadError, match="connection interrupted"):
        provider.paths("cm", "tabular")

    assert not list(tmp_path.rglob("tmp*"))


def test_nested_zip_members_are_flattened(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "nested/files/icd10cm_tabular_2026.xml",
            "<ICD10CM.tabular/>",
        )
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=FakeSession(buffer.getvalue()),  # type: ignore[arg-type]
    )

    path = provider.paths("cm", "tabular")[0]

    assert path.name == "icd10cm_tabular_2026.xml"


def test_duplicate_flattened_zip_filename_is_rejected(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("a/icd10cm_tabular_2026.xml", "first")
        archive.writestr("b/icd10cm_tabular_2026.xml", "second")
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=FakeSession(buffer.getvalue()),  # type: ignore[arg-type]
    )

    with pytest.raises(DownloadError, match="duplicate filename"):
        provider.paths("cm", "tabular")


def test_concurrent_requests_share_one_download(tmp_path: Path) -> None:
    session = FakeSession(_cm_archive())
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(lambda _: provider.paths("cm", "tabular"), range(4))
        )

    assert {result[0] for result in results} == {results[0][0]}
    assert session.downloads == 1


def test_catalog_is_reused_until_explicit_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_session = FakeSession(_cm_archive())
    first = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=first_session,  # type: ignore[arg-type]
    )

    assert first._load_catalog()
    assert first_session.catalog_reads == 2

    _clear_catalog_memory_cache()
    second_session = FakeSession(_cm_archive())
    second = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=second_session,  # type: ignore[arg-type]
    )
    assert second._load_catalog()
    assert second_session.catalog_reads == 0

    refreshed_session = FakeSession(_cm_archive())
    monkeypatch.setattr("cms_icd.sources.requests.Session", lambda: refreshed_session)
    refresh_cms_catalog(cache_dir=tmp_path)

    assert refreshed_session.catalog_reads == 2


def test_directory_provider_reports_missing_and_ambiguous_files(
    tmp_path: Path,
) -> None:
    provider = DirectoryProvider(tmp_path, Release(2026, date(2025, 10, 1)))
    with pytest.raises(MaterialUnavailableError):
        provider.paths("cm", "tabular")

    (tmp_path / "icd10cm_tabular_a.xml").touch()
    (tmp_path / "icd10cm_tabular_b.xml").touch()
    with pytest.raises(AmbiguousReleaseError):
        provider.paths("cm", "tabular")


def test_offline_provider_requires_cached_catalog(tmp_path: Path) -> None:
    provider = CMSProvider(
        Release(2018, date(2017, 10, 1)),
        cache_dir=tmp_path,
        offline=True,
    )

    with pytest.raises(DownloadError, match="cached CMS catalog"):
        provider.paths("cm", "gems")


def test_stale_lock_without_holder_is_reclaimed(tmp_path: Path) -> None:
    session = FakeSession(_cm_archive())
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
    )
    (tmp_path / "catalog.json.lock").mkdir()

    paths = provider.paths("cm", "tabular")

    assert [path.name for path in paths] == ["icd10cm_tabular_2026.xml"]
    assert not (tmp_path / "catalog.json.lock").exists()
    assert not list(tmp_path.rglob("*.lock"))


def test_stale_lock_with_dead_holder_pid_is_reclaimed(tmp_path: Path) -> None:
    with subprocess.Popen([sys.executable, "-c", "pass"]) as process:
        process.wait()
        dead_pid = process.pid
    try:
        os.kill(dead_pid, 0)
    except ProcessLookupError:
        pass
    else:
        pytest.skip("dead PID was reused before it could be probed")
    lock = tmp_path / "catalog.json.lock"
    lock.mkdir()
    (lock / _LOCK_MARKER_NAME).write_text(str(dead_pid), encoding="ascii")
    session = FakeSession(_cm_archive())
    provider = CMSProvider(
        Release(2026, date(2025, 10, 1)),
        cache_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
    )

    paths = provider.paths("cm", "tabular")

    assert [path.name for path in paths] == ["icd10cm_tabular_2026.xml"]
    assert not lock.exists()


def test_live_holder_lock_is_waited_not_reclaimed(tmp_path: Path) -> None:
    target = tmp_path / "catalog.json"
    acquired = Event()
    release = Event()

    def hold() -> None:
        with _directory_lock(target):
            acquired.set()
            release.wait(10)

    holder = Thread(target=hold)
    holder.start()
    try:
        assert acquired.wait(10)
        with pytest.raises(DownloadError, match="waiting for cache lock"):
            with _directory_lock(target, timeout=0.3):
                pass
        assert (tmp_path / "catalog.json.lock").exists()
    finally:
        release.set()
        holder.join(10)

    with _directory_lock(target):
        pass
    assert not (tmp_path / "catalog.json.lock").exists()


def test_reclaim_restores_lock_whose_marker_landed_before_rename(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "catalog.json.lock"
    lock.mkdir()
    # A waiter's staleness verdict was computed while the holder (this
    # process) was between mkdir and its atomic marker write; the marker
    # landed before the rename, so the holder is live and must keep the
    # lock rather than have it reclaimed in flight.
    (lock / _LOCK_MARKER_NAME).write_text(str(os.getpid()), encoding="ascii")

    assert not _reclaim_stale_lock(lock)

    assert lock.exists()
    assert (lock / _LOCK_MARKER_NAME).read_text(encoding="ascii") == str(os.getpid())


def test_unknown_fallback_value_is_rejected() -> None:
    for value in ("latest-fy", "latest_for_fy2026", ""):
        with pytest.raises(ValueError, match="fallback"):
            CMSProvider(Release(2026, date(2026, 2, 1)), fallback=value)

    provider = CMSProvider(Release(2026, date(2026, 2, 1)))
    assert provider.fallback is None
    provider = CMSProvider(Release(2026, date(2026, 2, 1)), fallback="latest_for_fy")
    assert provider.fallback == "latest_for_fy"


def test_from_cms_and_for_date_reject_unknown_fallback() -> None:
    for value in ("latest-fy", "latest_fy"):
        with pytest.raises(ValueError, match="fallback"):
            ICD10KnowledgeBase.from_cms(
                fiscal_year=2026,
                release_date=date(2026, 2, 1),
                fallback=value,
            )
        with pytest.raises(ValueError, match="fallback"):
            ICD10KnowledgeBase.for_date(date(2026, 2, 1), fallback=value)
