#!/usr/bin/env python3
"""
Session Buffer — Safe I/O Utilities

Provides atomic writes, validated reads, schema version checks,
and marker TTL enforcement. Imported by hooks and scripts via importlib.

Design principle: fail-loud for corruption, fail-silent for absence.
A missing file is normal (first run). A file that exists but is empty
or missing required fields is corruption and must be reported.
"""

import contextlib
import json
import os
import sys
import tempfile
import time


# ---------------------------------------------------------------------------
# Atomic JSON write — temp file + rename
# ---------------------------------------------------------------------------

def atomic_write_json(path, data, indent=2):
    """Write JSON atomically via temp-file-then-rename.

    On POSIX, os.rename is atomic if src and dst are on the same filesystem.
    On Windows, os.replace is atomic (overwrites existing file).

    Raises OSError on failure — caller decides whether to catch.
    """
    dir_name = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp', text=True)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        # os.replace is atomic on both POSIX and Windows
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_text(path, content):
    """Write text atomically via temp-file-then-rename."""
    dir_name = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp', text=True)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Validated JSON read — distinguishes missing vs empty vs corrupt
# ---------------------------------------------------------------------------

class HollowFileError(ValueError):
    """File exists with valid JSON structure but missing required payload."""
    pass


def read_json(path):
    """Read JSON file. Returns dict/list or None if file is missing.

    Uses utf-8-sig to transparently strip BOM if present (Windows editors
    like old Notepad add a BOM to UTF-8 files). Works identically to utf-8
    when no BOM exists.

    Raises json.JSONDecodeError if file exists but contains invalid JSON.
    Does NOT silently return {} on corruption.
    """
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    # Let JSONDecodeError and OSError propagate


def read_json_safe(path):
    """Read JSON file, returning None on missing or corrupt.

    Use this only for non-critical files where corruption is acceptable.
    For critical state files, use read_json() and handle errors explicitly.
    """
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def read_json_validated(path, required_keys=None):
    """Read JSON and validate required keys are present and non-empty.

    Returns the parsed dict.
    Returns None if file is missing.
    Raises HollowFileError if file exists but required keys are missing or empty.
    Raises json.JSONDecodeError if file is corrupt.

    BOM-safe: uses read_json() which strips BOM transparently.
    """
    data = read_json(path)
    if data is None:
        return None

    if required_keys and isinstance(data, dict):
        missing = []
        hollow = []
        for key in required_keys:
            if key not in data:
                missing.append(key)
            elif data[key] is None or data[key] == '' or data[key] == {} or data[key] == []:
                hollow.append(key)
        if missing:
            raise HollowFileError(
                f"{path}: missing required keys: {missing}")
        if hollow:
            raise HollowFileError(
                f"{path}: hollow payload in keys: {hollow}")

    return data


# ---------------------------------------------------------------------------
# Schema version check — forward compatibility guard
# ---------------------------------------------------------------------------

class SchemaVersionError(ValueError):
    """Schema version is higher than supported — upgrade required."""
    pass


def check_schema_version(data, max_supported, path='<unknown>'):
    """Check that schema_version is not higher than what we support.

    Args:
        data: parsed JSON dict
        max_supported: highest version this code knows how to handle
        path: file path for error messages

    Raises SchemaVersionError if version > max_supported.
    Returns the version found (int), defaulting to 1 if missing.
    """
    if not isinstance(data, dict):
        return 1
    version = data.get('schema_version', 1)
    if isinstance(version, str):
        # Handle semver strings like "2.0.0"
        try:
            version = int(version.split('.')[0])
        except (ValueError, IndexError):
            version = 1
    if version > max_supported:
        raise SchemaVersionError(
            f"{path}: schema_version {version} > {max_supported}. "
            f"Upgrade your plugin to read this file.")
    return version


# ---------------------------------------------------------------------------
# Marker TTL enforcement
# ---------------------------------------------------------------------------

def check_marker_ttl(marker_path, max_age_seconds):
    """Check if a marker file exists and is within its TTL.

    Returns:
        True if marker exists and is fresh (within max_age_seconds).
        False if marker is missing, stale, or unreadable.
    """
    try:
        mtime = os.path.getmtime(marker_path)
        age = time.time() - mtime
        return age < max_age_seconds
    except (FileNotFoundError, OSError):
        return False


def cleanup_stale_marker(marker_path, max_age_seconds):
    """Remove a marker file if it's older than max_age_seconds.

    Returns True if marker was removed (stale), False otherwise.
    """
    try:
        mtime = os.path.getmtime(marker_path)
        age = time.time() - mtime
        if age >= max_age_seconds:
            os.remove(marker_path)
            return True
    except (FileNotFoundError, OSError):
        pass
    return False


# ---------------------------------------------------------------------------
# File locking — cross-platform advisory lock for concurrent hook safety
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def file_lock(path, timeout=5):
    """Advisory file lock using a .lock sidecar file.

    On Windows, msvcrt.locking provides mandatory locking but only works on
    open file descriptors. On Unix, fcntl.flock provides advisory locks.
    This uses a cross-platform approach: create a .lock file with O_CREAT|O_EXCL
    (atomic create-if-not-exists), with a TTL to prevent deadlocks from crashed
    processes.

    Args:
        path: the file being protected (lock file will be path + '.lock')
        timeout: max seconds to wait for the lock (default 5)

    Raises:
        TimeoutError if lock can't be acquired within timeout.
    """
    lock_path = path + '.lock'
    deadline = time.time() + timeout
    acquired = False

    while time.time() < deadline:
        try:
            # O_CREAT | O_EXCL = atomic create-if-not-exists
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            # Lock exists — check if it's stale (holder crashed)
            try:
                lock_age = time.time() - os.path.getmtime(lock_path)
                if lock_age > timeout * 2:
                    # Stale lock from crashed process — force remove
                    try:
                        os.remove(lock_path)
                    except OSError:
                        pass
                    continue
            except OSError:
                pass
            time.sleep(0.05)
        except OSError:
            time.sleep(0.05)

    if not acquired:
        raise TimeoutError(f"Could not acquire lock on {path} within {timeout}s")

    try:
        yield
    finally:
        try:
            os.remove(lock_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Atomic read-modify-write for counters
# ---------------------------------------------------------------------------

def atomic_increment_counter(path, amount=1):
    """Atomically read, increment, and write back a plain-text integer counter.

    Creates the file with value=amount if it doesn't exist.
    Uses file_lock to prevent concurrent increments from losing counts.
    Returns the new count.
    """
    with file_lock(path):
        count = 0
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                count = int(f.read().strip() or '0')
        except (FileNotFoundError, ValueError, OSError):
            count = 0
        count += amount
        atomic_write_text(path, str(count))
        return count


def atomic_read_modify_write_json(path, modify_fn, default=None):
    """Atomically read a JSON file, apply modify_fn, and write back.

    Uses file_lock to prevent concurrent read-modify-write races.

    Args:
        path: file path
        modify_fn: callable(data) -> data. Can modify data in place (return None)
            or return a new object. If modify_fn returns None, the original
            data object is used (assumed in-place mutation).
        default: value to use if file doesn't exist (default: None, which skips).
            Can be a callable (factory) or a value.

    Returns the modified data, or None if file missing and no default.
    """
    with file_lock(path):
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
        except FileNotFoundError:
            if default is not None:
                data = default() if callable(default) else default
            else:
                return None
        except (json.JSONDecodeError, OSError):
            if default is not None:
                data = default() if callable(default) else default
            else:
                raise

        result = modify_fn(data)
        if result is not None:
            data = result
        atomic_write_json(path, data)
        return data
