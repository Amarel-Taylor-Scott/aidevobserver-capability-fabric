from __future__ import annotations

import http.client
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import threading
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode

from aidevobserver_fabric.webapp import create_server


TOKEN_RE = re.compile(r"ado_pat_[0-9a-f]{16}\.[A-Za-z0-9_-]{32,128}")


def rpc(request_id: int, method: str, params: dict | None = None) -> dict:
    message: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


class LiveMcpE2ETests(unittest.TestCase):
    def test_browser_signup_to_real_mcp_subprocess_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            server = create_server("127.0.0.1", 0, root / "fabric.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address[:2]

            def request(method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None):
                connection = http.client.HTTPConnection(host, port, timeout=5)
                connection.request(method, path, body=body, headers=headers or {})
                response = connection.getresponse()
                result = response.status, response.getheaders(), response.read()
                connection.close()
                return result

            try:
                status, landing_headers, landing = request("GET", "/")
                self.assertEqual(status, 200)
                pre_cookie = ""
                for key, value in landing_headers:
                    if key.lower() == "set-cookie" and value.startswith("ado_pre_csrf="):
                        parsed: SimpleCookie[str] = SimpleCookie()
                        parsed.load(value)
                        pre_cookie = parsed["ado_pre_csrf"].value
                self.assertIn(pre_cookie.encode(), landing)
                signup = urlencode({"email": "mcp@example.com", "password": "mcp-test-password", "pre_csrf": pre_cookie}).encode()
                status, headers, _ = request(
                    "POST",
                    "/signup",
                    signup,
                    {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(signup)), "Cookie": f"ado_pre_csrf={pre_cookie}"},
                )
                self.assertEqual(status, 303)
                cookies: dict[str, str] = {}
                for key, value in headers:
                    if key.lower() == "set-cookie":
                        parsed: SimpleCookie[str] = SimpleCookie()
                        parsed.load(value)
                        cookies.update({name: morsel.value for name, morsel in parsed.items()})
                cookie_header = f"ado_session={cookies['ado_session']}; ado_csrf={cookies['ado_csrf']}"
                mint = urlencode({"name": "Live MCP", "csrf": cookies["ado_csrf"]}).encode()
                status, _, page = request(
                    "POST",
                    "/app/tokens",
                    mint,
                    {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Content-Length": str(len(mint)),
                        "Cookie": cookie_header,
                    },
                )
                self.assertEqual(status, 200)
                match = TOKEN_RE.search(page.decode())
                self.assertIsNotNone(match)
                token = match.group(0)  # type: ignore[union-attr]

                requests = [
                    rpc(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "e2e", "version": "1"}}),
                    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                    rpc(2, "tools/list", {}),
                    rpc(3, "tools/call", {"name": "search_primitives", "arguments": {"query": "extract email addresses", "limit": 5}}),
                    rpc(4, "tools/call", {"name": "get_primitive", "arguments": {"primitive_id": "prim.text.extract_email.v1"}}),
                    rpc(5, "tools/call", {"name": "materialize_primitive", "arguments": {"primitive_id": "prim.text.extract_email.v1", "destination": "reused/extract_email.py"}}),
                    rpc(6, "tools/call", {"name": "execute_primitive", "arguments": {"primitive_id": "prim.text.extract_email.v1", "inputs": {"text": "Use dev@example.com"}}}),
                    rpc(7, "tools/call", {"name": "prove_primitive", "arguments": {"primitive_id": "prim.text.extract_email.v1"}}),
                    rpc(8, "tools/call", {"name": "record_reuse", "arguments": {"payload": {"primitive_id": "prim.text.extract_email.v1", "outcome": "accepted"}}}),
                    rpc(9, "ping", {}),
                ]
                env = os.environ.copy()
                env.update(
                    {
                        "AIDEVOBSERVER_URL": f"http://{host}:{port}",
                        "AIDEVOBSERVER_TOKEN": token,
                        "AIDEVOBSERVER_WORKSPACE": str(workspace),
                    }
                )
                process = subprocess.run(
                    [sys.executable, "-m", "aidevobserver_fabric.mcp_server"],
                    input="".join(json.dumps(item) + "\n" for item in requests),
                    text=True,
                    capture_output=True,
                    timeout=30,
                    env=env,
                    check=False,
                )
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(process.stderr, "")
                self.assertNotIn(token, process.stdout)
                responses = [json.loads(line) for line in process.stdout.splitlines()]
                self.assertEqual([item["id"] for item in responses], list(range(1, 10)))
                self.assertEqual(len(responses[1]["result"]["tools"]), 6)
                self.assertEqual(
                    responses[2]["result"]["structuredContent"]["data"]["results"][0]["primitive_id"],
                    "prim.text.extract_email.v1",
                )
                for response in responses[2:8]:
                    self.assertFalse(response["result"]["isError"], response)
                    self.assertEqual(
                        json.loads(response["result"]["content"][0]["text"]),
                        response["result"]["structuredContent"],
                    )
                self.assertEqual(responses[8]["result"], {})

                materialized = workspace / "reused" / "extract_email.py"
                self.assertTrue(materialized.is_file())
                module = runpy.run_path(str(materialized))
                self.assertEqual(module["execute"]({"text": "hello user@example.com"})["emails"], ["user@example.com"])
                receipts = server.auth_store.list_receipts(
                    server.auth_store.get_session(cookies["ado_session"]).user_id  # type: ignore[union-attr]
                )
                self.assertEqual(len(receipts), 2)  # materialization + explicit reuse
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
