# Open Capability Graph 0.1

**Status:** exploratory draft; not an adopted standard  
**Working name:** Open Capability Graph (OCG)  
**Version identifier:** `0.1.0-draft`

Draft documents use `application/json`. A producer advertises this versioned
profile in discovery metadata (for example, an ARD catalog record) or with an
RFC 6906 HTTP link such as
`Link: <https://example.org/ocg/v0.1/>; rel="profile"`. It does not add an
undefined `profile` parameter to `application/json`. No OCG-specific media
type is claimed yet. A future
standards-tree registration should wait until the wire format is stable,
independently implemented, and governed outside one vendor.

OCG is a portable contract graph for capability identities, implementations,
multi-port actions, directional compatibility, adapters, evidence, search
representations, and search profiles. Its Contract profile supports
fail-closed **planning eligibility**. Execution authorization remains reserved
for a later Execution profile and must be enforced by a conforming runtime and
policy engine.

It is intentionally not a graph database, vector database, package registry,
agent protocol, workflow engine, or universal schema language.

The normative machine-readable shape is
[`schemas/open-capability-graph.schema.json`](schemas/open-capability-graph.schema.json).
The semantic rules in this document are also normative because several
cross-record invariants cannot be expressed completely in JSON Schema.

## 1. Design principles

1. **Native formats remain authoritative.** JSON Schema, Protobuf, Avro,
   Arrow, OpenAPI, AsyncAPI, WIT, CWL, and other domain contracts are referenced
   by URI and digest. OCG does not silently translate away unsupported terms.
2. **Actions are hyperedges.** An action may consume and produce multiple
   ports, expose error/control ports, and carry conditional effects.
3. **Compatibility is directional.** Producer guarantees are checked against
   consumer requirements in the producer-to-consumer direction.
4. **Retrieval never authorizes execution.** Names, prose, representative
   queries, embeddings, and learned rankers propose candidates only.
5. **Unknown fails closed.** Unsupported dialect features, missing evidence,
   checker timeouts, and ambiguous semantics produce `unknown`.
6. **Weights have typed meaning.** Truth-bearing relations use measures with a
   metric, unit/context, uncertainty, and evidence. Query preferences live in
   search profiles.
7. **Embeddings are replaceable projections.** Multiple vector spaces may
   coexist. Vectors are comparable only inside an explicitly identical space
   or through a registered transformation/calibration.
8. **Evidence is scoped.** Evidence is bound to exact subjects, contracts,
   artifacts, environments, workloads, policies, and time.
9. **History is non-destructive.** Rejected, superseded, deprecated, and
   revoked records remain addressable.
10. **Unknown extensions round-trip.** A consumer may ignore an unknown
    extension for display or search, but may not use it to make a join eligible.

## 2. Document model

An OCG document contains these top-level collections:

- `nodes`: stable identities such as capabilities, contracts,
  implementations, environments, policies, and concepts;
- `actions`: invocable hyperedges with ports and behavior declarations;
- `relations`: typed assertions between nodes, actions, ports, artifacts,
  evidence, adapters, or representations;
- `adapters`: explicit directional transformations between contracts;
- `artifacts`: digest-addressed bytes or trees and their locators;
- `evidence`: claim-scoped test, build, provenance, performance, or policy
  results;
- `representations`: lexical, sparse, dense, multivector, code, graph, or
  other derived search views;
- `search_profiles`: engine-neutral retrieval, fusion, reranking, and
  evaluation intent.

Only `nodes`, `actions`, and `relations` are required by the Core profile.

## 3. Identity and references

Every record has a unique `id` within a document. Globally published records
SHOULD use URIs or domain-anchored URNs. Local drafts MAY use stable local IDs.

Logical identity and byte identity are separate:

```text
capability ID     what outcome is requested
implementation ID which implementation lineage may provide it
action ID         which invocable behavior is described
contract ID       which logical/native interaction contract is referenced
artifact digest   which exact bytes or tree are resolved
evidence ID       which scoped claim/result was observed
```

A `digest` MUST include its algorithm, currently `sha256:` or `sha512:`. A
logical identifier MUST NOT be treated as proof of byte identity.

## 4. Nodes

`Node.kind` is one of the registered core kinds or `custom`. The core kinds are:

