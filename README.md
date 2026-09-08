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

## At a glance

- Look up ICD-10-CM and ICD-10-PCS codes for the date that controls coding.
- Compare code definitions across CMS fiscal years and midyear revisions.
- Navigate hierarchies and indexes, inspect instructional notes, and read
  coding guidelines.
- Resolve ICD-9-CM mappings by discharge date and use later CMS corrections
  without changing the historical code vocabulary.

## Install

```bash
pip install cms-icd
```

## Look up ICD-10 codes

Use the date that controls coding for the encounter:

```pycon
>>> from datetime import date
>>> from cms_icd import ICD10KnowledgeBase
>>> icd = ICD10KnowledgeBase.for_date(date(2026, 5, 1))
>>> icd.cm["I10"].description
'Essential (primary) hypertension'
```

Use the discharge date for inpatient ICD-10-CM and ICD-10-PCS. For other
ICD-10-CM use cases, use the encounter or service date.

Use `icd.cm` for diagnoses and `icd.pcs` for inpatient procedures. See
[Work with ICD-10 materials](https://ipolharvard.github.io/cms-icd/guide/icd10-materials/)
for hierarchy navigation, index lookup, instructional notes, and guidelines.

## Compare exact releases

Use `from_cms()` to compare the same code across CMS fiscal years:

```pycon
>>> from cms_icd import ICD10KnowledgeBase
>>> for year in (2024, 2025):
...     icd = ICD10KnowledgeBase.from_cms(fiscal_year=year)
...     print(year, icd.cm["K58.9"].description)
2024 Irritable bowel syndrome without diarrhea
2025 Irritable bowel syndrome, unspecified
```

CMS may also publish an April update within a fiscal year. If a material did
not change in the update, `cms-icd` uses the most recent earlier material from
the same fiscal year.

The
[release guide](https://ipolharvard.github.io/cms-icd/guide/releases/)
explains fiscal years, midyear updates, exact snapshots, and fallback behavior.

## Map ICD-9-CM by discharge date

The applicable mapping can depend on the discharge date:

```pycon
>>> from datetime import date
>>> from cms_icd import resolve_icd9_to_icd10_cm_mappings
>>> from cms_icd.sources import fiscal_year_for
>>> discharge_dates = (date(2016, 9, 30), date(2016, 10, 1))
>>> years = [fiscal_year_for(value) for value in discharge_dates]
>>> by_year = resolve_icd9_to_icd10_cm_mappings(years)
>>> for discharge_date, year in zip(discharge_dates, years, strict=True):
...     print(discharge_date, by_year[year]["29682"].target_codes)
2016-09-30 ('F328',)
2016-10-01 ('F3289',)
```

## Use the best corrected GEM history

Later CMS releases corrected some earlier GEM rows. Compare the original FY2016
mapping with the best corrected history:

```pycon
>>> from cms_icd import GEMKnowledgeBase
>>> code = "27906"
>>> original = GEMKnowledgeBase.from_cms(fiscal_year=2016).cm.icd9_to_icd10
>>> corrected = GEMKnowledgeBase.corrected_from_cms(
...     fiscal_year=2016,
... ).cm.icd9_to_icd10
>>> tuple(entry.target for entry in original[code])
('D838', 'D839')
>>> tuple(entry.target for entry in corrected[code])
('D831',)
>>> corrected.provenance(code).selected_mapping_release.fiscal_year
2017
```

The corrected mapping retains the FY2016 target vocabulary while using the
complete corrected row set published for FY2017. GEM resolution is best effort,
not an authoritative one-to-one conversion. The
[GEM guide](https://ipolharvard.github.io/cms-icd/guide/general-equivalence-mappings/)
explains diagnosis and procedure mappings, alternatives, combinations, flags,
resolution policy, and correction history.

## Documentation

- [Getting started](https://ipolharvard.github.io/cms-icd/guide/getting-started/)
- [Release selection](https://ipolharvard.github.io/cms-icd/guide/releases/)
- [ICD-10 materials](https://ipolharvard.github.io/cms-icd/guide/icd10-materials/)
- [General Equivalence Mappings](https://ipolharvard.github.io/cms-icd/guide/general-equivalence-mappings/)
- [Caching and offline use](https://ipolharvard.github.io/cms-icd/guide/caching/)
- [API reference](https://ipolharvard.github.io/cms-icd/reference/knowledge-base/)
- [Development](https://ipolharvard.github.io/cms-icd/development/) and
  [testing](https://ipolharvard.github.io/cms-icd/testing/)

## Citation and acknowledgment

If you use `cms-icd` in research or published work, please cite the software
using
[`CITATION.cff`](https://github.com/ipolharvard/cms-icd/blob/main/CITATION.cff)
and acknowledge IPOL at MGH.

The project DOI is
[`10.5281/zenodo.21952934`](https://doi.org/10.5281/zenodo.21952934).

The source code is licensed under the
[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). See
[`NOTICE`](https://github.com/ipolharvard/cms-icd/blob/main/NOTICE) for
attribution information.

`cms-icd` is an independent open-source project. It is not affiliated with,
endorsed by, or sponsored by the Centers for Medicare & Medicaid Services.
