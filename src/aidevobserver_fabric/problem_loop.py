"""Persistent public-friction discovery to candidate-primitive loop."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlencode, urlsplit, urlunsplit

from . import primitive_factory
from .primitive_builder import (
    CandidateWorkspace,
    PrimitiveDraft,
    build_candidate,
    digest_bytes,
    digest_json,
    draft_from_problem,
    evaluate_registry_coverage_many,
)
from .problem_ledger import (
    append_event,
    claim_due_source,
    connect_ledger,
    finish_run,
    record_source_batch,
    record_source_failure,
    reconcile_ledger,
    stable_id,
    stable_json_bytes,
    start_run,
    status_snapshot,
)
from .problem_mining import (
    FRICTION_ARCHETYPES,
    OpportunityAssessment,
    ProblemCluster,
    ProblemSignal,
    assess_opportunity,
    classify_friction,
    cluster_problem_signals,
    extract_problem_signal,
)
from .problem_sources import (
    AccessClass,
    DEFAULT_GITHUB_OPERATIONAL_REPOS,
    DEFAULT_SOURCE_BY_ID,
    DEFAULT_SOURCE_SPECS,
    FetchResult,
    NormalizedObservation,
    SourceSpec,
    collect_source,
    load_source_specs,
)


LOOP_ID = "aidevobserver.business_friction_to_primitive.v1"
EXTRACTOR_ID = "deterministic_friction_lexicon.v2"
DEFAULT_OUTPUT_ROOT = Path("artifacts/problem_discovery")
DEFAULT_QUERY_BANK: tuple[str, ...] = (
    '"manual process"',
    '"double entry"',
    "workaround invoice order inventory",
    '"takes hours"',
    '"missing API"',
    '"failed to sync"',
    "duplicate invoice payment customer",
    "reconciliation manual exception",
    "approval bottleneck delay",
    "reporting burden recordkeeping burden",
    "legacy system migration export",
    "false positive manual triage",
)
COUNTEREVIDENCE_TERMS: tuple[str, ...] = (
    "resolved fixed supported now",
    "existing solution works",
)
QUERY_MUTATION_STOPWORDS = frozenset(
    {
        "act",
        "advantage",
        "affordable",
        "already",
        "also",
        "all",
        "ask",
        "automation",
        "author",
        "authorization",
        "been",
        "best",
        "built",
        "business",
        "but",
        "code",
        "continually",
        "day",
        "doing",
        "done",
        "each",
        "every",
        "existing",
        "free",
        "how",
        "manual",
        "process",
        "necessary",
        "workflow",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_after(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, seconds))).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8") + b"\n")


def _write_jsonl(path: Path, values: Iterable[Any]) -> None:
    rows = [json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False) for value in values]
    _atomic_write(path, (("\n".join(rows) + "\n") if rows else "").encode("utf-8"))


def _safe_run_name(run_id: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in run_id)


@dataclass(frozen=True, slots=True)
class LoopConfig:
    output_root: Path = DEFAULT_OUTPUT_ROOT
    source_ids: tuple[str, ...] = ()
    source_config: Path | None = None
    max_items: int = 20
    timeout_seconds: float = 15.0
    build_limit: int = 10
    minimum_cluster_similarity: float = 0.30
    execute_candidate_tests: bool = True
    candidate_test_timeout: float = 20.0
    query_bank: tuple[str, ...] = DEFAULT_QUERY_BANK
    include_counterevidence_queries: bool = True
    candidate_only: bool = True
    serves_truth: bool = False

    @property
    def ledger_path(self) -> Path:
        return self.output_root / "problem_loop.sqlite"

    @property
    def cas_root(self) -> Path:
        return self.output_root / "cas"

    @property
    def candidates_root(self) -> Path:
        return self.output_root / "candidates"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["output_root"] = str(self.output_root)
        data["source_config"] = str(self.source_config) if self.source_config else None
        return data

    def __post_init__(self) -> None:
        if not self.candidate_only or self.serves_truth:
            raise ValueError("problem discovery loop must remain candidate-only")
        if not 1 <= self.max_items <= 1_000:
            raise ValueError("max_items must be between 1 and 1,000")
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between 0 and 60")
        if not 0 <= self.build_limit <= 100:
            raise ValueError("build_limit must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class SourceAttempt:
    source_id: str
    status: str
    query: str | None
    request_url: str
    fetch_receipts: tuple[dict[str, Any], ...]
    observations: tuple[NormalizedObservation, ...]
    ledger_observation_ids: tuple[str, ...]
    error: dict[str, Any] | None
    candidate_only: bool = True
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "observations": [item.to_dict() for item in self.observations],
        }


def selected_sources(config: LoopConfig, sources: Sequence[SourceSpec] = DEFAULT_SOURCE_SPECS) -> tuple[SourceSpec, ...]:
    if config.source_config is not None:
        sources = load_source_specs(config.source_config)
    by_id = {source.source_id: source for source in sources}
    requested = config.source_ids or tuple(by_id)
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise KeyError("unknown problem sources: " + ", ".join(unknown))
    selected: list[SourceSpec] = []
    for source_id in requested:
        source = by_id[source_id]
        policy = replace(
            source.policy,
            max_records=min(config.max_items, source.policy.max_records),
            timeout_seconds=min(config.timeout_seconds, source.policy.timeout_seconds),
        )
        selected.append(replace(source, policy=policy))
    return tuple(selected)


def source_catalog(
    *,
    compact: bool = False,
    sources: Sequence[SourceSpec] = DEFAULT_SOURCE_SPECS,
) -> str | dict[str, Any]:
    data = {
        "loop_id": LOOP_ID,
        "source_count": len(sources),
        "sources": [source.to_dict() for source in sources],
        "query_bank": list(DEFAULT_QUERY_BANK),
        "counterevidence_terms": list(COUNTEREVIDENCE_TERMS),
        "boundary": "public_policy_approved_candidate_discovery",
        "candidate_only": True,
        "serves_truth": False,
    }
    if not compact:
        return data
    lines = [
        f"PROBLEM_SOURCES count:{len(sources)} candidate_only:true serves_truth:false",
    ]
    for source in sources:
        lines.append(
            f"SOURCE {source.source_id} adapter:{source.adapter} access:{source.policy.access_class.value} cadence:{source.cadence_seconds}s"
        )
    return "\n".join(lines) + "\n"


def load_fixture_map(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, Mapping) and isinstance(data.get("sources"), Mapping):
        data = data["sources"]
    if not isinstance(data, Mapping):
        raise ValueError("problem fixture must be an object keyed by source_id")
    return {str(key): value for key, value in data.items()}


def _replace_query(url: str, **updates: str) -> str:
    parts = urlsplit(url)
    from urllib.parse import parse_qsl

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(updates)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def request_plan(source: SourceSpec, cycle_index: int, query_bank: Sequence[str]) -> tuple[str, str | None, str]:
    positive_count = max(len(query_bank), 1)
    falsification = cycle_index % 10 == 9
    if falsification:
        query = COUNTEREVIDENCE_TERMS[cycle_index % len(COUNTEREVIDENCE_TERMS)]
        mode = "counterevidence"
    else:
        query = query_bank[cycle_index % positive_count] if query_bank else "manual process"
        mode = "opportunity"
    if source.adapter == "github_issues":
        repo = DEFAULT_GITHUB_OPERATIONAL_REPOS[cycle_index % len(DEFAULT_GITHUB_OPERATIONAL_REPOS)]
        since = (datetime.now(timezone.utc) - timedelta(days=180)).date().isoformat()
        terms = f"{query} is:issue updated:>={since} repo:{repo}"
        return _replace_query(source.endpoint, q=terms, per_page=str(source.policy.max_records)), query, mode
    if source.adapter == "stackexchange_questions":
        return _replace_query(source.endpoint, q=query, pagesize=str(source.policy.max_records), filter="withbody"), query, mode
    if source.adapter == "cfpb_complaints":
        return _replace_query(source.endpoint, search_term=query, size=str(source.policy.max_records)), query, mode
    if source.adapter == "federal_register":
        return _replace_query(source.endpoint, **{"conditions[term]": query, "per_page": str(source.policy.max_records)}), query, mode
    return source.endpoint, None, "stream"


def _code_digest() -> str:
    root = Path(__file__).resolve().parent
    files = (
        root / "problem_loop.py",
        root / "problem_sources.py",
        root / "problem_mining.py",
        root / "problem_ledger.py",
        root / "primitive_builder.py",
    )
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.name.encode("utf-8"))
        hasher.update(path.read_bytes())
    return "sha256:" + hasher.hexdigest()


def _source_state(con: Any, source_id: str) -> Mapping[str, Any]:
    row = con.execute("SELECT * FROM source_states WHERE source_id = ?", (source_id,)).fetchone()
    return dict(row) if row is not None else {}


def _expand_hn(source: SourceSpec, result: FetchResult, *, fixture_supplied: bool) -> tuple[FetchResult, ...]:
    if fixture_supplied or not result.ok:
        return (result,)
    references = [row for row in result.observations if row.kind == "hn_ask_reference"]
    if not references:
        return (result,)
    expanded: list[FetchResult] = []
    for row in references[: source.policy.max_records]:
        item_id = row.metadata.get("item_id")
        if item_id is None:
            continue
        expanded.append(
            collect_source(
                source,
                request_url=f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
            )
        )
    return tuple(expanded) or (result,)


def _retryable(result: FetchResult) -> bool:
    return result.error_code in {"network_error", "fetch_error"} or result.status_code in {408, 425, 429, 500, 502, 503, 504}


def _observation_payload(
    source: SourceSpec,
    result: FetchResult,
    observation: NormalizedObservation,
) -> bytes:
    # GREEN sources permit exact response retention.  AMBER sources retain only
    # the PII-minimized observation while preserving the response digest in
    # metadata; an official feed is not a blanket content relicense.
    if source.policy.access_class is AccessClass.GREEN and result._body:
        return result._body
    return stable_json_bytes(observation.to_dict())


def _ledger_observation_id(source: SourceSpec, observation: NormalizedObservation, content: bytes) -> str:
    return stable_id(
        "obs",
        {
            "source_id": source.source_id,
            "source_item_id": observation.observation_id,
            "canonical_url": observation.source_url,
            "content_digest": digest_bytes(content),
        },
    )


def _collect_one(
    con: Any,
    config: LoopConfig,
    source: SourceSpec,
    run_id: str,
    cycle_index: int,
    fixture: Any | None,
) -> SourceAttempt:
    request_url, query, search_mode = request_plan(source, cycle_index, config.query_bank)
    if not claim_due_source(con, source_id=source.source_id, run_id=run_id, lease_seconds=max(60, config.timeout_seconds * 4)):
        return SourceAttempt(
            source_id=source.source_id,
            status="not_due_or_leased",
            query=query,
            request_url=request_url,
            fetch_receipts=(),
            observations=(),
            ledger_observation_ids=(),
            error=None,
        )
    state = _source_state(con, source.source_id)
    first = collect_source(
        source,
        request_url=request_url,
        etag=state.get("etag"),
        last_modified=state.get("last_modified"),
        fixture=fixture,
    )
    results = _expand_hn(source, first, fixture_supplied=fixture is not None)
    successes = [result for result in results if result.ok]
    failures = [result for result in results if not result.ok]
    if not successes:
        failure = failures[0] if failures else first
        receipt = record_source_failure(
            con,
            run_id=run_id,
            source_id=source.source_id,
            error_class=failure.error_code or "unknown_source_error",
            error_message=failure.error_message or "source returned no successful result",
            retryable=_retryable(failure),
            cooldown_seconds=300 if _retryable(failure) else source.cadence_seconds,
        )
        return SourceAttempt(
            source_id=source.source_id,
            status=receipt["status"],
            query=query,
            request_url=request_url,
            fetch_receipts=tuple(result.to_dict() for result in results),
            observations=(),
            ledger_observation_ids=(),
            error={"class": receipt["error_class"], "digest": receipt["error_digest"]},
        )

    normalized_pairs = [
        (result, observation)
        for result in successes
        for observation in result.observations
    ]
    observation_inputs = []
    ledger_ids = []
    for result, observation in normalized_pairs:
        content = _observation_payload(source, result, observation)
        ledger_id = _ledger_observation_id(source, observation, content)
        ledger_ids.append(ledger_id)
        metadata = observation.to_dict()
        metadata["search_query"] = query
        metadata["search_mode"] = search_mode
        metadata["fetch_body_digest"] = result.body_digest
        observation_inputs.append(
            {
                "source_item_id": observation.observation_id,
                "canonical_url": observation.source_url,
                "content": content,
                "media_type": result.content_type or "application/octet-stream",
                "published_at": observation.published_at,
                "metadata": metadata,
                "retention_class": source.policy.content_policy,
            }
        )
    last = successes[-1]
    batch = record_source_batch(
        con,
        config.cas_root,
        run_id=run_id,
        source_id=source.source_id,
        observations=observation_inputs,
        cursor={
            "cycle_index": cycle_index,
            "request_url_digest": digest_bytes(request_url.encode("utf-8")),
            "query": query,
            "search_mode": search_mode,
            "body_digests": [result.body_digest for result in successes if result.body_digest],
            "observation_ids": [observation.observation_id for _, observation in normalized_pairs],
        },
        etag=last.etag,
        last_modified=last.last_modified,
        next_due_at=_iso_after(source.cadence_seconds),
        fetched_at=last.fetched_at,
    )
    status = "complete_with_item_failures" if failures else "complete"
    return SourceAttempt(
        source_id=source.source_id,
        status=status,
        query=query,
        request_url=request_url,
        fetch_receipts=tuple(result.to_dict() for result in results),
        observations=tuple(observation for _, observation in normalized_pairs),
        ledger_observation_ids=tuple(ledger_ids),
        error={"failed_item_fetches": len(failures), "batch": batch} if failures else None,
    )


def _actor_hint(observation: NormalizedObservation) -> str:
    return {
        "software_issue": "business software operator",
        "technical_question": "technical operator",
        "forum_topic": "business software operator",
        "consumer_complaint": "financial operations team",
        "regulatory_document": "compliance team",
        "hn_ask": "founder or operator",
    }.get(observation.kind, "business operator")


def _contradictions(text: str) -> tuple[str, ...]:
    lowered = text.casefold()
    phrases = ("resolved by", "fixed in", "already supported", "works now", "no longer an issue")
    return tuple(phrase for phrase in phrases if phrase in lowered)


def _signals_from_attempts(attempts: Sequence[SourceAttempt]) -> tuple[tuple[ProblemSignal, str], ...]:
    rows: list[tuple[ProblemSignal, str]] = []
    for attempt in attempts:
        for index, observation in enumerate(attempt.observations):
            ledger_id = attempt.ledger_observation_ids[index]
            text = " ".join(part for part in (observation.title, observation.excerpt or "") if part)
            friction_type, _ = classify_friction(text)
            archetype = FRICTION_ARCHETYPES.get(friction_type)
            oracle = archetype["oracle_kind"] if archetype else None
            extractor_digest = digest_bytes(Path(__file__).with_name("problem_mining.py").read_bytes())
            signal = extract_problem_signal(
                text=text,
                source_ref=observation.source_url,
                source_class=observation.kind,
                evidence_refs=(observation.source_url,),
                signal_id=stable_id(
                    "problem.signal",
                    {"ledger_observation_id": ledger_id, "extractor_digest": extractor_digest},
                ).replace(":", ".", 1),
                actor=_actor_hint(observation),
                workflow=observation.title,
                oracle=oracle,
                contradictions=_contradictions(text),
            )
            rows.append((signal, ledger_id))
    return tuple(rows)


def _signals_from_ledger(con: Any) -> tuple[tuple[ProblemSignal, str], ...]:
    attempts: list[SourceAttempt] = []
    for row in con.execute(
        "SELECT observation_id, source_id, metadata_json FROM observations ORDER BY observation_id"
    ):
        try:
            payload = json.loads(row["metadata_json"])
            observation = NormalizedObservation(
                source_id=str(payload["source_id"]),
                observation_id=str(payload["observation_id"]),
                kind=str(payload["kind"]),
                source_url=str(payload["source_url"]),
                title=str(payload["title"]),
                excerpt=payload.get("excerpt"),
                published_at=payload.get("published_at"),
                metadata=payload.get("metadata") or {},
                raw_digest=str(payload["raw_digest"]),
            )
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            continue
        attempts.append(
            SourceAttempt(
                source_id=row["source_id"],
                status="ledger_replay",
                query=None,
                request_url=observation.source_url,
                fetch_receipts=(),
                observations=(observation,),
                ledger_observation_ids=(row["observation_id"],),
                error=None,
            )
        )
    return _signals_from_attempts(attempts)


def _persist_problem_records(
    con: Any,
    *,
    run_id: str,
    signal_rows: Sequence[tuple[ProblemSignal, str]],
    clusters: Sequence[ProblemCluster],
    assessments: Mapping[str, OpportunityAssessment],
    coverage: Mapping[str, dict[str, Any]],
) -> None:
    timestamp = _now()
    extractor_digest = digest_bytes(Path(__file__).with_name("problem_mining.py").read_bytes())
    con.execute("BEGIN IMMEDIATE")
    try:
        for signal, observation_id in signal_rows:
            con.execute(
                """
                INSERT OR IGNORE INTO problem_signals(
                  signal_id, run_id, observation_id, extractor_id, extractor_digest,
                  friction_type, actor, task, workaround, desired_outcome,
                  impact_json, uncertainty_json, supporting_span_digest, lifecycle, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?)
                """,
                (
                    signal.signal_id,
                    run_id,
                    observation_id,
                    EXTRACTOR_ID,
                    extractor_digest,
                    signal.friction_type,
                    signal.actor,
                    signal.workflow,
                    signal.workaround,
                    signal.desired_outcome,
                    stable_json_bytes({"quantified_impact": signal.quantified_impact, "unit": signal.impact_unit}).decode("utf-8"),
                    stable_json_bytes(
                        {
                            "unknown_fields": signal.unknown_fields,
                            "classification_confidence": signal.classification_confidence,
                            "record": signal.to_dict(),
                        }
                    ).decode("utf-8"),
                    digest_bytes(signal.excerpt.encode("utf-8")),
                    timestamp,
                ),
            )
        for cluster in clusters:
            assessment = assessments[cluster.cluster_id]
            con.execute(
                """
                INSERT INTO problem_clusters(
                  cluster_id, created_run_id, fingerprint, canonical_statement,
                  score_vector_json, score_profile_digest, lifecycle, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'candidate', ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                  score_vector_json = excluded.score_vector_json,
                  score_profile_digest = excluded.score_profile_digest,
                  updated_at = excluded.updated_at
                """,
                (
                    cluster.cluster_id,
                    run_id,
                    cluster.membership_fingerprint,
                    cluster.representative_excerpt,
                    stable_json_bytes(dict(assessment.score_vector)).decode("utf-8"),
                    assessment.profile_digest,
                    timestamp,
                    timestamp,
                ),
            )
            for signal_id in cluster.member_signal_ids:
                con.execute(
                    "INSERT OR IGNORE INTO cluster_members(cluster_id, signal_id, relation, confidence) VALUES (?, ?, 'supports', NULL)",
                    (cluster.cluster_id, signal_id),
                )
            decision = coverage[cluster.cluster_id]
            decision_id = stable_id("coverage", {"run_id": run_id, "cluster_id": cluster.cluster_id, "coverage": decision})
            con.execute(
                """
                INSERT OR IGNORE INTO coverage_decisions(
                  decision_id, run_id, cluster_id, registry_snapshot_digest, outcome,
                  capability_refs_json, explanation_digest, created_at
                ) VALUES (?, ?, ?, ?, 'unknown', ?, ?, ?)
                """,
                (
                    decision_id,
                    run_id,
                    cluster.cluster_id,
                    decision.get("registry_snapshot_digest") or digest_json({"unavailable": True}),
                    stable_json_bytes([row.get("primitive_id") for row in decision.get("matches", [])]).decode("utf-8"),
                    digest_json({"retrieval_outcome": decision.get("outcome"), "semantic_compatibility": "unknown"}),
                    timestamp,
                ),
            )
        con.commit()
    except BaseException:
        con.rollback()
        raise


def _canonicalize_cluster_ids(con: Any, clusters: Sequence[ProblemCluster]) -> tuple[ProblemCluster, ...]:
    """Reuse a semantic-membership cluster ID across extractor revisions."""

    canonical: list[ProblemCluster] = []
    for cluster in clusters:
        row = con.execute(
            "SELECT cluster_id FROM problem_clusters WHERE fingerprint = ?",
            (cluster.membership_fingerprint,),
        ).fetchone()
        canonical.append(
            replace(cluster, cluster_id=row["cluster_id"])
            if row is not None and row["cluster_id"] != cluster.cluster_id
            else cluster
        )
    return tuple(canonical)


def _persist_build(con: Any, run_id: str, workspace: CandidateWorkspace) -> None:
    draft = workspace.draft
    receipt = workspace.test_receipt
    timestamp = _now()
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(
            """
            INSERT OR IGNORE INTO primitive_drafts(
              draft_id, run_id, cluster_id, capability_id, implementation_id,
              manifest_digest, workspace_digest, builder_digest, lifecycle, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?)
            """,
            (
                draft.draft_id,
                run_id,
                draft.cluster_id,
                draft.capability_id,
                draft.implementation_id,
                workspace.manifest["manifest_digest"],
                digest_json(workspace.manifest["files"]),
                workspace.manifest["builder_digest"],
                timestamp,
            ),
        )
        if receipt is not None:
            result = receipt["result"] if receipt["result"] in {"pass", "fail"} else "inconclusive"
            con.execute(
                """
                INSERT OR IGNORE INTO execution_receipts(
                  receipt_id, run_id, draft_id, claim_type, artifact_digest,
                  contract_digest, environment_digest, workload_digest,
                  fixture_digest, result, raw_result_digest, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt["receipt_id"],
                    run_id,
                    draft.draft_id,
                    receipt["claim_type"],
                    receipt["artifact_digest"],
                    digest_json(receipt["contract_digests"]),
                    receipt["environment_digest"],
                    digest_json({"scope": receipt["scope"]}),
                    digest_json(receipt["fixture_digests"]),
                    result,
                    digest_json(receipt),
                    receipt["started_at"],
                    receipt["finished_at"],
                ),
            )
        con.commit()
    except BaseException:
        con.rollback()
        raise


