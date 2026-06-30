# Open WebUI Wrapper

This wrapper sends candidate-only chat requests to an Open WebUI deployment.

Boundary:

```text
candidate_llm_request = true
serves_truth = false
```

The wrapper is for probing, primitive drafting, and demo/evaluation runs. A
response from the model is not proof, promotion, or served truth.

## Observed Deployment Shape

The investigated deployment is Open WebUI with:

```text
base_url: https://ui.iamretarded.net
model: gemma-4-coding
chat endpoint: /api/chat/completions
```

Unauthenticated direct HTTP probes were blocked by Cloudflare challenge pages,
but the same endpoint worked from a logged-in browser context.

## Modes

### Direct Mode

Use this when you have a stable bearer token available in an environment
variable:

```bash
export OPENWEBUI_TOKEN="..."

aidevobserver-fabric openwebui-chat \
  --mode direct \
  --prompt "Print exactly: AIDevObserver Open WebUI smoke test OK" \
  --out generated/openwebui_smoke_result.json
```

The token is read from `OPENWEBUI_TOKEN` by default and is never printed by the
plan command.

### Browser Context / CDP Mode

Use this when the endpoint requires the browser session, Cloudflare clearance,
or Open WebUI localStorage auth.

Start Chrome with DevTools enabled:

```bash
google-chrome \
  --user-data-dir=/tmp/aidevobserver-gemma-profile \
  --remote-debugging-port=9222 \
  --no-first-run \
  --disable-first-run-ui \
  --new-window https://ui.iamretarded.net
```

Log in through the browser, then run:

```bash
aidevobserver-fabric openwebui-chat \
  --mode cdp \
  --prompt "Print exactly: AIDevObserver Open WebUI smoke test OK" \
  --out generated/openwebui_smoke_result.json
```

CDP mode executes `fetch('/api/chat/completions', ...)` inside the authenticated
page. It does not export cookies, bearer tokens, localStorage tokens, or
passwords into the repo.

## Redacted Plan

Before sending a request:

```bash
aidevobserver-fabric openwebui-plan --mode direct
aidevobserver-fabric openwebui-plan --mode cdp
```

The plan output includes endpoint, model, mode, and redacted authorization
metadata.

## Output Shape

The normalized output is intentionally compact:

```json
{
  "assistant_content": "AIDevObserver Open WebUI smoke test OK",
  "auth_mode": "browser_context_token_not_exported",
  "base_url": "https://ui.iamretarded.net",
  "candidate_only": true,
  "endpoint": "/api/chat/completions",
  "finish_reason": "stop",
  "model": "gemma-4-coding",
  "prompt": "Print exactly: AIDevObserver Open WebUI smoke test OK",
  "serves_truth": false,
  "usage": {
    "completion_tokens": 10,
    "prompt_tokens": 25,
    "total_tokens": 35
  }
}
```

## Security Rules

- Do not commit passwords, cookies, bearer tokens, or browser storage dumps.
- Store API tokens in environment variables or a local credential broker.
- Treat browser-context runs as ephemeral integration checks.
- Keep generated model outputs under `generated/` unless they have gone through
  review and promotion.
