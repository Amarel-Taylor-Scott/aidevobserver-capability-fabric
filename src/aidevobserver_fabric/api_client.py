"""Small authenticated client used by the local MCP bridge."""

from __future__ import annotations

import json
import ipaddress
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class APIError(RuntimeError):
    """A sanitized error returned by the capability service."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


class _NoRedirect(HTTPRedirectHandler):
    """Never forward a bearer token through an HTTP redirect."""

    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def validate_base_url(base_url: str) -> str:
    if not isinstance(base_url, str):
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain credentials, query, or fragment")
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname.casefold() == "localhost"
    if parsed.scheme != "https" and not loopback:
        raise ValueError("non-loopback capability services must use HTTPS")
    return base_url.rstrip("/")


class FabricClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self.base_url = validate_base_url(base_url)
        self.token = token
        self.timeout = timeout
        self._opener = build_opener(_NoRedirect())

    def _safe_message(self, value: str) -> str:
        return value.replace(self.token, "<redacted>") if self.token else value

    @staticmethod
    def _is_json(headers: Any) -> bool:
        return headers.get_content_type() == "application/json"

    @staticmethod
    def _read_bounded(response: Any, maximum: int = 5_000_000) -> bytes:
        raw = response.read(maximum + 1)
        if len(raw) > maximum:
            raise APIError(0, "response_too_large", "Capability service response exceeded 5 MB")
        return raw

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if body is not None:
            try:
                payload = json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError):
                raise APIError(0, "invalid_request", "Request body must contain finite JSON values") from None
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=payload, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                if not self._is_json(response.headers):
                    raise APIError(response.status, "invalid_response", "Capability service returned non-JSON content")
                raw = self._read_bounded(response)
                try:
                    parsed = json.loads(raw, parse_constant=_reject_json_constant) if raw else {}
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                    raise APIError(response.status, "invalid_response", "Capability service returned malformed JSON") from None
                if not isinstance(parsed, dict):
                    raise APIError(response.status, "invalid_response", "Capability service response must be a JSON object")
                return parsed
        except HTTPError as exc:
            raw = self._read_bounded(exc)
            try:
                parsed = json.loads(raw, parse_constant=_reject_json_constant) if raw and self._is_json(exc.headers) else {}
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                parsed = {}
            if not isinstance(parsed, dict):
                parsed = {}
            code = self._safe_message(str(parsed.get("error", "http_error")))
            message = self._safe_message(str(parsed.get("message", f"Capability service returned HTTP {exc.code}")))
            raise APIError(exc.code, code, message) from None
        except (URLError, TimeoutError, OSError) as exc:
            # Never include the request object or headers: they contain the PAT.
            reason = getattr(exc, "reason", None)
            safe_reason = type(reason or exc).__name__
            raise APIError(0, "connection_error", f"Could not reach capability service ({safe_reason})") from None

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/v1/health")

    def me(self) -> dict[str, Any]:
        return self.request("GET", "/v1/me")

    def search(self, query: str, filters: dict[str, Any] | None = None, limit: int = 6) -> dict[str, Any]:
        return self.request(
            "POST",
            "/v1/primitives/search",
            {"query": query, "filters": filters if filters is not None else {}, "limit": limit},
        )

    def get(self, primitive_id: str) -> dict[str, Any]:
        return self.request("GET", f"/v1/primitives/{quote(primitive_id, safe='')}")

    def execute(self, primitive_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/v1/primitives/{quote(primitive_id, safe='')}/execute",
            {"inputs": inputs},
        )

    def prove(self, primitive_id: str) -> dict[str, Any]:
        return self.request("POST", f"/v1/primitives/{quote(primitive_id, safe='')}/prove", {})

    def record_reuse(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/v1/reuse-receipts", payload)

    def list_receipts(self) -> dict[str, Any]:
        return self.request("GET", "/v1/reuse-receipts")
