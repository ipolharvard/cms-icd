# Caches

Besides the persistent checksummed cache files, the process keeps catalog,
parsed-store, and mapping-resolution caches for the lifetime of the Python
process. Release all of that state explicitly when an application cycles
through distinct cache directories, such as per-use temporary directories:

```python
from cms_icd import clear_memory_caches

clear_memory_caches()
```

Pass selectors to release only specific layers:

```python
from cms_icd import MemoryCache, clear_memory_caches

clear_memory_caches(MemoryCache.PARSED, "resolution")
```

The function only releases in-memory state. Persistent catalog, artifact, and
derived cache files are left untouched.

::: cms_icd.memory_cache.MemoryCache

::: cms_icd.memory_cache.clear_memory_caches
