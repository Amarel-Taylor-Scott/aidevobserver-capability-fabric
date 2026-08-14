# Open Capability Graph interoperability bakeoff

**Date:** 2026-07-11  
**Status:** executed fixture-scale experiment; not an adoption or execution-safety claim

## Outcome

The first Open Capability Graph (OCG) interoperability slice now runs from
native-format fixtures to loss-aware candidate graphs, a shared retrieval
profile, two local lexical implementations with a shared vector/fusion
executor, and conservative compatibility receipts.

The experiment supports a narrower and more useful conclusion than “OCG can
translate everything”:

- one small overlay can retain native MCP, OpenAPI, CWL, WIT, and Agent Spec
  values without asserting semantic equivalence;
- one engine-neutral retrieval profile can execute against a Python reference
  scan and SQLite FTS5 while preserving explicit vector-space identity;
- multiple representations and query weights can coexist without treating a
  search score as compatibility or authorization;
- a conservative checker can return `safe`, `incompatible`, or `unknown` for a
  documented JSON Schema subset;
- unsupported native behavior remains `unknown`, and no imported action gains
  a compatibility edge, PlanLock, or execution authorization.

This is evidence that an open edge/primitive overlay is implementable. It is
not evidence that the current draft covers arbitrary repositories, native
schema evolution, effects, protocols, or ecosystem-scale retrieval.

## What was executed

### 1. Five loss-aware importers

The bakeoff imports representative documents from:

