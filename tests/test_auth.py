from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aidevobserver_fabric.auth import (
    AuthStore,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    InvalidCredentialsError,
    NotFoundError,
)


UTC = timezone.utc


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class AuthStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "fabric.sqlite"
        self.clock = MutableClock(datetime(2026, 7, 9, 12, 0, tzinfo=UTC))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make_store(self) -> AuthStore:
        return AuthStore(self.db, clock=self.clock)

    def test_initialization_is_non_destructive_and_restart_persists(self) -> None:
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE registry_sentinel (value TEXT NOT NULL)")
        con.execute("INSERT INTO registry_sentinel VALUES (?)", ("keep-me",))
        con.commit()
        con.close()

        store = self.make_store()
        issued_session = store.signup("Owner@Example.com", "correct horse battery staple")
        issued_token = store.create_api_token(
            issued_session.principal.user_id,
            "Codex",
            ("primitives:read", "receipts:read"),
        )
        receipt = store.append_receipt(
            issued_session.principal.user_id,
            {"primitive_id": "prim.example.v1", "reused": True},
        )
        store.initialize()
        store.close()

        reopened = self.make_store()
        self.assertEqual(
            reopened.authenticate_session(issued_session.session_token).user_id,
            issued_session.principal.user_id,
        )
        self.assertEqual(
            reopened.authenticate_bearer(
                f"Bearer {issued_token.token}",
                required_scopes=("primitives:read",),
            ).user_id,
            issued_session.principal.user_id,
        )
        self.assertEqual(reopened.get_receipt(issued_session.principal.user_id, receipt.receipt_id), receipt)
        reopened.close()

        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT value FROM registry_sentinel").fetchone()[0], "keep-me")
        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        con.close()
        self.assertTrue({"users", "web_sessions", "api_tokens", "reuse_receipts"}.issubset(tables))

    def test_password_and_api_token_plaintext_are_never_stored(self) -> None:
        password = "plain-password-never-store"
        store = self.make_store()
        session = store.signup("person@example.com", password)
        issued = store.create_api_token(
            session.principal.user_id,
            "Claude",
            ("primitives:read",),
        )
        token = issued.token
        store.close()

        con = sqlite3.connect(self.db)
        dump = "\n".join(con.iterdump())
        user_row = con.execute("SELECT password_salt, password_hash FROM users").fetchone()
        token_row = con.execute("SELECT public_id, token_hash FROM api_tokens").fetchone()
        con.close()

        self.assertNotIn(password, dump)
        self.assertNotIn(token, dump)
        self.assertNotIn(token.split(".", 1)[1], dump)
        self.assertIsInstance(user_row[0], bytes)
        self.assertIsInstance(user_row[1], bytes)
        self.assertNotEqual(user_row[1], password.encode())
        self.assertEqual(token_row[0], issued.principal.public_id)
        self.assertNotEqual(token_row[1], token)

    def test_invalid_revoked_and_expired_tokens_are_rejected(self) -> None:
        store = self.make_store()
        session = store.signup("person@example.com", "long-enough-password")
        user_id = session.principal.user_id

        valid = store.create_api_token(user_id, "valid", ("primitives:read",))
        principal = store.authenticate_bearer(f"bearer {valid.token}")
        self.assertEqual(principal.token_id, valid.principal.token_id)

        with self.assertRaises(AuthenticationError):
            store.authenticate_bearer("Bearer ado_pat_0000000000000000.not-a-valid-secret-value")

        self.assertTrue(store.revoke_api_token(user_id, valid.principal.token_id))
        with self.assertRaises(AuthenticationError):
            store.authenticate_bearer(f"Bearer {valid.token}")

        expiring = store.create_api_token(
            user_id,
            "expiring",
            ("primitives:read",),
            expires_at=self.clock.value + timedelta(seconds=1),
        )
        self.clock.value += timedelta(seconds=2)
        with self.assertRaises(AuthenticationError):
            store.authenticate_bearer(f"Bearer {expiring.token}")
        store.close()

    def test_api_token_scopes_and_listing_never_return_secret(self) -> None:
        store = self.make_store()
        session = store.signup("scope@example.com", "long-enough-password")
        issued = store.create_api_token(
            session.principal.user_id,
            "Read-only agent",
            ("receipts:read", "primitives:read", "primitives:read"),
        )
        principal = store.authenticate_api_token(
            issued.token,
            required_scopes=("primitives:read", "receipts:read"),
        )
        self.assertEqual(principal.scopes, ("primitives:read", "receipts:read"))
        with self.assertRaises(AuthorizationError):
            store.authenticate_api_token(issued.token, required_scopes=("proofs:run",))

        listed = store.list_api_tokens(session.principal.user_id)
        self.assertEqual(len(listed), 1)
        self.assertFalse(hasattr(listed[0], "token"))
        self.assertNotIn(issued.token, repr(listed[0]))
        store.close()

    def test_signup_login_session_csrf_and_logout(self) -> None:
        store = self.make_store()
        signup = store.signup("Session@Example.com", "session-password")
        self.assertEqual(signup.principal.email, "session@example.com")
        self.assertTrue(store.validate_csrf(signup.session_token, signup.csrf_token))
        self.assertFalse(store.validate_csrf(signup.session_token, "wrong-csrf"))
        with self.assertRaises(AuthorizationError):
            store.require_csrf(signup.session_token, "wrong-csrf")

        login = store.login("SESSION@example.com", "session-password")
        self.assertEqual(login.principal.user_id, signup.principal.user_id)
        with self.assertRaises(InvalidCredentialsError):
            store.login("session@example.com", "wrong-password")
        with self.assertRaises(InvalidCredentialsError):
            store.login("missing@example.com", "wrong-password")
        with self.assertRaises(ConflictError):
            store.signup("session@example.com", "another-password")

        self.assertTrue(store.logout(signup.session_token))
        with self.assertRaises(AuthenticationError):
            store.authenticate_session(signup.session_token)
        self.assertIsNotNone(store.authenticate_session(login.session_token))
        store.close()

    def test_first_owner_signup_is_atomic_under_concurrency(self) -> None:
        store = self.make_store()
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def signup(index: int) -> None:
            barrier.wait()
            try:
                store.signup_first_user(f"owner{index}@example.com", "owner-password")
                outcomes.append("created")
            except ConflictError:
                outcomes.append("closed")

        threads = [threading.Thread(target=signup, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(sorted(outcomes), ["closed", "created"])
        self.assertEqual(store.user_count(), 1)
        store.close()

    def test_receipts_are_append_only_chained_and_user_isolated(self) -> None:
        store = self.make_store()
        alice = store.signup("alice@example.com", "alice-password").principal.user_id
        bob = store.signup("bob@example.com", "bob-password").principal.user_id

        first = store.append_receipt(
            alice,
            {"primitive_id": "prim.one", "tokens_saved": 10},
            kind="reuse",
            subject_id="run-1",
        )
        second = store.append_receipt(
            alice,
            {"primitive_id": "prim.two", "tokens_saved": 20},
            kind="reuse",
            subject_id="run-2",
        )
        bob_receipt = store.append_receipt(bob, {"primitive_id": "prim.private"})

        self.assertEqual(first.sequence_no, 1)
        self.assertIsNone(first.previous_receipt_hash)
        self.assertEqual(second.sequence_no, 2)
        self.assertEqual(second.previous_receipt_hash, first.receipt_hash)
        self.assertEqual([item.receipt_id for item in store.list_receipts(alice)], [second.receipt_id, first.receipt_id])
        self.assertEqual([item.receipt_id for item in store.list_receipts(bob)], [bob_receipt.receipt_id])

        with self.assertRaises(NotFoundError):
            store.get_receipt(alice, bob_receipt.receipt_id)
        with self.assertRaises(NotFoundError):
            store.get_receipt(bob, first.receipt_id)
        store.close()


if __name__ == "__main__":
    unittest.main()