def _problem_signal_from_dict(value: Mapping[str, Any]) -> ProblemSignal:
    row = dict(value)
    for field_name in (
        "evidence_refs",
        "contradictions",
        "semantic_tokens",
        "unknown_fields",
    ):
        row[field_name] = tuple(row.get(field_name) or ())
    return ProblemSignal(**row)


def _historical_signals(con: Any) -> tuple[ProblemSignal, ...]:
    records: list[ProblemSignal] = []
    for row in con.execute("SELECT uncertainty_json FROM problem_signals ORDER BY signal_id"):
        try:
            payload = json.loads(row["uncertainty_json"])
            record = payload.get("record") if isinstance(payload, Mapping) else None
            if isinstance(record, Mapping):
                records.append(_problem_signal_from_dict(record))
        except (TypeError, ValueError, KeyError):
            continue
    return tuple(records)


def _next_queries(clusters: Sequence[ProblemCluster], limit: int = 8) -> list[str]:
    queries = []
    for cluster in clusters:
        if cluster.friction_type == "unknown" or cluster.archetype is None:
            continue
        tokens = [
            token
            for token in cluster.semantic_tokens
            if token not in QUERY_MUTATION_STOPWORDS and not token.isdigit()
        ][:4]
        if tokens:
            queries.append(" ".join((cluster.friction_type.replace("_", " "), *tokens)))
        if len(queries) >= limit:
            break
    return queries


