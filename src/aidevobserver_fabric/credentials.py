"""Mode-0600 local credential storage for the MCP bridge."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any

from .api_client import validate_base_url


PAT_RE = re.compile(r"^ado_pat_[0-9a-f]{16}\.[A-Za-z0-9_-]{32,128}$")


def credentials_path() -> Path:
    override = os.environ.get("AIDEVOBSERVER_CREDENTIALS")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()
    return base / "aidevobserver" / "credentials.json"


def _absolute(path: Path) -> Path:
    """Return a lexical absolute path without following symbolic links."""

    return Path(os.path.abspath(os.fspath(path)))


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("unsafe credential path") from exc


def _validate_directory(info: os.stat_result | None) -> None:
    if info is None:
        return
    if stat.S_ISLNK(info.st_mode):
        raise ValueError("unsafe credential path: symbolic-link directories are not allowed")
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("unsafe credential path: parent component is not a directory")


def _validate_parent_chain(parent: Path) -> None:
    """Reject symlinks in every existing component leading to ``parent``."""

    for component in (parent, *parent.parents):
        _validate_directory(_lstat(component))


def _open_directory(parent: Path) -> int:
    before = _lstat(parent)
    _validate_directory(before)
    if before is None:
        raise ValueError("unsafe credential path: parent directory is missing")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(parent, flags)
    except OSError as exc:
        raise ValueError("unsafe credential path: parent directory cannot be opened safely") from exc
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
    ):
        os.close(descriptor)
        raise ValueError("unsafe credential path: parent directory changed while opening")
    return descriptor


def _ensure_parent(parent: Path) -> None:
    """Create missing private directories, without chmodding existing ones."""

    _validate_parent_chain(parent)
    missing: list[Path] = []
    current = parent
    while _lstat(current) is None:
        missing.append(current)
        if current.parent == current:
            raise ValueError("unsafe credential path: no existing parent directory")
        current = current.parent
    _validate_directory(_lstat(current))

    for directory in reversed(missing):
        created = False
        try:
            os.mkdir(directory, 0o700)
            created = True
        except FileExistsError:
            # A concurrent creator is acceptable only if it created a real
            # directory. A symlink must never become a chmod target.
            pass
        info = _lstat(directory)
        _validate_directory(info)
        if created:
            descriptor = _open_directory(directory)
            try:
                os.fchmod(descriptor, 0o700)
            finally:
                os.close(descriptor)
    _validate_parent_chain(parent)


def _parent_descriptor(path: Path, *, create: bool) -> tuple[Path, int | None]:
    target = _absolute(path)
    if not target.name:
        raise ValueError("unsafe credential path: a file name is required")
    if create:
        _ensure_parent(target.parent)
    else:
        _validate_parent_chain(target.parent)
        if _lstat(target.parent) is None:
            return target, None
    return target, _open_directory(target.parent)


def _entry_stat(parent_descriptor: int, name: str) -> os.stat_result | None:
    try:
        info = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("unsafe credential path") from exc
    if stat.S_ISLNK(info.st_mode):
        raise ValueError("unsafe credential path: credential file must not be a symbolic link")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("unsafe credential path: credential path must be a regular file")
    return info


def _same_entry(left: os.stat_result | None, right: os.stat_result | None) -> bool:
    if left is None or right is None:
        return left is right
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _read(path: Path) -> dict[str, Any]:
    target, parent_descriptor = _parent_descriptor(path, create=False)
    if parent_descriptor is None:
        return {"version": 1, "servers": {}}
    file_descriptor: int | None = None
    try:
        before = _entry_stat(parent_descriptor, target.name)
        if before is None:
            return {"version": 1, "servers": {}}
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            file_descriptor = os.open(target.name, flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise ValueError("credential file is unreadable or malformed") from exc
        opened = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened.st_mode) or not _same_entry(before, opened):
            raise ValueError("unsafe credential path: credential file changed while opening")
        os.fchmod(file_descriptor, 0o600)
        stream = os.fdopen(file_descriptor, "r", encoding="utf-8")
        file_descriptor = None
        try:
            with stream:
                value = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("credential file is unreadable or malformed") from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        os.close(parent_descriptor)
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("servers"), dict):
        raise ValueError("credential file has an unsupported format")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    target, parent_descriptor = _parent_descriptor(path, create=True)
    assert parent_descriptor is not None
    before = _entry_stat(parent_descriptor, target.name)
    temporary_name: str | None = None
    file_descriptor: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        for _ in range(128):
            candidate = f".credentials.{secrets.token_hex(12)}.tmp"
            try:
                file_descriptor = os.open(candidate, flags, 0o600, dir_fd=parent_descriptor)
                temporary_name = candidate
                break
            except FileExistsError:
                continue
        if file_descriptor is None or temporary_name is None:
            raise ValueError("could not create a private temporary credential file")

        os.fchmod(file_descriptor, 0o600)
        payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        stream = os.fdopen(file_descriptor, "wb")
        file_descriptor = None
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

        current = _entry_stat(parent_descriptor, target.name)
        if not _same_entry(before, current):
            raise ValueError("unsafe credential path: credential file changed during update")
        os.replace(
            temporary_name,
            target.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        temporary_name = None
        os.fsync(parent_descriptor)
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        os.close(parent_descriptor)


def save_token(base_url: str, token: str, *, path: Path | None = None) -> Path:
    server = validate_base_url(base_url)
    if not isinstance(token, str) or PAT_RE.fullmatch(token) is None:
        raise ValueError("token does not have the expected ado_pat format")
    target = path or credentials_path()
    data = _read(target)
    data["servers"][server] = {"token": token}
    _write(target, data)
    return target


def load_token(base_url: str, *, path: Path | None = None) -> str | None:
    server = validate_base_url(base_url)
    target = path or credentials_path()
    entry = _read(target)["servers"].get(server)
    if not isinstance(entry, dict):
        return None
    token = entry.get("token")
    return token if isinstance(token, str) and PAT_RE.fullmatch(token) else None


def remove_token(base_url: str, *, path: Path | None = None) -> bool:
    server = validate_base_url(base_url)
    target = path or credentials_path()
    data = _read(target)
    existed = data["servers"].pop(server, None) is not None
    if existed:
        _write(target, data)
    return existed


def list_servers(*, path: Path | None = None) -> tuple[str, ...]:
    target = path or credentials_path()
    return tuple(sorted(_read(target)["servers"]))
