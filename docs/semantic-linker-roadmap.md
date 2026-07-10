# Semantic Linker Roadmap

## Product thesis

AIDevObserver should make model token use scale with the novel part of a
software change, not with the total size of the resulting implementation.

```text
developer intent
  -> compact unresolved capability graph
  -> constraint-aware retrieval and graph solving
  -> exact implementation bindings and lock
  -> deterministic workspace materialization
  -> compile, contract, integration, security, and policy verification
  -> residual code only for behavior the registry cannot validly supply
```

The language model plans with abstract capabilities. The linker, not the
model, selects versions, checks compatibility, inserts verified adapters,
applies changes, and records evidence.

The governing safety rule is:

```text
retrieval may be probabilistic; acceptance and execution must be deterministic
```

Generated descriptions, embeddings, and model judgments are retrieval
evidence. They never independently authorize execution or promotion.

## Repository boundary

This repository is the focused, installable local product and agent control
plane. It owns workspace profiling, compact search, graph solving, binding,
materialization, verification, credentials, the API, and the MCP surface.

Open Harness Hub remains the broader catalog, foundry, research, and evaluation
plane. A future provider should import selected catalog objects by reference;
the large corpus should not be copied into this package.

Suggested provider mappings are:

| Open Harness object | Linker object |
|---|---|
| deterministic tool, processor, or code template | capability and implementation candidate |
| pipeline or pattern | recipe candidate |
| adapter | adapter candidate |
| schema | port-contract candidate |
| benchmark, rubric, or dataset | evidence and verification artifact |

All imported objects remain candidate-only until contracts, implementation
availability, license, provenance, security policy, and executable proofs pass.

## v0.2 baseline

Version 0.2 establishes the product substrate:

- account/login website and scoped 90-day agent tokens;
- authenticated JSON API and MCP 2025-11-25 stdio server;
- blocker-first hybrid primitive search with relevance gates;
- 11 fixed, executable primitives with JSON contracts;
- source, runner, and fixture digests plus deterministic proof receipts;
- atomic, workspace-bounded, digest-verified materialization;
- account-scoped hash-chained reuse receipts; and
- a real browser-to-MCP-to-materialized-module acceptance test.

This is a working single-capability reuse service. It is not yet the complete
semantic linker described below.

## Versioned semantic objects

The next layer should add new versioned records rather than silently widening
the meaning of the current primitive record:

- `CapabilityCard`: abstract behavior and semantic identity;
- `ImplementationCard`: exact executable realization and artifact identity;
- `AdapterCard`: verified conversion between incompatible ports or protocols;
- `RecipeCard`: reusable abstract capability graph;
- `WorkspaceProfile`: local repository constraints and available bindings;
- `GraphIR`: unresolved typed, effect-aware capability graph;
- `BindingLock`: exact implementations, adapters, policies, hashes, and tools;
- `EvidenceClaim`: a narrowly stated claim backed by an immutable artifact;
- `ProofReceipt`: reproducible verification of a stated subject;
- `OutcomeReceipt`: task, token, edit, repair, merge, rollback, and incident data.

The semantic ABI must cover more than JSON shapes. It needs typed value and
error ports, refinements, nullability, partial results, effects, idempotency,
retry safety, transactions, ordering, cardinality, concurrency, cancellation,
timeouts, data classification, taint/declassification, security scopes,
resource envelopes, compatibility, provenance, license, and lifecycle state.

## Graph IR and edges

`GraphIR` should be compact enough for a model to emit, while remaining
unresolved. It must not contain invented package versions or artifact hashes.

Edges are first-class contracts and may represent:

- value or error flow;
- control dependency, fallback, fan-out, join, or collection mapping;
- retry, transaction, authorization, or declassification boundaries;
- serialization and protocol transitions; and
- stream ownership, cancellation, and backpressure.

Stateful protocols should use explicit state-machine or protocol contracts
rather than pretending that every interaction is an ordinary function call.

## P0 implementation sequence

1. **Workspace profiler**
   - Detect languages, frameworks, package managers, contracts, schemas,
     policies, tests, deployment targets, and available local implementations.
   - Keep proprietary repository analysis local by default.
