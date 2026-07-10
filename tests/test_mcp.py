from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aidevobserver_fabric import mcp_server


class FakeClient:
    def __init__(self, source: str = "def reused():\n    return 42\n") -> None:
        self.source = source
        self.digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        self.calls: list[tuple] = []
        self.execute_error: Exception | None = None
        self.record_error: Exception | None = None

    def search(self, query: str, filters: dict, limit: int) -> dict:
        self.calls.append(("search", query, filters, limit))
        return {"query": query, "results": [{"primitive_id": "prim.reused.v1"}], "limit": limit}

    def get(self, primitive_id: str) -> dict:
        self.calls.append(("get", primitive_id))
        return {
            "primitive": {
                "primitive_id": primitive_id,
                "label": "reused",
                "source": self.source,
                "source_sha256": self.digest,
                "module_filename": "generated/reused.py",
            }
        }

    def execute(self, primitive_id: str, inputs: dict) -> dict:
        self.calls.append(("execute", primitive_id, inputs))
        if self.execute_error is not None:
            raise self.execute_error
        return {"primitive_id": primitive_id, "output": {"value": inputs.get("value")}}

    def prove(self, primitive_id: str) -> dict:
        self.calls.append(("prove", primitive_id))
        return {"primitive_id": primitive_id, "proof": {"status": "passed"}}

    def record_reuse(self, payload: dict) -> dict:
        self.calls.append(("record_reuse", payload))
        if self.record_error is not None:
            raise self.record_error
        return {"receipt_id": "reuse-1", "recorded": True}


def rpc(request_id: int, method: str, params: dict | None = None) -> dict:
    value = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        value["params"] = params
    return value


def initialize(server: mcp_server.McpServer) -> None:
    response = server.handle_message(
        rpc(
            900,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "unit-test", "version": "1"},
            },
        )
    )
    assert response is not None and "result" in response
    server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})


