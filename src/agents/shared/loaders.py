"""Shared file-loading utilities for the UUO agent fleet.

Replaces the per-agent `_CACHE_LOCK + _X_CACHE + cached_x_data()` boilerplate
with two reusable primitives:

- `load_json(path)`: stdlib JSON load with a clear error if the file is missing.
- `mtime_cached(loader, path)`: wraps any `(path) -> T` loader so subsequent
  calls return a cached result until the file's mtime changes. Thread-safe.

Typical usage in an agent:

    from src.agents.shared.loaders import load_json, mtime_cached

    cached_billing_data = mtime_cached(load_json, DEFAULT_BILLING_FILE)
    cached_meter_data   = mtime_cached(load_meter_data, DEFAULT_METER_FILE)
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar


T = TypeVar("T")


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file from disk. Raises FileNotFoundError if missing."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def mtime_cached(loader: Callable[[Path], T], path: Path) -> Callable[[], T]:
    """Return a thread-safe parameterless getter that caches `loader(path)` by mtime.

    The loader is re-invoked when the file's mtime changes (e.g. you edit the
    file on disk) so agents pick up changes without restart. The cache is
    process-local — each worker process holds its own copy.
    """
    cache: tuple[int, T] | None = None
    lock = threading.Lock()
    resolved = Path(path)

    def get() -> T:
        nonlocal cache
        mtime = resolved.stat().st_mtime_ns
        with lock:
            if cache is not None and cache[0] == mtime:
                return cache[1]
        # Load outside the lock so concurrent callers don't serialize on first miss.
        data = loader(resolved)
        with lock:
            cache = (mtime, data)
        return data

    return get
