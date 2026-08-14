# CMS ICD

[![CI](https://github.com/ipolharvard/cms-icd/actions/workflows/ci.yml/badge.svg)](https://github.com/ipolharvard/cms-icd/actions/workflows/ci.yml)
[![Documentation](https://github.com/ipolharvard/cms-icd/actions/workflows/docs.yml/badge.svg)](https://ipolharvard.github.io/cms-icd/)
[![CMS catalog](https://github.com/ipolharvard/cms-icd/actions/workflows/catalog-cms.yml/badge.svg)](https://github.com/ipolharvard/cms-icd/actions/workflows/catalog-cms.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

`cms-icd` provides version-aware, structured access to official CMS ICD-10-CM
and ICD-10-PCS materials. Downloads and parsing are lazy: using diagnosis codes
does not download PCS files, and reading a tabular list does not parse indexes
or guideline PDFs.

Python 3.12 or newer is required. The package is tested on Python 3.12–3.14.
CMS-backed discovery supports production ICD-10 releases from FY 2016 onward,
including advertised intra-year updates.

Full documentation is available at
[ipolharvard.github.io/cms-icd](https://ipolharvard.github.io/cms-icd/).

The package also exposes the official ICD-9/ICD-10 General Equivalence Mappings
without imposing an application-specific target-selection policy:

```python
from cms_icd import GEMKnowledgeBase

gems = GEMKnowledgeBase.from_cms(fiscal_year=2018)
entries = gems.cm.icd9_to_icd10["4280"]
```

## Installation

Install an internal Git checkout with `uv`:

```bash
uv pip install -e /path/to/cms-icd
```

## Choosing a release

Select the release using the date that controls coding:

```python
from datetime import date

from cms_icd import ICD10KnowledgeBase

icd = ICD10KnowledgeBase.for_date(
    date(2026, 5, 1),
    cache_dir="data/cms_icd",
)
cm = icd.cm
code = cm["I10"]  # downloads and parses CM tabular material on first use
```

Use the discharge date for inpatient ICD-10-CM and ICD-10-PCS, and the encounter
or date of service for other ICD-10-CM coding.

For reproducible research, select an exact effective snapshot:

```python
icd = ICD10KnowledgeBase.from_cms(
    fiscal_year=2026,
    release_date=date(2026, 4, 1),
    cache_dir="data/cms_icd",
)
```

CMS commonly publishes an October release and an April 1 update. Materials not
changed in an update are inherited from the latest earlier revision in that
fiscal year. CMS does not always retain every historical revision, so snapshot
selection is strict by default. Pass `fallback="latest_for_fy"` only when using
the latest available fiscal-year material is scientifically acceptable.

The [release guide](https://ipolharvard.github.io/cms-icd/guide/releases-and-caching/)
documents supported guideline years and the exact October/April selection
rules.

## Offline and custom stores

An existing directory is not inspected until a material is requested:

```pycon
>>> from datetime import date
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from cms_icd import ICD10KnowledgeBase
>>> with TemporaryDirectory() as directory:
...     kb = ICD10KnowledgeBase.from_directory(
...         directory,
...         fiscal_year=2026,
...         release_date=date(2025, 10, 1),
...     )
...     repr(kb)
'ICD10KnowledgeBase(release=Release(fiscal_year=2026, release_date=datetime.date(2025, 10, 1)), loaded=[])'

```

Small custom or synthetic stores can be supplied directly:

```pycon
>>> from cms_icd import Code, ICD10CMKnowledgeBase
>>> from cms_icd.models import Node
>>> from cms_icd.stores import TabularStore
>>> root = Node("cm", "cm", children_ids=("I10",))
>>> code = Code("I10", "I10", "Essential hypertension", parent_id="cm")
>>> tabular = TabularStore({"cm": root, "I10": code}, {"I10": "I10"}, ("cm",))
>>> cm = ICD10CMKnowledgeBase.from_stores(tabular=tabular)
>>> cm["I10"].description
'Essential hypertension'
>>> cm.get_leaves("cm")
['I10']

```

## Development

```bash
make install-dev
make test
make install-docs
make docs
```

Normal tests are offline. `make test-live` accesses CMS and must be run only
when live integration testing is explicitly intended.

CMS compatibility is validated in separate catalog, fresh-current, historical,
and manual exhaustive lanes. See the
[testing strategy](https://ipolharvard.github.io/cms-icd/testing/).

The package depends on PyMuPDF for guideline extraction. Confirm PyMuPDF's
licensing is suitable for the intended distribution before publishing this
library outside the organization.