```text
capability
contract
implementation
environment
policy
concept
resource
agent
service
workflow
custom
```

A contract node MUST contain a `native_contract` object with:

- `dialect`: a URI or stable dialect identifier;
- `schema_uri` pointing to the authoritative native contract bytes;
- `digest`: digest of those exact referenced bytes;
- optional inline `schema`, which is only a mirror and MUST equal the parsed
  referenced JSON when both are present;
- optional semantic concept, unit, media type, and encoding metadata.

The native contract, not a human-readable port name, is the basis for a
compatibility check.

## 5. Actions and ports

An `Action` MUST reference one capability and one implementation. It MUST have
at least one `input` port and at least one `output` port.

Port directions are:

- `input`: required or optional consumed value;
- `output`: produced value;
- `error`: typed error/result channel;
- `control`: cancellation, progress, acknowledgement, or other control plane.

Each port references a contract and may add cardinality, protocol, semantic,
and requirement/guarantee constraints. A port label is for display; it does not
establish compatibility.

Action behavior may declare:

- preconditions, postconditions, and invariants;
- errors and result modes;
- state reads/writes/deletes;
- filesystem, network, database, subprocess, secret, clock, randomness, GPU,
  financial, physical, or human effects;
- idempotency, retry, timeout, transaction, and compensation behavior;
- sync, async, future, stream, batch, or interactive protocols;
- artifact, evidence, environment, and policy references.

Missing declarations mean `unknown`; they do not mean pure, safe, or absent.

## 6. Relations and parallel edges

Relations have independent IDs, so multiple relations between the same source
and target are allowed. Examples include:

```text
flow
compatibility
adapter
implements
depends_on
derives_from
supersedes
equivalent
close
broader
narrower
conflicts_with
evidence_for
embedding_transform
custom
```

An endpoint has a `subject_ref` and may add `port_id` when the subject is an
action. Relation direction is explicit.

Relations have lifecycle status:

```text
candidate
verified
rejected
deprecated
revoked
```

Rejected and revoked relations MUST remain distinguishable from missing
relations.

In v0.1, the checker gives execution-relevant endpoint semantics to
`compatibility`, `flow`, `adapter`, and `implements`. An `adapter` relation
MUST reference the corresponding `Adapter`; a verified `flow` MUST have a
matching verified compatibility relation. Mapping, lineage, and descriptive
relation kinds do not by themselves affect planning eligibility.

## 7. Compatibility assertions

A relation of kind `compatibility` MUST:

- be directed `source_to_target`;
- identify an output port as source and input port as target;
- contain a `compatibility` object;
- keep relationship, mechanism, lossiness, assurance, and join decision as
  independent axes;
- bind an `eligible_direct` decision to exact contract digests and an active,
  resolvable checker artifact whose digest exactly matches `checker_digest`;
- reference passing evidence whose RFC 8785 digest binds the exact relation.

The orthogonal axes are:

| Axis | Core values | Meaning |
|---|---|---|
| `relationship` | `identical`, `producer_substitutable`, `family_revision_compatible`, `explicitly_equivalent`, `transformable`, `related`, `unknown`, `incompatible` | What semantic relation is asserted. |
| `mechanism` | `direct`, `adapter` | Whether values join directly or through an explicit adapter. |
| `lossiness` | `none`, `total_lossless`, `total_lossy`, `partial_guarded`, `stateful_effectful`, `unknown` | Totality, loss, and effect class of the bridge. |
| `assurance` | one or more of `publisher_asserted`, `deterministically_checked`, `reviewed`, `behaviorally_qualified`, `formally_verified` | How the assertion was qualified. |
| `join_decision` | `eligible_direct`, `requires_adapter`, `requires_review`, `reject`, `unknown` | Planning result only, not execution authorization. |

`eligible_direct` requires a direct, non-lossy, verified relationship with
deterministic or formal assurance, an active checker artifact with an exact
digest match, exact contract digests, equal
effective port semantics for `identical`, and current digest-bound evidence.
`transformable` requires an adapter. In v0.1, `requires_adapter` is limited to
verified `total_lossless` adapters; lossy, partial, guarded, or effectful
transformations use `requires_review`. Retrieval similarity
belongs in descriptive relations or representations, never in
`eligible_direct`.

