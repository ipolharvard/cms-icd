"""Validate the installed package and required wheel contents."""

from __future__ import annotations

import sys
from pathlib import Path
from zipfile import ZipFile


def main() -> None:
    """Inspect the requested wheel and its installed package."""
    import cms_icd

    wheel = Path(sys.argv[1])
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())

    if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
        raise SystemExit(f"Wheel {wheel.name} does not contain LICENSE")
    if "cms_icd/__init__.py" not in names:
        raise SystemExit(f"Wheel {wheel.name} does not contain cms_icd")
    if not cms_icd.__all__:
        raise SystemExit("Installed cms_icd package exposes no public API")


if __name__ == "__main__":
    main()
