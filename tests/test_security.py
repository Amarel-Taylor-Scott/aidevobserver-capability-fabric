from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import re
import tempfile
import threading
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

from aidevobserver_fabric import cli, credentials, mcp_server, registry
from aidevobserver_fabric.api_client import APIError, FabricClient
from aidevobserver_fabric.webapp import create_server


class LiveProduct:
    def __init__(self, db: Path, **kwargs: object):
        self.server = create_server("127.0.0.1", 0, db, **kwargs)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address[:2]

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None):
        con = http.client.HTTPConnection(self.host, self.port, timeout=5)
        con.request(method, path, body=body, headers=headers or {})
        response = con.getresponse()
        result = response.status, response.getheaders(), response.read()
        con.close()
        return result

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


class SecurityTests(unittest.TestCase):
    def test_client_rejects_insecure_remote_url_and_never_follows_redirect(self) -> None:
        with self.assertRaises(ValueError):
            FabricClient("http://example.com", "ado_pat_0000000000000000." + "x" * 43)

        received: list[str | None] = []

        class Target(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                received.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format: str, *args: object) -> None:
                return

        target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
        target_thread = threading.Thread(target=target.serve_forever, daemon=True)
        target_thread.start()
        target_url = f"http://127.0.0.1:{target.server_address[1]}/capture"

        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(302)
                self.send_header("Location", target_url)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        origin = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        origin_thread = threading.Thread(target=origin.serve_forever, daemon=True)
        origin_thread.start()
        token = "ado_pat_0000000000000000." + "x" * 43
        try:
            with self.assertRaises(APIError) as raised:
                FabricClient(f"http://127.0.0.1:{origin.server_address[1]}", token).me()
            self.assertEqual(raised.exception.status, 302)
            self.assertEqual(received, [])
        finally:
            origin.shutdown()
            target.shutdown()
            origin_thread.join(timeout=5)
            target_thread.join(timeout=5)
            origin.server_close()
            target.server_close()

    def test_credentials_and_database_files_are_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            credential_file = root / "config" / "credentials.json"
            token = "ado_pat_0000000000000000." + "x" * 43
            credentials.save_token("http://127.0.0.1:8766", token, path=credential_file)
            self.assertEqual(credentials.load_token("http://127.0.0.1:8766", path=credential_file), token)
            self.assertEqual(credential_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(credential_file.parent.stat().st_mode & 0o777, 0o700)

            db = root / "private" / "fabric.sqlite"
            registry.build_db(db)
            self.assertEqual(db.stat().st_mode & 0o777, 0o600)
            self.assertEqual(db.parent.stat().st_mode & 0o777, 0o700)

    def test_credentials_do_not_change_existing_shared_parent_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared = root / "shared-config"
            shared.mkdir(mode=0o755)
            os.chmod(shared, 0o755)
            credential_file = shared / "credentials.json"
            token = "ado_pat_0000000000000000." + "x" * 43

            credentials.save_token("http://127.0.0.1:8766", token, path=credential_file)

            self.assertEqual(shared.stat().st_mode & 0o777, 0o755)
            self.assertEqual(credential_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(credentials.load_token("http://127.0.0.1:8766", path=credential_file), token)
            self.assertEqual(shared.stat().st_mode & 0o777, 0o755)

    def test_credentials_reject_symlink_parent_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            linked_parent = root / "linked-config"
            shared = root / "shared"
            shared.mkdir()
            victim = outside / "victim.json"
            victim.write_text("do not touch\n", encoding="utf-8")
            os.chmod(victim, 0o644)
            linked_file = shared / "credentials.json"
            try:
                linked_parent.symlink_to(outside, target_is_directory=True)
                linked_file.symlink_to(victim)
            except (NotImplementedError, OSError):
                self.skipTest("symlinks unavailable")
            token = "ado_pat_0000000000000000." + "x" * 43

            with self.assertRaisesRegex(ValueError, "symbolic-link"):
                credentials.save_token(
                    "http://127.0.0.1:8766",
                    token,
                    path=linked_parent / "credentials.json",
                )
            self.assertFalse((outside / "credentials.json").exists())

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                credentials.save_token("http://127.0.0.1:8766", token, path=linked_file)
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                credentials.load_token("http://127.0.0.1:8766", path=linked_file)
            self.assertEqual(victim.read_text(encoding="utf-8"), "do not touch\n")
            self.assertEqual(victim.stat().st_mode & 0o777, 0o644)

    def test_private_auth_login_feeds_mcp_without_env_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = LiveProduct(root / "fabric.sqlite")
            try:
                user = live.server.auth_store.signup("login@example.com", "login-password").principal
                issued = live.server.auth_store.create_api_token(user.user_id, "CLI", ("primitives:read",))
                credential_file = root / "credentials.json"
                environment = {
                    "AIDEVOBSERVER_CREDENTIALS": str(credential_file),
                    "AIDEVOBSERVER_URL": live.url,
                }
                stdout = io.StringIO()
                stderr = io.StringIO()
                with mock.patch.dict(os.environ, environment, clear=True), mock.patch(
                    "aidevobserver_fabric.cli.getpass.getpass", return_value=issued.token
                ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = cli.main(["auth", "login", "--server", live.url])
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertNotIn(issued.token, stdout.getvalue() + stderr.getvalue())
                self.assertEqual(credential_file.stat().st_mode & 0o777, 0o600)

                protocol_out = io.StringIO()
                protocol_err = io.StringIO()
                with mock.patch.dict(os.environ, environment, clear=True):
                    code = mcp_server.main(
                        ["--base-url", live.url, "--workspace-root", str(root)],
                        stdin=io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n'),
                        stdout=protocol_out,
                        stderr=protocol_err,
                    )
                self.assertEqual(code, 0, protocol_err.getvalue())
                self.assertEqual(json.loads(protocol_out.getvalue())["result"], {})
                self.assertNotIn(issued.token, protocol_out.getvalue() + protocol_err.getvalue())
            finally:
                live.close()

    def test_https_public_url_sets_secure_cookie_hsts_and_rejects_evil_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install = "pipx install https://downloads.example.com/fabric-0.2.0.whl"
            live = LiveProduct(
                Path(tmp) / "fabric.sqlite",
                public_url="https://fabric.example.com",
                bridge_install_command=install,
            )
            try:
                self.assertEqual(live.server.bridge_install_command, install)
                status, headers, page = live.request("GET", "/")
                self.assertEqual(status, 200)
                self.assertTrue(any(name.lower() == "strict-transport-security" for name, _ in headers))
                pre_header = next(value for name, value in headers if name.lower() == "set-cookie")
                self.assertIn("Secure", pre_header)
                parsed: SimpleCookie[str] = SimpleCookie()
                parsed.load(pre_header)
                pre = parsed["ado_pre_csrf"].value
                self.assertIn(pre.encode(), page)
                body = urlencode({"email": "evil@example.com", "password": "long-password", "pre_csrf": pre}).encode()
                status, _, _ = live.request(
                    "POST",
                    "/signup",
                    body,
                    {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Content-Length": str(len(body)),
                        "Cookie": f"ado_pre_csrf={pre}",
                        "Origin": "https://attacker.example",
                    },
                )
                self.assertEqual(status, 403)
                self.assertEqual(live.server.auth_store.user_count(), 0)
            finally:
                live.close()

    def test_local_signup_closes_after_first_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live = LiveProduct(Path(tmp) / "fabric.sqlite")
            try:
                live.server.auth_store.signup("owner@example.com", "owner-password")
                status, headers, page = live.request("GET", "/")
                self.assertEqual(status, 200)
                cookie_header = next(value for name, value in headers if name.lower() == "set-cookie")
                parsed: SimpleCookie[str] = SimpleCookie()
                parsed.load(cookie_header)
                pre = parsed["ado_pre_csrf"].value
                self.assertIn(pre.encode(), page)
                body = urlencode({"email": "second@example.com", "password": "second-password", "pre_csrf": pre}).encode()
                status, _, _ = live.request(
                    "POST",
                    "/signup",
                    body,
                    {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Content-Length": str(len(body)),
                        "Cookie": f"ado_pre_csrf={pre}",
                    },
                )
                self.assertEqual(status, 409)
                self.assertEqual(live.server.auth_store.user_count(), 1)
            finally:
                live.close()

    def test_login_rate_limit_is_account_scoped_behind_shared_peer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live = LiveProduct(Path(tmp) / "fabric.sqlite")
            try:
                status, headers, _ = live.request("GET", "/")
                self.assertEqual(status, 200)
                cookie_header = next(value for name, value in headers if name.lower() == "set-cookie")
                parsed: SimpleCookie[str] = SimpleCookie()
                parsed.load(cookie_header)
                pre = parsed["ado_pre_csrf"].value

                def attempt(email: str) -> int:
                    body = urlencode(
                        {"email": email, "password": "wrong-password", "pre_csrf": pre}
                    ).encode()
                    result, _, _ = live.request(
                        "POST",
                        "/login",
                        body,
                        {
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Content-Length": str(len(body)),
                            "Cookie": f"ado_pre_csrf={pre}",
                        },
                    )
                    return result

                self.assertEqual([attempt("first@example.com") for _ in range(8)], [401] * 8)
                self.assertEqual(attempt("first@example.com"), 429)
                # The same reverse-proxy/peer address must not inherit another
                # account's failed-login bucket.
                self.assertEqual(attempt("second@example.com"), 401)
            finally:
                live.close()

    def test_scope_isolation_filter_validation_and_strict_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live = LiveProduct(Path(tmp) / "fabric.sqlite")
            try:
                alice = live.server.auth_store.signup("alice@example.com", "alice-password").principal
                bob = live.server.auth_store.signup("bob@example.com", "bob-password").principal
                read = live.server.auth_store.create_api_token(alice.user_id, "read", ("primitives:read",))
                full = live.server.auth_store.create_api_token(
                    alice.user_id,
                    "full",
                    ("primitives:read", "primitives:execute", "receipts:read", "receipts:write"),
                )
                bob_token = live.server.auth_store.create_api_token(bob.user_id, "bob", ("receipts:read",))
                read_client = FabricClient(live.url, read.token)
                full_client = FabricClient(live.url, full.token)
                bob_client = FabricClient(live.url, bob_token.token)

                self.assertTrue(read_client.search("extract email addresses")["results"])
                with self.assertRaises(APIError) as forbidden:
                    read_client.execute("prim.text.extract_email.v1", {"text": "a@example.com"})
                self.assertEqual(forbidden.exception.status, 403)
                for filters in ([], {"serves_truth": "false"}, {"trust": "unknown"}):
                    with self.assertRaises(APIError) as invalid:
                        full_client.search("email", filters=filters)  # type: ignore[arg-type]
                    self.assertEqual(invalid.exception.status, 400)

                with self.assertRaises(APIError) as secret_receipt:
                    full_client.record_reuse(
                        {"primitive_id": "prim.text.extract_email.v1", "outcome": "used", "api_key": "secret"}
                    )
                self.assertEqual(secret_receipt.exception.status, 400)
                for unsafe in (
                    {"primitive_id": "prim.text.extract_email.v1", "outcome": "used", "notes": "sk-live-secret"},
                    {"primitive_id": "fake.primitive", "outcome": "used"},
                ):
                    with self.assertRaises(APIError) as rejected:
                        full_client.record_reuse(unsafe)
                    self.assertEqual(rejected.exception.status, 400)
                created = full_client.record_reuse(
                    {"primitive_id": "prim.text.extract_email.v1", "action": "reused", "outcome": "used"}
                )
                self.assertIn("receipt", created)
                self.assertEqual(bob_client.list_receipts()["receipts"], [])

                expired = live.server.auth_store.create_api_token(
                    alice.user_id,
                    "expired",
                    ("primitives:read",),
                    expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                )
                with self.assertRaises(APIError) as expired_error:
                    FabricClient(live.url, expired.token).me()
                self.assertEqual(expired_error.exception.status, 401)
                live.server.auth_store.revoke_api_token(alice.user_id, read.principal.token_id)
                with self.assertRaises(APIError) as revoked_error:
                    read_client.me()
                self.assertEqual(revoked_error.exception.status, 401)
            finally:
                live.close()


if __name__ == "__main__":
    unittest.main()
