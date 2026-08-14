# Business-friction discovery and primitive-building loop

This subsystem continuously looks for recurring operational pain in overlooked
public sources, tests whether the capability fabric already covers it, and
builds small candidate primitives for sufficiently corroborated gaps.

"Dark corners" means low-visibility but lawful public surfaces: issue trackers
for ERP and workflow software, niche support forums, public complaint data,
procurement notices, regulatory comments, incident datasets, Ask HN, and
specialist Q&A. It does not mean login-walled communities, bypassed access
controls, the dark web, or an unrestricted crawler.

## The loop

```text
approved source policies + search hypotheses + durable cursors
  -> bounded incremental fetch
  -> policy-permitted evidence bytes in content-addressed storage
  -> PII-minimized normalized observations
  -> attributed friction signals
  -> deduplication, corroboration, and contradiction-preserving clusters
  -> opportunity score vector and automatic-build gate
  -> retrieval-only comparison with the existing primitive catalog
  -> candidate contract and deterministic implementation scaffold
  -> positive and negative fixture execution in a child process
  -> digest-bound receipt, OCG candidate projection, and factory snapshot
  -> checkpoint, cooldown, and next cycle
```

The durable SQLite ledger is separate from the existing registry database.
The existing registry is rebuilt from seeds; the problem ledger is append-only
history plus repairable projections. Where policy permits, exact source
responses live in a content-addressed store. For `AMBER` user-content sources,
the store keeps only the minimized normalized observation and the raw response
digest. An observation update creates a new version rather than overwriting old
evidence.

## Truth boundaries

The loop is intentionally unable to promote its own output:

- a fetch proves only that exact bytes were observed at a URL and time;
- a `ProblemSignal` is a deterministic extractor's attributed interpretation;
- a cluster and score remain candidate market hypotheses;
- catalog matches are retrieval overlap, not semantic compatibility;
- generated contracts and code remain candidate material;
- a passing receipt supports only the exact code, contracts, environment, and
  generated fixture corpus named by that receipt;
- `serves_truth` remains `false`, effects start as unknown, and no executable
  compatibility edge is emitted;
- production admission remains a separate policy decision.

This also means an HTTP failure, rate-limit response, or source-policy denial is
recorded as a transport/source attempt. It is never counted as a primitive test
or benchmark result.

## Source policy

Each connector has a source-local policy with an admission class:

- `GREEN`: an explicit public API/download with public-domain, CC0, or other
  compatible reuse terms;
- `AMBER`: an official API/RSS feed where user-content rights vary; retain
  identifiers, metadata, link, content digest, a short redacted excerpt, and
  derived facts rather than republishing the corpus;
- `RED`: access-controlled, contractually prohibited, HTML-only against site
  policy, or otherwise unapproved; the connector fails closed.

Collectors use fixed configured HTTPS hosts, response-size and item limits,
timeouts, conditional request headers, source-specific cooldowns, and optional
environment-variable authentication. Credentials never enter plans, artifacts,
events, or receipts. Discovered links cannot expand the frontier until a new
source policy approves them.

The initial adapter set covers:

- GitHub issues in a curated allowlist of operational software repositories;
- Hacker News Ask stories through the official API;
- Stack Exchange advanced search;
- approved Discourse RSS feeds;
- the CFPB public complaint API;
- Federal Register search;
- deterministic fixture/replay input for tests and offline operation.

Good next adapters are Regulations.gov comments, TED and SAM.gov procurement,
UK Contracts Finder/OCDS, public GitLab issues, SEC EDGAR, and permitted
municipal complaint/inspection datasets. Common Crawl is an expansion and
corroboration lane, not the first ingestion firehose.

## Problem representation and build gate

A signal records the actor, workflow, trigger, failing step, friction class,
current workaround, desired outcome, systems, claimed impact, evidence span,
source class, source/content digests, uncertainty, and contradiction state.

The deterministic first-pass taxonomy maps recurring friction to reusable
primitive shapes:

