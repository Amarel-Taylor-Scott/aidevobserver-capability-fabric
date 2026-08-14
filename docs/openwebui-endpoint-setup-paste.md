# Open WebUI Gemma Coding Endpoint Setup

Use this document as a paste-ready integration brief for another program or
agent that needs to call the local Open WebUI-hosted coding model.

## Endpoint Summary

```text
Provider: Open WebUI
Base URL: https://ui.iamretarded.net
Chat endpoint: /api/chat/completions
Full URL: https://ui.iamretarded.net/api/chat/completions
Model: gemma-4-coding
Request shape: OpenAI-style chat completions
Response shape: OpenAI-style chat completion JSON
```

Observed working model:

```text
gemma-4-coding
```

Observed response metadata:

```text
object: chat.completion
system_fingerprint: vllm-...
usage.prompt_tokens
usage.completion_tokens
usage.total_tokens
```

## Important Auth Note

Raw unauthenticated HTTP requests are blocked by Cloudflare. Direct API calls
need a valid Open WebUI bearer token or another allowed service-token path.

Two supported modes:

```text
1. Direct mode:
   Program sends Authorization: Bearer <OPENWEBUI_TOKEN>

2. Browser-context mode:
   Program calls the endpoint from inside an already logged-in browser page
   through Chrome DevTools Protocol.
```

Do not hardcode passwords, cookies, bearer tokens, or browser storage dumps in
source files. Use environment variables, a local credential broker, or an
already authenticated browser context.

## Environment Variables

Recommended:

```bash
export OPENWEBUI_BASE_URL="https://ui.iamretarded.net"
export OPENWEBUI_MODEL="gemma-4-coding"
export OPENWEBUI_TOKEN="<your-openwebui-bearer-token-if-available>"
```

If using browser-context mode:

```bash
export OPENWEBUI_CDP_URL="http://127.0.0.1:9222"
```

## Direct API Request

Use this only when `OPENWEBUI_TOKEN` is valid and the host accepts direct API
traffic.

```bash
curl -sS "$OPENWEBUI_BASE_URL/api/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENWEBUI_TOKEN" \
  --data '{
    "model": "gemma-4-coding",
    "stream": false,
    "messages": [
      {
        "role": "user",
        "content": "Print exactly: Open WebUI integration OK"
      }
    ]
  }'
```

Expected response shape:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "gemma-4-coding",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Open WebUI integration OK"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

## Minimal Python Direct Client

```python
from __future__ import annotations

import json
import os
import urllib.request


BASE_URL = os.environ.get("OPENWEBUI_BASE_URL", "https://ui.iamretarded.net")
MODEL = os.environ.get("OPENWEBUI_MODEL", "gemma-4-coding")
TOKEN = os.environ["OPENWEBUI_TOKEN"]


def chat(prompt: str) -> dict:
    body = {
        "model": MODEL,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }
    request = urllib.request.Request(
        f"{BASE_URL.rstrip('/')}/api/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    result = chat("Print exactly: Open WebUI integration OK")
    print(result["choices"][0]["message"]["content"])
    print(result.get("usage", {}))
```

## Browser-Context Mode

Use browser-context mode when direct HTTP is challenged but the UI works after
login.

This is the mode we actually used to get the endpoint working.

## How We Interfaced Through Chrome

The endpoint was not discoverable through plain `curl` because the host returned
Cloudflare challenge pages to raw HTTP clients. The working path was:

```text
Chrome browser session
  -> logged-in Open WebUI page
  -> localStorage Open WebUI token remains inside browser
  -> Chrome DevTools Protocol on 127.0.0.1:9222
  -> Runtime.evaluate(...)
  -> fetch("/api/chat/completions", ...)
  -> normalized JSON result saved locally
```

The browser page itself was the trusted authenticated context. The wrapper did
not export cookies, `cf_clearance`, the Open WebUI token, or the password.

### Profile Discovery

On this machine, the requested Google account was found in the default Chrome
profile preferences:

```text
Chrome user data dir: /home/username/.config/google-chrome
Chrome profile directory: Default
Detected account: taremoteteam@gmail.com
```

For repeatable testing, we used an isolated profile instead of modifying the
main profile:

```text
/tmp/aidevobserver-gemma-profile
```

That isolated profile was logged into Open WebUI and reused for wrapper tests.

### Start Chrome With DevTools Enabled

Start Chrome with a dedicated profile and DevTools enabled:

