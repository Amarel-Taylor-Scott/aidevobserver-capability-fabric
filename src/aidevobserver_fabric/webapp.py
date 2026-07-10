"""Authenticated local website and versioned JSON API."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import secrets
import shlex
import shutil
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import auth
from .service import ProductService, ServiceError, validate_reuse_payload


MAX_BODY_BYTES = 10_000_000
SESSION_COOKIE = "ado_session"
CSRF_COOKIE = "ado_csrf"
PREAUTH_COOKIE = "ado_pre_csrf"
ALL_AGENT_SCOPES = (
    "primitives:read",
    "primitives:execute",
    "proofs:run",
    "receipts:read",
    "receipts:write",
)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _preauth_rate_identity(peer_address: str, email: str) -> str:
    """Scope unauthenticated throttles to one account at one network peer.

    TLS deployments normally see their reverse proxy as the peer address. A
    peer-only key would therefore let a handful of failures lock out every
    account behind that proxy. Hashing the normalized account keeps the
    in-memory rate key non-identifying while isolating accounts even when the
    peer is shared.
    """

    normalized = email.strip().casefold()
    account_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{peer_address}:{account_digest}"


class WebError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · AIDevObserver</title>
<style>
:root{{--ink:#12221d;--muted:#5b6d66;--line:#d7e2dc;--paper:#fbfdfb;--card:#fff;--accent:#196b52;--accent2:#d8f5e8;--warn:#8a4d0f}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(140deg,#eef8f2 0,#fbfdfb 42%,#f5f1e8 100%);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,sans-serif}}
main{{max-width:1080px;margin:auto;padding:42px 22px 70px}} nav{{display:flex;justify-content:space-between;align-items:center;margin-bottom:42px}} .brand{{font-weight:800;letter-spacing:-.02em;font-size:19px}} .pill{{padding:6px 11px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font-size:12px;background:#ffffffaa}}
h1{{font-size:clamp(35px,6vw,66px);line-height:.98;letter-spacing:-.055em;margin:.2em 0}} h2{{margin:0 0 14px;font-size:22px;letter-spacing:-.025em}} h3{{margin:0 0 8px;font-size:16px}} p{{color:var(--muted)}} .lede{{font-size:19px;max-width:720px}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin-top:28px}} .card{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px;box-shadow:0 12px 36px #244b3b0a}} .metric{{font-size:32px;font-weight:760;letter-spacing:-.04em}} label{{display:block;color:var(--muted);font-size:13px;margin:12px 0 5px}} input,textarea,select{{width:100%;border:1px solid #becdc5;border-radius:10px;padding:11px 12px;background:#fff;color:var(--ink);font:inherit}} textarea{{min-height:120px}} button,.button{{display:inline-block;border:0;border-radius:10px;padding:10px 15px;margin-top:14px;background:var(--accent);color:white;font-weight:700;text-decoration:none;cursor:pointer}} button.secondary{{background:#edf3ef;color:var(--ink);border:1px solid var(--line)}} .row{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}} .between{{justify-content:space-between}} .notice{{border-left:4px solid var(--accent);background:var(--accent2);padding:12px 15px;border-radius:8px;margin:18px 0}} .error{{border-left-color:#a53d2d;background:#fbe9e5;color:#792a20}} code,pre{{font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}} pre{{overflow:auto;background:#10241d;color:#dcf6ea;padding:15px;border-radius:12px;white-space:pre-wrap;word-break:break-word}} .result{{padding:14px 0;border-top:1px solid var(--line)}} .result:first-child{{border-top:0}} .tag{{display:inline-block;font-size:11px;padding:3px 8px;border-radius:999px;background:var(--accent2);color:#155642;margin-right:5px}} .muted{{color:var(--muted)}} .small{{font-size:12px}} form.inline{{display:inline}} form.inline button{{margin:0;padding:6px 9px;font-size:12px}} table{{width:100%;border-collapse:collapse}} td,th{{padding:9px 5px;border-bottom:1px solid var(--line);text-align:left;font-size:13px;vertical-align:top}} footer{{margin-top:35px;color:var(--muted);font-size:12px}}
</style></head><body><main><nav><div class="brand">AIDevObserver</div><div class="pill">Capability Fabric · local preview</div></nav>{body}<footer>Search before building. Execute only packaged, proof-carrying primitives.</footer></main></body></html>"""


