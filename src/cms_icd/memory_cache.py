"""Unified control of process-local caches."""

from enum import StrEnum

from .parsed_cache import _clear_memory_cache
from .resolution import _clear_resolution_memory_cache
from .sources import _clear_catalog_memory_cache


class MemoryCache(StrEnum):
    """A process-local cache that can be cleared independently."""

    CATALOG = "catalog"
    PARSED = "parsed"
    RESOLUTION = "resolution"


def clear_memory_caches(*caches: MemoryCache | str) -> None:
    """Clear selected process-local caches, or every cache when none are given.

    Args:
        *caches: Cache selectors. Enum members and their string values are accepted.

    Examples:
        Clear every process-local cache:

        >>> clear_memory_caches()

        Clear only derived mapping resolutions:

        >>> clear_memory_caches(MemoryCache.RESOLUTION)
    """
    selected = tuple(MemoryCache(cache) for cache in caches) or tuple(MemoryCache)
    clear = {
        MemoryCache.CATALOG: _clear_catalog_memory_cache,
        MemoryCache.PARSED: _clear_memory_cache,
        MemoryCache.RESOLUTION: _clear_resolution_memory_cache,
    }
    for cache in dict.fromkeys(selected):
        clear[cache]()
