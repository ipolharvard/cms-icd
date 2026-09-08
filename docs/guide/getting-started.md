# Getting started

## Select a release

For operational coding, select materials using the date that controls coding:

```python
from datetime import date

from cms_icd import ICD10KnowledgeBase

icd = ICD10KnowledgeBase.for_date(date(2026, 5, 1))
```

Use the discharge date for inpatient ICD-10-CM and ICD-10-PCS. Use the encounter
or date of service for other ICD-10-CM coding. See
[Release selection](releases.md) for the October/April boundary
and guideline availability.

For a reproducible dataset or experiment, pin the exact effective snapshot:

```python
icd = ICD10KnowledgeBase.from_cms(
    release_date=date(2026, 4, 1),
)
```

## Use a code-system view

The `.cm` and `.pcs` properties create independent lazy views:

```python
cm = icd.cm
pcs = icd.pcs
```

Creating either view is cheap. A material is acquired only when its associated
property or method is used:

```python
code = cm["I10"]  # loads CM tabular material
terms = cm.index  # loads the CM alphabetic index
rules = cm.guidelines  # loads the CM guideline PDF
```

## Navigate tabular material

Knowledge-base convenience methods return common relationship queries:

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
>>> [node.id for node in cm.tabular.parents("I10")]
['cm']
>>> cm.get_leaves("cm")
['I10']

```

The underlying [tabular store](../reference/stores.md#cms_icd.stores.TabularStore)
also exposes direct children, descendants, leaves, siblings, and parents.
Continue with [Work with ICD-10 materials](icd10-materials.md) for alphabetic
index, instructional-note, and guideline workflows.

## Load eagerly when needed

Lazy access is the default, but explicit loading is useful when preparing a
long-running process:

```python
cm.load_tabular()
cm.load_index()
cm.load_guidelines()
cm.load_all()
icd.load_all()
```

`icd.load_all()` downloads and parses every CM and PCS material. Use it only
when all materials are genuinely needed.
