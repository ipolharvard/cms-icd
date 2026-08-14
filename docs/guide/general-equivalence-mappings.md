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

Diagnosis mappings are available through `gems.cm`; procedure mappings are available
through `gems.pcs`. Each view provides `icd9_to_icd10` and `icd10_to_icd9` stores. The
requested system and direction are downloaded and parsed only when accessed.

## Flags and no-map rows

Each `GEMEntry` contains:

- `source` and nullable `target` code strings, with leading zeroes preserved;
- `approximate`, `no_map`, and `combination` boolean flags;
- numeric `scenario` and `choice_list` identifiers.

When CMS uses `NoDx` or `NoPCS`, `target` is `None` and `no_map` is true. Multiple
entries for a source are returned as an immutable tuple in deterministic
scenario/choice/target order.

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
