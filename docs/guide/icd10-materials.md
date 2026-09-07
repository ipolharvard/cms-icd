# Work with ICD-10 materials

An ICD-10 knowledge base exposes tabular codes, the alphabetic index, and
official coding guidelines through independently lazy CM and PCS views. Each
workflow loads only the material it uses.

## Look up codes and navigate the hierarchy

Direct lookup loads the tabular material for that code system:

```python
from datetime import date

from cms_icd import ICD10KnowledgeBase

icd = ICD10KnowledgeBase.for_date(date(2026, 5, 1))
cm = icd.cm

diagnosis = cm["I10"]
parents = cm.get_all_tabular_parents("I10")
```

Use the underlying [tabular store](../reference/stores.md#cms_icd.stores.TabularStore)
for direct children, descendants, siblings, parents, and assignable leaves.
Direct `cm[...]` lookup returns both assignable codes and non-assignable
code-category `Code` objects. It raises `KeyError` only when the resolved value
is a structural `Node` rather than a `Code`; use the store when working with
those structural nodes.

## Use the alphabetic index

Accessing `.index` loads the alphabetic index without loading guidelines. Terms
have stable identifiers that can be passed to the index helpers:

```python
main_terms = cm.get_all_main_terms()
term = main_terms[0]

subterms = cm.get_all_term_children(term.id)
codes = cm.get_term_codes(term.id, subterms=True)
```

`get_term_codes()` validates index targets against the tabular hierarchy and
returns deterministic, assignable code strings. Some terms are navigational or
instructional and resolve to no codes; callers should not treat every index
entry as an assignable diagnosis.

## Read inherited instructional notes

Instructional notes can be attached to a code or inherited from its tabular
ancestors. Requesting them loads only the tabular material:

```python
notes = cm.get_instructional_notes(["I10"])
```

The result is deduplicated across the requested codes and preserves structured
fields such as inclusion terms, exclusions, `code_first`, and
`use_additional_code`.

## Select and render guidelines

Accessing `.guidelines` loads the official guideline material for the selected
snapshot. Leaf sections are keyed by dotted identifiers, while section prefixes
can be expanded when rendering:

```python
section = cm.guidelines["I.A.1"]
rendered_section = cm.render_guidelines(["I.A.1"])
rendered_group = cm.render_guidelines(["I.A"])
```

`render_guidelines()` combines selected leaves in natural order and includes
shared ancestor headings once. An unknown key raises `KeyError` rather than
silently returning an empty result.

For ICD-10-CM, chapter-specific guidelines can be selected from diagnosis
codes:

```python
chapter_guidelines = cm.get_chapter_guidelines(["I10"])
```

The returned `Guideline.content` contains the rendered Markdown. PCS guidelines
use the same `.guidelines` and `render_guidelines()` interfaces; chapter lookup
is CM-specific.

## Control material loading

Views and materials are lazy by default. Applications that want predictable
startup work can load selected layers explicitly:

```python
cm.load_tabular()
cm.load_index()
cm.load_guidelines()
```

Use `cm.load_all()` for one code system or `icd.load_all()` for both CM and PCS.
See [Caching and offline use](caching.md) for storage and network behavior.
