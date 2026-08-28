"""Versioned caches for immutable parsed CMS materials."""

from __future__ import annotations

import hashlib
import json
import shutil
from concurrent.futures import Future
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import TYPE_CHECKING, Any

from .models import Code, GEMDirection, GEMEntry, GEMProvenance, Node, Release
from .parsers import parse_cm_tabular, parse_gems, parse_pcs_tabular
from .sources import CMSProvider, _directory_lock, _sha256
from .stores import GEMStore, TabularStore

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_CACHE_VERSION = "v1"
_GEM_SCHEMA = "gem-store-v1"
_CORRECTED_GEM_SCHEMA = "corrected-gem-store-v1"
_TABULAR_SCHEMA = "tabular-store-v1"
_memory_lock = Lock()
_memory: dict[tuple[str, str, str], Future[Any]] = {}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _key(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _release_payload(release: Release | None) -> list[object] | None:
    if release is None:
        return None
    return [release.fiscal_year, release.release_date.isoformat()]


def _release_from_payload(value: Sequence[object] | None) -> Release | None:
    if value is None:
        return None
    return Release(int(value[0]), date.fromisoformat(str(value[1])))


def _cache_root(cache_dir: Path, namespace: str, key: str) -> Path:
    return cache_dir / "_derived" / _CACHE_VERSION / namespace / key


def _read_payload(destination: Path, schema: str) -> object | None:
    try:
        manifest = json.loads((destination / "manifest.json").read_text())
        payload_bytes = (destination / "payload.json").read_bytes()
        if manifest.get("schema") != schema or hashlib.sha256(
            payload_bytes
        ).hexdigest() != manifest.get("payload_sha256"):
            return None
        return json.loads(payload_bytes)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_payload(destination: Path, schema: str, payload: object) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(destination.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    payload_bytes = _canonical_bytes(payload)
    with NamedTemporaryFile(dir=staging, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload_bytes)
    temporary.replace(staging / "payload.json")
    (staging / "manifest.json").write_text(
        json.dumps(
            {
                "schema": schema,
                "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if destination.exists():
        shutil.rmtree(destination)
    staging.replace(destination)


def _load_or_build[T](
    cache_dir: Path,
    namespace: str,
    key: str,
    schema: str,
    *,
    decode: Callable[[object], T],
    encode: Callable[[T], object],
    build: Callable[[], T],
) -> T:
    memory_key = (str(cache_dir.resolve()), namespace, key)
    with _memory_lock:
        future = _memory.get(memory_key)
        if future is None:
            future = Future()
            _memory[memory_key] = future
            owner = True
        else:
            owner = False
    if not owner:
        return future.result()

    destination = _cache_root(cache_dir, namespace, key)

    def decode_cached() -> T | None:
        payload = _read_payload(destination, schema)
        if payload is None:
            return None
        try:
            return decode(payload)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None

    try:
        cached = decode_cached()
        if cached is not None:
            result = cached
        else:
            with _directory_lock(destination):
                cached = decode_cached()
                if cached is not None:
                    result = cached
                else:
                    result = build()
                    _write_payload(destination, schema, encode(result))
        result._cache_fingerprint = key
        future.set_result(result)
        return result
    except BaseException as exc:
        future.set_exception(exc)
        with _memory_lock:
            _memory.pop(memory_key, None)
        raise


def _path_fingerprints(paths: Sequence[Path]) -> list[list[str]]:
    return [[path.name, _sha256(path)] for path in paths]


def _gem_payload(store: GEMStore, *, include_provenance: bool) -> dict[str, object]:
    rows = [
        [
            entry.source,
            entry.target,
            entry.approximate,
            entry.no_map,
            entry.combination,
            entry.scenario,
            entry.choice_list,
        ]
        for entries in store.values()
        for entry in entries
    ]
    provenance = None
    if include_provenance:
        provenance = [
            [
                source,
                _release_payload(item.vocabulary_release),
                _release_payload(item.selected_mapping_release),
                _release_payload(item.reviewed_through_release),
                _release_payload(item.blocked_by_code_lifecycle_release),
            ]
            for source in store
            for item in (store.provenance(source),)
        ]
    return {
        "system": store.system,
        "direction": store.direction.value,
        "release": _release_payload(store.release),
        "rows": rows,
        "provenance": provenance,
    }


def _gem_from_payload(payload: object) -> GEMStore:
    if not isinstance(payload, dict):
        raise TypeError("Invalid cached GEM payload")
    grouped: dict[str, list[GEMEntry]] = {}
    for row in payload["rows"]:
        entry = GEMEntry(
            source=str(row[0]),
            target=None if row[1] is None else str(row[1]),
            approximate=bool(row[2]),
            no_map=bool(row[3]),
            combination=bool(row[4]),
            scenario=int(row[5]),
            choice_list=int(row[6]),
        )
        grouped.setdefault(entry.source, []).append(entry)
    provenance: dict[str, GEMProvenance] = {}
    for row in payload.get("provenance") or ():
        provenance[str(row[0])] = GEMProvenance(
            vocabulary_release=_release_from_payload(row[1]),  # type: ignore[arg-type]
            selected_mapping_release=_release_from_payload(row[2]),  # type: ignore[arg-type]
            reviewed_through_release=_release_from_payload(row[3]),  # type: ignore[arg-type]
            blocked_by_code_lifecycle_release=_release_from_payload(row[4]),  # type: ignore[arg-type]
        )
    return GEMStore(
        {source: tuple(entries) for source, entries in grouped.items()},
        system=str(payload["system"]),
        direction=GEMDirection(str(payload["direction"])),
        release=_release_from_payload(payload.get("release")),  # type: ignore[arg-type]
        provenance=provenance,
    )


def load_gem_store(
    provider: CMSProvider, system: str, direction: GEMDirection
) -> GEMStore:
    paths = provider.paths(system, "gems")
    dependencies = {
        "schema": _GEM_SCHEMA,
        "release": _release_payload(provider.release),
        "system": system,
        "direction": direction.value,
        "files": _path_fingerprints(paths),
    }
    key = _key(dependencies)
    return _load_or_build(
        provider.cache_dir,
        "gems",
        key,
        _GEM_SCHEMA,
        decode=_gem_from_payload,
        encode=lambda store: _gem_payload(store, include_provenance=False),
        build=lambda: parse_gems(
            paths,
            system=system,
            direction=direction,
            release=provider.release,
        ),
    )


def load_corrected_gem_store(
    cache_dir: Path,
    stores: Sequence[GEMStore],
    target_universes: Sequence[set[str]],
    *,
    build: Callable[[], GEMStore],
) -> GEMStore:
    fingerprints = [getattr(store, "_cache_fingerprint", None) for store in stores]
    if any(item is None for item in fingerprints):
        return build()
    base = stores[0]
    dependencies = {
        "schema": _CORRECTED_GEM_SCHEMA,
        "system": base.system,
        "direction": base.direction.value,
        "stores": fingerprints,
        "target_universes": [
            hashlib.sha256("\0".join(sorted(values)).encode()).hexdigest()
            for values in target_universes
        ],
    }
    key = _key(dependencies)
    return _load_or_build(
        cache_dir,
        "corrected-gems",
        key,
        _CORRECTED_GEM_SCHEMA,
        decode=_gem_from_payload,
        encode=lambda store: _gem_payload(store, include_provenance=True),
        build=build,
    )


_TUPLE_FIELDS = {
    "children_ids",
    "notes",
    "includes",
    "inclusion_term",
    "excludes1",
    "excludes2",
    "use_additional_code",
    "code_first",
    "code_also",
}


def _tabular_payload(store: TabularStore) -> dict[str, object]:
    return {
        "roots": list(store.roots),
        "lookup": dict(store.lookup),
        "nodes": [
            {
                "type": "code" if isinstance(node, Code) else "node",
                "value": node.to_dict(),
            }
            for node in store.values()
        ],
    }


def _tabular_from_payload(payload: object) -> TabularStore:
    if not isinstance(payload, dict):
        raise TypeError("Invalid cached tabular payload")
    values: dict[str, Node] = {}
    for record in payload["nodes"]:
        value = dict(record["value"])
        for field in _TUPLE_FIELDS:
            if field in value:
                value[field] = tuple(value[field])
        node = Code(**value) if record["type"] == "code" else Node(**value)
        values[node.id] = node
    return TabularStore(values, payload["lookup"], tuple(payload["roots"]))


def load_tabular_store(provider: CMSProvider, system: str) -> TabularStore:
    path = provider.paths(system, "tabular")[0]
    dependencies = {
        "schema": _TABULAR_SCHEMA,
        "release": _release_payload(provider.release),
        "system": system,
        "file": [path.name, _sha256(path)],
    }
    key = _key(dependencies)
    parser = parse_cm_tabular if system == "cm" else parse_pcs_tabular
    return _load_or_build(
        provider.cache_dir,
        "tabular",
        key,
        _TABULAR_SCHEMA,
        decode=_tabular_from_payload,
        encode=_tabular_payload,
        build=lambda: parser(path),
    )


def clear_memory_cache() -> None:
    """Clear process-local parsed-store state for tests and diagnostics."""
    with _memory_lock:
        _memory.clear()
