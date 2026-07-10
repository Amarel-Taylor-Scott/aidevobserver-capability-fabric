from __future__ import annotations

import hashlib
import http.client
import json
import re
import sqlite3
import tempfile
import threading
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode

from aidevobserver_fabric.webapp import create_server


TOKEN_RE = re.compile(r"ado_pat_[0-9a-f]{16}\.[A-Za-z0-9_-]{32,128}")


class LiveProduct:
    def __init__(self, db: Path):
        self.server = create_server("127.0.0.1", 0, db)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address[:2]

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, list[tuple[str, str]], bytes]:
        con = http.client.HTTPConnection(self.host, self.port, timeout=5)
        con.request(method, path, body=body, headers=headers or {})
        response = con.getresponse()
        raw = response.read()
        result = (response.status, response.getheaders(), raw)
        con.close()
        return result

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


class ProductE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "fabric.sqlite"
        self.live = LiveProduct(self.db)

    def tearDown(self) -> None:
        self.live.close()
        self.tmp.cleanup()

    @staticmethod
    def _json(raw: bytes) -> dict:
        return json.loads(raw)

    def _signup(self) -> tuple[str, str]:
        status, landing_headers, landing = self.live.request("GET", "/")
        self.assertEqual(status, 200)
        pre_cookie = ""
        for name, value in landing_headers:
            if name.lower() == "set-cookie" and value.startswith("ado_pre_csrf="):
                parsed: SimpleCookie[str] = SimpleCookie()
                parsed.load(value)
                pre_cookie = parsed["ado_pre_csrf"].value
        self.assertTrue(pre_cookie)
        self.assertIn(pre_cookie.encode(), landing)
        body = urlencode({"email": "tester@example.com", "password": "correct-horse-battery", "pre_csrf": pre_cookie}).encode()
        status, headers, _ = self.live.request(
            "POST",
            "/signup",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body)), "Cookie": f"ado_pre_csrf={pre_cookie}"},
        )
        self.assertEqual(status, 303)
        cookies: dict[str, str] = {}
        for name, value in headers:
            if name.lower() == "set-cookie":
                parsed: SimpleCookie[str] = SimpleCookie()
                parsed.load(value)
                for key, morsel in parsed.items():
                    cookies[key] = morsel.value
        self.assertIn("ado_session", cookies)
        self.assertIn("ado_csrf", cookies)
        return f"ado_session={cookies['ado_session']}; ado_csrf={cookies['ado_csrf']}", cookies["ado_csrf"]

    def _mint_token(self, cookie: str, csrf: str) -> str:
        body = urlencode({"name": "E2E Codex", "csrf": csrf}).encode()
        status, _, raw = self.live.request(
            "POST",
            "/app/tokens",
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "Cookie": cookie,
            },
        )
        self.assertEqual(status, 200)
        rendered = raw.decode()
        token = TOKEN_RE.search(rendered)
        self.assertIsNotNone(token)
        self.assertIn("codex mcp add aidevobserver", rendered)
        self.assertIn("claude mcp add", rendered)
        self.assertTrue("pipx install" in rendered or "Bridge already installed" in rendered)
        self.assertIn("aidevobserver-fabric auth login", rendered)
        self.assertNotIn("--env AIDEVOBSERVER_TOKEN", rendered)
        return token.group(0)  # type: ignore[union-attr]

    def _api(
        self,
        token: str,
        method: str,
        path: str,
        payload: dict | None = None,
    ) -> tuple[int, dict]:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Authorization": f"Bearer {token}"}
        if body is not None:
            headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        status, _, raw = self.live.request(method, path, body=body, headers=headers)
        return status, self._json(raw)

    def test_signup_token_search_execute_prove_receipt_and_restart(self) -> None:
        cookie, csrf = self._signup()
        status, _, app = self.live.request("GET", "/app", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn(b"11", app)

        token = self._mint_token(cookie, csrf)
        status, search = self._api(
            token,
            "POST",
            "/v1/primitives/search",
            {"query": "extract email addresses from unstructured text", "limit": 5},
        )
        self.assertEqual(status, 200)
        self.assertEqual(search["results"][0]["primitive_id"], "prim.text.extract_email.v1")
        self.assertTrue(all(item["executable"] for item in search["results"]))

        status, detail = self._api(token, "GET", "/v1/primitives/prim.text.extract_email.v1")
        self.assertEqual(status, 200)
        primitive = detail["primitive"]
        self.assertEqual(hashlib.sha256(primitive["source"].encode()).hexdigest(), primitive["source_sha256"])

        status, execution = self._api(
            token,
            "POST",
            "/v1/primitives/prim.text.extract_email.v1/execute",
            {"inputs": {"text": "Write alice@example.com or bob@example.org"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(execution["output"]["emails"], ["alice@example.com", "bob@example.org"])

        large_field = "x" * 140_000
        status, csv_execution = self._api(
            token,
            "POST",
            "/v1/primitives/candidate.csv.profile_columns.v0/execute",
            {"inputs": {"csv_text": f"payload\n{large_field}\n"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(csv_execution["output"]["row_count"], 1)

        status, proof = self._api(token, "POST", "/v1/primitives/prim.text.extract_email.v1/prove", {})
        self.assertEqual(status, 200)
        self.assertTrue(proof["proof"]["passed"])

        status, created = self._api(
            token,
            "POST",
            "/v1/reuse-receipts",
            {
                "kind": "reuse",
                "subject_id": "prim.text.extract_email.v1",
                "payload": {"primitive_id": "prim.text.extract_email.v1", "outcome": "used"},
            },
        )
        self.assertEqual(status, 201)
        receipt_id = created["receipt"]["receipt_id"]
        status, listed = self._api(token, "GET", "/v1/reuse-receipts")
        self.assertEqual(status, 200)
        self.assertEqual(listed["receipts"][0]["receipt_id"], receipt_id)

        # Startup synchronizes packaged records but does not delete identity or
        # evidence tables.  The same PAT and receipt survive a real restart.
        self.live.close()
        self.live = LiveProduct(self.db)
        status, me = self._api(token, "GET", "/v1/me")
        self.assertEqual(status, 200)
        self.assertEqual(me["email"], "tester@example.com")
        status, listed = self._api(token, "GET", "/v1/reuse-receipts")
        self.assertEqual(status, 200)
        self.assertEqual(listed["receipts"][0]["receipt_id"], receipt_id)

        con = sqlite3.connect(self.db)
        dump = "\n".join(con.iterdump())
        con.close()
        self.assertNotIn(token, dump)
        self.assertNotIn("correct-horse-battery", dump)

    def test_api_auth_scope_and_browser_csrf_fail_closed(self) -> None:
        cookie, csrf = self._signup()
        token = self._mint_token(cookie, csrf)
        status, payload = self._api("ado_pat_0000000000000000.notavalidsecretnotavalidsecretnotavalid", "GET", "/v1/me")
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "unauthorized")

        body = urlencode({"query": "email", "csrf": "wrong"}).encode()
        status, _, _ = self.live.request(
            "POST",
            "/app/search",
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "Cookie": cookie,
            },
        )
        self.assertEqual(status, 403)

        status, payload = self._api(token, "POST", "/v1/primitives/search", {"query": "zxqv blorp"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["results"], [])

    def test_executable_search_has_domain_relevance_gates(self) -> None:
        cookie, csrf = self._signup()
        token = self._mint_token(cookie, csrf)
        cases = {
            "validate credit card number": "prim.validation.luhn.v1",
            "find phone numbers and normalize to e164": "prim.text.extract_phone_e164.v1",
            "extract email addresses from unstructured text": "prim.text.extract_email.v1",
        }
        for query, primitive_id in cases.items():
            with self.subTest(query=query):
                status, payload = self._api(token, "POST", "/v1/primitives/search", {"query": query})
                self.assertEqual(status, 200)
                self.assertEqual(payload["results"][0]["primitive_id"], primitive_id)
        status, payload = self._api(
            token,
            "POST",
            "/v1/primitives/search",
            {"query": "normalize regulatory interest rates"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["results"], [])


if __name__ == "__main__":
    unittest.main()
