"""Candidate-only Ollama chat wrapper."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib import request


DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma4:latest"
DEFAULT_TIMEOUT = 120.0


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    host: str = DEFAULT_HOST
    model: str = DEFAULT_MODEL
    candidate_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def chat_payload(
    prompt: str,
    model: str = DEFAULT_MODEL,
    *,
    system: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.0,
) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }


def redacted_plan(config: OllamaConfig) -> dict[str, Any]:
    return {
        "boundary": "candidate_llm_request_plan",
        "serves_truth": False,
        "candidate_only": True,
        "provider": "ollama",
        "host": config.host,
        "endpoint": "/api/chat",
        "model": config.model,
        "headers": {
            "Content-Type": "application/json",
            "Authorization": "<none-for-local-ollama>",
        },
    }


def list_models(config: OllamaConfig, *, timeout: float = 10.0) -> dict[str, Any]:
    response = _post_or_get_json(f"{config.host.rstrip('/')}/api/tags", timeout=timeout)
    models = []
    if isinstance(response, dict):
        for model in response.get("models", []):
            if isinstance(model, dict):
                models.append(model.get("name") or model.get("model"))
    return {
        "provider": "ollama",
        "host": config.host,
        "models": [model for model in models if model],
        "candidate_only": True,
        "serves_truth": False,
    }


def normalize_chat_response(response: Any) -> dict[str, Any]:
    message_content = None
    if isinstance(response, dict):
        message = response.get("message")
        if isinstance(message, dict):
            message_content = message.get("content")
    return {
        "provider": "ollama",
        "model": response.get("model") if isinstance(response, dict) else None,
        "assistant_content": message_content,
        "done": response.get("done") if isinstance(response, dict) else None,
        "done_reason": response.get("done_reason") if isinstance(response, dict) else None,
        "prompt_eval_count": response.get("prompt_eval_count") if isinstance(response, dict) else None,
        "eval_count": response.get("eval_count") if isinstance(response, dict) else None,
        "total_duration": response.get("total_duration") if isinstance(response, dict) else None,
        "candidate_only": True,
        "serves_truth": False,
    }


def chat(
    config: OllamaConfig,
    prompt: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    system: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.0,
) -> dict[str, Any]:
    url = f"{config.host.rstrip('/')}/api/chat"
    payload = chat_payload(
        prompt,
        config.model,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    response = _post_or_get_json(url, payload, timeout=timeout)
    normalized = normalize_chat_response(response)
    normalized.update(
        {
            "host": config.host,
            "endpoint": "/api/chat",
            "prompt": prompt,
            "auth_mode": "local_ollama_no_bearer",
        }
    )
    return normalized


def save_result(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _post_or_get_json(url: str, payload: dict[str, Any] | None = None, *, timeout: float) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": "aidevobserver-capability-fabric/0.1",
    }
    data = None
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"

    api_key = os.environ.get("OLLAMA_API_KEY")
    if api_key and "localhost" not in url and "127.0.0.1" not in url:
        headers["Authorization"] = f"Bearer {api_key}"

    req = request.Request(url, data=data, method=method, headers=headers)
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
