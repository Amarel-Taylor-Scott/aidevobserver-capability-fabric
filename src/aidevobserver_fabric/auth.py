"""Dependency-free authentication and receipt storage.

The store deliberately owns only identity/session/token/receipt tables.  Its
schema initialization is additive so it can safely share a SQLite database
with the capability registry without rebuilding or dropping registry data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


UTC = timezone.utc
PASSWORD_SALT_BYTES = 16
PASSWORD_HASH_BYTES = 32
PASSWORD_SCRYPT_N = 1 << 14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
PASSWORD_SCRYPT_MAXMEM = 64 * 1024 * 1024
DEFAULT_SESSION_TTL_SECONDS = 8 * 60 * 60
MAX_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60

SCOPE_RE = re.compile(r"^(?:\*|[a-z][a-z0-9:_-]{0,63})$")
PAT_RE = re.compile(r"^ado_pat_([0-9a-f]{16})\.([A-Za-z0-9_-]{32,128})$")


class AuthError(RuntimeError):
    """Base error for auth-store operations."""


class ValidationError(AuthError):
    """Input failed local validation."""


class ConflictError(AuthError):
    """A unique identity or token name conflicts with stored state."""


class InvalidCredentialsError(AuthError):
    """Login credentials are invalid."""


class AuthenticationError(AuthError):
    """A session or bearer token is missing, invalid, expired, or revoked."""


class AuthorizationError(AuthError):
    """An authenticated principal lacks a required scope or CSRF token."""


class NotFoundError(AuthError):
    """A user-owned object does not exist."""


@dataclass(frozen=True, slots=True)
class User:
    user_id: str
    email: str
    created_at: datetime
    disabled_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SessionPrincipal:
    session_id: str
    user_id: str
    email: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedWebSession:
    principal: SessionPrincipal
    session_token: str = field(repr=False)
    csrf_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class TokenPrincipal:
    token_id: str
    public_id: str
    user_id: str
    email: str
    name: str
    scopes: tuple[str, ...]
    created_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssuedApiToken:
    principal: TokenPrincipal
    token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ApiTokenInfo:
    token_id: str
    public_id: str
    name: str
    scopes: tuple[str, ...]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class ReuseReceipt:
    receipt_id: str
    user_id: str
    sequence_no: int
    kind: str
    subject_id: str | None
    payload: dict[str, Any]
    created_at: datetime
    previous_receipt_hash: str | None
    receipt_hash: str


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("value must be canonical-JSON serializable") from exc


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValidationError("timestamps must be timezone-aware")
    normalized = value.astimezone(UTC)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValidationError("email is invalid")
    normalized = unicodedata.normalize("NFKC", email.strip()).casefold()
    if not normalized or len(normalized) > 320 or "@" not in normalized:
        raise ValidationError("email is invalid")
    local, domain = normalized.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        raise ValidationError("email is invalid")
    return normalized


def _validate_password(password: str) -> None:
    if not isinstance(password, str):
        raise ValidationError("password is invalid")
    encoded = password.encode("utf-8")
    if len(encoded) < 8:
        raise ValidationError("password must contain at least 8 UTF-8 bytes")
    if len(encoded) > 1024:
        raise ValidationError("password is too long")


def _derive_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=PASSWORD_HASH_BYTES,
        maxmem=PASSWORD_SCRYPT_MAXMEM,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class AuthStore:
    """SQLite-backed auth/session/token/receipt service.

    One instance owns one thread-safe SQLite connection.  Call :meth:`close`
    when the containing service shuts down.  Reopening the same database path
    preserves all records because schema initialization uses only
    ``CREATE ... IF NOT EXISTS`` statements.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        raw_db_path = str(db_path)
        self.db_path = raw_db_path if raw_db_path == ":memory:" else str(Path(raw_db_path).expanduser())
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        if self.db_path != ":memory:":
            db_file = Path(self.db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            db_file.touch(mode=0o600, exist_ok=True)
            os.chmod(db_file, 0o600)
        self._con = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            check_same_thread=False,
        )
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")
        self._con.execute("PRAGMA busy_timeout = 30000")
        if self.db_path != ":memory:":
            self._con.execute("PRAGMA journal_mode = WAL")
            for companion in (Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm")):
                if companion.exists():
                    os.chmod(companion, 0o600)
        self.initialize()

    def __enter__(self) -> AuthStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise RuntimeError("AuthStore clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    def initialize(self) -> None:
        """Create auth tables and indices without dropping existing objects."""

        schema = """
        CREATE TABLE IF NOT EXISTS users (
          user_id TEXT PRIMARY KEY,
          email TEXT NOT NULL UNIQUE COLLATE NOCASE,
          password_salt BLOB NOT NULL,
          password_hash BLOB NOT NULL,
          created_at TEXT NOT NULL,
          disabled_at TEXT
        );

        CREATE TABLE IF NOT EXISTS web_sessions (
          session_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
          session_token_hash TEXT NOT NULL UNIQUE,
          csrf_token_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          revoked_at TEXT
        );

        CREATE TABLE IF NOT EXISTS api_tokens (
          token_id TEXT PRIMARY KEY,
          public_id TEXT NOT NULL UNIQUE,
          user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          token_hash TEXT NOT NULL UNIQUE,
          scopes_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          expires_at TEXT,
          last_used_at TEXT,
          revoked_at TEXT
        );

        CREATE TABLE IF NOT EXISTS reuse_receipts (
          receipt_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
          sequence_no INTEGER NOT NULL,
          kind TEXT NOT NULL,
          subject_id TEXT,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          previous_receipt_hash TEXT,
          receipt_hash TEXT NOT NULL UNIQUE,
          UNIQUE(user_id, sequence_no)
        );

        CREATE INDEX IF NOT EXISTS web_sessions_user_idx
          ON web_sessions(user_id, expires_at);
        CREATE INDEX IF NOT EXISTS api_tokens_user_idx
          ON api_tokens(user_id, created_at);
        CREATE INDEX IF NOT EXISTS reuse_receipts_user_idx
          ON reuse_receipts(user_id, sequence_no DESC);
        """
        with self._lock, self._con:
            self._con.executescript(schema)

    def _user_from_row(self, row: sqlite3.Row) -> User:
        return User(
            user_id=row["user_id"],
            email=row["email"],
            created_at=_parse_utc(row["created_at"]),  # type: ignore[arg-type]
            disabled_at=_parse_utc(row["disabled_at"]),
        )

    def _get_user_row(self, user_id: str) -> sqlite3.Row:
        row = self._con.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("user not found")
        return row

    def get_user(self, user_id: str) -> User:
        with self._lock:
            return self._user_from_row(self._get_user_row(user_id))

    def user_count(self) -> int:
        with self._lock:
            return int(self._con.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_user(self, email: str, password: str) -> User:
        normalized_email = _normalize_email(email)
        _validate_password(password)
        salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
        verifier = _derive_password(password, salt)
        user_id = _new_id("usr")
        created_at = self._now()
        try:
            with self._lock, self._con:
                self._con.execute(
                    """
                    INSERT INTO users (
                      user_id, email, password_salt, password_hash,
                      created_at, disabled_at
                    ) VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (user_id, normalized_email, salt, verifier, _format_utc(created_at)),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("email is already registered") from exc
        return User(user_id=user_id, email=normalized_email, created_at=created_at)

    def _issue_session(self, user: User, ttl_seconds: int) -> IssuedWebSession:
        if (
            not isinstance(ttl_seconds, int)
            or isinstance(ttl_seconds, bool)
            or ttl_seconds <= 0
            or ttl_seconds > MAX_SESSION_TTL_SECONDS
        ):
            raise ValidationError("session TTL is outside the allowed range")
        now = self._now()
        expires_at = now + timedelta(seconds=ttl_seconds)
        session_id = _new_id("sess")
        session_token = "ado_sess_" + secrets.token_urlsafe(32)
        csrf_token = "ado_csrf_" + secrets.token_urlsafe(32)
        principal = SessionPrincipal(
            session_id=session_id,
            user_id=user.user_id,
            email=user.email,
            created_at=now,
            expires_at=expires_at,
        )
        with self._lock, self._con:
            self._con.execute(
                """
                INSERT INTO web_sessions (
                  session_id, user_id, session_token_hash, csrf_token_hash,
                  created_at, expires_at, last_seen_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    session_id,
                    user.user_id,
                    _sha256_text(session_token),
                    _sha256_text(csrf_token),
                    _format_utc(now),
                    _format_utc(expires_at),
                    _format_utc(now),
                ),
            )
        return IssuedWebSession(principal, session_token, csrf_token)

    def signup(
        self,
        email: str,
        password: str,
        *,
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> IssuedWebSession:
        if (
            not isinstance(session_ttl_seconds, int)
            or isinstance(session_ttl_seconds, bool)
            or session_ttl_seconds <= 0
            or session_ttl_seconds > MAX_SESSION_TTL_SECONDS
        ):
            raise ValidationError("session TTL is outside the allowed range")
        user = self.create_user(email, password)
        return self._issue_session(user, session_ttl_seconds)

    def signup_first_user(
        self,
        email: str,
        password: str,
        *,
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> IssuedWebSession:
        """Atomically create the sole local bootstrap owner."""

        normalized_email = _normalize_email(email)
        _validate_password(password)
        if (
            not isinstance(session_ttl_seconds, int)
            or isinstance(session_ttl_seconds, bool)
            or session_ttl_seconds <= 0
            or session_ttl_seconds > MAX_SESSION_TTL_SECONDS
        ):
            raise ValidationError("session TTL is outside the allowed range")
        salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
        verifier = _derive_password(password, salt)
        user_id = _new_id("usr")
        created_at = self._now()
        with self._lock:
            self._con.execute("BEGIN IMMEDIATE")
            try:
                if int(self._con.execute("SELECT COUNT(*) FROM users").fetchone()[0]) != 0:
                    raise ConflictError("local owner signup is already complete")
                self._con.execute(
                    """
                    INSERT INTO users (
                      user_id, email, password_salt, password_hash,
                      created_at, disabled_at
                    ) VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (user_id, normalized_email, salt, verifier, _format_utc(created_at)),
                )
                self._con.commit()
            except Exception:
                self._con.rollback()
                raise
        user = User(user_id=user_id, email=normalized_email, created_at=created_at)
        return self._issue_session(user, session_ttl_seconds)

    def login(
        self,
        email: str,
        password: str,
        *,
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> IssuedWebSession:
        try:
            normalized_email = _normalize_email(email)
        except ValidationError:
            normalized_email = "invalid@example.invalid"
        with self._lock:
            row = self._con.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
                (normalized_email,),
            ).fetchone()
        if row is None:
            salt = bytes(PASSWORD_SALT_BYTES)
            expected = bytes(PASSWORD_HASH_BYTES)
        else:
            salt = bytes(row["password_salt"])
            expected = bytes(row["password_hash"])
        try:
            derived = _derive_password(password, salt)
        except (TypeError, ValueError):
            derived = bytes(PASSWORD_HASH_BYTES)
        password_valid = hmac.compare_digest(derived, expected)
        if row is None or not password_valid or row["disabled_at"] is not None:
            raise InvalidCredentialsError("invalid email or password")
        user = self._user_from_row(row)
        return self._issue_session(user, session_ttl_seconds)

    def get_session(self, session_token: str) -> SessionPrincipal | None:
        if not isinstance(session_token, str) or not session_token:
            return None
        digest = _sha256_text(session_token)
        now = self._now()
        with self._lock, self._con:
            row = self._con.execute(
                """
                SELECT s.*, u.email, u.disabled_at
                FROM web_sessions AS s
                JOIN users AS u ON u.user_id = s.user_id
                WHERE s.session_token_hash = ?
                """,
                (digest,),
            ).fetchone()
            if row is None:
                return None
            expires_at = _parse_utc(row["expires_at"])
            if row["revoked_at"] is not None or row["disabled_at"] is not None or expires_at <= now:
                return None
            self._con.execute(
                "UPDATE web_sessions SET last_seen_at = ? WHERE session_id = ?",
                (_format_utc(now), row["session_id"]),
            )
            return SessionPrincipal(
                session_id=row["session_id"],
                user_id=row["user_id"],
                email=row["email"],
                created_at=_parse_utc(row["created_at"]),  # type: ignore[arg-type]
                expires_at=expires_at,
            )

    def authenticate_session(self, session_token: str) -> SessionPrincipal:
        principal = self.get_session(session_token)
        if principal is None:
            raise AuthenticationError("session is invalid, expired, or revoked")
        return principal

    def validate_csrf(self, session_token: str, csrf_token: str) -> bool:
        if not session_token or not csrf_token:
            return False
        session_digest = _sha256_text(session_token)
        candidate_digest = _sha256_text(csrf_token)
        now = self._now()
        with self._lock:
            row = self._con.execute(
                """
                SELECT s.csrf_token_hash, s.expires_at, s.revoked_at,
                       u.disabled_at
                FROM web_sessions AS s
                JOIN users AS u ON u.user_id = s.user_id
                WHERE s.session_token_hash = ?
                """,
                (session_digest,),
            ).fetchone()
        if row is None:
            expected = "0" * 64
            valid_state = False
        else:
            expected = row["csrf_token_hash"]
            expires_at = _parse_utc(row["expires_at"])
            valid_state = (
                row["revoked_at"] is None
                and row["disabled_at"] is None
                and expires_at > now
            )
        return valid_state and hmac.compare_digest(candidate_digest, expected)

    def require_csrf(self, session_token: str, csrf_token: str) -> None:
        if not self.validate_csrf(session_token, csrf_token):
            raise AuthorizationError("CSRF token is invalid")

    def logout(self, session_token: str) -> bool:
        if not session_token:
            return False
        now = _format_utc(self._now())
        with self._lock, self._con:
            cursor = self._con.execute(
                """
                UPDATE web_sessions
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE session_token_hash = ?
                """,
                (now, _sha256_text(session_token)),
            )
            return cursor.rowcount > 0

    def _normalize_scopes(self, scopes: Iterable[str]) -> tuple[str, ...]:
        supplied = tuple(scopes)
        if any(not isinstance(scope, str) for scope in supplied):
            raise ValidationError("API-token scope is invalid")
        normalized = tuple(sorted(set(supplied)))
        if not normalized:
            raise ValidationError("at least one API-token scope is required")
        if any(not SCOPE_RE.fullmatch(scope) for scope in normalized):
            raise ValidationError("API-token scope is invalid")
        return normalized

    def create_api_token(
        self,
        user_id: str,
        name: str,
        scopes: Iterable[str],
        *,
        expires_at: datetime | None = None,
    ) -> IssuedApiToken:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 100:
            raise ValidationError("token name must contain 1 to 100 characters")
        normalized_scopes = self._normalize_scopes(scopes)
        if expires_at is not None:
            expires_at = _parse_utc(_format_utc(expires_at))
        now = self._now()
        with self._lock:
            user_row = self._get_user_row(user_id)
            if user_row["disabled_at"] is not None:
                raise AuthorizationError("user is disabled")
        token_id = _new_id("tok")
        public_id = secrets.token_hex(8)
        secret = secrets.token_urlsafe(32)
        token = f"ado_pat_{public_id}.{secret}"
        principal = TokenPrincipal(
            token_id=token_id,
            public_id=public_id,
            user_id=user_id,
            email=user_row["email"],
            name=clean_name,
            scopes=normalized_scopes,
            created_at=now,
            expires_at=expires_at,
        )
        with self._lock, self._con:
            self._con.execute(
                """
                INSERT INTO api_tokens (
                  token_id, public_id, user_id, name, token_hash, scopes_json,
                  created_at, expires_at, last_used_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    token_id,
                    public_id,
                    user_id,
                    clean_name,
                    _sha256_text(token),
                    _canonical_json(normalized_scopes),
                    _format_utc(now),
                    _format_utc(expires_at) if expires_at else None,
                ),
            )
        return IssuedApiToken(principal=principal, token=token)

    def _principal_from_token_row(self, row: sqlite3.Row) -> TokenPrincipal:
        return TokenPrincipal(
            token_id=row["token_id"],
            public_id=row["public_id"],
            user_id=row["user_id"],
            email=row["email"],
            name=row["name"],
            scopes=tuple(json.loads(row["scopes_json"])),
            created_at=_parse_utc(row["created_at"]),  # type: ignore[arg-type]
            expires_at=_parse_utc(row["expires_at"]),
        )

    def authenticate_api_token(
        self,
        token: str,
        *,
        required_scopes: Iterable[str] = (),
    ) -> TokenPrincipal:
        match = PAT_RE.fullmatch(token) if isinstance(token, str) else None
        public_id = match.group(1) if match else "0" * 16
        candidate_digest = _sha256_text(token if isinstance(token, str) else "")
        now = self._now()
        with self._lock, self._con:
            row = self._con.execute(
                """
                SELECT t.*, u.email, u.disabled_at
                FROM api_tokens AS t
                JOIN users AS u ON u.user_id = t.user_id
                WHERE t.public_id = ?
                """,
                (public_id,),
            ).fetchone()
            expected_digest = row["token_hash"] if row is not None else "0" * 64
            digest_valid = hmac.compare_digest(candidate_digest, expected_digest)
            if row is None or match is None or not digest_valid:
                raise AuthenticationError("bearer token is invalid")
            expires_at = _parse_utc(row["expires_at"])
            if (
                row["revoked_at"] is not None
                or row["disabled_at"] is not None
                or (expires_at is not None and expires_at <= now)
            ):
                raise AuthenticationError("bearer token is expired or revoked")
            principal = self._principal_from_token_row(row)
            requested = set(required_scopes)
            granted = set(principal.scopes)
            if requested and "*" not in granted and not requested.issubset(granted):
                raise AuthorizationError("bearer token has insufficient scope")
            self._con.execute(
                "UPDATE api_tokens SET last_used_at = ? WHERE token_id = ?",
                (_format_utc(now), principal.token_id),
            )
            return principal

    def authenticate_bearer(
        self,
        authorization_header: str,
        *,
        required_scopes: Iterable[str] = (),
    ) -> TokenPrincipal:
        if not isinstance(authorization_header, str):
            raise AuthenticationError("Authorization header is missing")
        parts = authorization_header.strip().split(None, 1)
        if len(parts) != 2 or parts[0].casefold() != "bearer":
            raise AuthenticationError("Authorization header must use Bearer")
        return self.authenticate_api_token(parts[1], required_scopes=required_scopes)

    def revoke_api_token(self, user_id: str, token_id: str) -> bool:
        now = _format_utc(self._now())
        with self._lock, self._con:
            cursor = self._con.execute(
                """
                UPDATE api_tokens
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE user_id = ? AND token_id = ?
                """,
                (now, user_id, token_id),
            )
            return cursor.rowcount > 0

    def list_api_tokens(self, user_id: str) -> list[ApiTokenInfo]:
        with self._lock:
            self._get_user_row(user_id)
            rows = self._con.execute(
                """
                SELECT token_id, public_id, name, scopes_json, created_at,
                       expires_at, last_used_at, revoked_at
                FROM api_tokens
                WHERE user_id = ?
                ORDER BY created_at DESC, token_id DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            ApiTokenInfo(
                token_id=row["token_id"],
                public_id=row["public_id"],
                name=row["name"],
                scopes=tuple(json.loads(row["scopes_json"])),
                created_at=_parse_utc(row["created_at"]),  # type: ignore[arg-type]
                expires_at=_parse_utc(row["expires_at"]),
                last_used_at=_parse_utc(row["last_used_at"]),
                revoked_at=_parse_utc(row["revoked_at"]),
            )
            for row in rows
        ]

    def _receipt_from_row(self, row: sqlite3.Row) -> ReuseReceipt:
        return ReuseReceipt(
            receipt_id=row["receipt_id"],
            user_id=row["user_id"],
            sequence_no=int(row["sequence_no"]),
            kind=row["kind"],
            subject_id=row["subject_id"],
            payload=dict(json.loads(row["payload_json"])),
            created_at=_parse_utc(row["created_at"]),  # type: ignore[arg-type]
            previous_receipt_hash=row["previous_receipt_hash"],
            receipt_hash=row["receipt_hash"],
        )

    def append_receipt(
        self,
        user_id: str,
        payload: Mapping[str, Any],
        *,
        kind: str = "reuse",
        subject_id: str | None = None,
    ) -> ReuseReceipt:
        if not isinstance(kind, str):
            raise ValidationError("receipt kind must contain 1 to 64 characters")
        clean_kind = kind.strip()
        if not clean_kind or len(clean_kind) > 64:
            raise ValidationError("receipt kind must contain 1 to 64 characters")
        if subject_id is not None and (not isinstance(subject_id, str) or len(subject_id) > 256):
            raise ValidationError("receipt subject is too long")
        payload_dict = dict(payload)
        payload_json = _canonical_json(payload_dict)
        receipt_id = _new_id("rcpt")
        created_at = self._now()
        with self._lock:
            self._get_user_row(user_id)
            self._con.execute("BEGIN IMMEDIATE")
            try:
                previous = self._con.execute(
                    """
                    SELECT sequence_no, receipt_hash
                    FROM reuse_receipts
                    WHERE user_id = ?
                    ORDER BY sequence_no DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
                sequence_no = int(previous["sequence_no"]) + 1 if previous else 1
                previous_hash = previous["receipt_hash"] if previous else None
                hash_input = {
                    "receipt_id": receipt_id,
                    "user_id": user_id,
                    "sequence_no": sequence_no,
                    "kind": clean_kind,
                    "subject_id": subject_id,
                    "payload": payload_dict,
                    "created_at": _format_utc(created_at),
                    "previous_receipt_hash": previous_hash,
                }
                receipt_hash = hashlib.sha256(_canonical_json(hash_input).encode("utf-8")).hexdigest()
                self._con.execute(
                    """
                    INSERT INTO reuse_receipts (
                      receipt_id, user_id, sequence_no, kind, subject_id,
                      payload_json, created_at, previous_receipt_hash,
                      receipt_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt_id,
                        user_id,
                        sequence_no,
                        clean_kind,
                        subject_id,
                        payload_json,
                        _format_utc(created_at),
                        previous_hash,
                        receipt_hash,
                    ),
                )
                self._con.commit()
            except Exception:
                self._con.rollback()
                raise
        return ReuseReceipt(
            receipt_id=receipt_id,
            user_id=user_id,
            sequence_no=sequence_no,
            kind=clean_kind,
            subject_id=subject_id,
            payload=payload_dict,
            created_at=created_at,
            previous_receipt_hash=previous_hash,
            receipt_hash=receipt_hash,
        )

    def get_receipt(self, user_id: str, receipt_id: str) -> ReuseReceipt:
        with self._lock:
            row = self._con.execute(
                """
                SELECT * FROM reuse_receipts
                WHERE user_id = ? AND receipt_id = ?
                """,
                (user_id, receipt_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("receipt not found")
        return self._receipt_from_row(row)

    def list_receipts(
        self,
        user_id: str,
        *,
        limit: int = 100,
        before_sequence: int | None = None,
    ) -> list[ReuseReceipt]:
        if limit < 1 or limit > 1000:
            raise ValidationError("receipt limit must be between 1 and 1000")
        with self._lock:
            self._get_user_row(user_id)
            if before_sequence is None:
                rows = self._con.execute(
                    """
                    SELECT * FROM reuse_receipts
                    WHERE user_id = ?
                    ORDER BY sequence_no DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
            else:
                rows = self._con.execute(
                    """
                    SELECT * FROM reuse_receipts
                    WHERE user_id = ? AND sequence_no < ?
                    ORDER BY sequence_no DESC
                    LIMIT ?
                    """,
                    (user_id, before_sequence, limit),
                ).fetchall()
        return [self._receipt_from_row(row) for row in rows]
