# Repository Instructions

## Project Commands

Prefer these repository Makefile targets for their corresponding operations:

```bash
make test
make docs
```

When dependency setup is approved, use `make install-dev` or
`make install-docs`. When cleanup is requested, use `make clean`; it preserves
`data/`, `.venv/`, source files, and untracked user files.

For a focused test, use:

```bash
uv run pytest -q --tb=line <test-group>
```

## Validation

Use targeted unit tests, import checks, syntax checks, and strict documentation
builds as appropriate for the change. Use the broader targets when their whole
responsibility is affected:

```bash
make test
make docs
```

## CMS Integration Tests

Normal tests must not access the network. Tests marked `live_cms` download
official CMS materials and must run only when live integration testing is
explicitly requested.

Do not run `make test-live` as part of routine validation. When live testing is
requested, keep output compact:

```bash
uv run pytest -q --tb=line -m live_cms tests/live
```

Use the narrower targets when only one external contract needs validation:

```bash
make test-live-catalog
make test-live-current
make test-live-historical
```

`make test-live-exhaustive` downloads and parses every advertised release. Run
it only when the user explicitly requests an exhaustive CMS compatibility
audit.

Do not delete downloaded CMS materials or caches without explicit approval.

## Test and Documentation Style

Demonstrate public deterministic behavior with executable examples in
docstrings, the README, or documentation pages. Prefer doctests when an example
is concise, readable, deterministic, and does not require network access.

Use conventional pytest tests for HTTP behavior, caching, filesystem access,
concurrency, corrupt input, parser integration, and other cases that require
fixtures or detailed assertions.

Do not write tests that assert exact wording in documentation or error prose
unless the wording itself is part of a compatibility contract. Prefer tests for
structured behavior, parsed records, hierarchy relationships, release
selection, cache behavior, and validation outcomes.

Build documentation with `make docs`; the build must pass in strict mode.

## Reproducibility

Do not silently change fiscal-year calculation, release-date selection,
fallback behavior, cache layout, filename matching, parser semantics, or public
record serialization. These behaviors can affect downstream coding and
research results.

When such a change is requested, explain its compatibility and reproducibility
impact and add focused tests and documentation.
