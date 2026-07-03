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

## High-Value Next Steps

1. Index `resolved_primitives.jsonl` into the SQLite registry alongside the
   existing seed primitives.
2. Add a graph route search that starts from a requested input and output type.
3. Generate PlanLock objects from `route_templates.jsonl`.
4. Run route templates through benchmark fixtures and record proof receipts.
5. Promote only implemented, source-backed, receipt-backed primitives.
