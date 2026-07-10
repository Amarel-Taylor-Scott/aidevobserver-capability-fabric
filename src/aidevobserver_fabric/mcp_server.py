"""Dependency-free MCP stdio server for the AIDevObserver capability fabric.

The transport is newline-delimited JSON-RPC 2.0 over stdin/stdout.  Stdout is
reserved for protocol messages; startup diagnostics and configuration errors
go to stderr in :func:`main`.

The server intentionally exposes a small, stable tool surface.  Discovery and
execution remain API concerns handled by ``FabricClient``; this module only
validates MCP input, delegates calls, projects deterministic responses, and
materializes verified source files inside an explicitly bounded workspace.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from copy import deepcopy
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping, TextIO

from .api_client import APIError


PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "aidevobserver-capability-fabric"
SERVER_VERSION = "0.2.0"
DEFAULT_BASE_URL = "http://127.0.0.1:8766"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

_NO_ID = object()
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def canonical_json(value: Any) -> str:
    """Return the canonical compact JSON representation used in MCP text blocks."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


FILTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "input_contract": {"type": "string", "minLength": 1},
        "output_contract": {"type": "string", "minLength": 1},
        "trust": {"type": "string", "minLength": 1},
        "executable_only": {"type": "boolean"},
        "candidate_only": {"type": "boolean"},
        "serves_truth": {"type": "boolean"},
    },
    "additionalProperties": False,
}

REUSE_PAYLOAD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "primitive_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "action": {"type": "string", "enum": ["searched", "inspected", "executed", "materialized", "reused"]},
        "outcome": {"type": "string", "enum": ["accepted", "rejected", "passed", "failed", "used"]},
    },
    "required": ["primitive_id", "outcome"],
    "additionalProperties": False,
}

ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["code", "message"],
    "properties": {
        "code": {"type": "string"},
        "message": {"type": "string"},
        "details": {"type": "object", "additionalProperties": True},
    },
    "additionalProperties": False,
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ok", "data"],
    "properties": {
        "ok": {"type": "boolean"},
        "data": {"type": "object", "additionalProperties": True},
        "error": ERROR_SCHEMA,
    },
    "additionalProperties": False,
}


def _object_schema(
    properties: Mapping[str, Any],
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "search_primitives",
        "title": "Search reusable primitives",
        "description": (
            "Search the capability fabric before writing new code. Returns compact candidates, "
            "contracts, readiness, and proof metadata."
        ),
        "inputSchema": _object_schema(
            {
                "query": {"type": "string", "minLength": 1},
                "filters": FILTER_SCHEMA,
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 6},
            },
            ("query",),
        ),
        "outputSchema": deepcopy(OUTPUT_SCHEMA),
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    },
    {
        "name": "get_primitive",
        "title": "Get a primitive",
        "description": "Fetch one primitive card, including its contract, source digest, and implementation metadata.",
        "inputSchema": _object_schema(
            {"primitive_id": {"type": "string", "minLength": 1}},
            ("primitive_id",),
        ),
        "outputSchema": deepcopy(OUTPUT_SCHEMA),
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    },
    {
        "name": "execute_primitive",
        "title": "Execute a primitive",
        "description": "Send JSON inputs to the configured capability service and execute a proved, server-authorized primitive with validated input/output.",
        "inputSchema": _object_schema(
            {
                "primitive_id": {"type": "string", "minLength": 1},
                "inputs": {"type": "object", "additionalProperties": True},
            },
            ("primitive_id", "inputs"),
        ),
        "outputSchema": deepcopy(OUTPUT_SCHEMA),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    },
    {
        "name": "materialize_primitive",
        "title": "Materialize primitive source",
        "description": (
            "Verify a primitive source digest and atomically write it beneath the configured workspace. "
            "Absolute paths, traversal, symlink escapes, and implicit overwrites are refused."
        ),
        "inputSchema": _object_schema(
            {
                "primitive_id": {"type": "string", "minLength": 1},
                "destination": {"type": "string", "minLength": 1},
                "overwrite": {"type": "boolean", "default": False},
            },
            ("primitive_id",),
        ),
        "outputSchema": deepcopy(OUTPUT_SCHEMA),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    },
    {
        "name": "prove_primitive",
        "title": "Fetch primitive proof",
        "description": "Fetch proof, oracle, provenance, and promotion evidence for one primitive.",
        "inputSchema": _object_schema(
            {"primitive_id": {"type": "string", "minLength": 1}},
            ("primitive_id",),
        ),
        "outputSchema": deepcopy(OUTPUT_SCHEMA),
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    },
    {
        "name": "record_reuse",
        "title": "Record primitive reuse",
        "description": "Record a reuse outcome or receipt so ranking can learn from verified agent work.",
        "inputSchema": _object_schema(
            {"payload": REUSE_PAYLOAD_SCHEMA},
            ("payload",),
        ),
        "outputSchema": deepcopy(OUTPUT_SCHEMA),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    },
)

