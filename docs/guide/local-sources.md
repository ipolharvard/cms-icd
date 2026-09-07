# Local and custom sources

## Load a CMS-format directory

Use `from_directory()` for an offline directory containing CMS XML and PDF
files:

```pycon
>>> from datetime import date
>>> from tempfile import TemporaryDirectory
>>> from cms_icd import ICD10KnowledgeBase
>>> with TemporaryDirectory() as directory:
...     kb = ICD10KnowledgeBase.from_directory(
...         directory,
...         fiscal_year=2026,
...         release_date=date(2025, 10, 1),
...     )
...     kb.release.fiscal_year
2026

```

Construction verifies that the directory exists but does not search or parse
its contents. Files for a specific material are discovered only when that
material is accessed.

Expected CMS filename patterns include:

| System | Material   | Representative filename              |
| ------ | ---------- | ------------------------------------ |
| CM     | Tabular    | `icd10cm_tabular_2026.xml`           |
| CM     | Index      | `icd10cm_index_2026.xml`             |
| CM     | Guidelines | `icd10cm-coding-guidelines-2026.pdf` |
| PCS    | Tabular    | `icd10pcs_tables_2026.xml`           |
| PCS    | Index      | `icd10pcs_index_2026.xml`            |
| PCS    | Guidelines | `icd10pcs-guidelines-2026.pdf`       |

Missing, duplicate, or ambiguous files raise a specific
[knowledge-base exception](../reference/exceptions.md).

## Supply prebuilt stores

Custom sources can parse their own data and construct a CM or PCS view from
immutable stores:

```pycon
>>> from cms_icd import Code, ICD10CMKnowledgeBase
>>> from cms_icd.models import Node
>>> from cms_icd.stores import TabularStore
>>> root = Node("cm", "cm", children_ids=("I10",))
>>> code = Code("I10", "I10", "Essential hypertension", parent_id="cm")
>>> tabular = TabularStore({"cm": root, "I10": code}, {"I10": "I10"}, ("cm",))
>>> cm = ICD10CMKnowledgeBase.from_stores(tabular=tabular)
>>> "I10" in cm
True

```

Only supplied stores are available. Accessing a missing store raises
`RuntimeError` because no material provider exists to load it.

For CMS-managed downloads, persistent reuse, or cache-only operation, use the
[caching and offline guide](caching.md) instead.
