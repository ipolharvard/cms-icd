# Repository Instructions

## Python Commands

Use the repository virtual environment at `.venv` for Python checks and tests.
Dependency management uses `uv`; do not create an environment or add, remove, or
change dependencies without explicit approval.

Prefer the repository Makefile targets for common tasks:

```bash
make install-dev
make install-docs
make test
make docs
make test-live
```

Use `make clean` to remove generated build, documentation, test, and cache files.
It preserves `data/`, `.venv/`, source files, and untracked user files.

Examples:

```bash
.venv/bin/python -m pytest ...
.venv/bin/pre-commit run --files ...
```

If a dependency is missing, report it clearly and suggest the appropriate `uv`
or Makefile command instead of installing or changing dependencies automatically.

## Validation

After editing files, run the fastest relevant validation for the touched
behavior.

Preferred checks include targeted unit tests, import checks, syntax checks,
strict documentation builds, and pre-commit on touched files:

```bash
.venv/bin/pre-commit run --files <touched-files>
make test
make docs
```

If validation cannot be run because a tool or dependency is unavailable, say
what failed and what command the user can run after fixing the environment.

## CMS Integration Tests

Normal tests must not access the network. Tests marked `live_cms` download
official CMS materials and must run only when live integration testing is
explicitly requested.

Do not run `make test-live` as part of routine validation. When live testing is
requested, keep output compact:

```bash
.venv/bin/python -m pytest -q --tb=line -m live_cms tests/live
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

## Commit Messages

Use a concise, clear title that summarizes the overall change. When more
context is useful, add a blank-line-separated body with a few bullets covering
the major behavior or capability changes. Avoid exhaustive file lists and
low-level implementation detail.

```text
Add GitHub Pages documentation

- Document release selection, caching, and custom sources
- Generate API references from public docstrings
- Validate and deploy the site through GitHub Actions
```

## Safety

Do not read secret-bearing files such as `.env`, `.env.*`, or `.envrc`.
Do not delete cached CMS materials or generated artifacts without approval.