TOOL_BY_NAME = {tool["name"]: tool for tool in TOOLS}


class RpcFault(Exception):
    """A JSON-RPC protocol error."""

    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class ToolFailure(Exception):
    """A handled business refusal/failure returned as an MCP tool result."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def _redact(value: Any, secrets: tuple[str, ...]) -> Any:
    """Recursively redact configured secret values from every outward payload."""

    live = tuple(secret for secret in secrets if secret)
    if isinstance(value, str):
        result = value
        for secret in live:
            result = result.replace(secret, "<redacted>")
        return result
    if isinstance(value, dict):
        return {str(_redact(str(key), live)): _redact(item, live) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, live) for item in value]
    return value


def _schema_error(value: Any, schema: Mapping[str, Any], path: str = "$") -> str | None:
    """Validate the dependency-free JSON-Schema subset used by the six tools."""

    expected = schema.get("type")
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} must be one of: {', '.join(map(str, schema['enum']))}"
    if expected == "object":
        if not isinstance(value, dict):
            return f"{path} must be an object"
        required = schema.get("required", [])
        missing = [name for name in required if name not in value]
        if missing:
            return f"{path} is missing required properties: {', '.join(sorted(missing))}"
        minimum = schema.get("minProperties")
        if isinstance(minimum, int) and len(value) < minimum:
            return f"{path} must contain at least {minimum} properties"
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                return f"{path} contains unknown properties: {', '.join(extras)}"
        for key, item in value.items():
            child = properties.get(key)
            if isinstance(child, dict):
                error = _schema_error(item, child, f"{path}.{key}")
                if error:
                    return error
        return None

    if expected == "array":
        if not isinstance(value, list):
            return f"{path} must be an array"
        if schema.get("uniqueItems") and len({canonical_json(item) for item in value}) != len(value):
            return f"{path} must contain unique items"
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                error = _schema_error(item, item_schema, f"{path}[{index}]")
                if error:
                    return error
        return None

    if expected == "string":
        if not isinstance(value, str):
            return f"{path} must be a string"
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(value) < minimum:
            return f"{path} must contain at least {minimum} characters"
        maximum = schema.get("maxLength")
        if isinstance(maximum, int) and len(value) > maximum:
            return f"{path} must contain at most {maximum} characters"
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            return f"{path} has an invalid format"
        return None

    if expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{path} must be an integer"
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path} must be at least {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path} must be at most {schema['maximum']}"
        return None

    if expected == "boolean" and not isinstance(value, bool):
        return f"{path} must be a boolean"
    return None


def _rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: Any, fault: RpcFault) -> dict[str, Any]:
    error: dict[str, Any] = {"code": fault.code, "message": fault.message}
    if fault.data is not None:
        error["data"] = fault.data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _tool_result(structured: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": canonical_json(structured)}],
        "structuredContent": structured,
        "isError": is_error,
    }


def _safe_relative_path(raw: str) -> Path:
    """Parse a platform-neutral relative path and reject traversal/drive syntax."""

    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ToolFailure("unsafe_destination", "destination must be a non-empty relative path")
    windows = PureWindowsPath(raw)
    if raw.startswith(("/", "\\")) or windows.is_absolute() or bool(windows.drive):
        raise ToolFailure("unsafe_destination", "absolute destination paths are not allowed")
    parts = raw.replace("\\", "/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ToolFailure("unsafe_destination", "destination contains an empty, dot, or traversal segment")
    if any(":" in part for part in parts):
        raise ToolFailure("unsafe_destination", "destination contains unsupported drive or stream syntax")
    return Path(*parts)


def _secure_dirfd_available() -> bool:
    """Return whether this runtime can keep every materialization step dirfd-bound."""

    required = (os.open, os.mkdir, os.stat, os.unlink, os.link, os.rename)
    return bool(
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and all(function in os.supports_dir_fd for function in required)
        and os.stat in os.supports_follow_symlinks
        and os.link in os.supports_follow_symlinks
    )


def _directory_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _regular_file_flags() -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _target_stat(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        raise ToolFailure("symlink_destination", "destination is a symbolic link")
    if not stat.S_ISREG(info.st_mode):
        raise ToolFailure("unsafe_destination", "destination exists and is not a regular file")
    return info


def _file_digest_at(parent_fd: int, name: str) -> str | None:
    """Hash one regular file without ever resolving a path or following a link."""

    try:
        fd = os.open(name, _regular_file_flags(), dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ToolFailure("symlink_destination", "destination is a symbolic link") from exc
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ToolFailure("unsafe_destination", "destination exists and is not a regular file")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)
    finally:
        os.close(fd)


class _MaterializedWrite:
    """Small transaction record used to finalize or roll back a staged write."""

    def __init__(
        self,
        parent_fd: int,
        target_name: str,
        backup_name: str | None,
        digest: str,
        overwrote: bool,
    ) -> None:
        self.parent_fd = parent_fd
        self.target_name = target_name
        self.backup_name = backup_name
        self.digest = digest
        self.overwrote = overwrote
        self._closed = False

    def _close(self) -> None:
        if not self._closed:
            os.close(self.parent_fd)
            self._closed = True

    def finalize(self) -> None:
        try:
            if self.backup_name is not None:
                try:
                    os.unlink(self.backup_name, dir_fd=self.parent_fd)
                except FileNotFoundError:
                    pass
        finally:
            self._close()

    def rollback(self) -> None:
        try:
            if self.backup_name is not None:
                try:
                    os.rename(
                        self.backup_name,
                        self.target_name,
                        src_dir_fd=self.parent_fd,
                        dst_dir_fd=self.parent_fd,
                    )
                    return
                except FileNotFoundError:
                    pass
            if _file_digest_at(self.parent_fd, self.target_name) == self.digest:
                try:
                    os.unlink(self.target_name, dir_fd=self.parent_fd)
                except FileNotFoundError:
                    pass
        finally:
            self._close()


class McpServer:
    """Pure JSON-RPC dispatcher around an injected synchronous Fabric client."""

    def __init__(
        self,
        client: Any,
        workspace_root: str | Path,
        *,
        secrets: tuple[str, ...] = (),
    ) -> None:
        self.client = client
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.secrets = tuple(secret for secret in secrets if secret)
        self.initialized = False
        self.ready = False

    def _clean(self, value: Any) -> Any:
        return _redact(value, self.secrets)

    def _upstream(self, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise ToolFailure(
                "invalid_upstream_response",
                f"fabric client returned {type(result).__name__}, expected a JSON object",
            )
        error = result.get("error")
        if result.get("ok") is False or error:
            if isinstance(error, dict):
                code = str(error.get("code") or "upstream_error")
                message = str(error.get("message") or result.get("message") or code)
            else:
                code = str(error or "upstream_error")
                message = str(result.get("message") or error or "fabric request failed")
            raise ToolFailure(code, message, {"upstream": self._clean(result)})
        return result

    def _success(self, data: dict[str, Any]) -> dict[str, Any]:
        return _tool_result({"ok": True, "data": self._clean(data)}, is_error=False)

    def _failure(self, failure: ToolFailure) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": failure.code,
            "message": str(self._clean(failure.message)),
        }
        if failure.details is not None:
            error["details"] = self._clean(failure.details)
        return _tool_result({"ok": False, "data": {}, "error": error}, is_error=True)

    @staticmethod
    def _open_child_directory(parent_fd: int, name: str, *, create: bool) -> int:
        try:
            return os.open(name, _directory_flags(), dir_fd=parent_fd)
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir(name, mode=0o755, dir_fd=parent_fd)
            except FileExistsError:
                # A concurrent creator won. The no-follow open below decides
                # whether it created a real directory or an unsafe link.
                pass
            try:
                return os.open(name, _directory_flags(), dir_fd=parent_fd)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise ToolFailure(
                        "symlink_escape", "destination ancestor is not a real directory"
                    ) from exc
                raise
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise ToolFailure(
                    "symlink_escape", "destination ancestor is not a real directory"
                ) from exc
            raise

    def _open_workspace_root(self) -> int:
        """Open the absolute workspace one component at a time without links."""

        if not _secure_dirfd_available():
            raise ToolFailure(
                "secure_materialization_unavailable",
                "this platform cannot securely materialize workspace files",
            )
        root_fd = os.open(os.path.sep, _directory_flags())
        current_fd = root_fd
        try:
            for part in self.workspace_root.parts[1:]:
                next_fd = self._open_child_directory(current_fd, part, create=False)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except FileNotFoundError as exc:
            os.close(current_fd)
            raise ToolFailure(
                "workspace_unavailable", "configured workspace root is not an existing directory"
            ) from exc
        except Exception:
            os.close(current_fd)
            raise

    def _open_parent(self, relative: Path, *, create: bool = True) -> int:
        current_fd = self._open_workspace_root()
        try:
            for part in relative.parts[:-1]:
                next_fd = self._open_child_directory(current_fd, part, create=create)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except Exception:
            os.close(current_fd)
            raise

    def _verify_parent_binding(self, relative: Path, pinned_fd: int) -> None:
        """Fail if a checked ancestor was swapped while the write was running."""

        try:
            check_fd = self._open_parent(relative, create=False)
        except FileNotFoundError as exc:
            raise ToolFailure(
                "symlink_escape", "destination ancestor changed during materialization"
            ) from exc
        try:
            pinned = os.fstat(pinned_fd)
            checked = os.fstat(check_fd)
            if (pinned.st_dev, pinned.st_ino) != (checked.st_dev, checked.st_ino):
                raise ToolFailure(
                    "symlink_escape", "destination ancestor changed during materialization"
                )
        finally:
            os.close(check_fd)

    @staticmethod
    def _unique_name(parent_fd: int, target_name: str, suffix: str) -> str:
        for _ in range(32):
            name = f".{target_name}.{uuid.uuid4().hex}.{suffix}"
            try:
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return name
        raise ToolFailure("temporary_name_exhausted", "could not allocate a staging filename")

    def _atomic_write(
        self,
        parent_fd: int,
        target_name: str,
        source: str,
        digest: str,
        *,
        overwrite: bool,
    ) -> _MaterializedWrite:
        current = _target_stat(parent_fd, target_name)
        if current is not None and not overwrite:
            raise ToolFailure("destination_exists", "destination exists; set overwrite=true to replace it")

        payload = source.encode("utf-8")
        staged_name = self._unique_name(parent_fd, target_name, "tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        staged_fd = os.open(staged_name, flags, 0o600, dir_fd=parent_fd)
        backup_name: str | None = None
        committed = False
        try:
            with os.fdopen(staged_fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o644)

            overwrote = False
            if overwrite:
                # Keep an inode-level rollback link when a target exists. If a
                # target appears after a missing check, retry and back it up
                # rather than silently clobbering an unprotected race winner.
                for _ in range(32):
                    backup_name = self._unique_name(parent_fd, target_name, "bak")
                    try:
                        os.link(
                            target_name,
                            backup_name,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        backup_name = None
                        try:
                            os.link(
                                staged_name,
                                target_name,
                                src_dir_fd=parent_fd,
                                dst_dir_fd=parent_fd,
                                follow_symlinks=False,
                            )
                        except FileExistsError:
                            continue
                        os.unlink(staged_name, dir_fd=parent_fd)
                        break
                    else:
                        backup_info = os.stat(
                            backup_name, dir_fd=parent_fd, follow_symlinks=False
                        )
                        if stat.S_ISLNK(backup_info.st_mode):
                            raise ToolFailure(
                                "symlink_destination", "destination is a symbolic link"
                            )
                        if not stat.S_ISREG(backup_info.st_mode):
                            raise ToolFailure(
                                "unsafe_destination",
                                "destination exists and is not a regular file",
                            )
                        os.rename(
                            staged_name,
                            target_name,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                        )
                        overwrote = True
                        break
                else:
                    raise ToolFailure(
                        "destination_race", "destination changed too often during materialization"
                    )
            else:
                # Hard-linking the fully-written staging inode is both atomic
                # and no-clobber while remaining bound to the pinned directory.
                try:
                    os.link(
                        staged_name,
                        target_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError as exc:
                    raise ToolFailure(
                        "destination_exists", "destination exists; set overwrite=true to replace it"
                    ) from exc
                os.unlink(staged_name, dir_fd=parent_fd)
                overwrote = False

            committed = True
            return _MaterializedWrite(
                os.dup(parent_fd), target_name, backup_name, digest, overwrote
            )
        finally:
            try:
                os.unlink(staged_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            if not committed and backup_name is not None:
                try:
                    os.unlink(backup_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass

    def _materialize(self, arguments: dict[str, Any]) -> dict[str, Any]:
        primitive_id = arguments["primitive_id"]
        lookup = self._upstream(self.client.get(primitive_id))
        primitive = lookup.get("primitive")
        if not isinstance(primitive, dict):
            raise ToolFailure("invalid_primitive", "fabric response does not contain a primitive object")
        returned_id = primitive.get("primitive_id")
        if returned_id != primitive_id:
            raise ToolFailure(
                "primitive_identity_mismatch",
                "returned primitive id does not match the requested primitive",
                {"requested": primitive_id, "returned": returned_id},
            )
        source = primitive.get("source")
        expected = primitive.get("source_sha256")
        module_filename = primitive.get("module_filename")
        if not isinstance(source, str):
            raise ToolFailure("source_unavailable", "primitive has no materializable text source")
        if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
            raise ToolFailure("digest_unavailable", "primitive has no valid source_sha256")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if digest != expected.lower():
            raise ToolFailure(
                "digest_mismatch",
                "primitive source does not match source_sha256",
                {"expected": expected.lower(), "actual": digest},
            )
        destination = arguments.get("destination")
        if destination is None:
            if not isinstance(module_filename, str) or not module_filename:
                raise ToolFailure("destination_required", "destination or primitive.module_filename is required")
            destination = module_filename
        relative = _safe_relative_path(destination)
        overwrite = arguments.get("overwrite", False)
        parent_fd = self._open_parent(relative)
        transaction: _MaterializedWrite | None = None
        try:
            target_name = relative.name
            existing = _target_stat(parent_fd, target_name)
            reused_existing = bool(
                existing is not None
                and not overwrite
                and _file_digest_at(parent_fd, target_name) == digest
            )
            if existing is not None and not overwrite and not reused_existing:
                raise ToolFailure(
                    "destination_exists", "destination exists; set overwrite=true to replace it"
                )
            if not reused_existing:
                transaction = self._atomic_write(
                    parent_fd,
                    target_name,
                    source,
                    digest,
                    overwrite=overwrite,
                )
            self._verify_parent_binding(relative, parent_fd)
            bytes_written = 0 if reused_existing else len(source.encode("utf-8"))
        except Exception:
            if transaction is not None:
                transaction.rollback()
                transaction = None
            raise
        finally:
            os.close(parent_fd)

        receipt_payload = {
            "primitive_id": primitive_id,
            "action": "materialized",
            "outcome": "used",
        }
        try:
            receipt = self._upstream(self.client.record_reuse(receipt_payload))
        except Exception:
            if transaction is not None:
                transaction.rollback()
            raise
        if transaction is not None:
            transaction.finalize()
        return {
            "primitive_id": primitive_id,
            "label": primitive.get("label"),
            "destination": relative.as_posix(),
            "source_sha256": digest,
            "bytes_written": bytes_written,
            "overwrote": transaction.overwrote if transaction is not None else False,
            "reused_existing": reused_existing,
            "receipt": receipt,
            "suggested_usage": primitive.get("suggested_usage"),
        }

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        descriptor = TOOL_BY_NAME.get(name)
        if descriptor is None:
            raise RpcFault(INVALID_PARAMS, f"unknown tool: {name}")
        validation_error = _schema_error(arguments, descriptor["inputSchema"])
        if validation_error:
            raise RpcFault(INVALID_PARAMS, validation_error)
        try:
            if name == "search_primitives":
                data = self._upstream(
                    self.client.search(
                        arguments["query"],
                        arguments.get("filters", {}),
                        arguments.get("limit", 6),
                    )
                )
            elif name == "get_primitive":
                data = self._upstream(self.client.get(arguments["primitive_id"]))
            elif name == "execute_primitive":
                data = self._upstream(
                    self.client.execute(arguments["primitive_id"], arguments["inputs"])
                )
            elif name == "materialize_primitive":
                data = self._materialize(arguments)
            elif name == "prove_primitive":
                data = self._upstream(self.client.prove(arguments["primitive_id"]))
            else:  # record_reuse (the fixed descriptor table makes this exhaustive)
                payload = arguments["payload"]
                data = self._upstream(
                    self.client.record_reuse(
                        {
                            "kind": "reuse",
                            "subject_id": payload["primitive_id"],
                            "payload": payload,
                        }
                    )
                )
            return self._success(data)
        except ToolFailure as failure:
            return self._failure(failure)
        except APIError as exc:
            return self._failure(
                ToolFailure(exc.code, str(self._clean(str(exc))), {"http_status": exc.status})
            )
        except Exception as exc:  # client/network/runtime failures are business failures, not protocol crashes
            return self._failure(
                ToolFailure("tool_execution_failed", f"{type(exc).__name__}: {self._clean(str(exc))}")
            )

    def handle_message(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return _rpc_error(None, RpcFault(INVALID_REQUEST, "request must be a JSON object"))
        request_id = message.get("id", _NO_ID)
        response_id = None if request_id is _NO_ID else request_id
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            if request_id is _NO_ID:
                return None
            return _rpc_error(response_id, RpcFault(INVALID_REQUEST, "invalid JSON-RPC 2.0 request"))
        method = message["method"]
        params = message.get("params", {})
        if not isinstance(params, dict):
            if request_id is _NO_ID:
                return None
            return _rpc_error(response_id, RpcFault(INVALID_PARAMS, "params must be an object"))

        try:
            if method == "initialize":
                if request_id is _NO_ID:
                    raise RpcFault(INVALID_REQUEST, "initialize must be a request")
                if self.initialized:
                    raise RpcFault(INVALID_REQUEST, "server is already initialized")
                if set(params) - {"protocolVersion", "capabilities", "clientInfo"}:
                    raise RpcFault(INVALID_PARAMS, "initialize contains unknown parameters")
                if not isinstance(params.get("protocolVersion"), str):
                    raise RpcFault(INVALID_PARAMS, "initialize requires protocolVersion")
                if not isinstance(params.get("capabilities"), dict):
                    raise RpcFault(INVALID_PARAMS, "initialize requires capabilities object")
                client_info = params.get("clientInfo")
                if (
                    not isinstance(client_info, dict)
                    or not isinstance(client_info.get("name"), str)
                    or not isinstance(client_info.get("version"), str)
                ):
                    raise RpcFault(INVALID_PARAMS, "initialize requires clientInfo name and version")
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": (
                        "Search before coding; inspect contracts and proof before execution or materialization."
                    ),
                }
                self.initialized = True
            elif method == "notifications/initialized":
                if not self.initialized:
                    return None
                self.ready = True
                return None
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                if not self.ready:
                    raise RpcFault(INVALID_REQUEST, "server is not initialized")
                allowed = {"cursor"}
                if set(params) - allowed or ("cursor" in params and not isinstance(params["cursor"], str)):
                    raise RpcFault(INVALID_PARAMS, "tools/list accepts only an optional string cursor")
                result = {"tools": [deepcopy(tool) for tool in TOOLS]}
            elif method == "tools/call":
                if not self.ready:
                    raise RpcFault(INVALID_REQUEST, "server is not initialized")
                if set(params) - {"name", "arguments"}:
                    raise RpcFault(INVALID_PARAMS, "tools/call contains unknown parameters")
                name = params.get("name")
                arguments = params.get("arguments", {})
                if not isinstance(name, str) or not name:
                    raise RpcFault(INVALID_PARAMS, "tools/call requires a non-empty string name")
                if not isinstance(arguments, dict):
                    raise RpcFault(INVALID_PARAMS, "tools/call arguments must be an object")
                result = self.call_tool(name, arguments)
            else:
                raise RpcFault(METHOD_NOT_FOUND, f"method not found: {method}")
        except RpcFault as fault:
            if request_id is _NO_ID:
                return None
            return self._clean(_rpc_error(response_id, fault))
        except Exception:
            if request_id is _NO_ID:
                return None
            return _rpc_error(response_id, RpcFault(INTERNAL_ERROR, "internal server error"))

        if request_id is _NO_ID:
            return None
        return self._clean(_rpc_result(response_id, result))


def serve_jsonl(server: McpServer, stdin: TextIO, stdout: TextIO) -> int:
    """Serve JSON-RPC messages until EOF, emitting one compact JSON object per response."""

    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
            response = _rpc_error(
                None,
                RpcFault(PARSE_ERROR, "parse error", {"detail": str(exc)}),
            )
        else:
            response = server.handle_message(message)
        if response is not None:
            stdout.write(canonical_json(response) + "\n")
            stdout.flush()
    return 0


def default_client_factory(base_url: str, token: str) -> Any:
    """Lazily import the HTTP client so the MCP module remains independently testable."""

    from .api_client import FabricClient

    return FabricClient(base_url, token)


def _workspace_from(args_workspace: str | None, env: Mapping[str, str]) -> Path:
    raw = (
        args_workspace
        or env.get("AIDEVOBSERVER_WORKSPACE")
        or env.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    )
    return Path(raw).expanduser().resolve()


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[[str, str], Any] | None = None,
) -> int:
    environment = os.environ if env is None else env
    parser = argparse.ArgumentParser(description="AIDevObserver MCP JSONL stdio server")
    parser.add_argument(
        "--base-url",
        default=environment.get("AIDEVOBSERVER_URL", DEFAULT_BASE_URL),
        help="Capability Fabric API base URL (default: AIDEVOBSERVER_URL or %(default)s)",
    )
    parser.add_argument("--workspace-root", default=None, help="bounded root for materialized primitive files")
    args = parser.parse_args(argv)
    err = sys.stderr if stderr is None else stderr
    token = environment.get("AIDEVOBSERVER_TOKEN", "")
    if not token and env is None:
        try:
            from .credentials import load_token

            token = load_token(args.base_url) or ""
        except ValueError as exc:
            err.write(f"could not read stored credential: {exc}\n")
            err.flush()
            return 2
    if not token:
        err.write(
            "No AIDevObserver credential. Run "
            f"aidevobserver-fabric auth login --server {args.base_url}\n"
        )
        err.flush()
        return 2
    workspace = _workspace_from(args.workspace_root, environment)
    factory = client_factory or default_client_factory
    try:
        client = factory(args.base_url, token)
    except Exception as exc:
        message = str(_redact(f"{type(exc).__name__}: {exc}", (token,)))
        err.write(f"could not initialize Fabric client: {message}\n")
        err.flush()
        return 2
    server = McpServer(client, workspace, secrets=(token,))
    return serve_jsonl(server, sys.stdin if stdin is None else stdin, sys.stdout if stdout is None else stdout)


if __name__ == "__main__":
    raise SystemExit(main())
