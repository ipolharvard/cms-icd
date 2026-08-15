# Testing CMS compatibility

CMS is an external, evolving source. A passing parser test alone cannot prove
that the website still advertises releases in the same way, that a URL still
returns the same artifact, or that a PDF and XML schema remain compatible.
`cms-icd` therefore uses several independent test layers.

## What is validated

The complete strategy covers:

- catalog labels, URLs, fiscal years, and effective revision dates;
- unique material selection for annual and April snapshots;
- direct PDFs and ZIP-packaged materials;
- expected ZIP member discovery;
- CM tabular, CM index, and CM guideline parsing;
- PCS tabular, PCS index, and PCS guideline parsing;
- semantic differences across a known April update;
- inheritance of unchanged material within a fiscal year;
- representative historical CMS formats;
- atomic concurrent acquisition;
- manifest and extracted-file integrity;
- downloaded artifact SHA-256 validation;
- known historical artifact fingerprints.

No test can guarantee that CMS will never make an incompatible change. The
layers are designed to make failures specific: a catalog failure points to
website discovery, while a current-artifact failure points to downloading,
archive contents, or parsing.

## Offline tests

Offline tests run on every pull request and push:

```bash
make test
```

They use synthetic HTML, ZIP, XML, cache, and directory fixtures. They verify
selection rules and failure handling without depending on the CMS website.
Important cases include:

- April appearing in a URL but not in the link label;
- administrative file corrections not becoming coding revisions;
- strict rejection of arbitrary exact snapshot dates;
- per-material snapshot inheritance;
- malformed manifests and corrupt extracted files;
- corrupt downloaded artifacts;
- invalid ZIP payloads;
- concurrent requests sharing one download;
- missing and ambiguous local files.

## Catalog contract

The catalog job runs weekly and downloads no ICD artifacts:

```bash
make test-live-catalog
```

It fetches the current and archive pages, resolves every supported fiscal-year
snapshot, and writes `.cms-diagnostics/catalog-matrix.json`. All releases
through the latest complete fiscal year must provide uniquely selectable CM and
PCS tables, indexes, and guidelines. A newer incomplete fiscal year is allowed
while CMS is still publishing its files.

This layer detects changes to page structure, labels, URLs, and effective-date
inference quickly and cheaply.

## Fresh current snapshot

The current-artifact job runs monthly with an empty cache:

```bash
make test-live-current
```

It discovers the latest complete snapshot, freshly downloads all six material
types, and parses them:

| System     | Materials                             |
| ---------- | ------------------------------------- |
| ICD-10-CM  | Tabular, alphabetic index, guidelines |
| ICD-10-PCS | Tables, alphabetic index, guidelines  |

The test checks structural invariants, representative codes, CM index sources,
guideline sections, manifest metadata, and checksums. This job intentionally
does not restore a CMS artifact cache, so CMS replacing a file at an unchanged
URL cannot be hidden by CI caching.

## Historical regression

The historical job runs monthly against representative releases:

```bash
make test-live-historical
```

The matrix currently covers:

| Release      | Compatibility contract                           |
| ------------ | ------------------------------------------------ |
| FY2017       | Old archive URLs and CM/PCS XML bundles          |
| FY2019       | Direct CM and ZIP-packaged PCS guideline formats |
| FY2022       | Corrected filenames and the four-part CM index   |
| FY2025 April | Midyear selection and known PCS code differences |
| FY2026 April | Inherited CM and updated PCS guidelines          |

Selected historical bundles have pinned SHA-256 fingerprints. A mismatch is not
automatically accepted: it signals that CMS changed a historical artifact and
that the reproducibility impact must be reviewed before updating the expected
fingerprint.

The GitHub Actions cache key changes each month. GitHub cache entries are
immutable, so rotating the key ensures scheduled runs periodically download
the artifacts again instead of testing one indefinitely stale cache.

## Exhaustive manual audit

The exhaustive workflow is manual because it can download and parse every
advertised release and material:

```bash
make test-live-exhaustive
```

Run it before changing catalog discovery, archive patterns, or parsers, and
before claiming support for a newly published fiscal year. Results are written
to `.cms-diagnostics/exhaustive-results.json`.

Guideline results include deterministic fingerprints of their keys, titles,
preambles, and whitespace-normalized content. Comparisons are performed by the
test code; successful runs do not print hashes, while failures identify the
release and material and retain detailed diagnostics as a workflow artifact.

The PyMuPDF-to-pypdf migration preserved the public guideline hierarchy and
canonical PCS text across the cached compatibility corpus. The reviewed CM
differences normalize PDF font spacing and correct the former footer heuristic:
body-text references to the *ICD-10-CM Official Guidelines for Coding and
Reporting* are now retained instead of being mistaken for running footers.

## Failure diagnostics

GitHub Actions uploads diagnostics even when a live job fails. Depending on the
job, these include:

- the parsed release-selection matrix;
- selected release metadata;
- cache manifests;
- source URLs;
- artifact and extracted-file checksums;
- per-material exhaustive results.

The full downloaded CMS bundles are not uploaded.

## Updating a historical fingerprint

Treat a changed historical checksum as a reproducibility event:

1. Confirm that the URL is still an official CMS URL.
2. Compare ZIP members and parsed code/guideline behavior.
3. Determine whether CMS corrected content or only repackaged the archive.
4. Record the impact in the change description.
5. Update the pinned SHA-256 only after review.

Do not weaken or remove the assertion simply to make the scheduled workflow
green.
