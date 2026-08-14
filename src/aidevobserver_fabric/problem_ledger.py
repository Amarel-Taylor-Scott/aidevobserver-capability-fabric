"""Durable candidate-only ledger for problem discovery and primitive building.

The ledger is deliberately separate from :mod:`registry`, whose SQLite database
is a rebuildable search projection.  This module owns durable run history,
source cursors, immutable source artifacts, observations, problem candidates,
and claim-scoped execution receipts.

Web observations and every object derived from them remain candidate evidence.
Nothing in this module promotes an artifact or sets ``serves_truth``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


SCHEMA_VERSION = 1
RUN_STATUSES = frozenset({"running", "complete", "partial", "failed"})
TERMINAL_RUN_STATUSES = RUN_STATUSES - {"running"}


def stable_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for identifiers and receipts."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    """Return the exact-byte SHA-256 digest used throughout the ledger."""

    if not isinstance(value, bytes):
        raise TypeError("digest_bytes requires bytes")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    """Digest a deterministic JSON projection."""

    return digest_bytes(stable_json_bytes(value))


def digest_file(path: Path) -> str:
    """Stream an exact-byte SHA-256 digest from *path*."""

    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def stable_id(prefix: str, value: Any, *, length: int = 32) -> str:
    """Create a compact, repeatable identifier from deterministic JSON."""

    hexdigest = digest_json(value).removeprefix("sha256:")
    return f"{prefix}:{hexdigest[:length]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _plus_seconds(value: str, seconds: float) -> str:
    result = _parse_timestamp(value) + timedelta(seconds=max(0.0, seconds))
    return result.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class CasObject:
    digest: str
    byte_size: int
    relative_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cas_relative_path(digest: str) -> Path:
    algorithm, separator, hexdigest = digest.partition(":")
    if separator != ":" or algorithm != "sha256" or len(hexdigest) != 64:
        raise ValueError(f"unsupported content digest: {digest}")
    return Path(algorithm) / hexdigest[:2] / f"{hexdigest}.blob"


def put_cas_bytes(cas_root: Path, value: bytes) -> CasObject:
    """Atomically store exact bytes in a SHA-256 content-addressed directory.

    The temporary file is created in the destination directory, flushed and
    fsynced, then atomically renamed.  Existing objects are read-verified before
    reuse.  Database registration is separate so a process crash can leave an
    orphan object; :func:`reconcile_ledger` reports such objects without deleting
    them.
    """

    if not isinstance(value, bytes):
        raise TypeError("CAS content must be bytes")
    digest = digest_bytes(value)
    relative_path = _cas_relative_path(digest)
    target = cas_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        if target.stat().st_size != len(value) or digest_file(target) != digest:
            raise RuntimeError(f"CAS digest collision or corrupt object at {target}")
        return CasObject(digest=digest, byte_size=len(value), relative_path=relative_path.as_posix())

    descriptor, temporary_name = tempfile.mkstemp(prefix=".cas-", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as fh:
            fh.write(value)
            fh.flush()
            os.fsync(fh.fileno())
        if digest_file(temporary) != digest:
            raise RuntimeError("CAS write failed exact-byte digest verification")
        try:
            os.replace(temporary, target)
        except OSError:
            # A concurrent writer may have installed the same immutable object.
            if not target.exists() or digest_file(target) != digest:
                raise
        try:
            directory_descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            # Some filesystems do not support directory fsync. The file itself
            # was fsynced and its digest was verified above.
            pass
    finally:
        temporary.unlink(missing_ok=True)

    if target.stat().st_size != len(value) or digest_file(target) != digest:
        raise RuntimeError(f"CAS read-back verification failed at {target}")
    return CasObject(digest=digest, byte_size=len(value), relative_path=relative_path.as_posix())


def connect_ledger(path: Path | str) -> sqlite3.Connection:
    """Open a configured ledger connection and apply idempotent migrations."""

    path_string = str(path)
    if path_string != ":memory:":
        Path(path_string).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path_string, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    if path_string != ":memory:":
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = FULL")
    migrate_ledger(con)
    return con


def migrate_ledger(con: sqlite3.Connection) -> None:
    """Create or validate the version-one schema without destroying data."""

    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS loop_runs (
          run_id TEXT PRIMARY KEY,
          parent_run_id TEXT REFERENCES loop_runs(run_id),
          config_digest TEXT NOT NULL,
          code_digest TEXT,
          status TEXT NOT NULL CHECK(status IN ('running', 'complete', 'partial', 'failed')),
          started_at TEXT NOT NULL,
          finished_at TEXT,
          counts_json TEXT NOT NULL DEFAULT '{}',
          aggregate_receipt_digest TEXT
        );

        CREATE TABLE IF NOT EXISTS loop_events (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          event_id TEXT NOT NULL UNIQUE,
          run_id TEXT NOT NULL REFERENCES loop_runs(run_id),
          stage TEXT NOT NULL,
          entity_type TEXT NOT NULL,
          entity_id TEXT NOT NULL,
          attempt INTEGER NOT NULL CHECK(attempt >= 1),
          status TEXT NOT NULL,
          input_digest TEXT,
          output_digest TEXT,
          error_class TEXT,
          error_digest TEXT,
          metrics_json TEXT NOT NULL DEFAULT '{}',
          observed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS source_states (
          source_id TEXT PRIMARY KEY,
          cursor_json TEXT NOT NULL DEFAULT '{}',
          etag TEXT,
          last_modified TEXT,
          next_due_at TEXT,
          lease_owner TEXT,
          lease_expires_at TEXT,
          consecutive_failures INTEGER NOT NULL DEFAULT 0,
          terminal_failure INTEGER NOT NULL DEFAULT 0,
          last_success_run_id TEXT REFERENCES loop_runs(run_id),
          last_failure_run_id TEXT REFERENCES loop_runs(run_id),
          last_error_class TEXT,
          last_error_digest TEXT,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS artifacts (
          digest TEXT PRIMARY KEY,
          hash_algorithm TEXT NOT NULL CHECK(hash_algorithm = 'sha256'),
          byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
          media_type TEXT NOT NULL,
          cas_path TEXT NOT NULL UNIQUE,
          acquired_at TEXT NOT NULL,
          source_ref TEXT,
          retention_class TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS observations (
          observation_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES loop_runs(run_id),
          source_id TEXT NOT NULL,
          source_item_id TEXT NOT NULL,
          canonical_url TEXT,
          artifact_digest TEXT NOT NULL REFERENCES artifacts(digest),
          content_digest TEXT NOT NULL,
          published_at TEXT,
          fetched_at TEXT NOT NULL,
          lifecycle TEXT NOT NULL DEFAULT 'candidate'
            CHECK(lifecycle IN ('candidate', 'rejected', 'revoked')),
          metadata_json TEXT NOT NULL DEFAULT '{}',
          UNIQUE(source_id, source_item_id, content_digest)
        );

        CREATE TABLE IF NOT EXISTS problem_signals (
          signal_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES loop_runs(run_id),
          observation_id TEXT NOT NULL REFERENCES observations(observation_id),
          extractor_id TEXT NOT NULL,
          extractor_digest TEXT NOT NULL,
          friction_type TEXT NOT NULL,
          actor TEXT,
          task TEXT,
          trigger_text TEXT,
          workaround TEXT,
          desired_outcome TEXT,
          impact_json TEXT NOT NULL DEFAULT '{}',
          uncertainty_json TEXT NOT NULL DEFAULT '{}',
          supporting_span_digest TEXT,
          lifecycle TEXT NOT NULL DEFAULT 'candidate'
            CHECK(lifecycle IN ('candidate', 'rejected', 'revoked')),
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS problem_clusters (
          cluster_id TEXT PRIMARY KEY,
          created_run_id TEXT NOT NULL REFERENCES loop_runs(run_id),
          fingerprint TEXT NOT NULL UNIQUE,
          canonical_statement TEXT NOT NULL,
          score_vector_json TEXT NOT NULL DEFAULT '{}',
          score_profile_digest TEXT,
          lifecycle TEXT NOT NULL DEFAULT 'candidate'
            CHECK(lifecycle IN ('candidate', 'rejected', 'revoked')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cluster_members (
          cluster_id TEXT NOT NULL REFERENCES problem_clusters(cluster_id),
          signal_id TEXT NOT NULL REFERENCES problem_signals(signal_id),
          relation TEXT NOT NULL,
          confidence REAL,
          PRIMARY KEY(cluster_id, signal_id)
        );

        CREATE TABLE IF NOT EXISTS coverage_decisions (
          decision_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES loop_runs(run_id),
          cluster_id TEXT NOT NULL REFERENCES problem_clusters(cluster_id),
          registry_snapshot_digest TEXT NOT NULL,
          outcome TEXT NOT NULL CHECK(outcome IN ('exact', 'adaptable', 'gap', 'unknown')),
          capability_refs_json TEXT NOT NULL DEFAULT '[]',
          explanation_digest TEXT,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS primitive_drafts (
          draft_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES loop_runs(run_id),
          cluster_id TEXT NOT NULL REFERENCES problem_clusters(cluster_id),
          capability_id TEXT NOT NULL,
          implementation_id TEXT NOT NULL,
          manifest_digest TEXT NOT NULL,
          workspace_digest TEXT,
          builder_digest TEXT,
          lifecycle TEXT NOT NULL DEFAULT 'candidate'
            CHECK(lifecycle IN ('candidate', 'rejected', 'revoked')),
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS execution_receipts (
          receipt_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES loop_runs(run_id),
          draft_id TEXT NOT NULL REFERENCES primitive_drafts(draft_id),
          claim_type TEXT NOT NULL,
          artifact_digest TEXT NOT NULL,
          contract_digest TEXT,
          environment_digest TEXT NOT NULL,
          workload_digest TEXT,
          fixture_digest TEXT,
          result TEXT NOT NULL CHECK(result IN ('pass', 'fail', 'inconclusive', 'not_run')),
          raw_result_digest TEXT,
          started_at TEXT NOT NULL,
          finished_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_loop_events_run_stage
          ON loop_events(run_id, stage, sequence);
        CREATE INDEX IF NOT EXISTS idx_source_states_due
          ON source_states(next_due_at);
        CREATE INDEX IF NOT EXISTS idx_observations_source
          ON observations(source_id, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_signals_observation
          ON problem_signals(observation_id);
        CREATE INDEX IF NOT EXISTS idx_cluster_members_signal
          ON cluster_members(signal_id);

        CREATE TRIGGER IF NOT EXISTS loop_events_no_update
        BEFORE UPDATE ON loop_events
        BEGIN
          SELECT RAISE(ABORT, 'loop_events are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS loop_events_no_delete
        BEFORE DELETE ON loop_events
        BEGIN
          SELECT RAISE(ABORT, 'loop_events are append-only');
        END;
        """
    )
    current = con.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    if current is not None and int(current["value"]) > SCHEMA_VERSION:
        raise RuntimeError(
            f"ledger schema {current['value']} is newer than supported version {SCHEMA_VERSION}"
        )
    con.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )


