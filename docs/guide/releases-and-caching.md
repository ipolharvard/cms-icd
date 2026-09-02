# Releases and caching

## Choose the date that controls coding

Pass the date on which the codes must be valid:

| Coding context                                 | Date to pass to `for_date()` |
| ---------------------------------------------- | ---------------------------- |
| ICD-10-CM for an inpatient stay                | Discharge date               |
| ICD-10-CM for an outpatient or other encounter | Encounter or date of service |
| ICD-10-PCS                                     | Inpatient discharge date     |

Do not use the date on which CMS published, corrected, or downloaded a file.
Those administrative dates do not necessarily change which codes apply.

```python
from datetime import date

from cms_icd import ICD10KnowledgeBase

# Inpatient CM and PCS materials for a discharge on April 1, 2025.
icd = ICD10KnowledgeBase.for_date(date(2025, 4, 1))
```

The date passed to `for_date()` controls both `.cm` and `.pcs`. If an
application is handling records governed by different dates, create a separate
knowledge base for each date.

## Fiscal years and revisions

CMS fiscal years begin on October 1. `for_date()` calculates the fiscal year and
selects the latest advertised revision effective on or before the relevant
coding date. CMS-backed discovery covers production ICD-10 releases from FY
2016 onward.

```pycon
>>> from datetime import date
>>> from cms_icd.sources import fiscal_year_for
>>> fiscal_year_for(date(2025, 9, 30))
2025
>>> fiscal_year_for(date(2025, 10, 1))
2026

```

Use `from_cms()` to pin an exact fiscal-year snapshot for a reproducible
dataset, model, or audit:

```python
icd = ICD10KnowledgeBase.from_cms(
    fiscal_year=2026,
    release_date=date(2026, 4, 1),
)
```

If `release_date` is omitted, October 1 before the fiscal year is used. The
requested date must be an effective revision advertised by CMS; an arbitrary
date such as February 1 is not accepted as an exact snapshot.

## How midyear updates work

CMS commonly starts a fiscal year with an October 1 release and publishes
additional files effective April 1. Both dates belong to the same fiscal year:

```pycon
>>> fiscal_year_for(date(2025, 3, 31))
2025
>>> fiscal_year_for(date(2025, 4, 1))
2025

```

The April update is not necessarily a complete replacement of every material.
A snapshot resolves each material independently:

1. Use an artifact effective on the requested revision when CMS published one.
2. Otherwise inherit the latest earlier artifact in the same fiscal year.
3. Never inherit an artifact from a different fiscal year.

For example, the currently advertised snapshots resolve as follows:

| Snapshot          | CM tables/index | CM guidelines     | PCS tables/index | PCS guidelines    |
| ----------------- | --------------- | ----------------- | ---------------- | ----------------- |
| FY2025, October 1 | October         | October           | October          | October           |
| FY2025, April 1   | April           | October inherited | April            | October inherited |
| FY2026, October 1 | October         | October           | October          | October           |
| FY2026, April 1   | April           | October inherited | April            | April             |

Consequently, two knowledge bases in the same fiscal year can contain different
codes:

```python
before_update = ICD10KnowledgeBase.for_date(date(2025, 3, 31))
after_update = ICD10KnowledgeBase.for_date(date(2025, 4, 1))
```

The live integration suite verifies this boundary using a PCS code that is
absent from the FY2025 October tables and present in the April tables.

## Guideline support

`cms-icd` supports the official CMS ICD-10-CM and ICD-10-PCS guideline files
associated with a snapshot. Availability in the CMS catalog, as checked in
July 2026, is:

| Fiscal year   | ICD-10-CM guidelines     | ICD-10-PCS guidelines | Revision behavior                             |
| ------------- | ------------------------ | --------------------- | --------------------------------------------- |
| FY2016–FY2024 | Supported                | Supported             | Annual October guideline                      |
| FY2025        | Supported                | Supported             | October guideline inherited by April snapshot |
| FY2026        | Supported                | Supported             | CM inherits October; PCS has an April update  |
| FY2027        | Not yet published by CMS | Supported             | October 2026 PCS guideline is advertised      |

