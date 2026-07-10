"""One-command, real-stack AIDevObserver primitive-reuse demonstration.

Run with::

    python -m aidevobserver_fabric.e2e --workspace-root /path/to/project

The demo starts the actual authenticated HTTP product on an ephemeral loopback
port, creates a temporary account and scoped personal access token, connects
the real HTTP client, and drives the real MCP dispatcher.  The temporary
database is always removed.  The only durable output is the digest-verified
primitive materialized beneath the selected workspace.
"""

from __future__ import annotations

import argparse
import json
import secrets
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from .api_client import FabricClient
from .mcp_server import McpServer, PROTOCOL_VERSION
from .webapp import ALL_AGENT_SCOPES, ProductHTTPServer, create_server


DEMO_PRIMITIVE_ID = "prim.text.extract_email.v1"
DEMO_DESTINATION = ".aidevobserver/primitives/extract_email.py"
DEMO_QUERY = "extract email addresses from unstructured text"
DEMO_INPUT = {"text": "Contact alpha@example.test and beta@example.test."}


class DemoError(RuntimeError):
    """A concise, secret-free demo invariant failure."""


def _phase(phases: list[dict[str, str]], name: str) -> None:
    phases.append({"name": name, "status": "passed"})


def _request(
    server: McpServer,
    request_id: int,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    response = server.handle_message(message)
    if not isinstance(response, dict):
        raise DemoError(f"{method} returned no JSON-RPC response")
    if "error" in response:
        code = response["error"].get("code", "unknown")
        raise DemoError(f"{method} failed with JSON-RPC code {code}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise DemoError(f"{method} returned a malformed result")
    return result


def _tool_call(
    server: McpServer,
    request_id: int,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    result = _request(
        server,
        request_id,
        "tools/call",
        {"name": name, "arguments": arguments},
    )
    if result.get("isError") is not False:
        structured = result.get("structuredContent")
        code = "tool_error"
        if isinstance(structured, dict) and isinstance(structured.get("error"), dict):
            code = str(structured["error"].get("code") or code)
        raise DemoError(f"{name} failed with business code {code}")
    structured = result.get("structuredContent")
    if not isinstance(structured, dict) or structured.get("ok") is not True:
        raise DemoError(f"{name} returned malformed structured content")
    data = structured.get("data")
    if not isinstance(data, dict):
        raise DemoError(f"{name} returned malformed data")
    return data


def run_demo(workspace_root: Path) -> dict[str, Any]:
    """Run a complete authenticated primitive-reuse flow.

    A fresh temporary database is used on every call.  Re-running against the
    same workspace is safe: materialization recognizes an existing file with
    the exact proved digest, records another receipt, and reports
    ``reused_existing=true`` without rewriting it.
    """

    workspace = Path(workspace_root).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if not workspace.is_dir():
        raise DemoError("workspace root is not a directory")

    phases: list[dict[str, str]] = []
    product_server: ProductHTTPServer | None = None
    service_thread: threading.Thread | None = None

    with tempfile.TemporaryDirectory(prefix="aidevobserver-e2e-") as temp_dir:
        db_path = Path(temp_dir) / "fabric.sqlite"
        try:
            product_server = create_server("127.0.0.1", 0, db_path)
            service_thread = threading.Thread(
                target=product_server.serve_forever,
                name="aidevobserver-e2e-http",
                daemon=True,
            )
            service_thread.start()

            # Create the real local account and a PAT carrying precisely the
            # scopes used by the product's agent setup flow.  The plaintext
            # credentials remain local variables and never enter the report.
            password = secrets.token_urlsafe(24)
            email = f"demo-{uuid.uuid4().hex}@example.test"
            session = product_server.auth_store.signup(email, password)
            issued = product_server.auth_store.create_api_token(
                session.principal.user_id,
                "One-command demo",
                ALL_AGENT_SCOPES,
            )
            _phase(phases, "account_and_scoped_pat")

            client = FabricClient(product_server.public_url, issued.token)
            health = client.health()
            executable_count = int(health.get("executable_primitives", 0))
            if executable_count != 11:
                raise DemoError(f"expected 11 executable primitives, found {executable_count}")
            _phase(phases, "authenticated_http_service")

            mcp = McpServer(client, workspace, secrets=(issued.token, password))
            initialized = _request(
                mcp,
                1,
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "aidevobserver-e2e", "version": "0.2.0"},
                },
            )
            if initialized.get("protocolVersion") != PROTOCOL_VERSION:
                raise DemoError("MCP protocol negotiation failed")
            notification = mcp.handle_message(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            )
            if notification is not None:
                raise DemoError("initialized notification unexpectedly returned a response")
            _phase(phases, "mcp_initialize")

            listed = _request(mcp, 2, "tools/list", {})
            tools = listed.get("tools")
            if not isinstance(tools, list) or len(tools) != 6:
                raise DemoError("MCP did not expose exactly six tools")
            _phase(phases, "mcp_tools_list")

            search = _tool_call(
                mcp,
                3,
                "search_primitives",
                {"query": DEMO_QUERY, "filters": {"executable_only": True}, "limit": 5},
            )
            results = search.get("results")
            if not isinstance(results, list) or not results:
                raise DemoError("primitive search returned no executable match")
            matched_primitive = str(results[0].get("primitive_id") or "")
            if matched_primitive != DEMO_PRIMITIVE_ID:
                raise DemoError("primitive search did not rank the expected implementation first")
            _phase(phases, "search_primitives")

            detail = _tool_call(
                mcp,
                4,
                "get_primitive",
                {"primitive_id": matched_primitive},
            )
            primitive = detail.get("primitive")
            if not isinstance(primitive, dict) or primitive.get("primitive_id") != matched_primitive:
                raise DemoError("primitive detail did not match search")
            _phase(phases, "get_primitive")

            materialized = _tool_call(
                mcp,
                5,
                "materialize_primitive",
                {"primitive_id": matched_primitive, "destination": DEMO_DESTINATION},
            )
            if materialized.get("source_sha256") != primitive.get("source_sha256"):
                raise DemoError("materialized digest did not match primitive detail")
            _phase(phases, "materialize_primitive")

            execution = _tool_call(
                mcp,
                6,
                "execute_primitive",
                {"primitive_id": matched_primitive, "inputs": DEMO_INPUT},
            )
            output = execution.get("output")
            if not isinstance(output, dict) or output.get("count") != 2:
                raise DemoError("primitive execution did not return two matches")
            _phase(phases, "execute_primitive")

            proof = _tool_call(
                mcp,
                7,
                "prove_primitive",
                {"primitive_id": matched_primitive},
            )
            proof_body = proof.get("proof")
            proof_passed = bool(isinstance(proof_body, dict) and proof_body.get("passed"))
            if not proof_passed:
                raise DemoError("primitive proof did not pass")
            _phase(phases, "prove_primitive")

            _tool_call(
                mcp,
                8,
                "record_reuse",
                {
                    "payload": {
                        "primitive_id": matched_primitive,
                        "action": "reused",
                        "outcome": "accepted",
                    }
                },
            )
            _phase(phases, "record_reuse")

            if _request(mcp, 9, "ping", {}) != {}:
                raise DemoError("MCP ping returned an unexpected payload")
            _phase(phases, "mcp_ping")

            receipt_listing = client.list_receipts()
            receipts = receipt_listing.get("receipts")
            if not isinstance(receipts, list) or len(receipts) != 2:
                raise DemoError("expected materialization and explicit-reuse receipts")
            _phase(phases, "receipt_verification")

            return {
                "status": "ok",
                "executable_count": executable_count,
                "tool_count": len(tools),
                "matched_primitive": matched_primitive,
                "proof_passed": proof_passed,
                "execution_result": {
                    "match_count": int(output["count"]),
                    "matches": list(output.get("emails") or []),
                },
                "materialized": {
                    "path": str(materialized["destination"]),
                    "sha256": str(materialized["source_sha256"]),
                    "reused_existing": bool(materialized.get("reused_existing")),
                    "bytes_written": int(materialized.get("bytes_written", 0)),
                },
                "receipt_count": len(receipts),
                "phases": phases,
            }
        finally:
            if product_server is not None:
                product_server.shutdown()
            if service_thread is not None:
                service_thread.join(timeout=5)
            if product_server is not None:
                product_server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AIDevObserver end-to-end primitive reuse demo")
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        report = run_demo(args.workspace_root)
    except Exception as exc:
        # The report intentionally contains no exception text: an underlying
        # client error must never turn a transient PAT or credential into CLI
        # output.  The exception type is sufficient for a one-command smoke.
        report = {"status": "error", "error_type": type(exc).__name__, "message": "demo failed"}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
