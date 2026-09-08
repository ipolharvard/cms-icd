# Caching and offline use

## Choose a cache location

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
from datetime import date

from cms_icd import ICD10KnowledgeBase

icd = ICD10KnowledgeBase.for_date(
    date(2026, 5, 1),
    cache_dir="data/cms_icd",
)
```

## Use ephemeral or offline storage

There is no separate cache enable/disable switch. CMS archives must be stored
and extracted before they can be parsed, so disabling persistence would still
require a temporary directory. Applications that need ephemeral storage can
own its lifetime explicitly:

```python
from datetime import date
from tempfile import TemporaryDirectory

from cms_icd import ICD10KnowledgeBase

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

Use [Local and custom sources](local-sources.md) instead when the application
already owns a directory of original CMS-format files.

## Release in-memory state

Shared catalog entries, parsed stores, and mapping resolutions remain retained
until the process exits or the application releases them. When cycling through
distinct cache directories, such as per-use temporary directories, release
that state explicitly:

```python
from cms_icd import clear_memory_caches

clear_memory_caches()
```

Pass `MemoryCache` members or their string values to clear only selected layers.
Releasing in-memory state does not modify persistent cache files. See the
[cache API reference](../reference/caches.md) for selectors and individual
cache-clearing functions.

## Refresh the CMS catalog

The downloaded catalog is persistent and is reused until explicitly refreshed.
This keeps repeated pipelines from downloading and parsing CMS catalog HTML
even when they do not set `offline=True`. Refresh it when newly advertised CMS
releases should become visible:

```python
from cms_icd import refresh_cms_catalog

refresh_cms_catalog(cache_dir="data/cms_icd")
```

Refreshing the catalog does not delete or redownload existing CMS artifacts.
See [Release selection](releases.md) for snapshot and fallback semantics.

## Cache integrity and reuse

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
`_derived`. Their compact JSON payloads are checksummed and keyed by source-file
digests and release metadata. The cache records the installed `cms-icd` package
version; changing versions deletes and rebuilds `_derived` without deleting or
redownloading official CMS artifacts. Final best-effort mapping resolutions are
assembled from these reusable stores and retained only for the life of the
Python process. Corrupt derived entries are rebuilt from the validated source
artifacts.