The package raises
[`ReleaseUnavailableError`](../reference/exceptions.md) when CMS does not
provide a requested guideline. It does not silently substitute a guideline from
another fiscal year.

CMS availability can change as new files are published. See the official
[current ICD-10 files](https://www.cms.gov/medicare/coding-billing/icd-10-codes)
and [ICD-10 archive](https://www.cms.gov/medicare/coding-billing/icd-10-codes/icd-10-cm-icd-10-pcs-gem-archive)
for the source catalog.

Guidelines are loaded independently of tables and indexes:

```python
cm_guidelines = icd.cm.guidelines
pcs_guidelines = icd.pcs.guidelines
```

## Strict selection and fallback

Snapshot selection is strict by default. If CMS does not advertise the
requested revision for any supported material, accessing its first material
raises
[`ReleaseUnavailableError`](../reference/exceptions.md).

An application may explicitly permit the latest available material in the same
fiscal year:

```python
icd = ICD10KnowledgeBase.from_cms(
    fiscal_year=2026,
    release_date=date(2026, 4, 1),
    fallback="latest_for_fy",
)
```

> [!WARNING]
> A fallback can change cohort labels or coding behavior. Record the resolved
> release and use fallback only when that scientific or operational tradeoff
> is acceptable.

## Cache behavior

By default, files are cached under:

```text
${XDG_CACHE_HOME}/ipolharvard/cms_icd
```

or `~/.cache/ipolharvard/cms_icd` when `XDG_CACHE_HOME` is not set. The package
does not automatically inspect or migrate the former `cms-icd` cache directory.
Every CMS-backed ICD and GEM constructor accepts `cache_dir` as either a string
or a [`pathlib.Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path).
Set it to keep artifacts with a project, scratch, or shared application cache:

```python
icd = ICD10KnowledgeBase.for_date(
    date(2026, 5, 1),
    cache_dir="data/cms_icd",
)
```

There is no separate cache enable/disable switch. CMS archives must be stored
and extracted before they can be parsed, so disabling persistence would still
require a temporary directory. Applications that need ephemeral storage can
own its lifetime explicitly:

```python
from datetime import date
from tempfile import TemporaryDirectory

with TemporaryDirectory() as cache_dir:
    icd = ICD10KnowledgeBase.for_date(
        date(2026, 5, 1),
        cache_dir=cache_dir,
    )
    code = icd.cm["I10"]
```

Keep all material access inside the context because the directory is removed
when the block exits. `offline=True` has different semantics: it prohibits
network access and requires the selected catalog and artifacts to exist in the
chosen cache directory.

The downloaded catalog is also persistent and is reused until explicitly
refreshed. This keeps repeated pipelines from downloading and parsing CMS
catalog HTML even when they do not set `offline=True`. Refresh it when newly
advertised CMS releases should become visible:

```python
from cms_icd import refresh_cms_catalog

refresh_cms_catalog(cache_dir="data/cms_icd")
```

Refreshing the catalog does not delete or redownload existing CMS artifacts.

Downloaded artifacts are keyed by URL, checksummed with SHA-256, and reused when
one CMS bundle supplies multiple lazy stores. Extraction uses a directory lock
and an atomic staging rename so concurrent readers do not observe partial
materials.

Each extracted material directory contains `manifest.json` with the source URL,
release metadata, artifact checksum, extracted filenames, and a checksum for
each extracted file. Checksums are revalidated before reuse; corrupt or
incomplete cache entries are rebuilt automatically.

Parsed GEM stores, retrospectively corrected GEM stores, ICD-10 tabular
hierarchies, alphabetic indexes, and coding-guideline stores are cached under
a versioned `_derived` directory. Their compact JSON payloads are checksummed
and keyed by source-file digests, release metadata, and parser or
correction-policy versions. Final best-effort mapping resolutions are
assembled from these reusable stores and retained only for the life of the
Python process. Corrupt or incompatible derived entries are rebuilt from the
validated source artifacts.
