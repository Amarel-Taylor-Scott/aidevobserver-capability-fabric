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
- Candidate-only RapidAPI social post ingestion for Facebook source pages.
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
  --provider-config examples/rapidapi_facebook_provider.example.json \
  --sources examples/facebook_sources.json \
  --limit 10
```

See [`docs/rapidapi-facebook-ingest.md`](docs/rapidapi-facebook-ingest.md).

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
