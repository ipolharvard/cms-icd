# CMS ICD

[![PyPI](https://img.shields.io/pypi/v/cms-icd.svg)](https://pypi.org/project/cms-icd/)
[![CI](https://github.com/ipolharvard/cms-icd/actions/workflows/ci.yml/badge.svg)](https://github.com/ipolharvard/cms-icd/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-latest-blue.svg)](https://ipolharvard.github.io/cms-icd/)
[![CMS source](https://github.com/ipolharvard/cms-icd/actions/workflows/catalog-cms.yml/badge.svg)](https://github.com/ipolharvard/cms-icd/actions/workflows/catalog-cms.yml)
[![License](https://img.shields.io/pypi/l/cms-icd.svg)](https://github.com/ipolharvard/cms-icd/blob/main/LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21952934.svg)](https://doi.org/10.5281/zenodo.21952934)

`cms-icd` makes official CMS ICD-10 materials easy to use from Python. Look up
ICD-10-CM diagnoses and ICD-10-PCS procedures, browse their hierarchies and
indexes, read coding guidelines, and work with ICD-9/ICD-10 General Equivalence
Mappings (GEMs).

Choose data by service date or by an exact CMS release. Files are downloaded
from CMS only when needed and cached for later use.

## Install

With `uv`:

```bash
uv add cms-icd
```

Or with `pip`:

```bash
pip install cms-icd
```

## Look up ICD-10 codes

Use the date that controls coding for the encounter:

```python
from datetime import date

from cms_icd import ICD10KnowledgeBase

icd = ICD10KnowledgeBase.for_date(date(2026, 5, 1))

diagnosis = icd.cm["I10"]
print(diagnosis.description)
```

Use the discharge date for inpatient ICD-10-CM and ICD-10-PCS. For other
ICD-10-CM use cases, use the encounter or service date.

The knowledge base provides separate views for:

- `icd.cm`: ICD-10-CM codes, hierarchy, index, and guidelines;
- `icd.pcs`: ICD-10-PCS codes, hierarchy, index, and guidelines.

See the [documentation](https://ipolharvard.github.io/cms-icd/) for code
navigation, index lookup, and guideline access.

## Choose an exact release

Use `from_cms()` when you need a specific CMS fiscal-year revision:

```python
from datetime import date

from cms_icd import ICD10KnowledgeBase

icd = ICD10KnowledgeBase.from_cms(
    fiscal_year=2026,
    release_date=date(2026, 4, 1),
)
```

CMS commonly starts a fiscal year with an October release and may publish an
April update. If a material did not change in the update, `cms-icd` uses the
most recent earlier material from the same fiscal year.

Release selection is strict by default. The
[release guide](https://ipolharvard.github.io/cms-icd/guide/releases-and-caching/)
explains available years, midyear updates, and explicit fallback behavior.

## Use General Equivalence Mappings

Access the official GEM rows and flags without losing alternatives or
combination mappings:

```python
from cms_icd import GEMKnowledgeBase

gems = GEMKnowledgeBase.from_cms(fiscal_year=2018)
entries = gems.cm.icd9_to_icd10["4280"]
mapping = gems.cm.icd9_to_icd10.mapping("4280")
```

Diagnosis mappings are available through `gems.cm`, and procedure mappings
through `gems.pcs`. Each provides both ICD-9-to-ICD-10 and ICD-10-to-ICD-9
directions.

For historical GEMs with later CMS corrections, use:

```python
gems = GEMKnowledgeBase.corrected_from_cms(fiscal_year=2016)
```

The library returns the official mapping structure and does not choose a
preferred target for you. See the
[GEM guide](https://ipolharvard.github.io/cms-icd/guide/general-equivalence-mappings/)
for alternatives, combinations, flags, and correction history.

## Configure caching and offline access

By default, downloaded CMS files are stored in the platform cache directory.
Provide `cache_dir` to use a project, scratch, or shared location:

```python
from datetime import date
from pathlib import Path

from cms_icd import ICD10KnowledgeBase

icd = ICD10KnowledgeBase.for_date(
    date(2026, 5, 1),
    cache_dir=Path("/shared/cache/cms_icd"),
)
```

After the selected files have been cached, set `offline=True` to prevent
network access:

```python
icd = ICD10KnowledgeBase.for_date(
    date(2026, 5, 1),
    cache_dir="/shared/cache/cms_icd",
    offline=True,
)
```

Use `ICD10KnowledgeBase.from_directory()` or
`GEMKnowledgeBase.from_directory()` when you already manage the original CMS
files yourself.

## Citation and acknowledgment

If you use `cms-icd` in research or published work, please cite the software
using
[`CITATION.cff`](https://github.com/ipolharvard/cms-icd/blob/main/CITATION.cff)
and acknowledge IPOL at MGH.

The version-independent project DOI is
[`10.5281/zenodo.21952934`](https://doi.org/10.5281/zenodo.21952934).

The source code is licensed under the
[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). See
[`NOTICE`](https://github.com/ipolharvard/cms-icd/blob/main/NOTICE) for
attribution information.

## Development

```bash
make install-dev
make test
make install-docs
make docs
```

See the [development guide](https://ipolharvard.github.io/cms-icd/development/)
and [testing guide](https://ipolharvard.github.io/cms-icd/testing/) for the
available checks and CMS integration tests.

`cms-icd` is an independent open-source project. It is not affiliated with,
endorsed by, or sponsored by the Centers for Medicare & Medicaid Services.
