"""Require a GitHub release tag to match the package version."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path


def main() -> None:
    """Validate the release tag from the GitHub Actions environment."""
    metadata = tomllib.loads(Path("pyproject.toml").read_text())
    expected = f"v{metadata['project']['version']}"
    actual = os.environ.get("GITHUB_REF_NAME", "")
    if actual != expected:
        raise SystemExit(f"Release tag {actual!r} must equal package tag {expected!r}")


if __name__ == "__main__":
    main()