| Friction | Candidate primitive shape |
|---|---|
| Manual reformatting or transfer | adapter |
| Matching and discrepancy work | reconciliation |
| Repeated checks and compliance | validation |
| Fragmented information | aggregation |
| Missing visibility | monitoring |
| Repeated search | lookup |
| Backlog prioritization | triage |
| Ownership or handoff failures | routing/handoff |
| Manual document extraction | extraction |
| Inconsistent decisions | policy evaluation |
| Scheduling coordination | scheduling |
| Systems falling out of sync | synchronization plan |

Automatic building requires either at least three independent evidence items
spanning two source classes, or one explicit budgeted procurement requirement
clearly marked as single-buyer evidence. The actor, workflow, input/output
contract, and executable oracle must also be clear. Otherwise the loop retains
a ProblemCard and seeks more evidence.

Opportunity ranking uses hard gates first, then a vector—not one universal
magic score—for demand, source diversity, recurrence, severity, buyer intent,
momentum, solution gap, standardizability, observability, contract clarity,
deterministic potential, proof feasibility, uncertainty, and risk. A transparent
weight-profile digest may order a bounded build queue, but the vector is kept.

## Running it

Inspect the approved connector plan without making network requests:

```bash
aidevobserver-fabric problem-sources --compact
aidevobserver-fabric problem-sources \
  --source-config examples/problem_sources.example.json \
  --compact
aidevobserver-fabric problem-loop \
  --fixture examples/problem_observations.fixture.json \
  --output-root artifacts/problem_discovery \
  --cycles 1
```

Run a bounded public-source cycle:

```bash
aidevobserver-fabric problem-loop \
  --source github.operational_issues \
  --source hn.ask \
  --source stackexchange.workflow_questions \
  --max-items 20 \
  --timeout 15 \
  --cycles 1
```

Use `--source-config examples/problem_sources.example.json` to replace the
default portfolio with a reviewed JSON portfolio. The loader revalidates HTTPS
hosts, supported adapters, access class, bounds, unique IDs, and credential
indirection; credential-bearing headers in the file are rejected.

Inspect and verify durable state:

```bash
aidevobserver-fabric problem-status --output-root artifacts/problem_discovery
aidevobserver-fabric problem-reconcile --output-root artifacts/problem_discovery
```

For continuous operation, run several bounded cycles under systemd, cron, or a
job scheduler. The command itself uses explicit cycle and runtime ceilings; it
does not become an unkillable daemon.

Each run writes:

```text
artifacts/problem_discovery/
  problem_loop.sqlite
  cas/sha256/...
  candidates/<draft-id>/
    primitive.json
    ocg.json
    contracts/*.schema.json
    src/primitive.py
    tests/test_contract.py
    fixtures/*.json
    source-evidence.json
    manifest.json
    receipts/test.json
  runs/<run-id>/
    observations.jsonl
    signals.jsonl
    clusters.jsonl
    coverage.jsonl
    primitive_candidates.jsonl
    factory_snapshot.json
    manifest.json
    receipt.json
```

## Evaluation and improvement

Do not optimize the loop on output volume. Track:

- source completeness, freshness, replay rate, permitted-content rate,
  backoff compliance, and failures by class;
- extraction facet F1, evidence-citation precision, unsupported-claim rate,
  human agreement, and confidence calibration on a held-out labeled set;
- false merges, missed duplicates, cluster stability, contamination, source and
  organization diversity, contradiction retention, and split/merge lineage;
- precision@k, nDCG@k, diversity@k, temporal backtests, and candidate-build
  success for opportunity ranking;
- reproducible builds, hidden-oracle success, unsafe-output rate,
  evidence-to-test traceability, materialization success, and route reuse;
- measured hours, errors, tickets, or cost reduced after a candidate is
  separately admitted and deployed;
- marginal validated yield per source and cost per validated cluster, build,
  and admitted primitive.

The weekly adjudication cycle should actively search for counterevidence:
existing products, resolved reports, incompatible contexts, and low-value
workarounds. Failed candidates and rejected mappings are retained as scoped
negative evidence rather than silently deleted.