2. **Capability/implementation split**
   - Add versioned cards, content-addressed identities, compatibility edges,
     and schema migrations.
3. **Bounded graph solver**
   - Solve backward from required outputs and guarantees.
   - Apply type, effect, trust, license, policy, and runtime blockers before
     ranking.
   - Insert only verified adapters and return structured unsatisfied goals.
4. **Resolver and binding lock**
   - Bind abstract nodes to exact artifacts and record transitive dependencies,
     toolchains, schemas, policies, tests, provenance, and hashes.
5. **Deterministic Python assembler**
   - Materialize imports, registrations, routes, configuration, tests, and
     rollback metadata with syntax-aware transforms.
   - Coalesce fine-grained capabilities into operationally sensible packages.
6. **Graph-wide verifier**
   - Run compilation, contract, compatibility, integration, security, policy,
     and reproducible-rebuild checks.
   - Return compact diagnostics suitable for graph repair.
7. **PrimitiveLink benchmark spine**
   - Compare the same frozen tasks, repositories, models, budgets, and tests.
   - Count every attempt, failure, repair, model call, and verification cost.

## MCP evolution

The MCP server must continue to expose a small fixed meta-tool surface rather
than publishing every primitive as a separate tool.

The existing six tools remain useful compatibility operations. The semantic
linker surface should cover these functions:

| Function | Responsibility |
|---|---|
| `workspace_profile` | Return compact local repository constraints |
| `primitive_search` | Return small capability sketches and hard blockers |
| `primitive_expand` | Expand contracts/evidence only for selected candidates |
| `graph_solve` | Produce candidate graphs, residuals, and rejection reasons |
| `graph_apply` | Apply an approved binding lock inside the workspace |
| `graph_verify` | Verify the exact graph, artifacts, and resulting workspace |
| `candidate_promote` | Promote only through explicit evidence and policy gates |

Progressive disclosure should enforce token budgets:

```text
sketch -> selected contract -> selected evidence -> implementation only if needed
```

## First graph-level vertical slice

Use one Python web/API family rather than attempting cross-language universality.
A useful create-user graph includes:

1. decode a JSON request;
2. validate and normalize the input;
3. hash a password without logging plaintext;
4. insert a user through a repository contract;
5. map duplicate and validation errors;
6. create a public user view; and
7. return a framework-compatible response.

The acceptance test should start from a frozen repository, solve and lock the
graph, apply it deterministically, run public and hidden tests, and reproduce
the same result from the same lock without a model call.

## Benchmark protocol

The initial falsification study should compare:

- **A — normal coding agent:** full-context implementation;
- **B — repository RAG:** retrieved context with generated implementation;
- **D — deterministic linker:** fully covered graph, no residual generation;
- **E — linker plus bounded residual:** generate only explicitly unmet typed
  behavior.

Primary outcomes are cache-weighted tokens and total cost per verified task.
Also record correctness, security/policy violations, first-graph validity,
quality-valid recall, hard-negative rejection, residual lines, adapter depth,
repair count, post-assembly edit distance, wall time, human review, merge,
rollback, and production incidents.

Both-fail comparisons are inconclusive. Headline savings require both lanes to
pass the same hidden oracle, and claims should be reported by model and task
family with adequate sample sizes.

## Promotion and scale gates

The lifecycle remains explicit:

```text
raw -> normalized -> candidate -> contract-checked -> sandboxed
    -> benchmarked -> reviewed -> promoted -> monitored -> deprecated
```

No candidate becomes served truth because a model described it well, search
ranked it highly, or one local fixture passed. Promotion requires the declared
security, provenance, license, compatibility, benchmark, and verifier gates.

Do not make a 50-million-object deployment the first milestone. First prove the
mechanism with roughly 50-200 trusted primitives and 10-20 executable fixtures,
then run a serious pilot at approximately 5,000-20,000 verified objects and 500
real repository tasks. Storage tiering and very large ANN infrastructure should
follow verified non-inferior quality and measured token/cost savings.

