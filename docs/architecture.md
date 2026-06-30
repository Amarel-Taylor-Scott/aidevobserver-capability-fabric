# Architecture

The fabric has four local layers.

## 1. Registry

`PrimitiveRecord` objects describe callable capabilities:

- id;
- label;
- input/output contracts;
- side effects;
- memory/cache policy;
- trust/readiness;
- remix tools;
- proof obligations;
- search text.

The registry is stored in SQLite with FTS5 for repeatable local proof.

## 2. Hybrid Search

Search applies hard blockers before ranking:

- input contract;
- output contract;
- trust;
- candidate-only;
- serves-truth.

It then runs lanes:

- exact contract;
- full text;
- deterministic semantic terms;
- template slot fit;
- trust/proof.

Results are fused with reciprocal-rank fusion.

## 3. CandidateBundle

The bundle turns search into route-shaped context:

```text
template
  slots
    candidates
    direct or remix fit
  graph/context notes
  compact PlanDelta shape
```

The LLM should select or request changes through a compact PlanDelta. The
compiler remains responsible for truth.

## 4. Service Fabric

The fabric tells agents what services exist:

- primitive search;
- route bundles;
- session review;
- context foundry;
- proof/promotion queue;
- agent discovery.

The local HTTP service is read-only. Discovery does not authorize execution or
promotion.

## 5. Source Surfaces

`SourceSurface` records describe public places to look for startup, tool,
research, benchmark, newsletter, community, and open-source signals.

They are intentionally candidate-only:

- source directories can suggest primitive families;
- launch feeds can suggest workflows and user pain;
- repositories can suggest callable surfaces and proof fixtures;
- benchmarks can suggest evaluation contracts;
- newsletters and VC essays can suggest trend labels.

None of those signals becomes registry truth by itself. A source-surface scan
can create primitive drafts, CandidateBundle examples, benchmark fixtures, or
review findings. PlanLocks, proofs, licensing review, and promotion decide what
can serve truth later.
