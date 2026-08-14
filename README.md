# AIDevObserver Capability Fabric

Local-first capability registry, hybrid primitive search, route bundles, and
agent discovery for AI coding sessions.

The product thesis:

```text
Your AI coding agent is rebuilding things your team already has.
AIDevObserver catches that and routes the session toward reusable work.
```

This repository is the generalized, public-safe core. It does not include any
private workspace inventory, transcripts, credentials, or local paths.

## What It Provides

- A small primitive registry with canonical records.
- SQLite + FTS5 local search.
- Deterministic semantic-token lane.
- Contract blockers before ranking.
- Reciprocal-rank fusion across retrieval lanes.
- Hierarchical CandidateBundle route context.
- A read-only capability service fabric.
- Compact agent discovery output.
- Candidate-only source-surface catalog for AI startups, repos, newsletters,
  benchmarks, launch trackers, and communities.
- Persistent business-friction discovery loop with policy-gated public source
  adapters, exact-byte CAS, evidence clustering, registry-gap retrieval,
  generated candidate implementations, sandboxed fixtures, and receipts.
- Candidate-only RapidAPI social post ingestion for Facebook source pages.
- Candidate-only Open WebUI wrapper for direct-token or browser-context LLM calls.
- Candidate-only local Ollama wrapper for Gemma-family coding calls.
- Evolutionary primitive factory views: genomes, mutations, crossovers,
  benchmark estimates, lineage, and fitness recommendations.
- Edge primitive catalog generator with 25k+ resolved primitive contracts,
  compatibility edges, route templates, and a compressed artifact.
- Exploratory Open Capability Graph draft with directional contracts,
  evidence-gated adapters, multi-space representations, portable search
  profiles, JSON Schema, and semantic conformance checks.
- Optional local HTTP server.

Every generated candidate remains advisory:

```text
discovery = awareness
search result = candidate advice
CandidateBundle = planning context
PlanLock + proof + promotion = served truth
```

## Quickstart

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
aidevobserver-fabric self-test
```

Run a hybrid query:

```bash
aidevobserver-fabric search \
  --query "csv profile rows for warehouse ingestion" \
  --output-contract ColumnProfileSet \
  --candidate-only \
  --compact
```

Discover available services:

```bash
aidevobserver-fabric discover "find reusable primitive search route"
```

List public source surfaces for primitive discovery:

```bash
aidevobserver-fabric sources --compact
aidevobserver-fabric sources --category startup_directory
```

The same catalog is available as a reviewer-friendly document in
[`docs/source-surfaces.md`](docs/source-surfaces.md).

Plan a RapidAPI/Facebook social post scrape without exposing keys:

```bash
aidevobserver-fabric social-sources --compact
aidevobserver-fabric rapidapi-plan \
  --provider-config examples/rapidapi_facebook_scraper3_provider.example.json \
  --sources examples/facebook_sources.json \
  --limit 10
aidevobserver-fabric rapidapi-key-status \
  --provider-config examples/rapidapi_facebook_scraper3_provider.example.json
```

See [`docs/rapidapi-facebook-ingest.md`](docs/rapidapi-facebook-ingest.md).

Plan or run a candidate-only Open WebUI chat request:

```bash
aidevobserver-fabric openwebui-plan --mode cdp
aidevobserver-fabric openwebui-chat \
  --mode cdp \
  --prompt "Print exactly: AIDevObserver Open WebUI smoke test OK" \
  --out generated/openwebui_smoke_result.json
```

Use `--mode direct` with `OPENWEBUI_TOKEN` when a stable bearer token is
available. See [`docs/openwebui-wrapper.md`](docs/openwebui-wrapper.md).

Plan or run a candidate-only local Ollama chat request:

```bash
aidevobserver-fabric ollama-plan
aidevobserver-fabric ollama-models
aidevobserver-fabric ollama-chat \
  --prompt "Print exactly: AIDevObserver Ollama smoke test OK" \
  --out generated/ollama_smoke_result.json
```

Inspect the candidate-only primitive lifecycle factory:

```bash
aidevobserver-fabric factory --compact
aidevobserver-fabric factory-lineage candidate.social.facebook_rapidapi_fetch_posts.v0
```

See [`docs/evolutionary-primitive-factory.md`](docs/evolutionary-primitive-factory.md).

Discover recurring business friction and turn corroborated needs into tested,
candidate-only primitives:

```bash
aidevobserver-fabric problem-sources --compact
aidevobserver-fabric problem-loop \
  --fixture examples/problem_observations.fixture.json \
  --source github.operational_issues \
  --source stackexchange.workflow_questions \
  --source cfpb.complaints \
  --cycles 1
