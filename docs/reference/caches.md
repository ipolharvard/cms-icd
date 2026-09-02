# Caches

Besides the persistent checksummed cache files, the process keeps lightweight
in-memory caches for the lifetime of the Python process: the shared CMS
catalog entries per cache directory and parsed stores per derived entry.
Release that state explicitly when an application cycles through distinct
cache directories, such as per-use temporary directories:

```python
from cms_icd import clear_catalog_memory_cache, clear_memory_cache

clear_catalog_memory_cache()
clear_memory_cache()
```

These functions only release in-memory state. Persistent catalog, artifact,
and derived cache files are left untouched.

::: cms_icd.sources.clear_catalog_memory_cache

::: cms_icd.parsed_cache.clear_memory_cache