@contextmanager
def _transaction(con: sqlite3.Connection) -> Iterator[None]:
    if con.in_transaction:
        yield
        return
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        con.rollback()
        raise
    else:
        con.commit()


def _require_running_run(con: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = con.execute("SELECT * FROM loop_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"unknown loop run: {run_id}")
    if row["status"] != "running":
        raise ValueError(f"loop run {run_id} is not running: {row['status']}")
    return row


def _append_event_row(
    con: sqlite3.Connection,
    *,
    run_id: str,
    stage: str,
    entity_type: str,
    entity_id: str,
    status: str,
    attempt: int = 1,
    input_digest: str | None = None,
    output_digest: str | None = None,
    error_class: str | None = None,
    error_digest: str | None = None,
    metrics: Mapping[str, Any] | None = None,
    observed_at: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    timestamp = observed_at or utc_now()
    material = {
        "run_id": run_id,
        "stage": stage,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "attempt": attempt,
        "status": status,
        "input_digest": input_digest,
        "output_digest": output_digest,
        "error_class": error_class,
        "error_digest": error_digest,
    }
    resolved_event_id = event_id or stable_id("event", material)
    cursor = con.execute(
        """
        INSERT OR IGNORE INTO loop_events(
          event_id, run_id, stage, entity_type, entity_id, attempt, status,
          input_digest, output_digest, error_class, error_digest, metrics_json,
          observed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_event_id,
            run_id,
            stage,
            entity_type,
            entity_id,
            attempt,
            status,
            input_digest,
            output_digest,
            error_class,
            error_digest,
            stable_json_bytes(dict(metrics or {})).decode("utf-8"),
            timestamp,
        ),
    )
    return {"event_id": resolved_event_id, "inserted": cursor.rowcount == 1}


def append_event(con: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]:
    """Append an idempotent event; existing events are never updated."""

    with _transaction(con):
        return _append_event_row(con, **kwargs)


def start_run(
    con: sqlite3.Connection,
    config: Mapping[str, Any] | str,
    *,
    code_digest: str | None = None,
    parent_run_id: str | None = None,
    run_id: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    """Start one independent loop attempt and append its first event."""

    timestamp = started_at or utc_now()
    config_digest = config if isinstance(config, str) and config.startswith("sha256:") else digest_json(config)
    resolved_run_id = run_id or f"run:{uuid.uuid4()}"
    with _transaction(con):
        con.execute(
            """
            INSERT INTO loop_runs(
              run_id, parent_run_id, config_digest, code_digest, status,
              started_at, counts_json
            ) VALUES (?, ?, ?, ?, 'running', ?, '{}')
            """,
            (resolved_run_id, parent_run_id, config_digest, code_digest, timestamp),
        )
        _append_event_row(
            con,
            run_id=resolved_run_id,
            stage="run",
            entity_type="loop_run",
            entity_id=resolved_run_id,
            status="started",
            input_digest=config_digest,
            observed_at=timestamp,
        )
    return {
        "run_id": resolved_run_id,
        "config_digest": config_digest,
        "code_digest": code_digest,
        "status": "running",
        "started_at": timestamp,
        "candidate_only": True,
        "serves_truth": False,
    }


def finish_run(
    con: sqlite3.Connection,
    run_id: str,
    status: str,
    *,
    counts: Mapping[str, Any] | None = None,
    aggregate_receipt_digest: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    """Finish a run truthfully as complete, partial, or failed."""

    if status not in TERMINAL_RUN_STATUSES:
        raise ValueError(f"terminal status must be one of {sorted(TERMINAL_RUN_STATUSES)}")
    timestamp = finished_at or utc_now()
    normalized_counts = dict(counts or {})
    receipt_digest = aggregate_receipt_digest or digest_json(
        {
            "run_id": run_id,
            "status": status,
            "counts": normalized_counts,
            "finished_at": timestamp,
        }
    )
    with _transaction(con):
        _require_running_run(con, run_id)
        con.execute(
            """
            UPDATE loop_runs
            SET status = ?, finished_at = ?, counts_json = ?, aggregate_receipt_digest = ?
            WHERE run_id = ?
            """,
            (
                status,
                timestamp,
                stable_json_bytes(normalized_counts).decode("utf-8"),
                receipt_digest,
                run_id,
            ),
        )
        _append_event_row(
            con,
            run_id=run_id,
            stage="run",
            entity_type="loop_run",
            entity_id=run_id,
            status=status,
            output_digest=receipt_digest,
            metrics=normalized_counts,
            observed_at=timestamp,
        )
    return {
        "run_id": run_id,
        "status": status,
        "finished_at": timestamp,
        "counts": normalized_counts,
        "aggregate_receipt_digest": receipt_digest,
        "candidate_only": True,
        "serves_truth": False,
    }


def _normalize_observation_input(item: Mapping[str, Any]) -> dict[str, Any]:
    source_item_id = str(item.get("source_item_id") or "").strip()
    if not source_item_id:
        raise ValueError("source observation requires source_item_id")
    content = item.get("content")
    if not isinstance(content, bytes):
        raise TypeError("source observation content must be exact bytes")
    metadata = item.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        raise TypeError("source observation metadata must be a mapping")
    return {
        "source_item_id": source_item_id,
        "canonical_url": str(item["canonical_url"]) if item.get("canonical_url") else None,
        "content": content,
        "media_type": str(item.get("media_type") or "application/octet-stream"),
        "published_at": str(item["published_at"]) if item.get("published_at") else None,
        "metadata": dict(metadata),
        "retention_class": str(item.get("retention_class") or "candidate_evidence"),
    }


def record_source_batch(
    con: sqlite3.Connection,
    cas_root: Path,
    *,
    run_id: str,
    source_id: str,
    observations: Iterable[Mapping[str, Any]],
    cursor: Mapping[str, Any] | None,
    etag: str | None = None,
    last_modified: str | None = None,
    next_due_at: str | None = None,
    fetched_at: str | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    """Persist a normalized source batch and advance its cursor atomically.

    CAS objects are installed before the database transaction.  The artifact
    registrations, observations, source cursor, and success event then commit in
    one transaction.  A crash between those phases can only leave an immutable
    orphan CAS object, which reconciliation reports.
    """

    normalized = tuple(_normalize_observation_input(item) for item in observations)
    timestamp = fetched_at or utc_now()
    staged: list[tuple[dict[str, Any], CasObject, str]] = []
    for item in normalized:
        cas_object = put_cas_bytes(cas_root, item["content"])
        observation_id = stable_id(
            "obs",
            {
                "source_id": source_id,
                "source_item_id": item["source_item_id"],
                "canonical_url": item["canonical_url"],
                "content_digest": cas_object.digest,
            },
        )
        staged.append((item, cas_object, observation_id))

    input_digest = digest_json(
        {
            "source_id": source_id,
            "cursor": dict(cursor or {}),
            "items": [
                {
                    "source_item_id": item["source_item_id"],
                    "canonical_url": item["canonical_url"],
                    "content_digest": cas_object.digest,
                }
                for item, cas_object, _ in staged
            ],
        }
    )
    output_material = {
        "source_id": source_id,
        "cursor": dict(cursor or {}),
        "observation_ids": [observation_id for _, _, observation_id in staged],
        "artifact_digests": [cas_object.digest for _, cas_object, _ in staged],
    }
    output_digest = digest_json(output_material)
    new_count = 0
    duplicate_count = 0

    with _transaction(con):
        _require_running_run(con, run_id)
        for item, cas_object, observation_id in staged:
            con.execute(
                """
                INSERT OR IGNORE INTO artifacts(
                  digest, hash_algorithm, byte_size, media_type, cas_path,
                  acquired_at, source_ref, retention_class
                ) VALUES (?, 'sha256', ?, ?, ?, ?, ?, ?)
                """,
                (
                    cas_object.digest,
                    cas_object.byte_size,
                    item["media_type"],
                    cas_object.relative_path,
                    timestamp,
                    f"source:{source_id}:{item['source_item_id']}",
                    item["retention_class"],
                ),
            )
            inserted = con.execute(
                """
                INSERT OR IGNORE INTO observations(
                  observation_id, run_id, source_id, source_item_id,
                  canonical_url, artifact_digest, content_digest, published_at,
                  fetched_at, lifecycle, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?)
                """,
                (
                    observation_id,
                    run_id,
                    source_id,
                    item["source_item_id"],
                    item["canonical_url"],
                    cas_object.digest,
                    cas_object.digest,
                    item["published_at"],
                    timestamp,
                    stable_json_bytes(item["metadata"]).decode("utf-8"),
                ),
            ).rowcount
            if inserted == 1:
                new_count += 1
            else:
                duplicate_count += 1

        con.execute(
            """
            INSERT INTO source_states(
              source_id, cursor_json, etag, last_modified, next_due_at,
              consecutive_failures, last_success_run_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
              cursor_json = excluded.cursor_json,
              etag = excluded.etag,
              last_modified = excluded.last_modified,
              next_due_at = excluded.next_due_at,
              lease_owner = NULL,
              lease_expires_at = NULL,
              consecutive_failures = 0,
              terminal_failure = 0,
              last_success_run_id = excluded.last_success_run_id,
              last_error_class = NULL,
              last_error_digest = NULL,
              updated_at = excluded.updated_at
            """,
            (
                source_id,
                stable_json_bytes(dict(cursor or {})).decode("utf-8"),
                etag,
                last_modified,
                next_due_at,
                run_id,
                timestamp,
            ),
        )
        event = _append_event_row(
            con,
            run_id=run_id,
            stage="source_fetch",
            entity_type="source",
            entity_id=source_id,
            status="complete",
            attempt=attempt,
            input_digest=input_digest,
            output_digest=output_digest,
            metrics={
                "received": len(staged),
                "new_observations": new_count,
                "duplicate_observations": duplicate_count,
            },
            observed_at=timestamp,
        )

    return {
        "run_id": run_id,
        "source_id": source_id,
        "received_count": len(staged),
        "new_observation_count": new_count,
        "duplicate_observation_count": duplicate_count,
        "artifact_count": len({cas_object.digest for _, cas_object, _ in staged}),
        "cursor_digest": digest_json(dict(cursor or {})),
        "input_digest": input_digest,
        "output_digest": output_digest,
        "event_id": event["event_id"],
        "candidate_only": True,
        "serves_truth": False,
    }


def record_source_failure(
    con: sqlite3.Connection,
    *,
    run_id: str,
    source_id: str,
    error_class: str,
    error_message: str,
    retryable: bool,
    cooldown_seconds: float = 300.0,
    attempt: int = 1,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Record a source attempt failure without recording it as an execution."""

    timestamp = observed_at or utc_now()
    error_digest = digest_bytes(error_message.encode("utf-8"))
    next_due_at = _plus_seconds(timestamp, cooldown_seconds) if retryable else None
    terminal_failure = 0 if retryable else 1
    status = "retryable_failure" if retryable else "terminal_failure"
    with _transaction(con):
        _require_running_run(con, run_id)
        con.execute(
            """
            INSERT INTO source_states(
              source_id, cursor_json, next_due_at, consecutive_failures, terminal_failure,
              last_failure_run_id, last_error_class, last_error_digest, updated_at
            ) VALUES (?, '{}', ?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
              next_due_at = excluded.next_due_at,
              lease_owner = NULL,
              lease_expires_at = NULL,
              consecutive_failures = source_states.consecutive_failures + 1,
              terminal_failure = excluded.terminal_failure,
              last_failure_run_id = excluded.last_failure_run_id,
              last_error_class = excluded.last_error_class,
              last_error_digest = excluded.last_error_digest,
              updated_at = excluded.updated_at
            """,
            (
                source_id,
                next_due_at,
                terminal_failure,
                run_id,
                error_class,
                error_digest,
                timestamp,
            ),
        )
        event = _append_event_row(
            con,
            run_id=run_id,
            stage="source_fetch",
            entity_type="source",
            entity_id=source_id,
            status=status,
            attempt=attempt,
            error_class=error_class,
            error_digest=error_digest,
            metrics={"retryable": retryable, "cooldown_seconds": cooldown_seconds if retryable else None},
            observed_at=timestamp,
        )
    return {
        "run_id": run_id,
        "source_id": source_id,
        "status": status,
        "attempt": attempt,
        "error_class": error_class,
        "error_digest": error_digest,
        "next_due_at": next_due_at,
        "event_id": event["event_id"],
        "candidate_only": True,
        "serves_truth": False,
    }


def claim_due_source(
    con: sqlite3.Connection,
    *,
    source_id: str,
    run_id: str,
    lease_seconds: float = 300.0,
    now: str | None = None,
) -> bool:
    """Lease a due source to a running run, returning false when unavailable."""

    timestamp = now or utc_now()
    lease_expires_at = _plus_seconds(timestamp, lease_seconds)
    with _transaction(con):
        _require_running_run(con, run_id)
        row = con.execute("SELECT * FROM source_states WHERE source_id = ?", (source_id,)).fetchone()
        if row is not None:
            if row["terminal_failure"]:
                return False
            if row["next_due_at"] and _parse_timestamp(row["next_due_at"]) > _parse_timestamp(timestamp):
                return False
            if row["lease_owner"] and row["lease_expires_at"]:
                if _parse_timestamp(row["lease_expires_at"]) > _parse_timestamp(timestamp):
                    return False
        con.execute(
            """
            INSERT INTO source_states(source_id, cursor_json, lease_owner, lease_expires_at, updated_at)
            VALUES (?, '{}', ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
              lease_owner = excluded.lease_owner,
              lease_expires_at = excluded.lease_expires_at,
              updated_at = excluded.updated_at
            """,
            (source_id, run_id, lease_expires_at, timestamp),
        )
        _append_event_row(
            con,
            run_id=run_id,
            stage="source_lease",
            entity_type="source",
            entity_id=source_id,
            status="claimed",
            output_digest=digest_json({"source_id": source_id, "lease_expires_at": lease_expires_at}),
            observed_at=timestamp,
        )
    return True


def status_snapshot(con: sqlite3.Connection, *, now: str | None = None) -> dict[str, Any]:
    """Return a compact read-only operational snapshot."""

    timestamp = now or utc_now()
    tables = (
        "loop_runs",
        "loop_events",
        "source_states",
        "artifacts",
        "observations",
        "problem_signals",
        "problem_clusters",
        "cluster_members",
        "coverage_decisions",
        "primitive_drafts",
        "execution_receipts",
    )
    counts = {
        table: int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 - fixed names
        for table in tables
    }
    run_status_counts = {
        row["status"]: int(row["count"])
        for row in con.execute("SELECT status, COUNT(*) AS count FROM loop_runs GROUP BY status")
    }
    source_rows = con.execute("SELECT * FROM source_states").fetchall()
    now_value = _parse_timestamp(timestamp)
    cooled = sum(
        1
        for row in source_rows
        if row["next_due_at"] and _parse_timestamp(row["next_due_at"]) > now_value
    )
    leased = sum(
        1
        for row in source_rows
        if row["lease_owner"]
        and row["lease_expires_at"]
        and _parse_timestamp(row["lease_expires_at"]) > now_value
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": timestamp,
        "counts": counts,
        "run_status_counts": run_status_counts,
        "sources": {
            "total": len(source_rows),
            "in_cooldown": cooled,
            "actively_leased": leased,
            "with_failures": sum(1 for row in source_rows if row["consecutive_failures"] > 0),
            "terminal_failures": sum(1 for row in source_rows if row["terminal_failure"]),
        },
        "candidate_only": True,
        "serves_truth": False,
    }


def reconcile_ledger(con: sqlite3.Connection, cas_root: Path) -> dict[str, Any]:
    """Audit DB/CAS consistency without changing or deleting either store."""

    artifact_rows = con.execute("SELECT * FROM artifacts ORDER BY digest").fetchall()
    registered_paths = {row["cas_path"]: row for row in artifact_rows}
    missing: list[dict[str, Any]] = []
    corrupt: list[dict[str, Any]] = []
    for row in artifact_rows:
        path = cas_root / row["cas_path"]
        if not path.exists():
            missing.append({"digest": row["digest"], "cas_path": row["cas_path"]})
            continue
        actual_size = path.stat().st_size
        actual_digest = digest_file(path)
        if actual_size != row["byte_size"] or actual_digest != row["digest"]:
            corrupt.append(
                {
                    "digest": row["digest"],
                    "cas_path": row["cas_path"],
                    "expected_size": row["byte_size"],
                    "actual_size": actual_size,
                    "actual_digest": actual_digest,
                }
            )

    orphan_paths: list[dict[str, Any]] = []
    cas_algorithm_root = cas_root / "sha256"
    if cas_algorithm_root.exists():
        for path in sorted(cas_algorithm_root.rglob("*.blob")):
            relative = path.relative_to(cas_root).as_posix()
            if relative not in registered_paths:
                orphan_paths.append(
                    {
                        "cas_path": relative,
                        "byte_size": path.stat().st_size,
                        "actual_digest": digest_file(path),
                    }
                )

    dangling_observations = [
        dict(row)
        for row in con.execute(
            """
            SELECT o.observation_id, o.artifact_digest
            FROM observations AS o
            LEFT JOIN artifacts AS a ON a.digest = o.artifact_digest
            WHERE a.digest IS NULL
            ORDER BY o.observation_id
            """
        )
    ]
    unreferenced_artifacts = [
        row["digest"]
        for row in con.execute(
            """
            SELECT a.digest
            FROM artifacts AS a
            LEFT JOIN observations AS o ON o.artifact_digest = a.digest
            WHERE o.observation_id IS NULL
            ORDER BY a.digest
            """
        )
    ]
    clean = not (missing or corrupt or orphan_paths or dangling_observations)
    return {
        "schema_version": SCHEMA_VERSION,
        "clean": clean,
        "registered_artifact_count": len(artifact_rows),
        "missing_artifacts": missing,
        "corrupt_artifacts": corrupt,
        "orphan_cas_objects": orphan_paths,
        "dangling_observations": dangling_observations,
        "unreferenced_artifacts": unreferenced_artifacts,
        "mutation_performed": False,
        "candidate_only": True,
        "serves_truth": False,
    }


__all__ = [
    "CasObject",
    "SCHEMA_VERSION",
    "append_event",
    "claim_due_source",
    "connect_ledger",
    "digest_bytes",
    "digest_file",
    "digest_json",
    "finish_run",
    "migrate_ledger",
    "put_cas_bytes",
    "record_source_batch",
    "record_source_failure",
    "stable_id",
    "stable_json_bytes",
    "start_run",
    "status_snapshot",
    "reconcile_ledger",
]