## 8. Adapters

An adapter is directional and references exact source and target contracts.
Its classification is one of:

```text
total_lossless
total_lossy
partial_guarded
stateful_effectful
```

The `operations` list is an extension point for a restricted adapter DSL.
Implementations SHOULD begin with deterministic operations such as rename,
reorder, project, select, nest, unnest, safe widening, enum mapping, validated
parse/format, and unit conversion.

An adapter is not verified merely because it exists. `lifecycle: verified`
requires evidence and an implementation/action reference.

## 9. Evidence

An evidence record binds a typed claim or result to exact subject references.
When evidence affects eligibility it MUST include `subject_digests` computed
over the RFC 8785 canonical form of the exact relation or adapter record.
It SHOULD include relevant digests for:

- contract;
- artifact or dependency closure;
- environment;
- workload, corpus, oracle, and seeds;
- tool/checker;
- policy.

Evidence result values are `pass`, `fail`, `inconclusive`, or `not_run`.
Evidence may expire or be revoked. A passing test is not a universal truth
claim.

For signed transport, an OCG evidence predicate SHOULD be carried inside an
in-toto Statement (or an equivalent signed attestation envelope). The OCG
record is the predicate/index view; it is not a replacement signature format.
Structural conformance and current eligibility are reported separately so an
expired or revoked record remains valid history without authorizing a current
join.

The reference checker reports `eligibility_evaluated: false` and
`currently_eligible: null` unless the document claims the Contract profile.
A Core-only or Core+Retrieval candidate can therefore be structurally valid
without being misreported as currently eligible.

Eligibility is claim-scoped, not merely digest-scoped. The v0.1 checker accepts
`contract-identity` for a direct relation, `action-contract-conformance` for
endpoint action/implementation/artifact records, and `adapter-conformance` for
an adapter route. A different passing claim such as embedding lineage cannot
qualify an executable join merely because it names the same subject. Future
policy profiles may register additional accepted predicates.

## 10. Measures and weights

A relation or evidence record MAY contain `measures`. A measure includes:

- a stable metric ID;
- a value;
- `measured`, `estimated`, or `declared` provenance;
- optional unit;
- optimization direction;
- context reference;
- aggregation/window, sample count, and measurement procedure where relevant;
- optional uncertainty bounds/confidence;
- evidence references and observation time.

Consumers MUST NOT infer the meaning of a measure from field position or an
unqualified name such as `weight`.

Search-stage fusion weights are versioned preferences inside a
`SearchProfile`. They MUST NOT be copied into compatibility relations as if
they were evidence.

## 11. Representations and embeddings

A `Representation` names one derived view of a subject. `encoding` may be:

```text
lexical
sparse_vector
dense_vector
multivector
binary_vector
graph_features
fingerprint
custom
```

Vector representations MUST specify:

- `space_id`;
- a digest-bound projection recipe;
- model identity and revision;
- model or tuning artifact digests when available;
- source-content digest and view/projection recipe;
- role/modality, dimensions, numeric type, normalization, and distance;
- inline payload or a digest-bound external payload reference;
- generation metadata.

A fine-tuned model or adapter creates a distinct `space_id` unless the producer
can demonstrate byte-identical outputs to the original space.

Two vectors may be compared directly only when their `space_id`, dimensions,
normalization, and distance semantics agree. Cross-space combination requires
rank fusion, declared score calibration, learned reranking, or a verified
`embedding_transform` relation.

## 12. Search profiles

A search profile describes portable retrieval intent:

- hard gates and filters;
- one or more lexical, structured, sparse, dense, multivector, graph, or
  reranker stages;
- candidate limits and backend-neutral parameters;
- fusion method and per-stage preferences;
- reranking and diversification;
- evaluation evidence;
- eligibility policy reference.

Backends may compile this intent into their own APIs. Conformance does not
require bit-identical scores across engines. A backend MUST emit a receipt that
records the executed profile, backend/version, index snapshot, parameters,
latency, and returned IDs if the result is used for evaluation or planning.

Search profiles can retrieve compatibility candidates. They cannot create a
verified compatibility relation by themselves.

## 13. Profiles and conformance