aidevobserver-fabric problem-status
aidevobserver-fabric problem-reconcile
```

The same command can use bounded live public APIs by omitting `--fixture`.
Web observations, extracted problems, cluster scores, catalog matches, and
generated code all remain candidates. A fixture receipt never sets
`serves_truth` or authorizes an execution edge. See
[`docs/problem-discovery-primitive-loop.md`](docs/problem-discovery-primitive-loop.md).

Generate and validate the larger edge primitive graph:

```bash
python3 scripts/build_edge_primitive_catalog.py
python3 scripts/check_edge_primitive_catalog.py
aidevobserver-fabric edge-summary
aidevobserver-fabric edge-search \
  --query "validate csv table customer import" \
  --domain data_ingest \
  --data-shape csv_table \
  --operation validate_contract \
  --runtime-target python_function \
  --compact
aidevobserver-fabric edge-planlock \
  --query "compile csv data ingest route" \
  --domain data_ingest \
  --data-shape csv_table \
  --pattern compact_data_route
```

The committed ZIP artifact is
[`artifacts/edge_primitive_catalog.zip`](artifacts/edge_primitive_catalog.zip).
It contains the generated raw JSONL pack. See
[`docs/edge-primitive-catalog.md`](docs/edge-primitive-catalog.md).

Validate the exploratory Open Capability Graph reference example:

```bash
python3 -m pip install -e .
python3 scripts/check_open_capability_graph.py
```

Run the five-format interoperability bakeoff with the optional native-format
validators (provide `wasm-tools` separately for WIT validation):

```bash
python3 -m pip install -e '.[ocg-interop]'
python3 scripts/run_ocg_interop_bakeoff.py \
  --wasm-tools /path/to/wasm-tools \
  --require-native
```

The format draft is
[`spec/open-capability-graph/v0.1/README.md`](spec/open-capability-graph/v0.1/README.md).
The wider standards review and tradeoff analysis is
[`docs/open-edge-and-primitive-standards-landscape-2026-07-10.md`](docs/open-edge-and-primitive-standards-landscape-2026-07-10.md).
The executed fixture-scale interoperability report and raw receipt are
[`docs/ocg-interoperability-bakeoff-2026-07-11.md`](docs/ocg-interoperability-bakeoff-2026-07-11.md)
and
[`artifacts/ocg_interop_bakeoff/receipt.json`](artifacts/ocg_interop_bakeoff/receipt.json).

Generate the local published-projects URL inventory:

```bash
python3 scripts/inventory_published_projects.py --root /path/to/repos
```

The generated inventory is
[`docs/published-projects.md`](docs/published-projects.md).

Start the local read-only service:

```bash
aidevobserver-fabric serve --host 127.0.0.1 --port 8766
```

Routes:

```text
GET /health
GET /services
GET /agents/discovery
GET /services/discover?q=primitive+search
GET /capabilities/search?q=csv+profile+rows&output_contract=ColumnProfileSet&candidate_only=1
GET /bundles
GET /factory
GET /factory?compact=1
GET /factory/lineage?id=candidate.social.facebook_rapidapi_fetch_posts.v0
GET /openapi.json
```

## Architecture

```text
PrimitiveRecord
  -> local SQLite/FTS registry
  -> blocker-first hybrid search
  -> CandidateBundle route context
  -> source-surface intake map
  -> social source ingestion
  -> business-friction evidence loop + candidate primitive builder
  -> evolutionary primitive factory
  -> agent discovery fabric
  -> optional HTTP service
```

The runtime deliberately separates:

- canonical records;
- compact generated views;
- LLM planning context;
- compiler/proof truth boundaries.

## Development

```bash
python -m unittest discover -s tests
python -m aidevobserver_fabric.cli self-test
```

## Publish Checklist

Before publishing publicly:

1. Run tests.
2. Confirm no generated DB files are committed.
3. Confirm no local paths, private transcripts, credentials, or raw copied
   source are present.
4. Confirm all examples use seed/demo records only.
5. Create the GitHub repo and push.

Suggested repo name:

```text
aidevobserver-capability-fabric
```

## License

MIT.
