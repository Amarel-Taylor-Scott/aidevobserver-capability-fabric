# Open Edge and Primitive Standards Landscape

**Date:** 2026-07-10  
**Status:** Research report and design recommendation  
**Scope:** executable code primitives, directional edges, multi-port actions,
agentic discovery, graph interchange, multiple embeddings, tunable retrieval,
weights, evidence, and search-engine portability

## Executive answer

As of 2026-07-10, this review found no adopted or de facto standard called
**Open Edge Format** or **Open Primitive Format** that combines all of the
following:

- independently published code or service primitives;
- typed, directional, multi-input and multi-output contracts;
- preconditions, guarantees, errors, effects, state, security, and protocol;
- machine-checkable producer-output to consumer-input compatibility;
- adapters, evidence, revocation, planning eligibility, and a path to
  policy-scoped execution admission;
- multiple embedding spaces and sparse/lexical/graph representations;
- portable search profiles, fusion weights, and backend projections.

There are, however, many strong partial standards. The important conclusion is
not that Teleon should invent an entire graph stack. It is that Teleon is in a
good position to publish the missing **application-layer contract graph** while
reusing existing standards below and beside it.

The closest literal “primitive/function format” found is the independent
[Function Ontology (FnO)](https://fno.io/spec/). FnO already distinguishes an
abstract function from implementations, parameters, outputs, mappings,
executions, and experimental compositions. It is a highly relevant projection
target and vocabulary source, but its own specification says it is a draft
without standards-organization standing. It does not provide the fail-closed
compatibility, effects, policy, evidence, vector-space, or search-profile layer
needed here.

The internal working name is **Open Capability Graph (OCG)**. This is not a
claim that a standards body has adopted it, and a broader collision search is
required before publication. Avoid these names:

- **Open Graph** conflicts with the established Open Graph Protocol and Open
  Graph Benchmark terminology.
- **Open Edge** is heavily associated with Progress OpenEdge and generic edge
  computing.
- **Open Primitive Protocol** is already used by a 2026 v0.1 data-provider
  manifest and signed-response-envelope project.
- **OPG** is an established abbreviation for Open Graph Protocol.
- **Capability Graph** is already used by other agent products, including the
  [Plane Capability Graph](https://www.vadyl.com/docs/concepts/plane-capability-graph),
  so OCG should remain a working name for now.

The best standards posture is:

> Preserve native formats, publish a small capability-contract kernel, and
> provide loss-aware projections into discovery, graph, vector, workflow,
> package, and provenance ecosystems.

OCG should not standardize one embedding model, one vector database, one graph
database, or one planner. It should standardize the identity and meaning of the
objects those systems index.

## 1. Google Open Knowledge Format is complementary, not sufficient

Google Cloud published [Open Knowledge Format (OKF) v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
on 2026-06-12. It deliberately makes a very small interoperability promise:
knowledge is a directory of Markdown files with YAML frontmatter, and only the
`type` field is required.

That minimalism is a useful precedent. OKF separates format from platform,
allows producer-defined extensions, works in Git, remains readable without an
SDK, and permits any search system to index the bundle.

But the OKF specification is explicit about its graph limit: a Markdown link
asserts that two concepts are related, while the type of the relationship is
left in surrounding prose. Consumers normally treat links as directed,
untyped edges. OKF also explicitly declines to define a schema registry,
storage system, query infrastructure, or replacement for domain formats such
as Protobuf and OpenAPI.

Therefore:

- OKF is a good narrative/documentation projection for an OCG bundle.
- An OCG action, contract, or evidence record can link to an OKF concept.
- OCG must not infer executable compatibility from an OKF link.
- OCG should copy OKF's producer/consumer independence and progressive
  disclosure, but not its deliberately untyped link semantics.

## 2. The closest 2026 agentic standards

### 2.1 Agentic Resource Discovery is the discovery layer

[Agentic Resource Discovery (ARD) v0.9](https://agenticresourcediscovery.org/spec/)
is a May 2026 proposal announced in June by a working group involving Google,
Microsoft, Hugging Face, and other companies. It is the most important new
neighbor for this project.

ARD defines:

- `/.well-known/ai-catalog.json` publishing;
- domain-anchored identifiers;
- catalogs and federated registries;
- natural-language search plus structured filters;
- representative queries intended for semantic indexing;
- artifact media types and value-or-reference delivery;
- optional identity, attestation, and provenance metadata;
- a REST discovery API.

ARD deliberately stops before invocation. It treats MCP servers, A2A agents,
skills, APIs, workflows, and nested catalogs as opaque artifact types and hands
the selected record to its native protocol. It does not define typed primitive
ports, compatibility, effects, adapters, graph planning, embedding identity,
score calibration, or execution admission.

This is an opportunity, not a conflict. An OCG bundle should be publishable as
an AI Catalog entry using `application/json`, with the profile URI advertised
in ARD metadata or an RFC 6906 `Link: <...>; rel="profile"` header. ARD
registries should be able to discover it. OCG then provides the deeper contract
graph after discovery; `application/json; profile=...` is not claimed.

### 2.2 MCP describes callable tools, not cross-tool edges

The [Model Context Protocol tool model](https://modelcontextprotocol.io/specification/2025-11-25/schema)
provides tool names, descriptions, JSON Schema input and optional output
schemas, structured results, and behavioral hints such as read-only,
destructive, idempotent, and open-world behavior.

This is valuable import material, but MCP does not define:

- whether one tool output satisfies another tool input;
- units, semantic concepts, pre/postconditions, or state transitions;
- a compatibility lattice or verified adapters;
- a global capability identity independent of a server;
- evidence-bound execution admission;
- multi-tool graph search.

MCP annotations are also hints, not proofs. OCG should import an MCP tool as an
implementation/action and preserve its native schema, while marking unsupported
semantic dimensions as unknown.

### 2.3 A2A describes agents and skills at media-type granularity

The [A2A Agent Card](https://a2a-protocol.org/latest/topics/agent-discovery/)
describes an agent's endpoint, protocol features, security schemes, and skills.
An `AgentSkill` has an ID, name, description, tags, examples, and input/output
media types. A2A v1.0 is a protocol for opaque agents to exchange messages,
artifacts, tasks, streams, and push updates.

A2A is richer than a plain directory but still does not carry field-level
input/output contracts, action effects, compatibility rules, or proof that two
skills can be safely chained. OCG can represent each A2A skill as a capability
and its remote agent as one implementation, retaining A2A as the invocation
binding.

### 2.4 OASF is a useful taxonomy and record system

The [Open Agentic Schema Framework (OASF)](https://docs.agntcy.org/oasf/agent-record-guide/)
defines versioned agent records, hierarchical skill and domain taxonomies,
locators, modules, schema validation, and discovery-oriented metadata. It is a
Linux Foundation AGNTCY project and reached a 1.0 line in 2026.

OASF is useful for classification and import/export. Its skill taxonomy does
not establish typed value flow, preconditions, effects, adapter safety, or
runtime substitutability. OCG should reference OASF skill/domain IDs rather
than create a competing universal skill taxonomy.

### 2.5 Agent Skills favors human-readable procedural packages

The [Agent Skills specification](https://agentskills.io/specification) defines
`SKILL.md` with required name and description, optional license,
compatibility, metadata, allowed tools, and supporting scripts/references.
It is intentionally instruction-oriented. It does not define typed inputs,
outputs, action semantics, or safe chaining. An OCG implementation can point
to a skill artifact without treating its prose as an executable contract.

### 2.6 Oracle Agent Spec is a real declarative composition format

[Open Agent Specification](https://github.com/oracle/agent-spec) defines
portable agents and structured flows, component references, JSON Schema
properties, edges, and runtime adapters. This is one of the closest current
formats to an agent implementation interchange language.

It remains agent-system oriented. It does not attempt to be a global code
primitive registry, general compatibility algebra, multi-embedding exchange
format, or cross-registry evidence graph. OCG should import Agent Spec agents
and flow components rather than duplicate their runtime configuration model.

### 2.7 FIPA already standardized federated agent-service discovery

The current revision listed for the
[FIPA Agent Management specification](https://www.fipa.org/specs/fipa00023/)
defines Agent Management Systems and Directory Facilitators with service
descriptions, search, and federated directories. Separate FIPA specifications
cover brokering and recruiting. This is an important historical counterexample
to any claim that agent discovery itself is new. FIPA does not define
field-level code contracts, producer-to-consumer substitutability, digest-bound
evidence, or multi-representation retrieval.

### 2.8 Other 2026 proposals confirm demand but not convergence

Several new projects use overlapping language:

- [Open Primitive Protocol v0.1.0](https://openprimitive.com/protocol.html)
  standardizes a data-provider manifest, query endpoint, provenance/freshness
  response envelope, and optional Ed25519 proof. It is not a code primitive or
  compatibility graph.
- The [Open Embeddings RFC](https://www.open-embeddings.org/rfc.html) proposes
  JSON distribution of multiple embeddings per content item. It is an informal
  community draft, and it does not yet identify enough of the vector-space,
  normalization, distance, calibration, artifact-digest, and trust context for
  portable comparison.
- [agentproto](https://agentproto.sh/) has draft proposals for tools, workflows,
  shared I/O blocks, actions, processors, adapters, registries, policies, and
  runtimes. Most relevant records remain drafts, and the project is not an
  executable compatibility or evidence standard.
- [JSON Agents](https://github.com/Json-Agents/Standard) is another immature,
  overlapping proposal spanning agent records, execution, governance, and
  graphs. Its existence reinforces the need for adapters and a neutral naming
  check rather than a premature claim of convergence.

These projects are evidence that the layer is emerging quickly. They are also
a reason to use distinct naming, explicit media types, and adapters instead of
claiming ownership of all agent metadata.

## 3. Existing graph and edge formats

| Format | What it already solves | Why it is not the missing primitive standard |
|---|---|---|
| [RDF 1.2](https://www.w3.org/TR/rdf12-concepts/) and [JSON-LD 1.1](https://www.w3.org/TR/json-ld11/) | Global IRIs, directed assertions, typed literals, named graphs, statement annotation/reification, linked-data serialization | Binary assertions do not by themselves define actions, ports, requirement/guarantee variance, effects, compatibility, admission, or embeddings. RDF's open-world semantics are a poor default for fail-closed execution. |
| [GraphML](https://graphml.graphdrawing.org/specification.html) | Nodes, directed/undirected edges, ports, nested graphs, attributes, and true hyperedges | Excellent structural precedent, but extension keys lack shared executable semantics and many consumers ignore advanced constructs. |
| [KGTK](https://kgtk.readthedocs.io/en/stable/specification/) | Simple TSV node/edge interchange, edge-as-node statements, qualifiers, provenance columns, arbitrary attributed graphs/hypergraphs | Useful bulk and curation projection; it does not define code contracts or safe composition. |
| [GEXF](https://docs.gephi.org/desktop/User_Manual/Import/GEXF_File_Format/) | Static/dynamic graphs, typed attributes, parallel edges, visualization metadata, and a scalar edge weight | Its weight is an application-defined number with no metric, unit, context, uncertainty, or evidence semantics. |
| [Apache TinkerPop GraphSON](https://tinkerpop.apache.org/docs/current/dev/io/) | JSON serialization for attributed property graphs and broad graph-tool support | Binary property-graph projection, not a portable contract/evidence model. Version and type modes can be lossy. |
| [ISO/IEC 39075:2024 GQL](https://www.iso.org/standard/76120.html) | Standard property-graph data definition, manipulation, and query language | A query language and database data model, not a portable executable-edge specification. |
| [Apache GraphAr](https://graphar.apache.org/docs/specification/format/) | Chunked, columnar, typed large-scale property graph storage over Parquet/ORC/CSV/JSON with CSR/CSC/COO layouts | Candidate bulk physical projection; it does not itself prove 100M-scale OCG serving or give application properties shared semantic meaning. |
| [PROV-O](https://www.w3.org/TR/prov-o/) | Standard provenance vocabulary for entities, activities, agents, use, generation, derivation, and attribution | Provenance does not establish functional correctness, compatibility, or current authorization. |
| [SHACL](https://www.w3.org/TR/shacl/) | RDF graph validation against shapes and constraints | It can validate an RDF projection but does not define producer/consumer compatibility or behavior. |
| [SKOS](https://www.w3.org/TR/skos-reference/) and [SSSOM](https://mapping-commons.github.io/sssom/dev/) | Exact/close/broader/narrower mappings, mapping provenance, confidence, review, and justification | These are semantic mapping records, not executable substitutability. A close match is intentionally not transitive proof. |

The lesson is to publish OCG projections into these ecosystems. Replacing them
would add work and reduce adoption.

## 4. Domain standards that already model executable primitives

### 4.1 FnO is the closest implementation-independent function vocabulary

The [Function Ontology](https://fno.io/spec/) is the most direct prior answer
to “has anyone published a primitive format?” It models:

- abstract functions, problems, and algorithms;
- ordered/required parameters and multiple outputs;
- concrete implementations and mappings from abstract parameters to
  implementation positions or properties;
- executions and returned values;
- experimental compositions whose directed mappings connect a constant,
  parameter, or output to another parameter or output.

OCG should therefore provide a loss-aware FnO/JSON-LD projection and reuse FnO
identifiers where their semantics match. FnO still does not define whether a
producer guarantee safely satisfies a consumer requirement, preconditions and
effects, evidence-based admission, multiple embedding spaces, backend-neutral
search profiles, or current authorization. Its composition vocabulary is also
explicitly experimental. OCG's strongest case is as a safety, evidence, and
retrieval profile around this lineage—not as a claim that functions and their
ports have never been modeled.

### 4.2 ONNX is the strongest successful precedent

[ONNX IR](https://onnx.ai/onnx/repo-docs/IR.html) represents a partially
ordered computation graph whose nodes invoke versioned operators and whose
named inputs and outputs carry tensor types and shapes. It supports operator
sets, custom domains, functions, subgraphs, type/shape inference, and tests.

ONNX succeeds because it has a bounded domain and a stable operator algebra.
It does not attempt to model arbitrary filesystem/network/database effects,
services, human actions, packages, licenses, security boundaries, or business
semantics. OCG should copy its versioned-profile and conformance-test strategy,
not stretch ONNX beyond tensors.

### 4.3 Common Workflow Language is close for command-line dataflow

[CWL v1.2](https://www.commonwl.org/v1.2/Workflow.html) defines command-line
tools and workflows with typed inputs and outputs, explicit step dependencies,
requirements, hints, network access, work reuse, scatter, and runtime
semantics. It is a real open, multi-vendor standard.

CWL is excellent for scientific/file-oriented command workflows. It is not a
general registry compatibility format for functions, APIs, stateful services,
agents, SQL, event streams, or deployment components. OCG can use CWL as a
carrier and execution profile.

### 4.4 TOSCA models requirements and capabilities in deployment graphs

[OASIS TOSCA](https://docs.oasis-open.org/tosca/TOSCA/v2.0/os/TOSCA-v2.0-os.html)
defines node types, relationship types, interfaces, artifacts, policies,
properties, requirements, and capabilities. A requirement on one node may be
fulfilled by a compatible capability on another node.

This is conceptually close to directional edge satisfaction, but it targets
cloud application topology and lifecycle orchestration, not arbitrary
value-flow contracts or code primitive search.

### 4.5 PDDL is the direct action-planning precedent

[PDDL 2.1](https://www.cs.cmu.edu/afs/cs/project/jair/pub/volume20/fox03a-html/JAIRpddl.html)
models actions, typed parameters, preconditions, effects, numeric fluents,
durations, resources, plan metrics, and temporal plans. It is the clearest
precedent for treating a primitive as an action rather than a binary graph
edge. PDDL does not provide artifact packaging, native API/schema preservation,
software supply-chain evidence, embeddings, or registry discovery. OCG should
borrow action semantics and planner discipline without becoming a new planning
language.

### 4.6 WIT defines portable interfaces but not behavior

[WebAssembly Interface Types (WIT)](https://component-model.bytecodealliance.org/design/wit.html)
defines functions, records, variants, resources, streams, futures, interfaces,
worlds, imports, and exports. It is a strong native contract dialect for Wasm
components. It does not define semantic meaning, preconditions, effects,
evidence, or search.

### 4.7 OpenAPI, AsyncAPI, Arazzo, and WoT describe protocol affordances

- OpenAPI describes HTTP operations and schemas. Its Link Object can map
  response values into another operation's parameters, while explicitly not
  guaranteeing that the linked operation will succeed or be permitted.
- AsyncAPI describes message-driven channels and operations.
- Arazzo describes sequences of API calls plus explicit `dependsOn` and
  output-reference dependencies.
- [W3C Web of Things Thing Description](https://www.w3.org/TR/wot-thing-description/)
  describes properties, actions, events, data schemas, forms, protocol
  bindings, and security mechanisms.

These should remain lossless native documents referenced by OCG action and port
records. Translating every construct into one super-IR would lose semantics.

### 4.8 OpenLineage models executed dataflow

[OpenLineage](https://openlineage.io/docs/spec/object-model/) standardizes
jobs, runs, input/output datasets, and extensible facets. It is useful for
observed execution and lineage receipts. It does not assert that an arbitrary
output is safe input for a different job.

## 5. The closest historical attempt: semantic web services

The absence of a modern standard does not mean the idea is new.

[OWL-S](https://www.w3.org/submissions/OWL-S/) was submitted to W3C in 2004.
It defined:

- a service profile for advertising and discovery;
- a process model for operation and composition;
- a grounding for concrete messages and protocols;
- inputs, outputs, preconditions, and effects (IOPEs);
- composite processes and automated service use.

OWL-S is remarkably close to the conceptual target. It never became a W3C
Recommendation, and its own specification noted that profiles and process
models could be inconsistent without becoming invalid OWL.

The [Web Service Modeling Ontology (WSMO)](https://www.w3.org/submissions/WSMO/)
was another close attempt. It separated ontologies, requested goals, Web
service capabilities/interfaces, and mediators for data, process, and protocol
mismatches. That mediator concept strongly anticipates first-class OCG
adapters. WSMO also illustrates the adoption cost of making a heavyweight
semantic framework the prerequisite for ordinary service publication.

[SAWSDL](https://www.w3.org/TR/sawsdl/) later standardized the smaller,
deployable subset: semantic model references on WSDL/XML Schema components and
lifting/lowering mappings between XML and semantic data. It did not prescribe
an ontology language, discovery algorithm, or composition engine.

The history suggests three adoption rules:

1. Keep the mandatory kernel much smaller than the full research model.
2. Make useful tooling possible without a reasoner or ontology server.
3. Separate descriptive/candidate semantics from verified executable claims.

## 6. Why a universal primitive-edge standard has not emerged

### 6.1 Registry search and automatic composition tolerate different errors

A package or code search result can be plausibly related; a human reads it
before use. Automatic composition must reject a false edge before code runs.
This changes the acceptable false-positive rate and makes prose or embedding
similarity insufficient.

### 6.2 Interfaces do not determine behavior

Two functions can share the same JSON shape while differing in units,
ordering, locale, error behavior, idempotency, side effects, transactions,
privacy boundaries, or meaning. Complete behavioral equivalence is generally
not decidable from source or schemas.

### 6.3 The useful domains have incompatible native semantics

Protobuf compatibility, Avro reader/writer resolution, JSON Schema
validation, WIT resources, SQL table constraints, OpenAPI operations, Arrow
schemas, and Python typing answer different questions. A universal Boolean
`compatible` would be either incomplete or unsafe.

### 6.4 Publishers have weak incentives to author expensive contracts

Package registries gain adoption from cheap publication. Requiring complete
preconditions, effects, proofs, ontological mappings, and benchmark receipts
would suppress supply. The core must allow a low-cost candidate record and
make higher assurance progressively valuable.

### 6.5 Search providers compete on ranking

GitHub, package registries, vector databases, and agent registries treat
ranking signals as product differentiation. Embedding models change quickly,
their vector spaces are incompatible, and raw scores are not calibrated across
models or engines. Standardizing one vector or ranking formula would freeze
the least stable layer.

### 6.6 Successful standards narrow their promise

ONNX narrows to tensor computation; CWL to command-line workflows; TOSCA to
deployment topology; WIT to interface types; OpenAPI to HTTP; ARD to discovery;
OKF to portable knowledge files. A broad standard should be a family of
profiles around a small kernel, not one maximal schema every producer must
fill.

### 6.7 Maturity is not uniform

The survey must not treat a product API, community draft, and formal standard
as equivalent:

| Family | Maturity as reviewed | Design use |
|---|---|---|
| JSON-LD 1.1, SAWSDL, TOSCA 2.0 | W3C/OASIS standards | Reuse directly where in scope |
| ONNX, CWL, OpenAPI, A2A | Established open specifications with implementations | Native carrier/import profile |
| RDF 1.2 | W3C Candidate Recommendation Snapshot; RDF 1.1 remains the Recommendation | Track, while keeping RDF 1.1 compatibility |
| GraphAr | Apache-incubating storage specification | Experimental bulk projection |
| OKF 0.1, ARD 0.9, FnO, Open Embeddings, JSON Agents | Draft, proposed, or unofficial | Interoperate experimentally; do not claim convergence |
| Qdrant, Weaviate, Milvus, Vespa, pgvector | Product/storage APIs | Backend adapters and benchmark targets, not wire semantics |

## 7. Options and tradeoffs

The scores below are architecture-fit judgments from this review, not
published benchmark measurements. Five is best. Implementation risk is scored
with five meaning lowest risk.

| Option | Reuse of standards | Expressiveness | Developer accessibility | Adoption path | Implementation risk | Main problem |
|---|---:|---:|---:|---:|---:|---|
| Universal new super-IR | 1 | 5 | 1 | 1 | 1 | High semantic loss, enormous governance surface, slow adoption |
| RDF/OWL ontology as the only format | 4 | 5 | 2 | 3 | 2 | Reasoning complexity and open-world behavior leak into execution |
| Extend ARD/AI Catalog only | 5 | 2 | 5 | 5 | 5 | Discovery envelope cannot honestly carry full action/edge semantics |
| Adopt CWL or TOSCA as the universal primitive | 4 | 3 | 3 | 3 | 4 | Strong domain bias; lossy for functions, APIs, agents, and services |
| JSON contract kernel plus native references and projections | 5 | 4 | 5 | 4 | 4 | Requires disciplined scope and conformance stewardship |

The last option is recommended.

### Where not following a standard creates value

Most individual ingredients below have precedents in FnO, WSMO, SAWSDL, PDDL,
in-toto, and graph standards. Teleon's differentiating scope should be their
small, cross-dialect combination—not a claim to have invented each concept:

- stable capability versus implementation identity;
- multi-port actions as hyperedges;
- requirement/guarantee contracts and effect boundaries;
- orthogonal relationship, mechanism, lossiness, assurance, and join-decision
  axes with fail-closed abstention;
- first-class verified, guarded, partial, and lossy adapters;
- claim-scoped evidence and planning-eligibility dependencies;
- embedding-space identity and comparison rules;
- portable search intent and experiment profiles;
- PlanLock and execution-receipt linkage.

### Where creating a new standard would destroy value

Teleon should not invent replacements for:

- JSON Schema, Protobuf, Avro, Arrow, OpenAPI, AsyncAPI, WIT, or CWL;
- RDF/JSON-LD identifiers, FnO function descriptions, and semantic graph exchange;
- ARD/AI Catalog federated discovery;
- MCP or A2A invocation;
- OCI, wheels, Wasm components, or source archives;
- PROV-O, in-toto, SLSA, SPDX, CycloneDX, TUF, or Sigstore;
- Parquet, Arrow, GraphAr, or vector-database storage engines;
- ANN indexes, lexical search, rerankers, or graph query languages.

## 8. Proposed Open Capability Graph kernel

### 8.1 Core records

| Record | Purpose |
|---|---|
| `Node` | Stable identity for capability, contract, implementation, concept, policy, environment, or other addressable object |
| `Action` | An executable or invocable hyperedge with multiple input/output/error/control ports |
| `Port` | Directional reference to a native contract plus cardinality, protocol, and semantic constraints |
| `Relation` | A typed, independently versioned assertion between nodes or ports |
| `CompatibilityAssertion` | Directional producer-to-consumer decision, checker, conditions, adapter, evidence, validity, and status |
| `Adapter` | A first-class transformation with lossiness/partiality classification, operations, guards, implementation, and evidence |
| `Artifact` | Immutable bytes/tree, digest, media type, and locators |
| `Evidence` | Claim/result bound to exact subjects, contracts, environments, workloads, policies, and time |
| `Representation` | One lexical, sparse, dense, multivector, code, graph, image, or other derived search representation |
| `SearchProfile` | Engine-neutral retrieval stages, hard filters, fusion, reranking, and evaluation references |

### 8.2 An action is a hyperedge, not a binary edge

A primitive that consumes three values and produces two values plus an error is
one action with six ports. It must not be flattened into three unrelated
binary edges. Readiness depends on all required inputs; outputs and effects may
be conditional or inseparable.

Binary property-graph projections may introduce an action node and connect it
to ports. The authoritative model remains the action/hyperedge.

### 8.3 Relations are assertions, not universal facts

Every relation should carry:

- a unique ID so parallel edges are possible;
- source, target, and direction;
- relation kind;
- candidate, verified, rejected, or revoked status;
- issuer and time validity;
- conditions and environment scope;
- evidence and counterexamples;
- typed measures.

A search system can add descriptive `close` or `related` relations without
corrupting verified compatibility. A failed mapping can remain as a rejected
edge and prevent repeat work.

### 8.4 Compatibility is directional and fail-closed

Do not collapse five different questions into one compatibility “lattice.”
The draft now records them independently:

| Axis | Examples |
|---|---|
| Relationship | identical, producer-substitutable, family/revision compatible, explicitly equivalent, transformable, related, unknown, incompatible |
| Mechanism | direct or adapter |
| Loss/totality/effect | none, total lossless, total lossy, partial guarded, stateful/effectful, unknown |
| Assurance | publisher asserted, deterministically checked, reviewed, behaviorally qualified, formally verified |
| Join decision | eligible direct, requires adapter, requires review, reject, unknown |

This matters because a lossy adapter may also be behaviorally qualified, and a
stateful adapter may still be total. Retrieval similarity can improve recall
but never creates an `eligible_direct` join. A timeout or unsupported schema
feature yields `unknown`. The v0.1 decision is planning eligibility only;
policy-, workload-, environment-, and time-scoped execution authorization is
reserved for the future Execution profile.

### 8.5 Evidence should reuse attestation envelopes

OCG should define a typed evidence predicate/index view, not a competing
unsigned signature envelope. Eligibility-bearing evidence binds the exact
relation or adapter through an RFC 8785 record digest and binds relevant native
contract, artifact, environment, workload, policy, checker, and time digests.
For transport, issuer identity, signature, and subject digest should map into
an [in-toto Statement](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
or an equivalent signed attestation envelope. Expiry and revocation affect
current eligibility without deleting the historical record.

## 9. Multiple embeddings and tunable retrieval

### 9.1 Multiple representations are required

One primitive may need separate representations for:

- human intent;
- when-to-use and when-not-to-use;
- input and output ports;
- effects and security boundaries;
- failure modes;
- source code;
- examples and counterexamples;
- graph neighborhood;
- observed traces;
- implementation/runtime fit.

The standard should allow any number of `Representation` records per subject.
It should not require every registry to materialize all of them.

### 9.2 Every vector space needs identity

An embedding record should identify at least:

- subject and exact source-content digest;
- view/projection recipe;
- modality and query/document role;
- model URI, revision, and artifact digest;
- base model and tuning adapter/recipe/data digests when fine-tuned;
- vector-space ID;
- dimensions and numeric type;
- normalization and distance metric;
- truncation, chunking, pooling, and quantization;
- generation tool and time;
- inline vector or digest-bound Arrow/Parquet/other sidecar reference.

Fine-tuning creates a new space ID. Two vectors with the same dimension are not
therefore comparable.

### 9.3 Cross-space comparison must be explicit

Raw distances from different models or even different normalization settings
must not be averaged. Valid combination methods include:

- rank fusion such as RRF;
- score fusion after declared calibration;
- learned reranking with a versioned model;
- a separately registered and evaluated space transformation.

A cross-space transform is itself an implementation with evidence and version
identity, not an implicit convenience.

### 9.4 Search profiles should be portable intent, not bit-identical execution

Current systems already demonstrate the required flexibility:

- [Qdrant](https://qdrant.tech/documentation/search/hybrid-queries/) supports
  named dense, sparse, and multivectors; nested prefetch; RRF/DBSF; multistage
  reranking; and formula queries.
- [Weaviate](https://weaviate.io/developers/weaviate/search/multi-vector)
  supports multiple target vector spaces and minimum, sum, average, manual
  weight, and normalized relative-score joins.
- [Milvus](https://milvus.io/docs/multi-vector-search.md) supports multiple
  vector fields, multiple ANN requests, weighted ranking, and RRF.
- [Vespa](https://docs.vespa.ai/en/querying/nearest-neighbor-search) supports
  multiple tensor/vector fields, hybrid query operators, arbitrary ranking
  expressions, and phased reranking.
- [pgvector](https://github.com/pgvector/pgvector) supports dense, half,
  binary, and sparse vector types plus several distance operators and HNSW or
  IVFFlat indexes.

These APIs are intentionally different. OCG should describe retrieval stages,
representation selection, filters, candidate counts, fusion, weights,
reranking, and evaluation IDs. Backend adapters compile that intent into
Qdrant, Weaviate, Milvus, Vespa, OpenSearch, pgvector, or another engine.
Exact scores and latency are backend-specific receipts.

### 9.5 Bare edge weights should be prohibited

`weight: 0.83` is not interoperable. It could mean similarity, confidence,
cost, probability, latency, risk, popularity, or a query preference.

A portable measure should look conceptually like:

```json
{
  "metric": "urn:example:ocg:metric:p95-latency",
  "value": 18.4,
  "unit": "ms",
  "objective": "minimize",
  "context_ref": "urn:example:ocg:workload:small-json",
  "uncertainty": {"lower": 17.8, "upper": 19.6, "confidence": 0.95},
  "evidence_refs": ["urn:example:ocg:evidence:bench-2026-07-10"]
}
```

Search-stage weights are a different concept: they express a query policy's
relative preference among retrieval legs. They belong in a versioned
`SearchProfile`, not on a truth-bearing compatibility edge.

## 10. Integration architecture

```text
OKF / docs / source / package metadata
                |
                v
        loss-aware importers
                |
                v
  OCG JSON kernel + native contract references
      |          |          |          |
      v          v          v          v
 ARD catalog   JSON-LD   GraphAr    Arrow/Parquet
 discovery     semantic  bulk graph vector sidecars
      |          |          |          |
      +----------+----------+----------+
                         |
                         v
        engine-specific retrieval projections
     Qdrant / Weaviate / Milvus / Vespa / OpenSearch
                         |
                         v
             compatibility and policy gates
                         |
                         v
                PlanLock + native invocation
             MCP / A2A / OpenAPI / WIT / CWL
                         |
                         v
                    execution receipt
```

The canonical record is not the vector index and not the graph database.
Indexes are rebuildable projections. Native schemas and artifacts remain
lossless references. Execution always resolves exact digests and rechecks
policy/evidence.

## 11. Conformance profiles

Start with independently useful profiles:

1. **Core graph:** IDs, nodes, actions, ports, relations, extensions.
2. **Contract:** native schema references, requirements, guarantees, effects,
   errors, protocols, compatibility assertions, adapters.
3. **Evidence:** artifact digests, claims, environments, workloads, policies,
   issuers, validity, revocation.
4. **Retrieval:** representations, embedding-space identity, search profiles,
   evaluation references.
5. **Agentic discovery:** ARD/AI Catalog projection plus MCP/A2A/Agent Skills
   imports.
6. **Bulk graph:** JSONL/Parquet/GraphAr projection.
7. **Execution:** implementation bindings, PlanLock, and execution receipts.

Unknown extension fields should round-trip. Unknown contract semantics must
produce `unknown` for planning eligibility. Only a later Execution profile may
define policy-, environment-, workload-, and time-scoped authorization.

## 12. Are we in a position to implement it?

Yes—if “implement” means publish a credible draft, reference validator,
importers, conformance fixtures, and measured pilot. Not yet if it means claim
industry-standard status before independent implementations exist.

The local capability-fabric already provides a useful testbed:

- 4,576 capability families;
- 25,344 resolved primitive candidates;
- 129,888 candidate compatibility edges;
- 1,760 route templates;
- 14 runtime wrapper types;
- 600 candidate-bundle examples;
- deterministic generation, ZIP distribution, search, graph routing, and
  PlanLock-shaped output.

Those records expose exactly why a new version is needed: contracts are mostly
names, compatibility is primarily exact equality, edges are binary, and
evidence/admission remain coarse. They are a migration corpus, not a standard
to freeze.

The companion `semantic-linker` work adds multiple retrieval channels, blocker
inventories, plan/lock schemas, implementation digests, and benchmark designs.
Together these assets are enough to build and falsify a v0.1 draft quickly.

### Implemented reference baseline

This repository now contains an exploratory, explicitly non-adopted v0.1
baseline:

- the normative semantic draft in
  [`spec/open-capability-graph/v0.1/README.md`](../spec/open-capability-graph/v0.1/README.md);
- a JSON Schema Draft 2020-12 wire schema;
- a small semantic checker using RFC 8785 canonicalization for exact evidence
  binding, plus checks for reference integrity, directional joins, current
  eligibility, adapter evidence, local artifact digests, vector spaces, and
  search-stage semantics;
- one executed three-action example containing 49 records under the
  RFC-reserved `urn:example` namespace, 12 artifacts, 9 relations (including
  parallel flow and compatibility edges), one verified adapter, 5 evidence
  records, 5 representations, 3 separate embedding spaces, and a five-leg RRF
  search profile;
- 2 positive checks and 44 adversarial checks covering unsafe eligibility,
  expired evidence, exact subject binding, path escape, malformed JSON,
  dangling references, digest mismatch, false contract identity, vector/space
  mismatch, cross-space fusion, and adapter invariants.

The reference checker and JSON Schema pass, the example executes end to end,
and all 66 repository tests pass. These are implementation receipts,
not evidence of retrieval quality, third-party interoperability, or standards
adoption. Draft documents should use `application/json` and advertise the
profile URI through ARD metadata or an RFC 6906 `Link` relation;
an OCG-specific standards-tree media type should not be pursued until
independent implementations stabilize the wire semantics and governance.

## 13. Recommended implementation sequence

### Stage 1 — publish the kernel and validator

- JSON Schema Draft 2020-12 bundle format.
- Semantic conformance checker for cross-record invariants JSON Schema cannot
  express.
- Two positive and at least ten adversarial/negative fixtures.
- Canonicalization and digest rules.
- Clear draft status and change process.
- Specification/license and patent/IPR terms, namespace ownership,
  errata/security handling, and an open change-control authority.
- At least one producer and one consumer implemented outside Teleon before any
  neutral-standard claim.

**Current status:** baseline implemented with RFC 8785 record binding. Official
canonicalization test vectors, a formal governance process, stable namespace,
and independently authored fixtures remain before Stage 1 is complete.

### Stage 2 — import real standards

- MCP tool importer.
- OpenAPI operation importer.
- WIT interface/world importer.
- A2A skill and OASF taxonomy linker.
- Current edge-catalog migrator.
- Preserve all unsupported native constructs and report loss.

### Stage 3 — retrieval projections

- SQLite/FTS baseline.
- Qdrant or pgvector adapter.
- Vespa or OpenSearch adapter for richer hybrid ranking.
- Arrow/Parquet sidecars for vectors.
- RRF baseline before learned fusion.

### Stage 4 — compatibility and evidence

- Exact contract digest and family/revision rules.
- Conservative JSON Schema subset.
- WIT and Protobuf-specific checkers.
- Restricted deterministic adapter DSL.
- Claim-scoped evidence and planning-eligibility policy, projected into signed
  in-toto Statements rather than a new signature envelope.

### Stage 5 — federation and independent implementation

- Publish OCG through ARD/AI Catalog.
- Build a second implementation in another language or recruit one.
- Add a conformance test kit and compatibility matrix.
- Submit media-type and well-known vocabulary registrations only after the
  wire format stabilizes.

### Stage 6 — neutral governance, only if the pilot earns it

- Move the specification namespace and change authority to a durable,
  non-personal domain or neutral foundation process.
- Publish specification copyright/license, patent/IPR terms, extension
  registry rules, errata, security reporting, and backwards-compatibility
  policy.
- Require interoperable producers and consumers from outside Teleon; two code
  paths owned by one organization are not standards validation.
- Keep the current **OCG** name provisional until trademark, acronym, package,
  domain, and existing “Capability Graph” uses have been checked.

## 14. Promotion and kill criteria

Promote v0.1 to a stable 1.0 only if:

- two independent producers and two independent consumers round-trip core
  records;
- native-format loss reports are explicit and tested;
- a held-out benchmark shows better feasible-edge recall than exact names
  without increasing unsafe joins marked planning-eligible;
- at least two search backends execute the same logical search profile;
- compatibility decisions are reproducible from pinned checker and contract
  digests;
- unknown and rejected edges survive round-trip;
- bulk projection handles at least 1M records before claiming 100M readiness.

Narrow or stop the effort if:

- ARD or another standards group adopts equivalent contract/edge semantics;
- most fields cannot be populated without manual ontology work;
- independent consumers use only prose descriptions and ignore contracts;
- backend projections require hidden semantics not expressible in the kernel;
- a simpler MCP/OpenAPI/WIT profile produces equal planning safety and recall.

## 15. Final recommendation

Publish the draft, but position it precisely:

> Open Capability Graph is a portable contract and evidence layer that supports
> fail-closed planning eligibility for independently published capabilities.
> A later conforming executor and policy profile must enforce actual
> authorization. It is not a graph database, vector database, package registry,
> agent protocol, workflow engine, or universal type system.

That boundary is the standard's best chance of adoption. It fills the missing
semantic joint between OKF/ARD discovery and MCP/A2A/WIT/OpenAPI/CWL execution,
while allowing every organization to choose its own embeddings, ranking,
storage, and policy.

## Primary and official references

### Agentic and knowledge formats

- Google Cloud, [Open Knowledge Format v0.1 specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
- Google Developers, [Agentic Resource Discovery announcement](https://developers.googleblog.com/announcing-the-agentic-resource-discovery-specification/)
- ARD working group, [ARD v0.9 specification](https://agenticresourcediscovery.org/spec/)
- ARD working group, [AI Catalog standard](https://agenticresourcediscovery.org/ai_catalog_spec/)
- Model Context Protocol, [tool schema](https://modelcontextprotocol.io/specification/2025-11-25/schema)
- A2A project, [Agent discovery and Agent Cards](https://a2a-protocol.org/latest/topics/agent-discovery/)
- AGNTCY, [OASF agent record guide](https://docs.agntcy.org/oasf/agent-record-guide/)
- Agent Skills, [specification](https://agentskills.io/specification)
- Oracle, [Open Agent Specification](https://github.com/oracle/agent-spec)
- FIPA, [Agent Management Specification](https://www.fipa.org/specs/fipa00023/)
- IETF, [RFC 6906 profile link relation](https://www.rfc-editor.org/rfc/rfc6906.html)
- JSON Agents, [draft standard](https://github.com/Json-Agents/Standard)
- Open Primitive, [Open Primitive Protocol v0.1.0](https://openprimitive.com/protocol.html)
- Open Embeddings, [draft RFC](https://www.open-embeddings.org/rfc.html)

### Graph, mapping, and provenance

- W3C, [RDF 1.2 Concepts](https://www.w3.org/TR/rdf12-concepts/)
- W3C, [JSON-LD 1.1](https://www.w3.org/TR/json-ld11/)
- GraphML, [specification](https://graphml.graphdrawing.org/specification.html)
- KGTK, [file specification](https://kgtk.readthedocs.io/en/stable/specification/)
- Gephi, [GEXF format](https://docs.gephi.org/desktop/User_Manual/Import/GEXF_File_Format/)
- Apache TinkerPop, [GraphSON I/O reference](https://tinkerpop.apache.org/docs/current/dev/io/)
- ISO, [ISO/IEC 39075:2024 GQL](https://www.iso.org/standard/76120.html)
- Apache GraphAr, [format specification](https://graphar.apache.org/docs/specification/format/)
- W3C, [PROV-O](https://www.w3.org/TR/prov-o/)
- W3C, [SHACL](https://www.w3.org/TR/shacl/)
- W3C, [SKOS](https://www.w3.org/TR/skos-reference/)
- Mapping Commons, [SSSOM](https://mapping-commons.github.io/sssom/dev/)
- Function Ontology project, [FnO specification](https://fno.io/spec/)
- in-toto, [Statement v1 specification](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
- RFC Editor, [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785.html)

### Executable and workflow formats

- ONNX, [IR specification](https://onnx.ai/onnx/repo-docs/IR.html)
- Common Workflow Language, [v1.2 workflow specification](https://www.commonwl.org/v1.2/Workflow.html)
- OASIS, [TOSCA 2.0](https://docs.oasis-open.org/tosca/TOSCA/v2.0/os/TOSCA-v2.0-os.html)
- Fox and Long, [PDDL 2.1](https://www.cs.cmu.edu/afs/cs/project/jair/pub/volume20/fox03a-html/JAIRpddl.html)
- Bytecode Alliance, [WIT reference](https://component-model.bytecodealliance.org/design/wit.html)
- OpenAPI Initiative, [OpenAPI 3.2 specification](https://spec.openapis.org/oas/v3.2.0.html)
- OpenAPI Initiative, [Arazzo workflow specification](https://spec.openapis.org/arazzo/latest.html)
- AsyncAPI Initiative, [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0)
- W3C, [Web of Things Thing Description](https://www.w3.org/TR/wot-thing-description/)
- OpenLineage, [object model](https://openlineage.io/docs/spec/object-model/)
- W3C Member Submission, [OWL-S](https://www.w3.org/submissions/OWL-S/)
- W3C Member Submission, [WSMO](https://www.w3.org/submissions/WSMO/)
- W3C, [SAWSDL](https://www.w3.org/TR/sawsdl/)

### Vector and search systems

- Apache Arrow, [canonical fixed-shape tensor extension](https://arrow.apache.org/docs/format/CanonicalExtensions.html#fixed-shape-tensor)
- Qdrant, [hybrid and multistage queries](https://qdrant.tech/documentation/search/hybrid-queries/)
- Weaviate, [multiple target vectors](https://weaviate.io/developers/weaviate/search/multi-vector)
- Milvus, [multi-vector hybrid search](https://milvus.io/docs/multi-vector-search.md)
- Vespa, [nearest-neighbor and multi-vector search](https://docs.vespa.ai/en/querying/nearest-neighbor-search)
- pgvector, [vector similarity search for PostgreSQL](https://github.com/pgvector/pgvector)