def _landing(message: str | None = None, error: bool = False, pre_csrf: str = "") -> str:
    notice = ""
    if message:
        notice = f'<div class="notice {"error" if error else ""}">{html.escape(message)}</div>'
    return _page(
        "Reuse what already works",
        f"""<section><div class="pill">Primitive-aware coding agents</div>
<h1>Stop rebuilding<br>the solved parts.</h1>
<p class="lede">Create an account, mint one scoped agent token, and connect Codex or Claude Code. Your agent can search, inspect, execute, prove, and materialize reusable primitives without loading the whole catalog into context.</p></section>
{notice}<div class="grid">
<section class="card"><h2>Create account</h2><p>Local preview accounts stay in your SQLite database.</p>
<form method="post" action="/signup"><input type="hidden" name="pre_csrf" value="{html.escape(pre_csrf)}"><label>Email</label><input type="email" name="email" autocomplete="email" required><label>Password</label><input type="password" name="password" minlength="8" autocomplete="new-password" required><button>Create account</button></form></section>
<section class="card"><h2>Sign in</h2><p>Return to tokens, primitive search, proofs, and receipts.</p>
<form method="post" action="/login"><input type="hidden" name="pre_csrf" value="{html.escape(pre_csrf)}"><label>Email</label><input type="email" name="email" autocomplete="email" required><label>Password</label><input type="password" name="password" autocomplete="current-password" required><button>Sign in</button></form></section>
</div>""",
    )


def _install_commands(server: ProductHTTPServer) -> tuple[str | None, str, str, str]:
    base_url = server.public_url
    quoted_url = shlex.quote(base_url)
    login = f"aidevobserver-fabric auth login --server {quoted_url}"
    mcp = "aidevobserver-mcp"
    codex = (
        "codex mcp add aidevobserver "
        f"--env AIDEVOBSERVER_URL={quoted_url} "
        f"-- {mcp}"
    )
    claude = (
        "claude mcp add "
        f"--env AIDEVOBSERVER_URL={quoted_url} "
        f"--transport stdio --scope user aidevobserver -- {mcp}"
    )
    return server.bridge_install_command, login, codex, claude