```bash
google-chrome \
  --user-data-dir=/tmp/aidevobserver-gemma-profile \
  --remote-debugging-port=9222 \
  --no-first-run \
  --disable-first-run-ui \
  --new-window https://ui.iamretarded.net
```

Expected DevTools startup line:

```text
DevTools listening on ws://127.0.0.1:9222/devtools/browser/<id>
```

Check targets:

```bash
curl -sS http://127.0.0.1:9222/json/list
```

The page target should look like:

```json
{
  "title": "Open WebUI",
  "type": "page",
  "url": "https://ui.iamretarded.net/",
  "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/..."
}
```

### Login Flow

The login page was Open WebUI:

```text
URL: https://ui.iamretarded.net/auth
Title: Open WebUI
Fields:
  input type=email name=email id=email
  input type=password name=password id=password
  button type=submit text=Sign in
```

After login, the page showed:

```text
gemma-4-coding
Set as default
Open WebUI
```

Observed successful login/API endpoints:

```text
POST /api/v1/auths/signin               200 application/json
GET  /api/config                        200 application/json
GET  /api/models                        200 application/json
GET  /api/v1/tools/                     200 application/json
GET  /api/v1/functions/                 200 application/json
GET  /api/v1/skills/                    200 application/json
```

The Open WebUI token is available to the page as:

```javascript
localStorage.getItem("token")
```

The wrapper uses that token only inside the browser context.

### Browser Fetch Used By The Wrapper

Once logged in through the browser window, a local program can use Chrome
DevTools Protocol to execute this fetch inside the authenticated page:

```javascript
const token = localStorage.getItem("token");
const headers = {
  "Content-Type": "application/json",
  "Accept": "application/json"
};

if (token) {
  headers.Authorization = `Bearer ${token}`;
}

const response = await fetch("/api/chat/completions", {
  method: "POST",
  headers,
  body: JSON.stringify({
    model: "gemma-4-coding",
    stream: false,
    messages: [
      {
        role: "user",
        content: "Print exactly: Open WebUI browser-context integration OK"
      }
    ]
  })
});

const data = await response.json();
```

This keeps cookies and localStorage inside the browser profile instead of
exporting them to the calling program.

### Minimal CDP Execution Shape

The wrapper talks to Chrome DevTools Protocol like this:

```text
GET http://127.0.0.1:9222/json/list
  -> find page target where url contains ui.iamretarded.net

Open websocket:
  ws://127.0.0.1:9222/devtools/page/<target-id>

Send:
  Runtime.enable
  Runtime.evaluate {
    expression: "(async () => { ... fetch('/api/chat/completions') ... })()",
    awaitPromise: true,
    returnByValue: true
  }
```

The repo wrapper implements this in:

```text
src/aidevobserver_fabric/openwebui.py
```

Important functions:

```text
OpenWebUIConfig
chat_payload(prompt, model, system=None)
redacted_plan(config, mode)
direct_chat(config, prompt, token=None)
cdp_chat(config, prompt)
normalize_chat_response(response)
```

The CDP mode uses a small stdlib-only WebSocket client in the same module, so
it does not require Playwright.

## AIDevObserver Wrapper Commands

If using the `aidevobserver-capability-fabric` repo, the wrapper is already
available.

Plan a redacted request:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
python3 -m aidevobserver_fabric.cli openwebui-plan --mode cdp
```

Send a browser-context prompt:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
python3 -m aidevobserver_fabric.cli openwebui-chat \
  --mode cdp \
  --prompt "Print exactly: Open WebUI wrapper OK" \
  --out generated/openwebui_wrapper_result.json
```

Send a direct bearer-token prompt:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
OPENWEBUI_TOKEN="$OPENWEBUI_TOKEN" \
python3 -m aidevobserver_fabric.cli openwebui-chat \
  --mode direct \
  --prompt "Print exactly: Open WebUI direct wrapper OK" \
  --out generated/openwebui_direct_result.json
