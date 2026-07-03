# Edge Primitive Catalog

This catalog expands the fabric from a small seed registry into a large
candidate graph that a planner can search and compile from edge contracts.

The purpose is not row count by itself. The purpose is to make common
programming tasks available as small, reusable capability contracts:

- input edge
- output edge
- blackbox behavior
- effects
- runtime target
- proof requirements
- promotion blockers

Every generated row is candidate material:

```json
{
  "candidate": true,
  "serves_truth": false
}
```

Promotion requires source references, implementation, effect audit, fixture
receipts, and benchmark evidence.

## Generated Files

The pack is generated under:

```text
generated/edge_primitive_catalog/
```

It contains:

- `primitive_families.jsonl`: stable capability families across domains,
  data shapes, and route stages.
- `runtime_wrappers.jsonl`: runtime surfaces such as Python functions,
  FastAPI endpoints, MCP tools, queue workers, cloud functions, Kubernetes
  jobs, GitHub Actions, Terraform modules, and human review tasks.
- `resolved_primitives.jsonl`: family plus runtime wrapper contracts.
- `compatibility_edges.jsonl`: direct output-type to input-type graph edges.
- `route_templates.jsonl`: reusable graph skeletons with step sequences and
  required proofs.
- `candidate_bundle_examples.jsonl`: compact planner examples for route
  selection.
- `manifest.json`: row counts and SHA-256 hashes.

Build and check:

```bash
python3 scripts/build_edge_primitive_catalog.py
python3 scripts/check_edge_primitive_catalog.py
```

Use the catalog from the CLI:

```bash
aidevobserver-fabric edge-summary
aidevobserver-fabric edge-search \
  --query "validate csv table customer import" \
  --domain data_ingest \
  --data-shape csv_table \
  --operation validate_contract \
  --runtime-target python_function \
  --compact
aidevobserver-fabric edge-routes \
  --query "compile csv data ingest route" \
  --domain data_ingest \
  --data-shape csv_table
aidevobserver-fabric edge-planlock \
  --query "compile csv data ingest route" \
  --domain data_ingest \
  --data-shape csv_table \
  --pattern compact_data_route
aidevobserver-fabric edge-graph-route \
  --start-type "Parsed[data_ingest.csv_table]" \
  --end-type "Plan[data_ingest.csv_table]"
```

## Why Wrappers Multiply Primitives

The same family is a different primitive when it lowers into a different
runtime shape. A validation step as a pure Python function, FastAPI endpoint,
MCP tool, queue worker, and Airflow task has different effects, failure modes,
proofs, and deployment surfaces. The builder therefore crosses each family only
with applicable wrappers, rather than applying every wrapper everywhere.

## Compilation Model

A graph compiler should use this pack like this:

```text
TaskIntent
-> CandidateBundle
-> RouteTemplate
-> selected resolved primitives
-> edge-signature compatibility check
-> proof requirement union
-> PlanLock
-> deterministic execution
-> proof and telemetry receipts
```

The LLM should first see the compact edge cards. It should drill into deeper
problem-solution details, source refs, implementation, or proofs only when the
edge contract is insufficient or a checker requests it.

## Route Compatibility

Compatibility edges are deliberately simple in this pack:

```text
left.primary_output_type == right.primary_input_type
```

That is enough to seed graph compilation. Later catalog versions can add:

- subtype compatibility
- deterministic mutators
- field rename/project adapters
- batch/map wrappers
- JSON/row/Parquet transformations
- source-span or citation-preserving adapters
- human-review gates
- negative-memory suppression

## Implemented Consumption Path

The package can now read the ignored exploded catalog or the committed ZIP
artifact through `aidevobserver_fabric.edge_catalog`.

Implemented:

1. Catalog summary from directory or ZIP.
2. Resolved primitive search over compact edge contracts.
3. Route template search.
4. PlanLock-shaped route compilation with route hash, effect union, and proof
   requirement union.
5. Graph route search from requested start artifact type to end artifact type.

Remaining promotion work:

1. Run selected route templates against benchmark fixtures.
2. Attach source references and implementation receipts.
3. Add negative memory for failed route candidates.
4. Promote only implemented, source-backed, receipt-backed primitives.
