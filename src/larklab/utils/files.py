"""File helpers."""

import fcntl
import json
import logging
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class LockBusy(Exception):
    """Another process holds the lock."""


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on `path` (created if missing) for the `with` block.

    Raises `LockBusy` at once, instead of waiting, when another process holds it.
    The lock goes away with the process, so a crash never leaves one behind.
    """
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LockBusy(path) from error
        yield


def read_json_or[T](path: Path, parse: Callable[[Any], T], default: T, what: str) -> T:
    """`parse` the JSON in `path`; a file that is missing, unreadable or not shaped
    as `parse` expects gives `default`. Only a damaged file is warned about."""
    try:
        return parse(json.loads(path.read_text()))
    except FileNotFoundError:
        return default
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        logger.warning("Ignoring unreadable %s file %s: %s", what, path, error)
        return default


def write_text_atomically(path: Path, text: str) -> None:
    """Write `text` to `path` so readers never see a half-written file.

    The text goes to a temporary file in the same folder first and is then
    renamed over `path`. An existing file keeps its permissions.
    """
    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temp_name, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
