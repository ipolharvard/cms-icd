# CMS ICD

`cms-icd` provides version-aware, structured access to official CMS ICD-10-CM
and ICD-10-PCS materials.

The library is designed for applications and research pipelines that need to
select a reproducible CMS release while paying only for the materials they use.
Downloads and parsing are lazy: accessing CM codes does not download PCS files,
and reading a tabular list does not parse an index or guideline PDF.

## Quick start

Install the package with Python 3.12 or newer:

```bash
uv pip install cms-icd
```

Select the release applicable to a service date:

```python
from datetime import date

from cms_icd import ICD10KnowledgeBase

icd = ICD10KnowledgeBase.for_date(
    date(2026, 5, 1),
    cache_dir="data/cms_icd",
)
diagnosis = icd.cm["I10"]
print(diagnosis.description)
```

No network request is made when the knowledge base or its CM view is created.
The first code lookup downloads and parses only the CM tabular material.

## What is available?

- ICD-10-CM and ICD-10-PCS tabular hierarchies
- Alphabetic indexes with parent and child relationships
- Official coding guidelines addressable by section
- Exact fiscal-year revisions or service-date-based selection
- Persistent, checksummed artifact caching
- Offline loading from directories containing CMS-format files
- Immutable records and read-only stores for predictable shared use

!!! note

```
CMS does not always retain every historical intra-year revision. Exact
release selection is strict unless the caller explicitly enables a
fiscal-year fallback.
```

## Citation

If you use `cms-icd` in research or published work, cite the software using
the repository's `CITATION.cff` metadata and acknowledge IPOL at MGH. The
software is distributed under Apache-2.0; its `NOTICE` records the IPOL
attribution that accompanies redistributed copies.
