"""Optional, explicitly typed frame output for resolved ICD mappings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import ModuleType

    import polars as pl

    from .models import ICDCMMappingResolution, ICDPCSMappingResolution


def _require_polars() -> ModuleType:
    """Import the optional backend before acquisition starts."""
    try:
        import polars
    except ModuleNotFoundError as exc:
        if exc.name != "polars":
            raise
        raise ImportError(
            "Frame output requires Polars; install 'cms-icd[polars]'."
        ) from exc
    return polars


def _resolution_frame(
    mappings: Mapping[
        int, Mapping[str, ICDCMMappingResolution | ICDPCSMappingResolution]
    ],
    *,
    kind: Literal["cm", "pcs"],
) -> pl.DataFrame:
    """Build start-dated mappings and null boundary rows for backward as-of joins."""
    pl = _require_polars()
    target_attribute = "target_codes" if kind == "cm" else "target_patterns"

    def rows():
        for year, resolutions in mappings.items():
            start = datetime(year - 1, 10, 1, tzinfo=UTC)
            end = datetime(year, 10, 1, tzinfo=UTC)
            following = mappings.get(year + 1, {})
            for source, resolution in resolutions.items():
                yield year, source, list(getattr(resolution, target_attribute)), start
                if source not in following:
                    # Prevent stale matches after a code disappears, across omitted
                    # years, or beyond the final selected release.
                    yield None, source, None, end

    return (
        pl.DataFrame(
            rows(),
            schema={
                "fiscal_year": pl.Int16,
                "source_code": pl.String,
                "targets": pl.List(pl.String),
                "effective_date": pl.Datetime("us", "UTC"),
            },
            orient="row",
        )
        .lazy()
        .sort("effective_date", "source_code")
        .collect()
    )
