# Evolutionary Primitive Factory

The primitive factory turns the existing registry into candidate lifecycle
evidence. It does not replace canonical primitive records and does not promote
anything by itself.

```text
Observation
  -> Problem
  -> Intent
  -> Capability
  -> PrimitiveGenome
  -> MutationRecord
  -> CrossoverRecord
  -> BenchmarkRecord
  -> FitnessRecord
  -> Proof / Promotion later
```

## Boundary

Every generated record is candidate-only:

```text
candidate_only = true
serves_truth = false
```

The factory can propose that a primitive should be mapped over sequences,
cached, retried, wrapped with schema validation, materialized as an artifact,
or rewritten into a deterministic rule. Those proposals become truth only after
proof and promotion.

## Record Types

`ObservationRecord` captures why a primitive family exists.

`PrimitiveGenome` captures the "DNA" of a primitive:

- identity and label;
- input/output contracts;
- effects;
- memory and cache policies;
- determinism class;
- available mutators;
- proof obligations;
- promotion blockers;
- source references.

`MutationRecord` is a deterministic variation proposal. Examples:

- `map_sequence`;
- `retry_wrapper`;
- `ttl_cache`;
- `provider_fallback`;
- `schema_gate`;
- `artifact_materialize`;
- `deterministic_rewrite`;
- `rule_extractor`;
- `embedding_filter`.

`CrossoverRecord` proposes a route when one primitive's output contract already
matches another primitive's input contract.

`BenchmarkRecord` estimates what must be measured before the primitive should
be trusted.

`FitnessRecord` ranks candidates by correctness, determinism, reliability,
proof readiness, latency, cost, and blockers.

## CLI

Compact factory view:

```bash
aidevobserver-fabric factory --compact --limit 8
```

Lineage for one primitive:

```bash
aidevobserver-fabric factory-lineage candidate.social.facebook_rapidapi_fetch_posts.v0
```

## How Agents Should Use It

Agents can use the factory to decide what to improve next:

```text
low determinism + deterministic_rewrite mutator
  -> prioritize rule extraction and proof fixtures

network effects + retry/cache/provider fallback mutators
  -> build provider fixtures, idempotency receipts, and freshness policy

high crossover count
  -> consider composite primitive promotion after end-to-end proof
```

Agents should not execute or publish factory suggestions as truth. They should
use them to open proof tasks, benchmark tasks, and registry-improvement PRs.