| Native source | Imported surface | Deliberately unresolved |
|---|---|---|
| [MCP Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) | Tool input and optional structured-output schemas | Tool behavior, effect completeness, and annotation truth |
| [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.1.html) | Operation request/response projections | `$ref` resolution, callbacks, links, security authorization, and runtime behavior |
| [CWL 1.2](https://www.commonwl.org/v1.2/Workflow.html) | `Operation` and `CommandLineTool` ports | Expressions, requirements, environment effects, and execution authorization |
| [WIT](https://github.com/WebAssembly/component-model/blob/main/design/mvp/WIT.md) | Interface function parameters and result type projections | Behavioral semantics and automatic splitting of result/error meaning |
| [Agent Spec](https://github.com/oracle/agent-spec) | `ServerTool` input/output property contracts | Tool code, implementation behavior, and safe composition |

Each imported value or explicitly labeled projection is serialized as
deterministically sorted JSON bytes in a data URI and bound to a SHA-256
digest. This is not claimed to be RFC 8785 canonical JSON. WIT raw source and
the normalized JSON projection and normalizer binary are separate digest-bound
artifacts, linked through typed `derives_from`/`depends_on` relations and
contract artifact references. Import warnings are structured and fail closed.
The generated documents claim the OCG Core profile only and contain no
compatibility or flow relation.

### 2. One portable search profile

The merged graph uses the same OCG search profile with two independent lexical
implementations and a shared Python vector/fusion executor:

- deterministic Python token scoring;
- an actual in-memory SQLite FTS5 index using `MATCH` and `bm25`;
- reciprocal-rank fusion across lexical, word-feature-hash,
  character-trigram-feature-hash, and corpus-token sparse stages;
- hard lifecycle gates before ranking;
- four results per query from six candidate capabilities.

Only lexical candidate generation changes between the two runs. Structured
filters, dense/sparse vector comparisons, fusion, and output projection share
the same Python implementation. The receipt therefore tests profile parsing
and lexical-backend substitution, not independent full-stack vector-engine
portability. SQLite timing includes cold in-memory index construction and is
not compared as a performance result.

The three vector projections are explicitly non-learned deterministic test
features. No embedding API or learned model ran. Each vector stage declares an
independent `space_id`, dimensions, normalization, distance, projection recipe
artifact, and query vector. Fusion combines ranks, not raw scores from unlike
spaces.

The projection artifacts contain the exact token regex and transforms,
feature-hash byte/bucket/sign rules, float32 quantization, character-trigram
padding, and the ordered sparse vocabulary. Every test `space_id` is derived
from its recipe digest, and query-vector digests are included in search
receipts. This makes the committed test projections independently
reimplementable without making them normative OCG embedding algorithms.

### 3. Directional compatibility benchmark

The checker supports a conservative subset of JSON Schema 2020-12. It checks
producer-to-consumer direction and refuses to let names or embeddings override
a structural contradiction.

The default held-out set has 15 adversarial cases:

- 4 labeled `safe`;
- 8 labeled `incompatible`;
- 3 labeled `unknown` for unsupported or under-specified semantics.

The additional interoperability set contains six manually selected projection
pairs: five cross-format pairs and one same-format negative control. Its labels
are three safe, two incompatible, and one unknown unresolved-`$ref` case.
These projections and expected labels are fixture-authored benchmark inputs,
not mappings inferred or authorized by the importers and not an independent
validation set. CWL and WIT compatibility remain unassessed.

### 4. Native-format checks

The executed receipt used heterogeneous checks with explicitly recorded scope:

| Fixture | Executed check | Result |
|---|---|---:|
| MCP schemas | `jsonschema.Draft202012Validator.check_schema` | pass |
| OpenAPI | `openapi-spec-validator` 0.9.0 | pass |
| CWL | `cwl-utils` 0.42 parser | pass; parsed as `Operation` |
| Agent Spec | `pyagentspec` 26.1.2 `Agent.from_json` | pass; one tool |
| WIT | `wasm-tools component wit --json` 1.253.0 | pass; normalized output matched the committed projection |

The MCP row checks four JSON Schema contracts: input and output for each of two
tools. It is intentionally not
described as an official whole-document MCP validator.

## Measured receipt

The committed run produced:

| Measurement | Result |
|---|---:|
| Native formats | 5 |
| Imported actions | 6 |
| Merged OCG records | 69 |
| Nodes / relations | 24 / 8 |
| Artifacts | 6 (3 WIT provenance/tool + 3 retrieval recipes) |
| Retrieval representations | 24 |
| Explicit vector spaces | 3 |
| Search queries | 4 |
| Reference backend top-1 accuracy / MRR / mean recall@4 | 1.00 / 1.00 / 1.00 |
| SQLite FTS5 top-1 accuracy / MRR / mean recall@4 | 1.00 / 1.00 / 1.00 |
| Backend top-1 agreement | 1.00 |
| Backend exact-order agreement | 0.25 |
| Mean backend top-4 Jaccard | 0.80 |
| Default compatibility exact accuracy / abstention | 1.00 / 0.20 |
| Interoperability fixture-label concordance / abstention | 1.00 / 0.167 |
| Non-safe fixture labels predicted `safe` | 0 |
| Heterogeneous native-format checks available and passing | 5 / 5 |

The search numbers are descriptive only. The corpus has just six candidates,
the four queries and relevance labels were authored with the fixtures, and no
confidence interval is meaningful. Top-1/MRR are more informative here than
recall@4; exact ranking differs between backends despite identical top-1
results. Compatibility “accuracy” is agreement with this small self-authored
label set; it is not a measurement of execution or semantic safety. No claim
is made about OpenSearch, Vespa, a graph database, learned embeddings, or
100M-record scale.

The exact raw data is in:

- [`artifacts/ocg_interop_bakeoff/receipt.json`](../artifacts/ocg_interop_bakeoff/receipt.json)
- [`artifacts/ocg_interop_bakeoff/manifest.json`](../artifacts/ocg_interop_bakeoff/manifest.json)
- [`artifacts/ocg_interop_bakeoff/merged-retrieval-graph.ocg.json`](../artifacts/ocg_interop_bakeoff/merged-retrieval-graph.ocg.json)

## Reproduce

Install the core package and optional Python validators:

```bash
python3 -m pip install -e '.[ocg-interop]'
```

Install or provide a `wasm-tools` executable if WIT native validation is
required, then run:

```bash
python3 scripts/run_ocg_interop_bakeoff.py \
  --wasm-tools /path/to/wasm-tools \
  --require-native
```

Without `--require-native`, unavailable optional validators are recorded as
`unavailable` rather than silently treated as passes. On a successful run, the
command emits the imported graphs, merged graph, raw receipt, and digest
manifest. The runner and reference assets are currently repository resources,
not installed wheel data; reproduce this bakeoff from a source checkout.

## What this says about an open edge/primitive standard

The practical standards boundary remains:

1. Preserve native formats as authoritative artifacts.
2. Standardize the small missing overlay: stable capability and implementation
   identity, action ports, directional relation assertions, projection-space
   identity, search-profile intent, scoped evidence, and explicit unknowns.
3. Let registries and search engines implement replaceable physical indexes.
4. Never standardize one embedding model, one global score, one graph database,
   or one package carrier as normative.
5. Require a stronger Contract/Evidence/Execution profile before a retrieved
   candidate can become an eligible plan or authorized invocation.

This avoids a universal super-IR while still making edges, representations,
weights, and search intent portable.

## Next experiments and promotion gates

1. Import at least 1,000 heterogeneous real actions and measure native-feature
   preservation, unsupported-feature frequency, and round-trip loss.
2. Add format-specific compatibility plugins for Protobuf, OpenAPI, WIT, and
   Arrow; retain `unknown` when no checker applies.
3. Execute the same search-profile fixture through one external engine adapter
   and compare filters, top-k, ranks, latency, and failure semantics.
4. Add two real learned embedding spaces plus a lexical-only control. Record
   model and revision identity; never compare raw scores across spaces.
5. Split labels by mint/repository and add same-name/different-semantics,
   units, effects, security-boundary, stream/batch, and error-channel attacks.
6. Require zero unsafe automatic admissions on the held-out safety set before
   any compatibility assertion can be promoted beyond `candidate`.
7. Add evidence-bound adapters and PlanLock receipts only after the
   compatibility and artifact-resolution layers are independently verified.

Until those gates pass, OCG remains a useful candidate interchange experiment,
not an agentic execution standard.