```

## Normalized Wrapper Output

The AIDevObserver wrapper normalizes responses to:

```json
{
  "assistant_content": "Open WebUI wrapper OK",
  "auth_mode": "browser_context_token_not_exported",
  "base_url": "https://ui.iamretarded.net",
  "candidate_only": true,
  "endpoint": "/api/chat/completions",
  "finish_reason": "stop",
  "http_status": 200,
  "model": "gemma-4-coding",
  "prompt": "Print exactly: Open WebUI wrapper OK",
  "provider": "open_webui",
  "response_id": "chatcmpl-...",
  "serves_truth": false,
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

## Observed Smoke Test

Prompt:

```text
Print exactly: AIDevObserver wrapper CLI smoke test OK
```

Observed assistant content:

```text
AIDevObserver wrapper CLI smoke test OK
```

Observed usage:

```json
{
  "prompt_tokens": 24,
  "completion_tokens": 9,
  "total_tokens": 33
}
```

## Program Generation Test

We used the wrapper to ask `gemma-4-coding` to generate small Python programs.
The responses were saved as JSON under `generated/`, and the fenced Python code
blocks were extracted into:

```text
generated/llm_programs/word_stats.py
generated/llm_programs/primitive_link_extractor.py
generated/llm_programs/tiny_json_kv_server.py
```

Example prompt shape:

```text
Write one standalone Python 3 program named word_stats.py.
Requirements: no third-party dependencies, no network, no subprocess, argparse
CLI, accepts an optional file path or stdin, prints JSON with line_count,
word_count, char_count, and top_words.
Return exactly one fenced python code block and no extra prose.
```

Verification performed:

```bash
python3 - <<'PY'
from pathlib import Path
for path in sorted(Path("generated/llm_programs").glob("*.py")):
    compile(path.read_text(), str(path), "exec")
    print(f"ok {path}")
PY

python3 generated/llm_programs/word_stats.py README.md
python3 generated/llm_programs/primitive_link_extractor.py README.md
```

The generated HTTP server was smoke-tested on a non-default local port:

```bash
python3 -c "import sys; sys.path.insert(0, 'generated/llm_programs'); import tiny_json_kv_server as s; s.run(8017)"

curl -sS http://127.0.0.1:8017/health
curl -sS -X PUT http://127.0.0.1:8017/items/demo \
  -H 'Content-Type: application/json' \
  --data '{"value":42}'
curl -sS http://127.0.0.1:8017/items/demo
curl -sS -X DELETE http://127.0.0.1:8017/items/demo
```

## Observed Throughput

Sequential LeetCode-style coding prompts through browser-context mode:

```text
Short run: 8/8 tasks, 1098 completion tokens, 8.97 seconds
Aggregate completion TPS: ~122.4

Heavier hard-problem run: 5/5 tasks, 2323 completion tokens, 15.83 seconds
Aggregate completion TPS: ~146.8
```

These numbers include browser-context and request overhead. They are not raw
backend streaming throughput.

Benchmark artifacts:

```text
generated/gemma_leetcode_tps_benchmark.json
generated/gemma_leetcode_heavy_tps_benchmark.json
```

## Common Failure Modes

### Raw HTTP Returns 403

Symptom:

```text
HTTP 403 text/html
Cloudflare "Just a moment..." page
```

Meaning:

```text
The direct HTTP client is challenged. Use browser-context mode or obtain a
stable bearer/service token path accepted by the host.
```

### Browser Page Is On `/error`

Symptom:

```text
https://ui.iamretarded.net/error
500: Internal Error
```

Recovery:

```text
Navigate back to https://ui.iamretarded.net/
If API calls still return 403, clear only the Open WebUI app token in the
isolated browser profile and log in again through the browser page.
```

### `/api/models` Returns 403 From Browser Context

Meaning:

```text
The browser has an Open WebUI token but the Cloudflare clearance/session is not
accepted for the API request.
```

Recovery:

```text
Reload or re-login in the browser profile, then confirm:
GET /api/models -> 200 application/json
```

### DevTools Port Not Available

Symptom:

```text
curl: (7) Failed to connect to 127.0.0.1 port 9222
```

Recovery:

```text
Start Chrome with --remote-debugging-port=9222.
If another Chrome instance is already using a profile, use the isolated
/tmp/aidevobserver-gemma-profile profile.
```

## Integration Rules

1. Prefer direct mode if a stable bearer token is available.
2. Use browser-context mode if Cloudflare blocks raw HTTP.
3. Never commit credentials, cookies, tokens, localStorage dumps, or passwords.
4. Keep model outputs as candidate artifacts until reviewed.
5. Use `usage.total_tokens`, `usage.prompt_tokens`, and
   `usage.completion_tokens` from the response for accounting.
6. Treat endpoint availability as session-dependent if using browser-context
   mode.
