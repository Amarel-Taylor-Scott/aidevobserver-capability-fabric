# AIDevObserver Capability Fabric

A testable, local-first primitive reuse service for coding agents. It now ships
as one Python package with:

- an account and login website;
- scoped personal agent tokens;
- an authenticated JSON API;
- an MCP 2025-11-25 stdio bridge for Codex and Claude Code;
- hybrid primitive search that searches before it ranks by trust;
- 11 packaged, executable primitives with JSON contracts and deterministic
  proof fixtures;
- digest-verified, workspace-bounded source materialization; and
- account-scoped, hash-chained reuse receipts.

The working product loop is:

```text
sign up → create token → connect agent → search → inspect → reuse/execute
        → replay digest-bound proof fixtures → record receipt
```

This repository is the public-safe capability core. It contains no private
workspace inventory, transcripts, credentials, or hosted production secrets.

## Try It

Python 3.10 or newer is required. Runtime dependencies are standard-library
only.

```bash
git clone https://github.com/Amarel-Taylor-Scott/aidevobserver-capability-fabric.git
cd aidevobserver-capability-fabric
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .

aidevobserver-fabric self-test
aidevobserver-fabric serve
```

Open [http://127.0.0.1:8766](http://127.0.0.1:8766), then:

1. Create an account.
2. Create an agent token.
3. Copy the generated Codex or Claude Code install command.
4. Ask the agent to search for an existing primitive before implementing a
   common capability.

Or run the whole authenticated reuse loop automatically. This leaves one
inspectable, digest-verified module under `.aidevobserver/primitives/`:

```bash
aidevobserver-fabric e2e-demo --workspace-root .
```

The default database is
`~/.local/share/aidevobserver/fabric.sqlite`. Override its directory with
`AIDEVOBSERVER_HOME`, or pass `--db` to the CLI.

For a remotely reachable test deployment, set the URL shown in install
commands and secure the session cookie:

```bash
aidevobserver-fabric serve \
  --host 0.0.0.0 \
  --port 8766 \
  --public-url https://fabric.example.com \
  --secure-cookie \
  --signup-mode open \
  --bridge-install-command 'pipx install https://downloads.example.com/aidevobserver-capability-fabric-0.2.0-py3-none-any.whl'
```

Put that process behind TLS. HTTPS public URLs automatically enable Secure
cookies and HSTS; non-loopback binds without an HTTPS public URL are refused.
Hosted signup defaults to disabled, so `--signup-mode open` is an explicit
controlled-preview choice. The included account/PAT flow is not a replacement
for production OAuth, email verification, invitations, or a managed secret
store. Replace the example wheel URL with a real pinned artifact you publish;
remote onboarding intentionally shows an installer error when the operator has
not configured `--bridge-install-command` (or
`AIDEVOBSERVER_INSTALL_COMMAND`).

## Connect an Agent

The website first shows a one-time token, then generates a private prompt so
the token does not enter shell history or the MCP configuration:

```bash
cd /path/to/aidevobserver-capability-fabric
pipx install .

aidevobserver-fabric auth login --server http://127.0.0.1:8766
# paste the token at the hidden prompt
```

The token is validated, then stored in
`~/.config/aidevobserver/credentials.json` with mode `0600`. The generated MCP
commands contain the URL but no PAT. Their general form is:

```bash
codex mcp add aidevobserver \
  --env AIDEVOBSERVER_URL=http://127.0.0.1:8766 \
  -- aidevobserver-mcp
```

```bash
claude mcp add \
  --env AIDEVOBSERVER_URL=http://127.0.0.1:8766 \
  --transport stdio \
  --scope user \
  aidevobserver -- aidevobserver-mcp
```

The equivalent module command is:

```bash
AIDEVOBSERVER_URL=http://127.0.0.1:8766 \
python -m aidevobserver_fabric.mcp_server --workspace-root .
```

The MCP server exposes six tools:

| Tool | Purpose |
|---|---|
| `search_primitives` | Find relevant executable primitives and contracts |
| `get_primitive` | Inspect source, schemas, digest, license, and proof metadata |
| `execute_primitive` | Run a fixed allowlisted primitive with validated input/output |
| `materialize_primitive` | Atomically write digest-verified source inside the workspace |
| `prove_primitive` | Replay deterministic fixtures tied to captured source and runner digests |
| `record_reuse` | Append a strict, compact account-scoped reuse receipt |

Materialization rejects absolute paths, traversal, symlink escapes, digest
mismatches, and differing existing files unless overwrite is explicit. Reusing
an existing file with the same digest is idempotent. Race-safe materialization
requires POSIX directory-descriptor and no-follow support; on platforms without
those primitives, this one MCP tool fails closed with
`secure_materialization_unavailable` while the other tools remain available.

`execute_primitive` sends its JSON inputs to the configured capability service.
Use the loopback service for local-only data; do not send secrets or raw private
prompts to a remote preview deployment.

## Working Primitives

Ten primitives are verified/R8 executable. The CSV profiler is deliberately
still a candidate even though it is executable and proven; a passing local
proof does not silently promote governance state.

```text
prim.text.extract_email.v1
prim.text.extract_url.v1
prim.text.extract_phone_e164.v1
prim.date.normalize.v1
prim.finance.validate_iban.v1
prim.validation.luhn.v1
prim.text.count_tokens_approx.v1
prim.similarity.jaro_winkler.v1
prim.similarity.cosine.v1
prim.crypto.sha256.v1
candidate.csv.profile_columns.v0
```

Run every packaged proof:

```bash
aidevobserver-fabric prove-all
```

Each implementation has a fixed ID, immutable captured source and contract
metadata, JSON input/output schemas, SHA-256 source/runner/fixture digests,
deterministic fixtures, and an MIT license marker. The proof states its subject
precisely: the loaded allowlisted callable bound to that captured source. The
runtime has no dynamic import path, `eval`, arbitrary shell command, or
client-selected callable.

## Authenticated API

Public:

```text
GET /v1/health
```

Bearer-token routes:

```text
GET  /v1/me
POST /v1/primitives/search
GET  /v1/primitives/{primitive_id}
POST /v1/primitives/{primitive_id}/execute
POST /v1/primitives/{primitive_id}/prove
GET  /v1/reuse-receipts
POST /v1/reuse-receipts
```

Agent tokens use fixed product scopes:

```text
primitives:read
primitives:execute
proofs:run
receipts:read
receipts:write
```

Passwords use salted scrypt. Session and agent-token secrets are hashed in
SQLite; the raw agent token is shown once. Website PATs expire after 90 days
and can use full-workflow or discovery-only scope. Browser mutations require
same-origin checks and CSRF tokens, including pre-authentication signup/login
forms. Auth, execution, proof, and receipt routes are rate-limited. Session
cookies are HttpOnly and SameSite=Lax; HTTPS deployments add Secure and HSTS
automatically. Database files use mode `0600`.

## Test the Complete Path

Run the complete suite:

```bash
python -m unittest discover -s tests -v
```

The suite includes a live acceptance test that:

1. starts the real website/API on an ephemeral port;
2. signs up through HTTP and mints a PAT through the browser flow;
3. launches the real MCP server as a subprocess;
4. negotiates MCP and lists the six tools;
5. searches, gets, materializes, executes, and proves a primitive;
6. imports and runs the materialized Python module;
7. records and reads reuse receipts;
8. confirms the PAT never appears in MCP output or SQLite; and
9. restarts the service and verifies identity and receipts persist.

Focused smoke commands:

```bash
aidevobserver-fabric self-test
aidevobserver-fabric prove-all
aidevobserver-fabric e2e-demo --workspace-root /tmp/aidevobserver-demo
python -m unittest tests.test_live_mcp -v
```

## Search and Truth Boundaries

Search uses typed contract filters, FTS, domain aliases, meaningful-overlap
gates, semantic-token overlap, and reciprocal-rank fusion. Trust can only add a
small post-relevance boost; it cannot create a match. Empty, nonsense, or
unsupported executable queries return no primitive.

The registry initializes with idempotent upserts. Starting or restarting the
service does not drop user accounts, API tokens, receipts, imported records, or
FTS state.

Discovery remains awareness. Executability is a fixed allowlist. A proof is
evidence tied to source and fixture digests. Candidate execution or a passing
proof does not automatically change `trust`, `readiness`, or `serves_truth`.

## Semantic Linker Direction

Version 0.2 is the working single-capability reuse substrate. The next major
layer turns compact intent into a typed capability graph, resolves it to exact
verified implementations, applies an immutable binding lock, and generates code
only for explicitly unmet behavior. The architecture, staged implementation
sequence, MCP evolution, first graph-level vertical slice, and paired
token-savings benchmark are defined in
[`docs/semantic-linker-roadmap.md`](docs/semantic-linker-roadmap.md).

## Existing Research Surfaces

The earlier candidate-only source catalog, social/RapidAPI ingestion planner,
route bundles, and evolutionary primitive factory remain available:

```bash
aidevobserver-fabric search --query "csv profile rows" --compact
aidevobserver-fabric sources --compact
aidevobserver-fabric social-sources --compact
aidevobserver-fabric factory --compact
```

These surfaces generate discovery and planning context; they are not
automatically executable or promoted product truth.

## License

MIT.
