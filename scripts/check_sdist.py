"""Validate required source-distribution metadata."""

from __future__ import annotations

import sys
from pathlib import Path
from tarfile import open as open_tar


def main() -> None:
    """Require release, attribution, and citation metadata in the sdist."""
    archive_path = Path(sys.argv[1])
    with open_tar(archive_path, mode="r:gz") as archive:
        names = archive.getnames()

    for filename in ("CITATION.cff", "LICENSE", "NOTICE", "pyproject.toml"):
        if not any(name.endswith(f"/{filename}") for name in names):
            raise SystemExit(f"Source distribution lacks {filename}")


if __name__ == "__main__":
    main()
