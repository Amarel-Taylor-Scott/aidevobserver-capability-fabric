"""Candidate-only Open WebUI wrapper.

The wrapper supports two execution modes:

- direct: call the Open WebUI chat endpoint with a bearer token from env;
- cdp: call the endpoint inside an already-authenticated browser page via the
  Chrome DevTools Protocol, without exporting cookies or tokens.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib import parse, request


DEFAULT_BASE_URL = "https://ui.iamretarded.net"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_ENDPOINT = "/api/chat/completions"
DEFAULT_MODEL = "gemma-4-coding"
DEFAULT_TOKEN_ENV = "OPENWEBUI_TOKEN"


@dataclass(frozen=True, slots=True)
class OpenWebUIConfig:
    base_url: str = DEFAULT_BASE_URL
    endpoint: str = DEFAULT_ENDPOINT
    model: str = DEFAULT_MODEL
    token_env: str = DEFAULT_TOKEN_ENV
    cdp_url: str = DEFAULT_CDP_URL
    candidate_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def chat_payload(prompt: str, model: str = DEFAULT_MODEL, *, system: str | None = None) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return {
        "model": model,
        "messages": messages,
        "stream": False,
    }


def redacted_plan(config: OpenWebUIConfig, *, mode: str = "direct") -> dict[str, Any]:
    return {
        "boundary": "candidate_llm_request_plan",
        "serves_truth": False,
        "candidate_only": True,
        "mode": mode,
        "provider": "open_webui",
        "base_url": config.base_url,
        "endpoint": config.endpoint,
        "model": config.model,
        "token_env": config.token_env,
        "headers": {
            "Content-Type": "application/json",
            "Authorization": "<redacted>" if mode == "direct" else "<browser-context>",
        },
    }


def normalize_chat_response(response: Any) -> dict[str, Any]:
    content = None
    finish_reason = None
    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                if content is None:
                    content = first.get("text")
                finish_reason = first.get("finish_reason") or first.get("stop_reason")
    return {
        "provider": "open_webui",
        "model": response.get("model") if isinstance(response, dict) else None,
        "assistant_content": content,
        "finish_reason": finish_reason,
        "usage": response.get("usage") if isinstance(response, dict) else None,
        "response_id": response.get("id") if isinstance(response, dict) else None,
        "candidate_only": True,
        "serves_truth": False,
    }


def direct_chat(
    config: OpenWebUIConfig,
    prompt: str,
    *,
    token: str | None = None,
    timeout: float = 120.0,
    system: str | None = None,
) -> dict[str, Any]:
    bearer = token or os.environ.get(config.token_env)
    if not bearer:
        raise RuntimeError(f"missing Open WebUI token environment variable: {config.token_env}")

    url = _join_url(config.base_url, config.endpoint)
    body = json.dumps(chat_payload(prompt, config.model, system=system)).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer}",
            "User-Agent": "aidevobserver-capability-fabric/0.1",
        },
    )
    with request.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    normalized = normalize_chat_response(data)
    normalized.update(
        {
            "base_url": config.base_url,
            "endpoint": config.endpoint,
            "prompt": prompt,
            "auth_mode": "direct_bearer_env",
        }
    )
    return normalized


def cdp_chat(
    config: OpenWebUIConfig,
    prompt: str,
    *,
    timeout: float = 120.0,
    system: str | None = None,
) -> dict[str, Any]:
    target = _find_openwebui_target(config.cdp_url, config.base_url, timeout=timeout)
    expression = _browser_fetch_expression(config.endpoint, chat_payload(prompt, config.model, system=system))
    value = _runtime_evaluate(target["webSocketDebuggerUrl"], expression, timeout=timeout)
    status = value.get("status") if isinstance(value, dict) else None
    response = value.get("response") if isinstance(value, dict) else None
    if status and int(status) >= 400:
        raise RuntimeError(f"Open WebUI browser-context request failed with HTTP {status}")
    normalized = normalize_chat_response(response)
    normalized.update(
        {
            "base_url": config.base_url,
            "endpoint": config.endpoint,
            "prompt": prompt,
            "auth_mode": "browser_context_token_not_exported",
            "http_status": status,
        }
    )
    return normalized


def save_result(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _join_url(base_url: str, endpoint: str) -> str:
    return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"


def _json_get(url: str, *, timeout: float) -> Any:
    with request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _find_openwebui_target(cdp_url: str, base_url: str, *, timeout: float) -> dict[str, Any]:
    host = parse.urlparse(base_url).netloc
    targets = _json_get(f"{cdp_url.rstrip('/')}/json/list", timeout=timeout)
    for target in targets:
        if target.get("type") == "page" and host in target.get("url", ""):
            return target
    raise RuntimeError(f"no Open WebUI page target for host {host!r} at {cdp_url}")


def _browser_fetch_expression(endpoint: str, payload: dict[str, Any]) -> str:
    return f"""(async () => {{
      const endpoint = {json.dumps(endpoint)};
      const payload = {json.dumps(payload)};
      const token = localStorage.getItem('token');
      const headers = {{'Content-Type': 'application/json', 'Accept': 'application/json'}};
      if (token) headers.Authorization = `Bearer ${{token}}`;
      const response = await fetch(endpoint, {{
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      }});
      const text = await response.text();
      let parsed = null;
      try {{ parsed = JSON.parse(text); }} catch (_) {{}}
      return {{
        status: response.status,
        ok: response.ok,
        contentType: response.headers.get('content-type'),
        response: parsed,
        textPrefix: parsed ? null : text.slice(0, 240)
      }};
    }})()"""


def _runtime_evaluate(websocket_url: str, expression: str, *, timeout: float) -> Any:
    ws = _MinimalWebSocket.connect(websocket_url, timeout=timeout)
    try:
        msg_id = 0

        def send(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            nonlocal msg_id
            msg_id += 1
            ws.send_json({"id": msg_id, "method": method, "params": params or {}})
            while True:
                msg = ws.recv_json()
                if msg.get("id") == msg_id:
                    return msg

        send("Runtime.enable")
        result = send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        )
        if "exceptionDetails" in result:
            raise RuntimeError("browser evaluation raised an exception")
        return result.get("result", {}).get("result", {}).get("value")
    finally:
        ws.close()


class _MinimalWebSocket:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    @classmethod
    def connect(cls, websocket_url: str, *, timeout: float) -> "_MinimalWebSocket":
        parsed = parse.urlparse(websocket_url)
        if parsed.scheme != "ws":
            raise RuntimeError("only ws:// DevTools endpoints are supported")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
        sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request_text = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request_text.encode("ascii"))
        response = sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError("DevTools WebSocket handshake failed")
        accept_source = (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        expected = base64.b64encode(hashlib.sha1(accept_source).digest())
        if expected not in response:
            raise RuntimeError("DevTools WebSocket accept header mismatch")
        return cls(sock)

    def send_json(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.sock.sendall(self._frame(payload))

    def recv_json(self) -> dict[str, Any]:
        while True:
            opcode, payload = self._read_frame()
            if opcode == 1:
                return json.loads(payload.decode("utf-8"))
            if opcode == 8:
                raise RuntimeError("DevTools WebSocket closed")
            if opcode == 9:
                self.sock.sendall(self._frame(payload, opcode=10))

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _frame(self, payload: bytes, *, opcode: int = 1) -> bytes:
        first = 0x80 | opcode
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", first, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", first, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first, 0x80 | 127, length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return header + mask + masked

    def _read_frame(self) -> tuple[int, bytes]:
        head = self._recv_exact(2)
        first, second = head
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _recv_exact(self, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise RuntimeError("unexpected EOF from DevTools WebSocket")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