def run_loop_once(
    config: LoopConfig,
    *,
    fixture_map: Mapping[str, Any] | None = None,
    cycle_index: int = 0,
    run_id: str | None = None,
) -> dict[str, Any]:
    config.output_root.mkdir(parents=True, exist_ok=True)
    con = connect_ledger(config.ledger_path)
    fixture_map = fixture_map or {}
    code_digest = _code_digest()
    run = start_run(con, config.to_dict(), code_digest=code_digest, run_id=run_id)
    run_id = run["run_id"]
    run_dir = config.output_root / "runs" / _safe_run_name(run_id)
    attempts: list[SourceAttempt] = []
    try:
        for source in selected_sources(config):
            attempts.append(
                _collect_one(
                    con,
                    config,
                    source,
                    run_id,
                    cycle_index,
                    fixture_map.get(source.source_id),
                )
            )

        signal_rows = _signals_from_ledger(con)
        signals = tuple(row[0] for row in signal_rows)
        clusters = _canonicalize_cluster_ids(
            con,
            cluster_problem_signals(
                signals,
                minimum_similarity=config.minimum_cluster_similarity,
            ),
        )
        assessments = {cluster.cluster_id: assess_opportunity(cluster) for cluster in clusters}
        coverage = evaluate_registry_coverage_many(list(clusters))
        _persist_problem_records(
            con,
            run_id=run_id,
            signal_rows=signal_rows,
            clusters=clusters,
            assessments=assessments,
            coverage=coverage,
        )
        append_event(
            con,
            run_id=run_id,
            stage="problem_mining",
            entity_type="run",
            entity_id=run_id,
            status="complete",
            output_digest=digest_json([cluster.to_dict() for cluster in clusters]),
            metrics={"signals": len(signals), "clusters": len(clusters)},
        )

        eligible = sorted(
            (cluster for cluster in clusters if assessments[cluster.cluster_id].build_gate_passed),
            key=lambda cluster: (-assessments[cluster.cluster_id].queue_score, cluster.cluster_id),
        )
        eligible_new = [
            cluster
            for cluster in eligible
            if con.execute(
                "SELECT 1 FROM primitive_drafts WHERE cluster_id = ? LIMIT 1",
                (cluster.cluster_id,),
            ).fetchone()
            is None
        ][: config.build_limit]
        workspaces: list[CandidateWorkspace] = []
        for cluster in eligible_new:
            cluster_data = cluster.to_dict()
            assessment = assessments[cluster.cluster_id]
            cluster_data["score_vector"] = dict(assessment.score_vector)
            cluster_data["opportunity"] = assessment.to_dict()
            cluster_data["build_gate"] = {
                "eligible": assessment.build_gate_passed,
                "reasons": list(assessment.build_gate_reasons),
            }
            draft = draft_from_problem(cluster_data, coverage=coverage[cluster.cluster_id])
            workspace = build_candidate(
                draft,
                config.candidates_root,
                execute_tests=config.execute_candidate_tests,
                timeout=config.candidate_test_timeout,
            )
            _persist_build(con, run_id, workspace)
            workspaces.append(workspace)

        primitive_records = tuple(workspace.draft.to_primitive_record() for workspace in workspaces)
        factory = primitive_factory.factory_snapshot(primitive_records)
        factory["measurement_boundary"] = {
            "benchmark_records": "estimated_not_executed",
            "execution_receipts": len([workspace for workspace in workspaces if workspace.test_receipt]),
            "candidate_only": True,
            "serves_truth": False,
        }

        _write_jsonl(run_dir / "source_attempts.jsonl", [attempt.to_dict() for attempt in attempts])
        _write_jsonl(run_dir / "observations.jsonl", [observation.to_dict() for attempt in attempts for observation in attempt.observations])
        _write_jsonl(run_dir / "signals.jsonl", [signal.to_dict() for signal in signals])
        _write_jsonl(
            run_dir / "clusters.jsonl",
            [
                {**cluster.to_dict(), "assessment": assessments[cluster.cluster_id].to_dict()}
                for cluster in clusters
            ],
        )
        _write_jsonl(run_dir / "coverage.jsonl", [coverage[cluster.cluster_id] for cluster in clusters])
        _write_jsonl(run_dir / "primitive_candidates.jsonl", [workspace.to_dict() for workspace in workspaces])
        _write_json(run_dir / "factory_snapshot.json", factory)

        failure_count = sum(attempt.status in {"retryable_failure", "terminal_failure"} for attempt in attempts)
        source_success_count = sum(attempt.status.startswith("complete") for attempt in attempts)
        skipped_count = sum(attempt.status == "not_due_or_leased" for attempt in attempts)
        counts = {
            "sources_requested": len(attempts),
            "sources_succeeded": source_success_count,
            "sources_failed": failure_count,
            "sources_skipped": skipped_count,
            "observations": sum(len(attempt.observations) for attempt in attempts),
            "signals": len(signals),
            "historical_signals_considered": max(
                0,
                len(signals) - sum(len(attempt.observations) for attempt in attempts),
            ),
            "clusters": len(clusters),
            "clusters_build_gate_passed": len(eligible),
            "primitive_candidates_built": len(workspaces),
            "fixture_tests_passed": sum(workspace.test_receipt is not None and workspace.test_receipt["result"] == "pass" for workspace in workspaces),
            "fixture_tests_failed": sum(workspace.test_receipt is not None and workspace.test_receipt["result"] != "pass" for workspace in workspaces),
        }
        status = "failed" if source_success_count == 0 and failure_count else "partial" if failure_count else "complete"
        receipt = {
            "loop_id": LOOP_ID,
            "run_id": run_id,
            "status": status,
            "config_digest": run["config_digest"],
            "code_digest": code_digest,
            "counts": counts,
            "next_queries": _next_queries(clusters),
            "source_attempt_statuses": {attempt.source_id: attempt.status for attempt in attempts},
            "candidate_only": True,
            "serves_truth": False,
            "promotion_decision": "none",
            "finished_at": _now(),
        }
        receipt["receipt_digest"] = digest_json(receipt)
        _write_json(run_dir / "receipt.json", receipt)
        manifest_files = {}
        for path in sorted(run_dir.iterdir()):
            if path.is_file():
                manifest_files[path.name] = {"digest": digest_bytes(path.read_bytes()), "bytes": path.stat().st_size}
        manifest = {
            "run_id": run_id,
            "files": manifest_files,
            "candidate_workspace_paths": [str(workspace.path) for workspace in workspaces],
            "candidate_only": True,
            "serves_truth": False,
        }
        manifest["manifest_digest"] = digest_json(manifest)
        _write_json(run_dir / "manifest.json", manifest)
        finish_run(
            con,
            run_id,
            status,
            counts=counts,
            aggregate_receipt_digest=receipt["receipt_digest"],
        )
        return {**receipt, "run_dir": str(run_dir), "manifest_digest": manifest["manifest_digest"]}
    except BaseException as exc:
        error = {"class": type(exc).__name__, "digest": digest_bytes(str(exc).encode("utf-8"))}
        try:
            finish_run(con, run_id, "failed", counts={"unhandled_error": 1}, aggregate_receipt_digest=digest_json(error))
        except Exception:
            pass
        _write_json(run_dir / "failure.json", {"run_id": run_id, "error": error, "candidate_only": True, "serves_truth": False})
        raise
    finally:
        con.close()