def _dashboard(
    server: ProductHTTPServer,
    principal: auth.SessionPrincipal,
    csrf_token: str,
    *,
    message: str | None = None,
    error: bool = False,
    issued_token: str | None = None,
    search_result: dict[str, Any] | None = None,
    proof_result: dict[str, Any] | None = None,
) -> str:
    tokens = server.auth_store.list_api_tokens(principal.user_id)
    receipts = server.auth_store.list_receipts(principal.user_id, limit=10)
    notice = f'<div class="notice {"error" if error else ""}">{html.escape(message)}</div>' if message else ""
    token_panel = ""
    if issued_token:
        install, login, codex, claude = _install_commands(server)
        install_step = (
            f'<h3>0. Install the local bridge once</h3><pre>{html.escape(install)}</pre>'
            if install
            else '<div class="notice error">This service has not published a bridge installer. Ask the operator for the AIDevObserver 0.2 package.</div>'
        )
        token_panel = f"""<section class="card"><h2>Your token — shown once</h2><p>Copy it now. Only its SHA-256 digest is stored.</p>
<pre>{html.escape(issued_token)}</pre>{install_step}<h3>1. Store it without shell history</h3><pre>{html.escape(login)}</pre><p class="small muted">The command prompts privately and writes a mode-0600 credentials file.</p><h3>2. Connect Codex</h3><pre>{html.escape(codex)}</pre><h3>Or connect Claude Code</h3><pre>{html.escape(claude)}</pre></section>"""

    results_html = ""
    if search_result is not None:
        rows = []
        for item in search_result.get("results", []):
            primitive_id = html.escape(item["primitive_id"])
            rows.append(
                f"""<div class="result"><div class="row between"><div><strong>{html.escape(item['label'])}</strong><br><code>{primitive_id}</code></div><span class="tag">{html.escape(item.get('trust',''))}</span></div>
<p>{html.escape(item.get('description',''))}</p><div class="small muted">source sha256 {html.escape(item.get('source_sha256','')[:16])}… · {item.get('proof_case_count',0)} proof cases</div>
<form class="inline" method="post" action="/app/prove"><input type="hidden" name="csrf" value="{html.escape(csrf_token)}"><input type="hidden" name="primitive_id" value="{primitive_id}"><button class="secondary">Run proof</button></form></div>"""
            )
        if not rows:
            rows.append('<p class="muted">No executable primitive matched. Try describing the capability rather than a package name.</p>')
        results_html = f'<section class="card"><h2>Search results</h2>{"".join(rows)}</section>'

    proof_html = ""
    if proof_result is not None:
        passed = bool(proof_result.get("proof", {}).get("passed"))
        proof_html = f"""<section class="card"><h2>Proof {'passed' if passed else 'failed'}</h2><pre>{html.escape(json.dumps(proof_result, indent=2, sort_keys=True))}</pre></section>"""

    token_rows = []
    now = datetime.now(timezone.utc)
    for item in tokens:
        state = "revoked" if item.revoked_at else "expired" if item.expires_at and item.expires_at <= now else "active"
        revoke = ""
        if item.revoked_at is None:
            revoke = f"""<form class="inline" method="post" action="/app/tokens/revoke"><input type="hidden" name="csrf" value="{html.escape(csrf_token)}"><input type="hidden" name="token_id" value="{html.escape(item.token_id)}"><button class="secondary">Revoke</button></form>"""
        expiry = item.expires_at.date().isoformat() if item.expires_at else "never"
        token_rows.append(f"<tr><td>{html.escape(item.name)}<br><span class='small muted'>ado_pat_{html.escape(item.public_id)}.… · {html.escape(', '.join(item.scopes))}</span></td><td>{state}<br><span class='small muted'>expires {expiry}</span></td><td>{revoke}</td></tr>")
    token_table = "".join(token_rows) or '<tr><td colspan="3" class="muted">No agent tokens yet.</td></tr>'
    receipt_rows = "".join(
        f"<tr><td>#{item.sequence_no}</td><td>{html.escape(item.kind)}</td><td><code>{html.escape(item.receipt_id[:20])}…</code></td></tr>"
        for item in receipts
    ) or '<tr><td colspan="3" class="muted">No reuse receipts yet.</td></tr>'

    return _page(
        "Workspace",
        f"""<div class="row between"><div><h1 style="font-size:42px">Agent workspace</h1><p>{html.escape(principal.email)}</p></div>
<form method="post" action="/logout"><input type="hidden" name="csrf" value="{html.escape(csrf_token)}"><button class="secondary">Sign out</button></form></div>{notice}
<div class="grid"><section class="card"><div class="metric">{server.product.executable_count}</div><h3>executable primitives</h3><p>Packaged source, schemas, deterministic fixtures, and content digests—not catalog stubs.</p></section>
<section class="card"><div class="metric">6</div><h3>MCP tools</h3><p>Search, inspect, execute, materialize, prove, and record reuse.</p></section>
<section class="card"><div class="metric">{len(receipts)}</div><h3>recent receipts</h3><p>Account-scoped, append-only, hash-chained reuse evidence.</p></section></div>
<div class="grid"><section class="card"><h2>Connect an agent</h2><p>Create a scoped personal token. The secret is displayed once.</p>
<form method="post" action="/app/tokens"><input type="hidden" name="csrf" value="{html.escape(csrf_token)}"><label>Token name</label><input name="name" value="My coding agent" maxlength="100" required><label>Access profile</label><select name="profile"><option value="full">Full reuse workflow (90 days)</option><option value="discovery">Search and inspect only (90 days)</option></select><button>Create token</button></form>
<table><thead><tr><th>Name</th><th>Status</th><th></th></tr></thead><tbody>{token_table}</tbody></table></section>
<section class="card"><h2>Find a primitive</h2><p>Use intent, inputs, and expected outcome. Search returns executable matches by default.</p>
<form method="post" action="/app/search"><input type="hidden" name="csrf" value="{html.escape(csrf_token)}"><label>What are you trying to build?</label><input name="query" placeholder="Extract email addresses from unstructured text" required><button>Search primitives</button></form></section></div>
<div class="grid">{token_panel}{results_html}{proof_html}</div>
<section class="card" style="margin-top:18px"><h2>Reuse receipts</h2><table><thead><tr><th>Sequence</th><th>Kind</th><th>Receipt</th></tr></thead><tbody>{receipt_rows}</tbody></table></section>""",
    )


class ProductHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(
        self,
        address: tuple[str, int],
        db_path: Path,
        *,
        public_url: str | None = None,
        secure_cookie: bool = False,
        signup_mode: str | None = None,
        bridge_install_command: str | None = None,
    ) -> None:
        bind_host = address[0]
        try:
            loopback_bind = ipaddress.ip_address(bind_host).is_loopback
        except ValueError:
            loopback_bind = bind_host.casefold() == "localhost"
        if not loopback_bind and (not public_url or urlparse(public_url).scheme != "https"):
            raise ValueError("non-loopback service binding requires an HTTPS public_url")
        self.product = ProductService(db_path)
        self.auth_store = auth.AuthStore(db_path)
        self._rate_lock = threading.Lock()
        self._rate_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        super().__init__(address, ProductHandler)
        host, port = self.server_address[:2]
        display_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
        self.public_url = (public_url or f"http://{display_host}:{port}").rstrip("/")
        public_scheme = urlparse(self.public_url).scheme
        public_host = (urlparse(self.public_url).hostname or "").casefold()
        install_override = bridge_install_command or os.environ.get("AIDEVOBSERVER_INSTALL_COMMAND")
        source_root = Path(__file__).resolve().parents[2]
        local_install = None
        if public_host in {"localhost", "127.0.0.1", "::1"}:
            installed_bridge = shutil.which("aidevobserver-mcp")
            if installed_bridge:
                local_install = f"# Bridge already installed at {shlex.quote(installed_bridge)}"
            elif (source_root / "pyproject.toml").is_file():
                local_install = f"pipx install {shlex.quote(str(source_root))}"
        self.bridge_install_command = install_override or local_install
        self.secure_cookie = bool(secure_cookie or public_scheme == "https")
        self.signup_mode = signup_mode or ("disabled" if public_scheme == "https" else "local")
        if self.signup_mode not in {"local", "open", "disabled"}:
            self.server_close()
            raise ValueError("signup_mode must be local, open, or disabled")

    def check_rate(self, bucket: str, identity: str, *, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        key = (bucket, identity)
        with self._rate_lock:
            events = self._rate_events[key]
            while events and events[0] <= now - window_seconds:
                events.popleft()
            if len(events) >= limit:
                raise WebError(429, "rate_limited", "Too many requests; try again later")
            events.append(now)

    def server_close(self) -> None:
        super().server_close()
        self.auth_store.close()


class ProductHandler(BaseHTTPRequestHandler):
    server: ProductHTTPServer
    server_version = "AIDevObserver/0.2"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")
        if self.server.secure_cookie:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = (json.dumps(jsonable(payload), allow_nan=False, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, payload: str, status: int = 200) -> None:
        body = payload.encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_landing(self, message: str | None = None, *, error: bool = False, status: int = 200) -> None:
        pre_csrf = "ado_pre_" + secrets.token_urlsafe(24)
        body = _landing(message, error=error, pre_csrf=pre_csrf).encode("utf-8")
        secure = "; Secure" if self.server.secure_cookie else ""
        self.send_response(status)
        self._security_headers()
        self.send_header("Set-Cookie", f"{PREAUTH_COOKIE}={pre_csrf}; Path=/; HttpOnly; SameSite=Strict; Max-Age=600{secure}")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location: str) -> None:
        self.send_response(303)
        self._security_headers()
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cookies(self) -> SimpleCookie[str]:
        cookie: SimpleCookie[str] = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        return cookie

    def _cookie_value(self, name: str) -> str:
        item = self._cookies().get(name)
        return item.value if item else ""

    def _set_login_cookies(self, issued: auth.IssuedWebSession) -> None:
        secure = "; Secure" if self.server.secure_cookie else ""
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}={issued.session_token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=28800{secure}")
        self.send_header("Set-Cookie", f"{CSRF_COOKIE}={issued.csrf_token}; Path=/; SameSite=Lax; Max-Age=28800{secure}")

    def _clear_login_cookies(self) -> None:
        secure = "; Secure" if self.server.secure_cookie else ""
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}")
        self.send_header("Set-Cookie", f"{CSRF_COOKIE}=; Path=/; SameSite=Lax; Max-Age=0{secure}")

    def _login_redirect(self, issued: auth.IssuedWebSession) -> None:
        self.send_response(303)
        self._security_headers()
        self._set_login_cookies(issued)
        self.send_header("Location", "/app")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_body(self, maximum: int = MAX_BODY_BYTES) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise WebError(400, "invalid_content_length", "Invalid Content-Length") from None
        if length < 0 or length > maximum:
            raise WebError(413, "body_too_large", "Request body is too large")
        return self.rfile.read(length)

    def _read_form(self) -> dict[str, str]:
        try:
            values = parse_qs(self._read_body(64_000).decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            raise WebError(400, "invalid_form", "Form must be UTF-8") from None
        return {key: items[-1] for key, items in values.items()}

    def _read_json(self) -> dict[str, Any]:
        try:
            value = json.loads(self._read_body() or b"{}", parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise WebError(400, "invalid_json", "Request body must be a JSON object") from None
        if not isinstance(value, dict):
            raise WebError(400, "invalid_json", "Request body must be a JSON object")
        return value

    def _session(self) -> auth.SessionPrincipal | None:
        return self.server.auth_store.get_session(self._cookie_value(SESSION_COOKIE))

    def _require_session(self) -> tuple[auth.SessionPrincipal, str, str]:
        session_token = self._cookie_value(SESSION_COOKIE)
        principal = self.server.auth_store.authenticate_session(session_token)
        return principal, session_token, self._cookie_value(CSRF_COOKIE)

    def _require_same_origin(self) -> None:
        if self.headers.get("Sec-Fetch-Site", "").casefold() == "cross-site":
            raise auth.AuthorizationError("Cross-site form submission is not allowed")
        origin = self.headers.get("Origin")
        if not origin:
            return
        supplied = urlparse(origin)
        expected = urlparse(self.server.public_url)
        if (
            supplied.scheme.casefold(),
            supplied.netloc.casefold(),
        ) != (
            expected.scheme.casefold(),
            expected.netloc.casefold(),
        ):
            raise auth.AuthorizationError("Form origin is not allowed")

    def _require_preauth_csrf(self, form: dict[str, str]) -> None:
        self._require_same_origin()
        submitted = form.get("pre_csrf", "")
        cookie = self._cookie_value(PREAUTH_COOKIE)
        if not submitted or not cookie or not secrets.compare_digest(submitted, cookie):
            raise auth.AuthorizationError("Pre-authentication CSRF token is invalid")

    def _require_form_csrf(self, form: dict[str, str]) -> auth.SessionPrincipal:
        self._require_same_origin()
        principal, session_token, cookie_csrf = self._require_session()
        submitted = form.get("csrf", "")
        if not submitted or submitted != cookie_csrf:
            raise auth.AuthorizationError("CSRF token is invalid")
        self.server.auth_store.require_csrf(session_token, submitted)
        return principal

    def _rate(self, bucket: str, identity: str, *, limit: int, window_seconds: int) -> None:
        self.server.check_rate(bucket, identity, limit=limit, window_seconds=window_seconds)

    def _bearer(self, *scopes: str) -> auth.TokenPrincipal:
        return self.server.auth_store.authenticate_bearer(
            self.headers.get("Authorization", ""),
            required_scopes=scopes,
        )

    def _handle_error(self, exc: Exception) -> None:
        if isinstance(exc, ServiceError):
            status, code, message = exc.status, exc.code, str(exc)
        elif isinstance(exc, WebError):
            status, code, message = exc.status, exc.code, str(exc)
        elif isinstance(exc, auth.AuthenticationError):
            status, code, message = 401, "unauthorized", str(exc)
        elif isinstance(exc, auth.AuthorizationError):
            status, code, message = 403, "forbidden", str(exc)
        elif isinstance(exc, auth.ConflictError):
            status, code, message = 409, "conflict", str(exc)
        elif isinstance(exc, auth.NotFoundError):
            status, code, message = 404, "not_found", str(exc)
        elif isinstance(exc, (auth.ValidationError, auth.InvalidCredentialsError)):
            status = 401 if isinstance(exc, auth.InvalidCredentialsError) else 400
            code, message = "invalid_credentials" if status == 401 else "invalid_request", str(exc)
        else:
            status, code, message = 500, "internal_error", "Unexpected service error"
        if urlparse(self.path).path.startswith("/v1/"):
            self.send_json({"error": code, "message": message}, status)
        else:
            self.send_landing(message, error=True, status=status)

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._do_get()
        except Exception as exc:  # centralized sanitization
            self._handle_error(exc)

    def _do_get(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/health":
            self.send_json({"status": "ok", "version": "0.2.0", "executable_primitives": self.server.product.executable_count})
            return
        if path == "/v1/me":
            principal = self._bearer()
            self.send_json({"user_id": principal.user_id, "email": principal.email, "token_name": principal.name, "scopes": principal.scopes})
            return
        match = re.fullmatch(r"/v1/primitives/([^/]+)", path)
        if match:
            self._bearer("primitives:read")
            self.send_json(self.server.product.get(unquote(match.group(1))))
            return
        if path == "/v1/reuse-receipts":
            principal = self._bearer("receipts:read")
            self.send_json({"receipts": self.server.auth_store.list_receipts(principal.user_id)})
            return
        if path == "/":
            if self._session() is not None:
                self.redirect("/app")
            else:
                self.send_landing()
            return
        if path == "/app":
            principal, _, csrf_token = self._require_session()
            self.send_html(_dashboard(self.server, principal, csrf_token))
            return
        raise WebError(404, "not_found", "Page not found")

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._do_post()
        except Exception as exc:  # centralized sanitization
            self._handle_error(exc)

    def _do_post(self) -> None:
        path = urlparse(self.path).path
        if path == "/signup":
            form = self._read_form()
            self._require_preauth_csrf(form)
            self._rate(
                "signup",
                _preauth_rate_identity(self.client_address[0], form.get("email", "")),
                limit=5,
                window_seconds=600,
            )
            if self.server.signup_mode == "disabled":
                raise auth.AuthorizationError("Public signup is disabled")
            if self.server.signup_mode == "local":
                issued = self.server.auth_store.signup_first_user(form.get("email", ""), form.get("password", ""))
            else:
                issued = self.server.auth_store.signup(form.get("email", ""), form.get("password", ""))
            self._login_redirect(issued)
            return
        if path == "/login":
            form = self._read_form()
            self._require_preauth_csrf(form)
            self._rate(
                "login",
                _preauth_rate_identity(self.client_address[0], form.get("email", "")),
                limit=8,
                window_seconds=300,
            )
            self._login_redirect(self.server.auth_store.login(form.get("email", ""), form.get("password", "")))
            return
        if path == "/logout":
            form = self._read_form()
            self._require_form_csrf(form)
            self.server.auth_store.logout(self._cookie_value(SESSION_COOKIE))
            self.send_response(303)
            self._security_headers()
            self._clear_login_cookies()
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/app/tokens":
            form = self._read_form()
            principal = self._require_form_csrf(form)
            self._rate("token", principal.user_id, limit=10, window_seconds=3600)
            profile = form.get("profile", "full")
            if profile == "full":
                scopes = ALL_AGENT_SCOPES
            elif profile == "discovery":
                scopes = ("primitives:read",)
            else:
                raise auth.ValidationError("Unknown token access profile")
            issued = self.server.auth_store.create_api_token(
                principal.user_id,
                form.get("name", "Coding agent"),
                scopes,
                expires_at=datetime.now(timezone.utc) + timedelta(days=90),
            )
            self.send_html(_dashboard(self.server, principal, form["csrf"], message="Token created. Copy it now.", issued_token=issued.token))
            return
        if path == "/app/tokens/revoke":
            form = self._read_form()
            principal = self._require_form_csrf(form)
            self.server.auth_store.revoke_api_token(principal.user_id, form.get("token_id", ""))
            self.send_html(_dashboard(self.server, principal, form["csrf"], message="Token revoked."))
            return
        if path == "/app/search":
            form = self._read_form()
            principal = self._require_form_csrf(form)
            self._rate("browser_search", principal.user_id, limit=120, window_seconds=60)
            result = self.server.product.search(form.get("query", ""))
            self.send_html(_dashboard(self.server, principal, form["csrf"], search_result=result))
            return
        if path == "/app/prove":
            form = self._read_form()
            principal = self._require_form_csrf(form)
            self._rate("browser_proof", principal.user_id, limit=30, window_seconds=60)
            result = self.server.product.prove(form.get("primitive_id", ""))
            self.send_html(_dashboard(self.server, principal, form["csrf"], proof_result=result))
            return
        if path == "/v1/primitives/search":
            principal = self._bearer("primitives:read")
            self._rate("search", principal.token_id, limit=120, window_seconds=60)
            body = self._read_json()
            self.send_json(self.server.product.search(body.get("query"), body.get("filters"), body.get("limit", 6)))
            return
        match = re.fullmatch(r"/v1/primitives/([^/]+)/(execute|prove)", path)
        if match:
            primitive_id, action = unquote(match.group(1)), match.group(2)
            if action == "execute":
                principal = self._bearer("primitives:execute")
                self._rate("execute", principal.token_id, limit=60, window_seconds=60)
                body = self._read_json()
                self.send_json(self.server.product.execute(primitive_id, body.get("inputs")))
            else:
                principal = self._bearer("proofs:run")
                self._rate("proof", principal.token_id, limit=30, window_seconds=60)
                body = self._read_json()
                self.send_json(self.server.product.prove(primitive_id))
            return
        if path == "/v1/reuse-receipts":
            principal = self._bearer("receipts:write")
            self._rate("receipt", principal.token_id, limit=120, window_seconds=60)
            body = self._read_json()
            if "payload" in body:
                unknown = set(body) - {"payload", "kind", "subject_id"}
                if unknown:
                    raise WebError(400, "invalid_receipt", f"unknown receipt envelope fields: {', '.join(sorted(unknown))}")
                payload = validate_reuse_payload(body["payload"])
            else:
                payload = validate_reuse_payload(body)
            subject_id = body.get("subject_id") if "payload" in body else None
            if subject_id is not None and not isinstance(subject_id, str):
                raise WebError(400, "invalid_receipt", "subject_id must be a string")
            if subject_id is not None and subject_id != payload["primitive_id"]:
                raise WebError(400, "invalid_receipt", "subject_id must match primitive_id")
            kind = body.get("kind", "reuse") if "payload" in body else "reuse"
            if kind not in {"reuse", "materialization"}:
                raise WebError(400, "invalid_receipt", "receipt kind is not supported")
            receipt = self.server.auth_store.append_receipt(
                principal.user_id,
                payload,
                kind=kind,
                subject_id=subject_id,
            )
            self.send_json({"receipt": receipt}, status=201)
            return
        raise WebError(404, "not_found", "Page not found")

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_server(
    host: str,
    port: int,
    db_path: Path,
    *,
    public_url: str | None = None,
    secure_cookie: bool = False,
    signup_mode: str | None = None,
    bridge_install_command: str | None = None,
) -> ProductHTTPServer:
    return ProductHTTPServer(
        (host, port),
        db_path,
        public_url=public_url,
        secure_cookie=secure_cookie,
        signup_mode=signup_mode,
        bridge_install_command=bridge_install_command,
    )


def serve(
    host: str,
    port: int,
    db_path: Path,
    *,
    public_url: str | None = None,
    secure_cookie: bool | None = None,
    signup_mode: str | None = None,
    bridge_install_command: str | None = None,
) -> None:
    if secure_cookie is None:
        secure_cookie = os.environ.get("AIDEVOBSERVER_SECURE_COOKIE") == "1"
    try:
        loopback_bind = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback_bind = host.casefold() == "localhost"
    if not loopback_bind and (not public_url or urlparse(public_url).scheme != "https"):
        raise ValueError("non-loopback service binding requires an HTTPS --public-url")
    server = create_server(
        host,
        port,
        db_path,
        public_url=public_url,
        secure_cookie=secure_cookie,
        signup_mode=signup_mode,
        bridge_install_command=bridge_install_command,
    )
    print(f"AIDevObserver serving {server.public_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
