# General Equivalence Mappings

CMS General Equivalence Mappings (GEMs) describe relationships between ICD-9-CM
and ICD-10. They are not one-to-one conversion tables: a source can have no target,
several alternatives, or a combination of targets that must be interpreted together.

`cms-icd` therefore exposes every official row and flag. It deliberately does not pick
a preferred target. Applications remain responsible for that policy.

```python
from cms_icd import GEMKnowledgeBase

gems = GEMKnowledgeBase.from_cms(
    fiscal_year=2018,
    cache_dir="cache/cms_icd",
)
entries = gems.cm.icd9_to_icd10["4280"]
for entry in entries:
    print(entry.target, entry.approximate, entry.scenario, entry.choice_list)
```

For structured alternatives and combinations, request the grouped mapping:

```python
mapping = gems.cm.icd9_to_icd10.mapping("4280")
for scenario in mapping.scenarios:
    for choice_list in scenario.choice_lists:
        print([entry.target for entry in choice_list.alternatives])
```

Simple alternatives are OR relationships. Scenarios are OR relationships, choice lists
inside one scenario are AND relationships, and alternatives inside one choice list are
OR relationships. A mapping may contain both simple and combination entries; the
library exposes both and does not impose a resolution policy.

Diagnosis mappings are available through `gems.cm`; procedure mappings are available
through `gems.pcs`. Each view provides `icd9_to_icd10` and `icd10_to_icd9` stores. The
requested system and direction are downloaded and parsed only when accessed.

## Flags and no-map rows

Each `GEMEntry` contains:

- `source` and nullable `target` code strings, with leading zeroes preserved;
- `approximate`, `no_map`, and `combination` boolean flags;
- numeric `scenario` and `choice_list` identifiers.

When CMS uses `NoDx` in CM files, `NoPCS` in forward PCS files, or `NoI9` in reverse PCS
files, `target` is `None` and `no_map` is true. Multiple entries for a source are returned
as an immutable tuple in deterministic scenario/choice/target order. A few official
reverse PCS releases omit the no-map flag on `NoI9` rows; the parser treats the sentinel
as authoritative and normalizes those rows to `no_map=True`.

## Reproducible and offline use

Select a fiscal year explicitly; GEMs are fiscal-year artifacts and do not use the
intra-year snapshot selection of ICD-10 tabular files. After an online run has populated
the catalog and artifact cache, require cache-only operation with `offline=True`:

```python
gems = GEMKnowledgeBase.from_cms(
    fiscal_year=2018,
    cache_dir="cache/cms_icd",
    offline=True,
)
```

Offline mode never contacts CMS and raises `DownloadError` with the missing cache
requirement. For externally managed files, use
`GEMKnowledgeBase.from_directory(directory, fiscal_year=2018)` with the original CMS
filenames intact.

GEMs are distinct from reimbursement mappings and other conversion tables. Catalog
discovery excludes those artifacts.

## Exact and retrospectively corrected history

`from_cms()` returns the official rows for one fiscal year without modification.
`corrected_from_cms()` retains that fiscal year's target-code vocabulary while adopting
later correction-only complete row sets:

```python
corrected = GEMKnowledgeBase.corrected_from_cms(
    fiscal_year=2016,
    cache_dir="cache/cms_icd",
)
store = corrected.cm.icd9_to_icd10
entries = store["27906"]
lineage = store.provenance("27906")
```

Procedure mappings use the same release selection and provenance contract:

```python
pcs_store = corrected.pcs.icd9_to_icd10
pcs_mapping = pcs_store.mapping("0001")
pcs_lineage = pcs_store.provenance("0001")
```

`ICD10_PCS_CHARACTERS` exposes the ordered, release-stable PCS alphabet for consumers
that represent the seven code axes independently. It excludes the ambiguous letters
`I` and `O`.

The algorithm compares consecutive official releases and their opposite-direction code
universes. It stops a source at the first transition involving an introduced or retired
source/target code. Mixed lifecycle and correction changes are not partially applied,
and processing does not resume for that source after the boundary. Consequently, every
result is a complete row set copied from one official release rather than a filtered or
synthetic cluster.

The correction horizon defaults to FY2018, the final CMS GEM release. Pass
`corrections_through_fiscal_year` only when a deliberately narrower review horizon is
required.

`GEMProvenance` records the historical vocabulary release, the release supplying the
selected rows, the pinned review horizon, and the first lifecycle boundary when one was
encountered. Missing intermediate releases remain errors; there is no silent fallback.
