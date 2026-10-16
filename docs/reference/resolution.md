# Mapping resolution API

## Optional Polars output

Install `cms-icd[polars]` to request a join-ready DataFrame directly from any of
the four resolvers. The extra supports Polars 1.38 or newer, below 2.0.

```python
from cms_icd import resolve_icd9_to_icd10_cm_mappings

lookup = resolve_icd9_to_icd10_cm_mappings([2016, 2017], output_frame=True)

# A single year or every compatible advertised year:
one_year = resolve_icd9_to_icd10_cm_mappings(2016, output_frame=True)
all_years = resolve_icd9_to_icd10_cm_mappings(None, output_frame=True)
```

The default `output_frame=False` returns the existing immutable mapping with full
resolution diagnostics and release provenance. Frame output is a compact projection:

| Column           | Polars type             | Meaning                                               |
| ---------------- | ----------------------- | ----------------------------------------------------- |
| `fiscal_year`    | `Int16`                 | Source vocabulary fiscal year; null for boundary rows |
| `source_code`    | `String`                | Source code, retaining leading zeros                  |
| `targets`        | `List(String)`          | Ordered resolved CM codes or PCS patterns             |
| `effective_date` | `Datetime("us", "UTC")` | Inclusive start of applicability                      |

Frames contain one mapping row per `(fiscal_year, source_code)`, starting at UTC
midnight on October 1 of the preceding calendar year. They are sorted by
`effective_date` and then `source_code`. This date identifies the historical vocabulary
period, not when a later correction was published. The correction horizon remains
independent and defaults to FY2018.

The name follows CMS's [effective-date terminology for GEM updates](https://www.cms.gov/regulations-and-guidance/guidance/transmittals/2017downloads/r119msp.pdf).

There is no `valid_to` column. If the immediately following fiscal year is not
selected or has no mapping for that source, a boundary row with null `fiscal_year`
and null `targets` starts at the next October 1. **Retain these rows during as-of joins.** They prevent stale mappings
from continuing across unselected years, disappearing codes, or the end of coverage.
An empty target list means a known unmappable source; a null list means no mapping
applies from that boundary onward, until another mapping row for that source appears.
Never-seen sources have no lookup rows and also join to null.

Single-year calls include the same columns and closing boundary rows. Empty requests
retain the schema. Target order, repeated targets in combination mappings, and PCS
`?` axes are preserved. PCS patterns and CM category targets are not necessarily
assignable codes. To obtain only annual mapping rows for an equality join, filter
`fiscal_year.is_not_null()` and project the first three columns.

For timestamp matching, use a backward `join_asof`, grouped by source code. Normalize
events to the same coding-date convention and `Datetime("us", "UTC")` type first.
The timestamp used must determine the source coding version; an encounter timestamp
is not necessarily the assignment date. Given a lazy `events` table with `time` and
`source_code` columns:

```python
import polars as pl

result = (
    events.with_row_index("event_order")
    .sort("time")
    .join_asof(
        lookup.lazy(),
        by="source_code",
        left_on="time",
        right_on="effective_date",
        strategy="backward",
        # Both inputs are sorted explicitly. Polars 1.x cannot verify grouped
        # sortedness reliably; the frame is already sorted by effective_date.
        check_sortedness=False,
    )
    .sort("event_order")
    .drop("event_order")
    .collect()
)
```

The join includes exact start timestamps. A boundary row stops the prior mapping
at its timestamp, without a separate end-date predicate. This preserves unmatched
observations rather than dropping them. If targets are subsequently exploded,
applications must choose how to handle both empty and null lists first.

Use separate CM and PCS lookups. Frame output does not change release selection,
correction horizons, resolution semantics, or cache layout. Missing Polars raises
`ImportError` before material discovery or downloads. Resolution results are shared
with mapping calls through the existing cache; each frame is independently constructed.

::: cms_icd.resolution.resolve_icd9_to_icd10_cm_mappings

::: cms_icd.resolution.resolve_icd9_to_icd10_cm_mapping

::: cms_icd.resolution.resolve_icd9_to_icd10_pcs_mappings

::: cms_icd.resolution.resolve_icd9_to_icd10_pcs_mapping
