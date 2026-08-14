from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aidevobserver_fabric import problem_ledger


FIXED_TIME = "2026-07-11T12:00:00Z"


class ProblemLedgerTests(unittest.TestCase):
    def open_ledger(self, root: Path) -> sqlite3.Connection:
        return problem_ledger.connect_ledger(root / "problem_loop.sqlite")

    def test_migration_is_idempotent_and_uses_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = self.open_ledger(root)
            try:
                problem_ledger.migrate_ledger(con)
                problem_ledger.migrate_ledger(con)
                version = con.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()[0]
                self.assertEqual(version, str(problem_ledger.SCHEMA_VERSION))
                self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                tables = {
                    row[0]
                    for row in con.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertTrue(
                    {
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
                    }.issubset(tables)
                )
            finally:
                con.close()

    def test_digest_helpers_and_cas_are_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            value = b"exact\x00source\nbytes"
            first = problem_ledger.put_cas_bytes(root / "cas", value)
            second = problem_ledger.put_cas_bytes(root / "cas", value)
            self.assertEqual(first, second)
            self.assertEqual(first.digest, problem_ledger.digest_bytes(value))
            path = root / "cas" / first.relative_path
            self.assertEqual(path.read_bytes(), value)
            self.assertEqual(problem_ledger.digest_file(path), first.digest)
            self.assertEqual(list(path.parent.glob(".cas-*.tmp")), [])
            with self.assertRaises(TypeError):
                problem_ledger.put_cas_bytes(root / "cas", "not bytes")  # type: ignore[arg-type]

    def test_run_lifecycle_and_events_are_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            con = self.open_ledger(Path(tmp))
            try:
                started = problem_ledger.start_run(
                    con,
                    {"sources": ["hn.ask"]},
                    run_id="run:test",
                    started_at=FIXED_TIME,
                )
                self.assertEqual(started["status"], "running")
                self.assertFalse(started["serves_truth"])
                first = problem_ledger.append_event(
                    con,
                    run_id="run:test",
                    stage="normalize",
                    entity_type="source",
                    entity_id="hn.ask",
                    status="complete",
                    input_digest=problem_ledger.digest_json({"input": 1}),
                    output_digest=problem_ledger.digest_json({"output": 1}),
                    observed_at=FIXED_TIME,
                )
                duplicate = problem_ledger.append_event(
                    con,
                    run_id="run:test",
                    stage="normalize",
                    entity_type="source",
                    entity_id="hn.ask",
                    status="complete",
                    input_digest=problem_ledger.digest_json({"input": 1}),
                    output_digest=problem_ledger.digest_json({"output": 1}),
                    observed_at="2026-07-11T12:01:00Z",
                )
                self.assertTrue(first["inserted"])
                self.assertFalse(duplicate["inserted"])
                self.assertEqual(first["event_id"], duplicate["event_id"])
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute(
                        "UPDATE loop_events SET status = 'changed' WHERE event_id = ?",
                        (first["event_id"],),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute(
                        "DELETE FROM loop_events WHERE event_id = ?", (first["event_id"],)
                    )

                finished = problem_ledger.finish_run(
                    con,
                    "run:test",
                    "partial",
                    counts={"sources_succeeded": 1, "sources_failed": 1},
                    finished_at="2026-07-11T12:02:00Z",
                )
                self.assertEqual(finished["status"], "partial")
                row = con.execute(
                    "SELECT status, counts_json FROM loop_runs WHERE run_id = 'run:test'"
                ).fetchone()
                self.assertEqual(row["status"], "partial")
                self.assertEqual(json.loads(row["counts_json"])["sources_failed"], 1)
                with self.assertRaises(ValueError):
                    problem_ledger.finish_run(con, "run:test", "complete")
            finally:
                con.close()

    def test_record_source_batch_commits_artifacts_observations_cursor_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = self.open_ledger(root)
            try:
                problem_ledger.start_run(con, {}, run_id="run:batch", started_at=FIXED_TIME)
                items = [
                    {
                        "source_item_id": "ask-1",
                        "canonical_url": "https://example.test/questions/1",
                        "content": b'{"title":"manual reconciliation takes hours"}',
                        "media_type": "application/json",
                        "published_at": "2026-07-10T10:00:00Z",
                        "metadata": {"score": 7},
                    },
                    {
                        "source_item_id": "ask-2",
                        "canonical_url": "https://example.test/questions/2",
                        "content": b'{"title":"copy paste between systems"}',
                        "media_type": "application/json",
                    },
                ]
                receipt = problem_ledger.record_source_batch(
                    con,
                    root / "cas",
                    run_id="run:batch",
                    source_id="hn.ask",
                    observations=items,
                    cursor={"after": 2},
                    etag='"etag-2"',
                    next_due_at="2026-07-12T12:00:00Z",
                    fetched_at=FIXED_TIME,
                )
                self.assertEqual(receipt["received_count"], 2)
                self.assertEqual(receipt["new_observation_count"], 2)
                self.assertEqual(receipt["duplicate_observation_count"], 0)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], 2)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)
                state = con.execute(
                    "SELECT * FROM source_states WHERE source_id = 'hn.ask'"
                ).fetchone()
                self.assertEqual(json.loads(state["cursor_json"]), {"after": 2})
                self.assertEqual(state["etag"], '"etag-2"')
                self.assertEqual(state["consecutive_failures"], 0)
                event = con.execute(
                    "SELECT * FROM loop_events WHERE event_id = ?", (receipt["event_id"],)
                ).fetchone()
                self.assertEqual(event["status"], "complete")
                self.assertEqual(json.loads(event["metrics_json"])["new_observations"], 2)

                repeated = problem_ledger.record_source_batch(
                    con,
                    root / "cas",
                    run_id="run:batch",
                    source_id="hn.ask",
                    observations=items,
                    cursor={"after": 2},
                    etag='"etag-2"',
                    next_due_at="2026-07-12T12:00:00Z",
                    fetched_at="2026-07-11T12:05:00Z",
                )
                self.assertEqual(repeated["new_observation_count"], 0)
                self.assertEqual(repeated["duplicate_observation_count"], 2)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)
                self.assertEqual(receipt["event_id"], repeated["event_id"])
            finally:
                con.close()

    def test_invalid_batch_does_not_advance_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = self.open_ledger(root)
            try:
                problem_ledger.start_run(con, {}, run_id="run:atomic", started_at=FIXED_TIME)
                problem_ledger.record_source_batch(
                    con,
                    root / "cas",
                    run_id="run:atomic",
                    source_id="feed.one",
                    observations=[],
                    cursor={"page": 1},
                    fetched_at=FIXED_TIME,
                )
                with self.assertRaises(TypeError):
                    problem_ledger.record_source_batch(
                        con,
                        root / "cas",
                        run_id="run:atomic",
                        source_id="feed.one",
                        observations=[{"source_item_id": "bad", "content": "not exact bytes"}],
                        cursor={"page": 2},
                    )
                state = con.execute(
                    "SELECT cursor_json FROM source_states WHERE source_id = 'feed.one'"
                ).fetchone()
                self.assertEqual(json.loads(state["cursor_json"]), {"page": 1})
            finally:
                con.close()

    def test_failures_set_cooldown_and_success_resets_failure_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = self.open_ledger(root)
            try:
                problem_ledger.start_run(con, {}, run_id="run:failure", started_at=FIXED_TIME)
                failure = problem_ledger.record_source_failure(
                    con,
                    run_id="run:failure",
                    source_id="api.vendor",
                    error_class="TimeoutError",
                    error_message="upstream timed out after 10 seconds",
                    retryable=True,
                    cooldown_seconds=600,
                    attempt=2,
                    observed_at=FIXED_TIME,
                )
                self.assertEqual(failure["status"], "retryable_failure")
                self.assertEqual(failure["next_due_at"], "2026-07-11T12:10:00Z")
                self.assertNotIn("timed out", json.dumps(failure))
                state = con.execute(
                    "SELECT * FROM source_states WHERE source_id = 'api.vendor'"
                ).fetchone()
                self.assertEqual(state["consecutive_failures"], 1)
                self.assertEqual(state["last_error_class"], "TimeoutError")
                self.assertFalse(
                    problem_ledger.claim_due_source(
                        con,
                        source_id="api.vendor",
                        run_id="run:failure",
                        now="2026-07-11T12:05:00Z",
                    )
                )
                self.assertTrue(
                    problem_ledger.claim_due_source(
                        con,
                        source_id="api.vendor",
                        run_id="run:failure",
                        now="2026-07-11T12:11:00Z",
                    )
                )
                problem_ledger.record_source_batch(
                    con,
                    root / "cas",
                    run_id="run:failure",
                    source_id="api.vendor",
                    observations=[],
                    cursor={"next": None},
                    next_due_at="2026-07-12T12:00:00Z",
                    fetched_at="2026-07-11T12:12:00Z",
                )
                reset = con.execute(
                    "SELECT * FROM source_states WHERE source_id = 'api.vendor'"
                ).fetchone()
                self.assertEqual(reset["consecutive_failures"], 0)
                self.assertIsNone(reset["last_error_class"])
                self.assertIsNone(reset["lease_owner"])
            finally:
                con.close()

    def test_expired_lease_can_be_reclaimed_but_active_lease_cannot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            con = self.open_ledger(Path(tmp))
            try:
                problem_ledger.start_run(con, {}, run_id="run:lease-a", started_at=FIXED_TIME)
                problem_ledger.start_run(con, {}, run_id="run:lease-b", started_at=FIXED_TIME)
                self.assertTrue(
                    problem_ledger.claim_due_source(
                        con,
                        source_id="feed.lease",
                        run_id="run:lease-a",
                        lease_seconds=60,
                        now=FIXED_TIME,
                    )
                )
                self.assertFalse(
                    problem_ledger.claim_due_source(
                        con,
                        source_id="feed.lease",
                        run_id="run:lease-b",
                        now="2026-07-11T12:00:30Z",
                    )
                )
                self.assertTrue(
                    problem_ledger.claim_due_source(
                        con,
                        source_id="feed.lease",
                        run_id="run:lease-b",
                        now="2026-07-11T12:01:01Z",
                    )
                )
                owner = con.execute(
                    "SELECT lease_owner FROM source_states WHERE source_id = 'feed.lease'"
                ).fetchone()[0]
                self.assertEqual(owner, "run:lease-b")
            finally:
                con.close()

    def test_terminal_source_failure_blocks_claim_until_a_successful_reconfiguration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            con = self.open_ledger(Path(tmp))
            try:
                problem_ledger.start_run(con, {}, run_id="run:terminal", started_at=FIXED_TIME)
                problem_ledger.record_source_failure(
                    con,
                    run_id="run:terminal",
                    source_id="feed.unsupported",
                    error_class="UnsupportedFormat",
                    error_message="no adapter for this representation",
                    retryable=False,
                    observed_at=FIXED_TIME,
                )
                state = con.execute(
                    "SELECT * FROM source_states WHERE source_id = 'feed.unsupported'"
                ).fetchone()
                self.assertEqual(state["terminal_failure"], 1)
                self.assertIsNone(state["next_due_at"])
                self.assertFalse(
                    problem_ledger.claim_due_source(
                        con,
                        source_id="feed.unsupported",
                        run_id="run:terminal",
                        now="2027-07-11T12:00:00Z",
                    )
                )
            finally:
                con.close()

    def test_status_snapshot_reports_partial_operational_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            con = self.open_ledger(Path(tmp))
            try:
                problem_ledger.start_run(con, {}, run_id="run:status", started_at=FIXED_TIME)
                problem_ledger.record_source_failure(
                    con,
                    run_id="run:status",
                    source_id="feed.status",
                    error_class="RateLimit",
                    error_message="retry later",
                    retryable=True,
                    cooldown_seconds=3600,
                    observed_at=FIXED_TIME,
                )
                snapshot = problem_ledger.status_snapshot(
                    con, now="2026-07-11T12:10:00Z"
                )
                self.assertEqual(snapshot["run_status_counts"]["running"], 1)
                self.assertEqual(snapshot["sources"]["in_cooldown"], 1)
                self.assertEqual(snapshot["sources"]["with_failures"], 1)
                self.assertFalse(snapshot["serves_truth"])
            finally:
                con.close()

    def test_reconciliation_reports_missing_corrupt_and_orphan_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cas_root = root / "cas"
            con = self.open_ledger(root)
            try:
                problem_ledger.start_run(con, {}, run_id="run:reconcile", started_at=FIXED_TIME)
                problem_ledger.record_source_batch(
                    con,
                    cas_root,
                    run_id="run:reconcile",
                    source_id="feed.reconcile",
                    observations=[
                        {"source_item_id": "missing", "content": b"missing later"},
                        {"source_item_id": "corrupt", "content": b"corrupt later"},
                    ],
                    cursor={"done": True},
                    fetched_at=FIXED_TIME,
                )
                rows = con.execute("SELECT * FROM artifacts ORDER BY digest").fetchall()
                missing_row, corrupt_row = rows
                (cas_root / missing_row["cas_path"]).unlink()
                (cas_root / corrupt_row["cas_path"]).write_bytes(b"changed bytes")
                orphan = problem_ledger.put_cas_bytes(cas_root, b"orphan exact bytes")

                report = problem_ledger.reconcile_ledger(con, cas_root)
                self.assertFalse(report["clean"])
                self.assertEqual(len(report["missing_artifacts"]), 1)
                self.assertEqual(len(report["corrupt_artifacts"]), 1)
                self.assertEqual(len(report["orphan_cas_objects"]), 1)
                self.assertEqual(
                    report["orphan_cas_objects"][0]["actual_digest"], orphan.digest
                )
                self.assertFalse(report["mutation_performed"])
                self.assertTrue((cas_root / orphan.relative_path).exists())
                self.assertEqual(con.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], 2)
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