class McpServerTests(unittest.TestCase):
    def test_tool_surface_is_exact_and_schemas_are_strict(self) -> None:
        expected = [
            "search_primitives",
            "get_primitive",
            "execute_primitive",
            "materialize_primitive",
            "prove_primitive",
            "record_reuse",
        ]
        self.assertEqual([tool["name"] for tool in mcp_server.TOOLS], expected)
        for tool in mcp_server.TOOLS:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIs(tool["inputSchema"]["additionalProperties"], False)
            self.assertEqual(tool["outputSchema"]["type"], "object")
            self.assertIs(tool["outputSchema"]["additionalProperties"], False)
            self.assertIn("ok", tool["outputSchema"]["required"])
            self.assertIn("data", tool["outputSchema"]["required"])

    def test_initialize_ping_list_and_search_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            server = mcp_server.McpServer(client, tmp)
            initialized = server.handle_message(
                rpc(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
            )
            self.assertEqual(initialized["result"]["protocolVersion"], "2025-11-25")
            self.assertEqual(initialized["result"]["serverInfo"]["name"], mcp_server.SERVER_NAME)
            self.assertEqual(server.handle_message(rpc(2, "ping"))["result"], {})
            server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

            listed = server.handle_message(rpc(3, "tools/list", {}))
            self.assertEqual(len(listed["result"]["tools"]), 6)
            called = server.handle_message(
                rpc(
                    4,
                    "tools/call",
                    {
                        "name": "search_primitives",
                        "arguments": {
                            "query": "dedupe chunks",
                            "filters": {"executable_only": True},
                            "limit": 7,
                        },
                    },
                )
            )
            result = called["result"]
            self.assertFalse(result["isError"])
            self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
            self.assertEqual(result["structuredContent"]["data"]["limit"], 7)
            self.assertIn(("search", "dedupe chunks", {"executable_only": True}, 7), client.calls)

    def test_jsonl_wire_notifications_parse_errors_and_eof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = mcp_server.McpServer(FakeClient(), tmp)
            input_lines = "\n".join(
                [
                    json.dumps(rpc(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})),
                    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
                    "{not-json",
                    json.dumps(rpc(2, "ping", {})),
                ]
            ) + "\n"
            output = io.StringIO()
            self.assertEqual(mcp_server.serve_jsonl(server, io.StringIO(input_lines), output), 0)
            rows = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(len(rows), 3)  # initialized notification emits nothing
            self.assertEqual(rows[0]["id"], 1)
            self.assertEqual(rows[1]["error"]["code"], mcp_server.PARSE_ERROR)
            self.assertEqual(rows[2], {"jsonrpc": "2.0", "id": 2, "result": {}})

            empty = io.StringIO()
            self.assertEqual(mcp_server.serve_jsonl(server, io.StringIO(""), empty), 0)
            self.assertEqual(empty.getvalue(), "")

    def test_business_errors_are_tool_errors_and_token_is_redacted(self) -> None:
        token = "super-secret-api-token"
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            client.execute_error = RuntimeError(f"authorization failed for Bearer {token}")
            server = mcp_server.McpServer(client, tmp, secrets=(token,))
            initialize(server)
            response = server.handle_message(
                rpc(
                    1,
                    "tools/call",
                    {
                        "name": "execute_primitive",
                        "arguments": {"primitive_id": "prim.reused.v1", "inputs": {}},
                    },
                )
            )
            wire = json.dumps(response)
            self.assertNotIn(token, wire)
            self.assertIn("<redacted>", wire)
            self.assertTrue(response["result"]["isError"])
            self.assertFalse(response["result"]["structuredContent"]["ok"])
            self.assertEqual(
                json.loads(response["result"]["content"][0]["text"]),
                response["result"]["structuredContent"],
            )

    def test_materialize_verifies_digest_writes_atomically_and_records_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            server = mcp_server.McpServer(client, tmp)
            initialize(server)
            response = server.handle_message(
                rpc(
                    1,
                    "tools/call",
                    {
                        "name": "materialize_primitive",
                        "arguments": {"primitive_id": "prim.reused.v1"},
                    },
                )
            )
            result = response["result"]
            self.assertFalse(result["isError"])
            target = Path(tmp) / "generated" / "reused.py"
            self.assertEqual(target.read_text(encoding="utf-8"), client.source)
            first_data = result["structuredContent"]["data"]
            self.assertEqual(first_data["destination"], "generated/reused.py")
            self.assertFalse(first_data["reused_existing"])
            self.assertEqual(first_data["bytes_written"], len(client.source.encode("utf-8")))

            # A repeated install is idempotent when the existing destination
            # already has the proved source digest.  It still emits a reuse
            # receipt, but performs no write and requires no overwrite flag.
            repeated = server.handle_message(
                rpc(
                    2,
                    "tools/call",
                    {
                        "name": "materialize_primitive",
                        "arguments": {"primitive_id": "prim.reused.v1"},
                    },
                )
            )
            repeated_data = repeated["result"]["structuredContent"]["data"]
            self.assertFalse(repeated["result"]["isError"])
            self.assertTrue(repeated_data["reused_existing"])
            self.assertEqual(repeated_data["bytes_written"], 0)
            self.assertEqual(target.read_text(encoding="utf-8"), client.source)
            receipt_calls = [call for call in client.calls if call[0] == "record_reuse"]
            self.assertEqual(len(receipt_calls), 2)
            payload = receipt_calls[0][1]
            self.assertEqual(payload, {"primitive_id": "prim.reused.v1", "action": "materialized", "outcome": "used"})
            self.assertEqual(receipt_calls[1][1], payload)
            leftovers = [path for path in target.parent.iterdir() if path.name.endswith((".tmp", ".bak"))]
            self.assertEqual(leftovers, [])

    def test_materialize_rejects_traversal_absolute_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            client = FakeClient()
            server = mcp_server.McpServer(client, tmp)
            initialize(server)

            for index, destination in enumerate(("../escape.py", "/tmp/escape.py", r"C:\\escape.py"), 1):
                response = server.handle_message(
                    rpc(
                        index,
                        "tools/call",
                        {
                            "name": "materialize_primitive",
                            "arguments": {
                                "primitive_id": "prim.reused.v1",
                                "destination": destination,
                            },
                        },
                    )
                )
                self.assertTrue(response["result"]["isError"], destination)
                self.assertEqual(
                    response["result"]["structuredContent"]["error"]["code"],
                    "unsafe_destination",
                )

            link = Path(tmp) / "linked"
            try:
                link.symlink_to(Path(outside), target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            response = server.handle_message(
                rpc(
                    10,
                    "tools/call",
                    {
                        "name": "materialize_primitive",
                        "arguments": {
                            "primitive_id": "prim.reused.v1",
                            "destination": "linked/escape.py",
                        },
                    },
                )
            )
            self.assertTrue(response["result"]["isError"])
            self.assertEqual(response["result"]["structuredContent"]["error"]["code"], "symlink_escape")
            self.assertFalse((Path(outside) / "escape.py").exists())

    @unittest.skipUnless(
        mcp_server._secure_dirfd_available(),
        "secure dirfd materialization is unavailable on this platform",
    )
    def test_materialize_fails_closed_when_checked_ancestor_is_swapped_to_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            checked = root / "checked"
            checked.mkdir()
            moved = root / "checked-before-swap"
            outside_root = Path(outside)
            client = FakeClient()
            server = mcp_server.McpServer(client, root)
            initialize(server)
            original_open_parent = server._open_parent
            swapped = False

            def open_then_swap(relative: Path, *, create: bool = True) -> int:
                nonlocal swapped
                parent_fd = original_open_parent(relative, create=create)
                if not swapped:
                    checked.rename(moved)
                    try:
                        checked.symlink_to(outside_root, target_is_directory=True)
                    except (OSError, NotImplementedError):
                        os.close(parent_fd)
                        self.skipTest("symlinks unavailable")
                    swapped = True
                return parent_fd

            with mock.patch.object(server, "_open_parent", side_effect=open_then_swap):
                response = server.handle_message(
                    rpc(
                        11,
                        "tools/call",
                        {
                            "name": "materialize_primitive",
                            "arguments": {
                                "primitive_id": "prim.reused.v1",
                                "destination": "checked/nested/escape.py",
                            },
                        },
                    )
                )

            result = response["result"]
            self.assertTrue(result["isError"])
            self.assertEqual(result["structuredContent"]["error"]["code"], "symlink_escape")
            self.assertFalse((outside_root / "nested" / "escape.py").exists())
            self.assertFalse((moved / "nested" / "escape.py").exists())
            self.assertFalse(any(call[0] == "record_reuse" for call in client.calls))

    def test_materialize_fails_closed_without_secure_dirfd_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            server = mcp_server.McpServer(client, tmp)
            initialize(server)
            with mock.patch.object(mcp_server, "_secure_dirfd_available", return_value=False):
                response = server.handle_message(
                    rpc(
                        12,
                        "tools/call",
                        {
                            "name": "materialize_primitive",
                            "arguments": {
                                "primitive_id": "prim.reused.v1",
                                "destination": "generated/reused.py",
                            },
                        },
                    )
                )
            result = response["result"]
            self.assertTrue(result["isError"])
            self.assertEqual(
                result["structuredContent"]["error"]["code"],
                "secure_materialization_unavailable",
            )
            self.assertFalse((Path(tmp) / "generated" / "reused.py").exists())

    def test_materialize_rejects_bad_digest_and_requires_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            client.digest = "0" * 64
            server = mcp_server.McpServer(client, tmp)
            initialize(server)
            bad = server.handle_message(
                rpc(
                    1,
                    "tools/call",
                    {
                        "name": "materialize_primitive",
                        "arguments": {"primitive_id": "prim.reused.v1", "destination": "reused.py"},
                    },
                )
            )
            self.assertTrue(bad["result"]["isError"])
            self.assertEqual(bad["result"]["structuredContent"]["error"]["code"], "digest_mismatch")
            self.assertFalse((Path(tmp) / "reused.py").exists())

            client.digest = hashlib.sha256(client.source.encode("utf-8")).hexdigest()
            target = Path(tmp) / "reused.py"
            target.write_text("user-owned\n", encoding="utf-8")
            refused = server.handle_message(
                rpc(
                    2,
                    "tools/call",
                    {
                        "name": "materialize_primitive",
                        "arguments": {"primitive_id": "prim.reused.v1", "destination": "reused.py"},
                    },
                )
            )
            self.assertTrue(refused["result"]["isError"])
            self.assertEqual(target.read_text(encoding="utf-8"), "user-owned\n")

            replaced = server.handle_message(
                rpc(
                    3,
                    "tools/call",
                    {
                        "name": "materialize_primitive",
                        "arguments": {
                            "primitive_id": "prim.reused.v1",
                            "destination": "reused.py",
                            "overwrite": True,
                        },
                    },
                )
            )
            self.assertFalse(replaced["result"]["isError"])
            self.assertTrue(replaced["result"]["structuredContent"]["data"]["overwrote"])
            self.assertEqual(target.read_text(encoding="utf-8"), client.source)

    @unittest.skipUnless(
        mcp_server._secure_dirfd_available(),
        "secure dirfd materialization is unavailable on this platform",
    )
    def test_materialize_rolls_back_new_and_overwritten_files_when_receipt_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = FakeClient()
            client.record_error = RuntimeError("receipt unavailable")
            server = mcp_server.McpServer(client, root)
            initialize(server)

            new_file = root / "generated" / "new.py"
            failed_new = server.handle_message(
                rpc(
                    20,
                    "tools/call",
                    {
                        "name": "materialize_primitive",
                        "arguments": {
                            "primitive_id": "prim.reused.v1",
                            "destination": "generated/new.py",
                        },
                    },
                )
            )
            self.assertTrue(failed_new["result"]["isError"])
            self.assertFalse(new_file.exists())

            existing = root / "generated" / "existing.py"
            existing.write_text("user-owned\n", encoding="utf-8")
            failed_overwrite = server.handle_message(
                rpc(
                    21,
                    "tools/call",
                    {
                        "name": "materialize_primitive",
                        "arguments": {
                            "primitive_id": "prim.reused.v1",
                            "destination": "generated/existing.py",
                            "overwrite": True,
                        },
                    },
                )
            )
            self.assertTrue(failed_overwrite["result"]["isError"])
            self.assertEqual(existing.read_text(encoding="utf-8"), "user-owned\n")
            leftovers = [
                path
                for path in existing.parent.iterdir()
                if path.name.endswith((".tmp", ".bak"))
            ]
            self.assertEqual(leftovers, [])

    def test_protocol_errors_for_malformed_unknown_and_invalid_tool_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = mcp_server.McpServer(FakeClient(), tmp)
            invalid = server.handle_message({"jsonrpc": "1.0", "id": 1, "method": "ping"})
            self.assertEqual(invalid["error"]["code"], mcp_server.INVALID_REQUEST)
            unknown = server.handle_message(rpc(2, "missing/method", {}))
            self.assertEqual(unknown["error"]["code"], mcp_server.METHOD_NOT_FOUND)
            premature = server.handle_message(rpc(20, "tools/list", {}))
            self.assertEqual(premature["error"]["code"], mcp_server.INVALID_REQUEST)
            malformed_initialize = server.handle_message(rpc(21, "initialize", {}))
            self.assertEqual(malformed_initialize["error"]["code"], mcp_server.INVALID_PARAMS)
            initialize(server)
            unknown_tool = server.handle_message(
                rpc(3, "tools/call", {"name": "unknown", "arguments": {}})
            )
            self.assertEqual(unknown_tool["error"]["code"], mcp_server.INVALID_PARAMS)
            invalid_args = server.handle_message(
                rpc(
                    4,
                    "tools/call",
                    {
                        "name": "search_primitives",
                        "arguments": {"query": "x", "unexpected": True},
                    },
                )
            )
            self.assertEqual(invalid_args["error"]["code"], mcp_server.INVALID_PARAMS)
            secret_receipt = server.handle_message(
                rpc(
                    5,
                    "tools/call",
                    {
                        "name": "record_reuse",
                        "arguments": {
                            "payload": {
                                "primitive_id": "prim.reused.v1",
                                "outcome": "used",
                                "api_key": "must-not-store",
                            }
                        },
                    },
                )
            )
            self.assertEqual(secret_receipt["error"]["code"], mcp_server.INVALID_PARAMS)

    def test_main_requires_token_and_keeps_stdout_empty(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = mcp_server.main([], stdin=io.StringIO(""), stdout=stdout, stderr=stderr, env={})
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("aidevobserver-fabric auth login", stderr.getvalue())

    def test_main_uses_env_and_injected_factory_without_printing_token(self) -> None:
        token = "never-print-this-token"
        captured: list[tuple[str, str]] = []

        def factory(base_url: str, supplied_token: str) -> FakeClient:
            captured.append((base_url, supplied_token))
            return FakeClient()

        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            stderr = io.StringIO()
            code = mcp_server.main(
                [],
                stdin=io.StringIO(json.dumps(rpc(1, "ping", {})) + "\n"),
                stdout=stdout,
                stderr=stderr,
                env={
                    "AIDEVOBSERVER_TOKEN": token,
                    "AIDEVOBSERVER_URL": "http://fabric.test",
                    "AIDEVOBSERVER_WORKSPACE": tmp,
                },
                client_factory=factory,
            )
            self.assertEqual(code, 0)
            self.assertEqual(captured, [("http://fabric.test", token)])
            self.assertEqual(stderr.getvalue(), "")
            self.assertNotIn(token, stdout.getvalue())
            self.assertEqual(json.loads(stdout.getvalue()), {"jsonrpc": "2.0", "id": 1, "result": {}})


if __name__ == "__main__":
    unittest.main()