### Core profile

Requires valid top-level metadata, nodes, actions, ports, and relations plus all
cross-reference and uniqueness rules.

### Contract profile

Adds native contract references, behavior constraints, effects, compatibility
assertions, and adapters.

### Evidence profile

Adds digest-bound artifacts, evidence, validity, and issuer information.

### Retrieval profile

Adds representations, embedding identity, search profiles, and evaluation
references.

### Execution profile

Will add implementation bindings, authorization-policy references, PlanLocks,
and receipts. The execution profile is reserved for a later draft and is
rejected by the v0.1 checker; this version does not define a universal
invocation or authorization protocol.

A producer MUST list the profiles it claims in `profiles`. A consumer MUST
report which profiles it actually validates.

## 14. Extensions

The top-level `extensions` object and record-local `metadata` objects may carry
producer fields. Extension keys SHOULD be URI-qualified or use a registered
namespace prefix.

Consumers SHOULD preserve unknown extensions when round-tripping. Unknown
extensions MUST NOT weaken a core constraint or convert `unknown` into an
eligible join.

## 15. Native-format and ecosystem projections

Recommended mappings are:

- OKF for narrative concepts and progressive-disclosure documentation;
- ARD/AI Catalog for web publication and federated discovery;
- MCP, A2A, OpenAPI, AsyncAPI, WIT, CWL, and Agent Spec for invocation or
  workflow bindings;
- JSON-LD/RDF for semantic-web graph exchange;
- FnO for abstract function, parameter, output, implementation, mapping, and
  execution projections;
- GraphML for ported/hyperedge visualization/interchange;
- GraphAr/Parquet for large property-graph projections;
- Arrow/Parquet for vector sidecars;
- PROV-O and in-toto-style attestations for provenance/evidence projections;
- OCI, wheels, Wasm components, or source bundles for artifacts.

Projection loss MUST be reported. A lossy projection MUST NOT become the new
authoritative contract.

## 16. Versioning

Draft versions use semantic versioning plus a `-draft` suffix. Before 1.0,
breaking changes may occur in minor versions but MUST be documented.

After 1.0:

- patch: editorial or conformance clarifications;
- minor: backward-compatible optional fields or registered values;
- major: breaking wire or semantic change.

## 17. Reference files

- Schema: [`schemas/open-capability-graph.schema.json`](schemas/open-capability-graph.schema.json)
- Example: [`examples/customer-record-pipeline.ocg.json`](examples/customer-record-pipeline.ocg.json)
- Validator: [`../../../scripts/check_open_capability_graph.py`](../../../scripts/check_open_capability_graph.py)
- Interoperability fixtures: [`interoperability/fixtures/`](interoperability/fixtures/)
- Interoperability runner: [`../../../scripts/run_ocg_interop_bakeoff.py`](../../../scripts/run_ocg_interop_bakeoff.py)
- Executed interoperability report: [`../../../docs/ocg-interoperability-bakeoff-2026-07-11.md`](../../../docs/ocg-interoperability-bakeoff-2026-07-11.md)

From the repository root:

```bash
python3 -m pip install -e .
python3 scripts/check_open_capability_graph.py
```

The checker validates both JSON shape assumptions and semantic invariants such
as unique IDs, valid references, action port directions, compatibility safety,
embedding dimensions, vector-space selection, and search-stage references.

Current reference receipt:

```text
49 fixture records using RFC-reserved urn:example identifiers
3 actions / 9 relations / 1 verified adapter / 12 artifacts
5 evidence records, 4 with RFC 8785 subject bindings / 5 representations / 3 embedding spaces
JSON Schema: pass
semantic, RFC 8785 binding, local-digest, and current-eligibility checks: pass
2 positive and 44 adversarial conformance tests: pass
130 repository tests: pass
```

This receipt demonstrates the draft and checker, not ecosystem adoption,
retrieval quality, universal semantic compatibility, or standards status.

The separate interoperability bakeoff imports candidate-only MCP, OpenAPI,
CWL, WIT, and Agent Spec fixtures, executes one retrieval profile on a Python
reference backend and SQLite FTS5, and runs conservative compatibility cases.
Its receipts intentionally do not establish planning or execution eligibility.