def run_loop(
    config: LoopConfig,
    *,
    fixture_map: Mapping[str, Any] | None = None,
    cycles: int = 1,
    interval_seconds: float = 0.0,
    max_runtime_seconds: float | None = None,
) -> dict[str, Any]:
    if cycles < 1:
        raise ValueError("cycles must be at least one")
    if interval_seconds < 0:
        raise ValueError("interval_seconds cannot be negative")
    started = time.monotonic()
    receipts: list[dict[str, Any]] = []
    dynamic_queries = list(config.query_bank)
    query_state_path = config.output_root / "query_state.json"
    if query_state_path.is_file():
        try:
            prior_state = json.loads(query_state_path.read_text(encoding="utf-8"))
            for query in prior_state.get("queries", []):
                if isinstance(query, str) and query not in dynamic_queries:
                    dynamic_queries.append(query)
        except (OSError, ValueError, TypeError):
            pass
    try:
        base_cycle = int(loop_status(config.output_root)["counts"]["loop_runs"])
    except (OSError, ValueError, KeyError):
        base_cycle = 0
    for cycle_index in range(cycles):
        cycle_config = replace(config, query_bank=tuple(dynamic_queries))
        receipt = run_loop_once(
            cycle_config,
            fixture_map=fixture_map,
            cycle_index=base_cycle + cycle_index,
        )
        receipts.append(receipt)
        for query in receipt.get("next_queries", []):
            if query not in dynamic_queries:
                dynamic_queries.append(query)
        query_state = {
            "loop_id": LOOP_ID,
            "queries": dynamic_queries,
            "source_run_id": receipt["run_id"],
            "query_count": len(dynamic_queries),
            "candidate_only": True,
            "serves_truth": False,
            "updated_at": _now(),
        }
        query_state["state_digest"] = digest_json(query_state)
        _write_json(query_state_path, query_state)
        if cycle_index + 1 >= cycles:
            break
        if max_runtime_seconds is not None:
            remaining = max_runtime_seconds - (time.monotonic() - started)
            if remaining <= 0 or interval_seconds > remaining:
                break
        if interval_seconds:
            time.sleep(interval_seconds)
    return {
        "loop_id": LOOP_ID,
        "requested_cycles": cycles,
        "completed_cycles": len(receipts),
        "receipts": receipts,
        "dynamic_query_count": len(dynamic_queries),
        "candidate_only": True,
        "serves_truth": False,
    }


def loop_status(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    con = connect_ledger(output_root / "problem_loop.sqlite")
    try:
        return status_snapshot(con)
    finally:
        con.close()


def loop_reconcile(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    con = connect_ledger(output_root / "problem_loop.sqlite")
    try:
        return reconcile_ledger(con, output_root / "cas")
    finally:
        con.close()


__all__ = [
    "COUNTEREVIDENCE_TERMS",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_QUERY_BANK",
    "LOOP_ID",
    "LoopConfig",
    "SourceAttempt",
    "load_fixture_map",
    "loop_reconcile",
    "loop_status",
    "request_plan",
    "run_loop",
    "run_loop_once",
    "selected_sources",
    "source_catalog",
]
