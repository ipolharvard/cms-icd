# Development

The project requires Python 3.12 or newer and uses `uv` for dependency
management.

## Set up

Use the repository virtual environment:

```bash
make install-dev
make install-docs
```

## Validate

Run offline tests and documentation examples:

```bash
make test
```

Build the documentation with strict link and configuration checks:

```bash
make docs
```

Preview it locally:

```bash
make docs-serve
```

Normal tests do not access CMS. Live CMS tests are marked `live_cms` and run
only through the explicitly requested live integration workflow or
`make test-live`.

The live suite is divided into catalog, fresh-current, historical, and
exhaustive lanes. See
[Testing CMS compatibility](testing.md) for their scope, schedules, cache
policy, and maintenance instructions.

## Documentation deployment

Pull requests build the site without deploying it. A push to `main` builds the
same site and deploys it through GitHub Actions to GitHub Pages.

The repository's **Settings → Pages → Build and deployment → Source** must be
set to **GitHub Actions**.

## Publishing releases

Production releases use PyPI Trusted Publishing; no API token is stored in
GitHub. Complete this one-time setup before the first release:

1. Create a protected GitHub environment named `pypi` with required reviewers.
2. In the PyPI account's **Publishing** settings, register a pending publisher
   with project `cms-icd`, owner `ipolharvard`, repository `cms-icd`, workflow
   `publish.yml`, and environment `pypi`. The first successful publication
   creates the PyPI project; the pending publisher does not reserve its name.
3. Connect the maintainer's GitHub account to Zenodo, synchronize repositories,
   and enable `ipolharvard/cms-icd`. Zenodo then archives each GitHub release
   and assigns its DOI.

For each release, set the same version in `pyproject.toml` and `CITATION.cff`,
merge the validated change to `main`, and publish a GitHub Release whose tag is
exactly `v<version>`. The workflow builds and validates the distributions in a
job without publishing credentials, then passes only those artifacts to the
protected publishing job. In parallel, Zenodo archives the tagged source. After
Zenodo assigns the first DOI, add it to `CITATION.cff`, the README, and the
documentation for subsequent releases.
