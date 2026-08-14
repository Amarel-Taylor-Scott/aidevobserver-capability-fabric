"""Deterministic, evidence-bound business-friction mining primitives.

The module deliberately stops short of claiming that lexical extraction proves a
business problem.  It creates candidate records with preserved evidence and
unknowns, clusters them reproducibly, and exposes a transparent build gate and
queue score for later policy and execution-backed qualification.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_MAX_EXCERPT_CHARS = 512
UNKNOWN_FRICTION = "unknown"


# Keep these mappings intentionally broad.  They describe the shape of a
# candidate primitive, not a domain-specific executable contract.
FRICTION_ARCHETYPES: dict[str, dict[str, str]] = {
    "manual_transfer": {
        "label": "manual transfer or duplicate entry",
        "archetype": "adapter",
        "input_contract": "SourceRecord",
        "output_contract": "DestinationRecord",
        "oracle_kind": "field_mapping_equivalence",
    },
    "reconciliation": {
        "label": "reconciliation or mismatch resolution",
        "archetype": "matcher_diff",
        "input_contract": "RecordSetPair",
        "output_contract": "ReconciliationReport",
        "oracle_kind": "known_match_and_difference_fixture",
    },
    "validation_compliance": {
        "label": "validation or compliance checking",
        "archetype": "validator",
        "input_contract": "CandidateRecord",
        "output_contract": "ValidationReport",
        "oracle_kind": "positive_and_negative_rule_fixture",
    },
    "aggregation": {
        "label": "fragmented-source aggregation",
        "archetype": "aggregator",
        "input_contract": "SourceCollection",
        "output_contract": "NormalizedAggregate",
        "oracle_kind": "source_completeness_and_dedup_fixture",
    },
    "monitoring": {
        "label": "state monitoring or alerting",
        "archetype": "monitor",
        "input_contract": "ObservedStateStream",
        "output_contract": "AlertEventSet",
        "oracle_kind": "state_transition_alert_fixture",
    },
    "lookup": {
        "label": "lookup or discovery",
        "archetype": "retriever",
        "input_contract": "LookupQuery",
        "output_contract": "EvidenceBoundResultSet",
        "oracle_kind": "held_out_relevance_fixture",
    },
    "triage": {
        "label": "triage, prioritization, or routing",
        "archetype": "classifier_router",
        "input_contract": "WorkItemSet",
        "output_contract": "RoutedWorkItemSet",
        "oracle_kind": "held_out_routing_fixture",
    },
    "handoff": {
        "label": "workflow handoff or coordination",
        "archetype": "orchestrator",
        "input_contract": "WorkflowHandoff",
        "output_contract": "HandoffReceipt",
        "oracle_kind": "state_transition_and_receipt_fixture",
    },
    "extraction": {
        "label": "unstructured-data extraction",
        "archetype": "extractor_normalizer",
        "input_contract": "UnstructuredArtifact",
        "output_contract": "StructuredRecordSet",
        "oracle_kind": "golden_extraction_fixture",
    },
    "decision_inconsistency": {
        "label": "inconsistent or subjective decisions",
        "archetype": "policy_evaluator",
        "input_contract": "DecisionContext",
        "output_contract": "PolicyDecision",
        "oracle_kind": "policy_decision_table_fixture",
    },
    "missing_integration": {
        "label": "missing integration or synchronization",
        "archetype": "synchronizer",
        "input_contract": "SystemSnapshotPair",
        "output_contract": "ChangePlan",
        "oracle_kind": "known_create_update_delete_fixture",
    },
    "scheduling_coordination": {
        "label": "scheduling and capacity coordination",
        "archetype": "scheduler",
        "input_contract": "SchedulingConstraintSet",
        "output_contract": "CandidateSchedule",
        "oracle_kind": "constraint_satisfaction_fixture",
    },
    "exception_handling": {
        "label": "manual exception handling",
        "archetype": "classifier_router",
        "input_contract": "ExceptionItemSet",
        "output_contract": "PrioritizedExceptionQueue",
        "oracle_kind": "held_out_exception_routing_fixture",
    },
    "data_quality_cleanup": {
        "label": "repeated data-quality cleanup",
        "archetype": "validator",
        "input_contract": "CandidateRecordSet",
        "output_contract": "DataQualityReport",
        "oracle_kind": "positive_and_negative_quality_fixture",
    },
    "status_chasing": {
        "label": "manual status chasing",
        "archetype": "monitor",
        "input_contract": "WorkflowStateSet",
        "output_contract": "StalledItemAlertSet",
        "oracle_kind": "stalled_state_transition_fixture",
    },
    "manual_workflow": {
        "label": "repetitive manual workflow",
        "archetype": "workflow_orchestrator",
        "input_contract": "WorkflowAutomationRequest",
        "output_contract": "AutomationPlan",
        "oracle_kind": "known_step_order_and_trigger_fixture",
    },
}


FRICTION_VOCABULARY: dict[str, tuple[str, ...]] = {
    "manual_transfer": (
        "manual transfer",
        "manually copy",
        "manually enter",
        "manual entry",
        "copy and paste",
        "copy paste",
        "copy/paste",
        "duplicate data entry",
        "enter by hand",
        "re-key",
        "rekey",
        "spreadsheet to",
    ),
    "reconciliation": (
        "manually reconcile",
        "reconcile",
        "reconciliation",
        "mismatch",
        "matching records",
        "match records",
        "compare records",
        "compare systems",
        "find duplicates",
        "difference report",
    ),
    "validation_compliance": (
        "compliance",
        "validate",
        "validation",
        "verify against",
        "audit",
        "policy check",
        "regulatory",
        "rule check",
        "eligibility check",
    ),
    "aggregation": (
        "aggregate",
        "aggregation",
        "consolidate",
        "combine sources",
        "fragmented",
        "across multiple systems",
        "single view",
        "siloed",
        "merge feeds",
    ),
    "monitoring": (
        "monitor",
        "monitoring",
        "alert",
        "notify when",
        "watch for",
        "detect changes",
        "track status",
        "status changed",
    ),
    "lookup": (
        "look up",
        "lookup",
        "search for",
        "find the",
        "discover",
        "locate",
        "where is",
        "retrieve the",
    ),
    "triage": (
        "triage",
        "route tickets",
        "route requests",
        "assign tickets",
        "assign cases",
        "classify requests",
        "prioritize",
        "work queue",
        "routing queue",
    ),
    "handoff": (
        "handoff",
        "hand off",
        "between teams",
        "approval chain",
        "coordinate teams",
        "workflow transition",
        "falls through the cracks",
        "handover",
    ),
    "extraction": (
        "extract",
        "parse documents",
        "parse pdf",
        "ocr",
        "unstructured",
        "email attachment",
        "turn documents into",
        "structured data",
        "read fields from",
    ),
    "decision_inconsistency": (
        "inconsistent decision",
        "inconsistent decisions",
        "different decisions",
        "decision varies",
        "subjective scoring",
        "subjective decision",
        "policy interpretation",
        "same case different",
        "inconsistent prioritization",
    ),
    "missing_integration": (
        "missing integration",
        "cannot integrate",
        "no integration",
        "missing api",
        "no api",
        "failed to sync",
        "out of sync",
        "sync conflict",
        "different microservices",
        "between systems",
        "webhook missing",
        "synchronization between",
        "interoperability of systems",
    ),
    "scheduling_coordination": (
        "scheduling conflict",
        "schedule manually",
        "reschedule",
        "overbooked",
        "no show",
        "no-show",
        "shift coverage",
        "capacity planning",
    ),
    "exception_handling": (
        "exception handling",
        "exception queue",
        "manual exception",
        "review exceptions",
        "failed items",
        "dead letter",
        "retry queue",
    ),
    "data_quality_cleanup": (
        "data cleanup",
        "clean up data",
        "invalid records",
        "malformed records",
        "missing fields",
        "bad data",
        "data quality",
        "normalize records",
    ),
    "status_chasing": (
        "chase status",
        "chasing status",
        "follow up manually",
        "manual follow up",
        "waiting for update",
        "where is my request",
        "check status every",
    ),
    "manual_workflow": (
        "manual process",
        "manual business process",
        "manual workflow",
        "repetitive manual",
        "automate the process",
        "same steps every day",
    ),
}


DEFAULT_QUEUE_PROFILE: dict[str, Any] = {
    "version": "problem-opportunity-queue.v1",
    "normalizers": {
        "evidence_count_cap": 5.0,
        "source_class_count_cap": 3.0,
    },
    "weights": {
        "evidence_strength": 0.14,
        "source_diversity": 0.10,
        "buyer_intent": 0.10,
        "severity": 0.10,
        "momentum": 0.05,
        "solution_gap": 0.05,
        "actor_clarity": 0.05,
        "workflow_clarity": 0.08,
        "contract_clarity": 0.10,
        "oracle_clarity": 0.15,
        "friction_confidence": 0.05,
        "impact_coverage": 0.03,
    },
    "penalty_weights": {"contradiction_pressure": 0.15},
    "unknown_policy": "zero_contribution_without_relabeling_unknown_as_zero",
}


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_KNOWN_TOKEN_RE = re.compile(
    r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{12,})\b",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(api[_-]?key|access[_-]?token|refresh[_-]?token|auth(?:orization)?|"
    r"secret|password)\b(\s*[:=]\s*)([^\s,;&#]+)",
    re.IGNORECASE,
)
_SECRET_QUERY_RE = re.compile(
    r"([?&](?:api[_-]?key|access[_-]?token|token|secret|signature|password)=)"
    r"([^&#\s]+)",
    re.IGNORECASE,
)
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d ()./-]{7,}\d)(?!\w)")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "by",
    "can",
    "do",
    "every",
    "for",
    "from",
    "have",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "this",
    "to",
    "we",
    "when",
    "with",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}.{_digest(value).split(':', 1)[1][:24]}"


def redact_sensitive(value: str) -> str:
    """Redact common contact details and bearer/API token forms deterministically."""

    text = str(value)
    text = _BEARER_RE.sub("Bearer <redacted-token>", text)
    text = _KNOWN_TOKEN_RE.sub("<redacted-token>", text)
    text = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted-token>", text
    )
    text = _SECRET_QUERY_RE.sub(lambda match: f"{match.group(1)}<redacted-token>", text)
    text = _EMAIL_RE.sub("<redacted-email>", text)

    def redact_phone(match: re.Match[str]) -> str:
        candidate = match.group(0)
        digit_count = sum(character.isdigit() for character in candidate)
        return "<redacted-phone>" if 10 <= digit_count <= 15 else candidate

    return _PHONE_CANDIDATE_RE.sub(redact_phone, text)


def bounded_excerpt(value: str, *, max_chars: int = DEFAULT_MAX_EXCERPT_CHARS) -> str:
    """Return whitespace-normalized, redacted text no longer than ``max_chars``."""

    if max_chars < 8:
        raise ValueError("max_chars must be at least 8")
    cleaned = " ".join(redact_sensitive(value).split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _bounded_ref(value: str) -> str:
    return bounded_excerpt(value, max_chars=2048)


def _clean_optional(value: str | None, *, max_chars: int = 240) -> str | None:
    if value is None:
        return None
    cleaned = bounded_excerpt(value, max_chars=max_chars)
    return cleaned or None


def _normalized_phrase(value: str) -> str:
    return " " + " ".join(_TOKEN_RE.findall(value.casefold())) + " "


def _phrase_present(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = " ".join(_TOKEN_RE.findall(phrase.casefold()))
    return bool(normalized_phrase) and f" {normalized_phrase} " in normalized_text


def classify_friction(text: str) -> tuple[str, float | None]:
    """Classify text with an auditable phrase vocabulary.

    The confidence is a relative lexical score, not a calibrated probability.
    """

    normalized = _normalized_phrase(redact_sensitive(text))
    scores: dict[str, int] = {}
    for friction_type, phrases in FRICTION_VOCABULARY.items():
        score = 0
        for phrase in phrases:
            if _phrase_present(normalized, phrase):
                word_count = len(_TOKEN_RE.findall(phrase))
                score += 3 if word_count > 1 else 1
        scores[friction_type] = score
    total = sum(scores.values())
    if total == 0:
        return UNKNOWN_FRICTION, None
    # dict insertion order is the declared vocabulary precedence for exact ties.
    winner = max(scores, key=lambda key: scores[key])
    return winner, round(scores[winner] / total, 6)


def _infer_actor(text: str) -> str | None:
    pattern = re.compile(
        r"\b(?:our|the)\s+([a-z][a-z0-9& /-]{0,48}?"
        r"(?:team|staff|analysts?|operators?|agents?|clerks?|engineers?|"
        r"accountants?|buyers?|vendors?|customers?|users?))\b",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return _clean_optional(match.group(1), max_chars=80) if match else None


def _infer_workflow(text: str) -> str | None:
    for pattern in (
        re.compile(r"\bduring\s+([^,.;]{3,100})", re.IGNORECASE),
        re.compile(r"\bwhen\s+([^,.;]{3,100})", re.IGNORECASE),
    ):
        match = pattern.search(text)
        if match:
            return _clean_optional(match.group(1), max_chars=100)
    return None


def _infer_clause(text: str, prefixes: Sequence[str]) -> str | None:
    joined = "|".join(re.escape(prefix) for prefix in prefixes)
    match = re.search(rf"\b(?:{joined})\s+([^.;]{{3,160}})", text, re.IGNORECASE)
    return _clean_optional(match.group(1), max_chars=160) if match else None


def _normalize_token(token: str) -> str:
    aliases = {
        "emails": "email",
        "invoices": "invoice",
        "records": "record",
        "systems": "system",
        "tickets": "ticket",
        "requests": "request",
        "documents": "document",
        "manually": "manual",
        "copies": "copy",
    }
    if token in aliases:
        return aliases[token]
    if len(token) > 5 and token.endswith("s") and not token.endswith(("ss", "us")):
        return token[:-1]
    return token


_GENERIC_FRICTION_TOKENS = {
    _normalize_token(token)
    for phrases in FRICTION_VOCABULARY.values()
    for phrase in phrases
    for token in _TOKEN_RE.findall(phrase.casefold())
}


def _semantic_tokens(*values: str | None) -> tuple[str, ...]:
    tokens: set[str] = set()
    for value in values:
        if not value:
            continue
        for raw in _TOKEN_RE.findall(value.casefold()):
            token = _normalize_token(raw)
            if len(token) < 3 or token in _STOPWORDS or token in _GENERIC_FRICTION_TOKENS:
                continue
            tokens.add(token)
    return tuple(sorted(tokens))


def _metric(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def _nonnegative(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return number


@dataclass(frozen=True, slots=True)
class ProblemSignal:
    signal_id: str
    source_ref: str
    source_class: str | None
    evidence_refs: tuple[str, ...]
    excerpt: str
    friction_type: str
    classification_confidence: float | None
    actor: str | None
    workflow: str | None
    consequence: str | None
    desired_outcome: str | None
    workaround: str | None
    archetype: str | None
    input_contract: str | None
    output_contract: str | None
    oracle: str | None
    explicit_budgeted_procurement: bool
    budget_amount: float | None
    budget_currency: str | None
    quantified_impact: float | None
    impact_unit: str | None
    severity: float | None
    momentum: float | None
    solution_gap: float | None
    contradictions: tuple[str, ...]
    semantic_tokens: tuple[str, ...]
    fingerprint: str
    unknown_fields: tuple[str, ...]
    candidate_only: bool = True
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProblemCluster:
    cluster_id: str
    friction_type: str
    archetype: str | None
    input_contract: str | None
    output_contract: str | None
    actor: str | None
    actors: tuple[str, ...]
    workflow: str | None
    workflows: tuple[str, ...]
    oracle_refs: tuple[str, ...]
    member_signal_ids: tuple[str, ...]
    member_fingerprints: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    source_classes: tuple[str, ...]
    contradictions: tuple[str, ...]
    representative_signal_id: str
    representative_excerpt: str
    semantic_tokens: tuple[str, ...]
    semantic_fingerprint: str
    membership_fingerprint: str
    explicit_budgeted_procurement_signal_ids: tuple[str, ...]
    budget_items: tuple[tuple[str, float, str | None], ...]
    quantified_impacts: tuple[tuple[str, float, str | None], ...]
    severity_values: tuple[float, ...]
    momentum_values: tuple[float, ...]
    solution_gap_values: tuple[float, ...]
    classification_confidences: tuple[float, ...]
    known_actor_count: int
    known_workflow_count: int
    known_oracle_count: int
    unknown_counts: tuple[tuple[str, int], ...]
    unknown_fields: tuple[str, ...]
    candidate_only: bool = True
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OpportunityAssessment:
    assessment_id: str
    cluster_id: str
    score_vector: tuple[tuple[str, float | None], ...]
    unknown_dimensions: tuple[str, ...]
    queue_score: float
    queue_components: tuple[tuple[str, float | None, float, float], ...]
    queue_formula: str
    profile_digest: str
    build_gate_passed: bool
    build_gate_reasons: tuple[str, ...]
    candidate_only: bool = True
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_problem_signal(
    *,
    text: str,
    source_ref: str,
    source_class: str | None,
    evidence_refs: Iterable[str] | None = None,
    signal_id: str | None = None,
    friction_type: str | None = None,
    actor: str | None = None,
    workflow: str | None = None,
    consequence: str | None = None,
    desired_outcome: str | None = None,
    workaround: str | None = None,
    oracle: str | None = None,
    contradictions: Iterable[str] = (),
    explicit_budgeted_procurement: bool = False,
    budget_amount: float | None = None,
    budget_currency: str | None = None,
    quantified_impact: float | None = None,
    impact_unit: str | None = None,
    severity: float | None = None,
    momentum: float | None = None,
    solution_gap: float | None = None,
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS,
) -> ProblemSignal:
    """Extract one candidate problem signal from evidence text.

    Caller-provided actor/workflow/outcome fields take precedence over the small
    deterministic phrase extractors.  Missing values remain ``None``.
    """

    clean_source_ref = _bounded_ref(source_ref)
    if not clean_source_ref:
        raise ValueError("source_ref must not be empty")
    clean_source_class = _clean_optional(source_class, max_chars=80)
    excerpt = bounded_excerpt(text, max_chars=max_excerpt_chars)

    if friction_type is None:
        selected_friction, confidence = classify_friction(excerpt)
    else:
        selected_friction = friction_type.strip().casefold()
        if selected_friction not in FRICTION_ARCHETYPES and selected_friction != UNKNOWN_FRICTION:
            raise ValueError(f"unsupported friction_type: {friction_type}")
        inferred_friction, inferred_confidence = classify_friction(excerpt)
        confidence = inferred_confidence if selected_friction == inferred_friction else None

    mapping = FRICTION_ARCHETYPES.get(selected_friction)
    clean_actor = _clean_optional(actor, max_chars=80) or _infer_actor(excerpt)
    clean_workflow = _clean_optional(workflow, max_chars=120) or _infer_workflow(excerpt)
    clean_consequence = _clean_optional(consequence) or _infer_clause(
        excerpt,
        (
            "causes",
            "cause",
            "causing",
            "leading to",
            "led to",
            "results in",
            "resulting in",
            "costs us",
        ),
    )
    clean_outcome = _clean_optional(desired_outcome) or _infer_clause(
        excerpt, ("we need", "need to", "we want", "so that we can", "should produce")
    )
    clean_workaround = _clean_optional(workaround) or _infer_clause(
        excerpt, ("workaround is", "we have to", "we currently", "currently use")
    )
    clean_oracle = _clean_optional(oracle)

    refs = evidence_refs if evidence_refs is not None else (clean_source_ref,)
    clean_refs = tuple(sorted({_bounded_ref(ref) for ref in refs if str(ref).strip()}))
    if not clean_refs:
        clean_refs = (clean_source_ref,)
    clean_contradictions = tuple(
        sorted(
            {
                bounded_excerpt(value, max_chars=256)
                for value in contradictions
                if str(value).strip()
            }
        )
    )

    clean_budget = _nonnegative(budget_amount, "budget_amount")
    clean_impact = _nonnegative(quantified_impact, "quantified_impact")
    clean_currency = _clean_optional(budget_currency, max_chars=24)
    clean_impact_unit = _clean_optional(impact_unit, max_chars=48)
    clean_severity = _metric(severity, "severity")
    clean_momentum = _metric(momentum, "momentum")
    clean_solution_gap = _metric(solution_gap, "solution_gap")

    semantic_tokens = _semantic_tokens(
        excerpt,
        clean_actor,
        clean_workflow,
        clean_consequence,
        clean_outcome,
    )
    fingerprint_material = {
        "friction_type": selected_friction,
        "actor": clean_actor.casefold() if clean_actor else None,
        "workflow": clean_workflow.casefold() if clean_workflow else None,
        "semantic_tokens": semantic_tokens,
    }
    fingerprint = _digest(fingerprint_material)
    resolved_signal_id = (
        _bounded_ref(signal_id)
        if signal_id
        else _stable_id(
            "problem.signal",
            {
                "source_ref": clean_source_ref,
                "source_class": clean_source_class,
                "evidence_refs": clean_refs,
                "excerpt": excerpt,
                "fingerprint": fingerprint,
            },
        )
    )

    unknown_candidates = {
        "source_class": clean_source_class,
        "actor": clean_actor,
        "workflow": clean_workflow,
        "consequence": clean_consequence,
        "desired_outcome": clean_outcome,
        "workaround": clean_workaround,
        "archetype": mapping["archetype"] if mapping else None,
        "input_contract": mapping["input_contract"] if mapping else None,
        "output_contract": mapping["output_contract"] if mapping else None,
        "oracle": clean_oracle,
        "budget_amount": clean_budget,
        "budget_currency": clean_currency,
        "quantified_impact": clean_impact,
        "impact_unit": clean_impact_unit,
        "severity": clean_severity,
        "momentum": clean_momentum,
        "solution_gap": clean_solution_gap,
    }
    unknown_fields = tuple(
        sorted(key for key, value in unknown_candidates.items() if value is None)
    )

    return ProblemSignal(
        signal_id=resolved_signal_id,
        source_ref=clean_source_ref,
        source_class=clean_source_class,
        evidence_refs=clean_refs,
        excerpt=excerpt,
        friction_type=selected_friction,
        classification_confidence=confidence,
        actor=clean_actor,
        workflow=clean_workflow,
        consequence=clean_consequence,
        desired_outcome=clean_outcome,
        workaround=clean_workaround,
        archetype=mapping["archetype"] if mapping else None,
        input_contract=mapping["input_contract"] if mapping else None,
        output_contract=mapping["output_contract"] if mapping else None,
        oracle=clean_oracle,
        explicit_budgeted_procurement=bool(explicit_budgeted_procurement),
        budget_amount=clean_budget,
        budget_currency=clean_currency,
        quantified_impact=clean_impact,
        impact_unit=clean_impact_unit,
        severity=clean_severity,
        momentum=clean_momentum,
        solution_gap=clean_solution_gap,
        contradictions=clean_contradictions,
        semantic_tokens=semantic_tokens,
        fingerprint=fingerprint,
        unknown_fields=unknown_fields,
    )


def _normalized_label(value: str | None) -> str | None:
    return " ".join(value.casefold().split()) if value else None


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def signal_similarity(left: ProblemSignal, right: ProblemSignal) -> float:
    """Return deterministic similarity without treating it as compatibility truth."""

    if left.friction_type != right.friction_type:
        return 0.0
    if left.fingerprint == right.fingerprint:
        return 1.0
    score = _jaccard(left.semantic_tokens, right.semantic_tokens)
    left_actor = _normalized_label(left.actor)
    right_actor = _normalized_label(right.actor)
    if left_actor and left_actor == right_actor:
        score += 0.15
    workflow_similarity = _jaccard(
        _semantic_tokens(left.workflow), _semantic_tokens(right.workflow)
    )
    score += 0.20 * workflow_similarity
    return round(min(score, 1.0), 6)


def _consensus(values: Iterable[str | None]) -> tuple[str | None, tuple[str, ...]]:
    cleaned = [_clean_optional(value) for value in values if value]
    known = tuple(sorted(set(value for value in cleaned if value)))
    if not known:
        return None, ()
    counts = Counter(_normalized_label(value) for value in cleaned if value)
    winner_normalized = sorted(counts, key=lambda value: (-counts[value], value))[0]
    winner = sorted(value for value in known if _normalized_label(value) == winner_normalized)[0]
    return winner, known


def _representative(signals: Sequence[ProblemSignal]) -> ProblemSignal:
    if len(signals) == 1:
        return signals[0]
    scored: list[tuple[float, str, ProblemSignal]] = []
    for signal in signals:
        average = sum(signal_similarity(signal, other) for other in signals) / len(signals)
        scored.append((-average, signal.signal_id, signal))
    return sorted(scored, key=lambda row: (row[0], row[1]))[0][2]


def _cluster_record(signals: Sequence[ProblemSignal]) -> ProblemCluster:
    ordered = tuple(sorted(signals, key=lambda signal: signal.signal_id))
    representative = _representative(ordered)
    actor, actors = _consensus(signal.actor for signal in ordered)
    workflow, workflows = _consensus(signal.workflow for signal in ordered)
    evidence_refs = tuple(sorted({ref for signal in ordered for ref in signal.evidence_refs}))
    source_classes = tuple(
        sorted({signal.source_class for signal in ordered if signal.source_class}, key=str.casefold)
    )
    contradictions = tuple(
        sorted({value for signal in ordered for value in signal.contradictions})
    )
    token_counts = Counter(
        token for signal in ordered for token in set(signal.semantic_tokens)
    )
    common_tokens = tuple(
        token
        for token, _ in sorted(token_counts.items(), key=lambda row: (-row[1], row[0]))[:12]
    )
    semantic_fingerprint = _digest(
        {
            "friction_type": representative.friction_type,
            "archetype": representative.archetype,
            "input_contract": representative.input_contract,
            "output_contract": representative.output_contract,
            "tokens": common_tokens,
        }
    )
    member_fingerprints = tuple(sorted(signal.fingerprint for signal in ordered))
    membership_fingerprint = _digest(member_fingerprints)
    cluster_id = _stable_id(
        "problem.cluster",
        {
            "friction_type": representative.friction_type,
            "member_signal_ids": tuple(signal.signal_id for signal in ordered),
            "membership_fingerprint": membership_fingerprint,
        },
    )
    oracle_refs = tuple(sorted({signal.oracle for signal in ordered if signal.oracle}))
    explicit_budgeted = tuple(
        sorted(
            signal.signal_id
            for signal in ordered
            if signal.explicit_budgeted_procurement
            and signal.budget_amount is not None
            and signal.budget_amount > 0
        )
    )
    budget_items = tuple(
        sorted(
            (
                (signal.signal_id, signal.budget_amount, signal.budget_currency)
                for signal in ordered
                if signal.budget_amount is not None
            ),
            key=lambda row: row[0],
        )
    )
    quantified_impacts = tuple(
        sorted(
            (
                (signal.signal_id, signal.quantified_impact, signal.impact_unit)
                for signal in ordered
                if signal.quantified_impact is not None
            ),
            key=lambda row: row[0],
        )
    )
    tracked_unknowns = (
        "actor",
        "workflow",
        "oracle",
        "severity",
        "momentum",
        "solution_gap",
        "quantified_impact",
    )
    unknown_counts = tuple(
        (field_name, sum(field_name in signal.unknown_fields for signal in ordered))
        for field_name in tracked_unknowns
    )
    fully_unknown = tuple(
        field_name for field_name, count in unknown_counts if count == len(ordered)
    )

    return ProblemCluster(
        cluster_id=cluster_id,
        friction_type=representative.friction_type,
        archetype=representative.archetype,
        input_contract=representative.input_contract,
        output_contract=representative.output_contract,
        actor=actor,
        actors=actors,
        workflow=workflow,
        workflows=workflows,
        oracle_refs=oracle_refs,
        member_signal_ids=tuple(signal.signal_id for signal in ordered),
        member_fingerprints=member_fingerprints,
        evidence_refs=evidence_refs,
        source_classes=source_classes,
        contradictions=contradictions,
        representative_signal_id=representative.signal_id,
        representative_excerpt=representative.excerpt,
        semantic_tokens=common_tokens,
        semantic_fingerprint=semantic_fingerprint,
        membership_fingerprint=membership_fingerprint,
        explicit_budgeted_procurement_signal_ids=explicit_budgeted,
        budget_items=budget_items,
        quantified_impacts=quantified_impacts,
        severity_values=tuple(signal.severity for signal in ordered if signal.severity is not None),
        momentum_values=tuple(signal.momentum for signal in ordered if signal.momentum is not None),
        solution_gap_values=tuple(
            signal.solution_gap for signal in ordered if signal.solution_gap is not None
        ),
        classification_confidences=tuple(
            signal.classification_confidence
            for signal in ordered
            if signal.classification_confidence is not None
        ),
        known_actor_count=sum(signal.actor is not None for signal in ordered),
        known_workflow_count=sum(signal.workflow is not None for signal in ordered),
        known_oracle_count=sum(signal.oracle is not None for signal in ordered),
        unknown_counts=unknown_counts,
        unknown_fields=fully_unknown,
    )


def cluster_problem_signals(
    signals: Iterable[ProblemSignal], *, minimum_similarity: float = 0.30
) -> tuple[ProblemCluster, ...]:
    """Cluster signals with deterministic connected components.

    Cluster IDs are invariant to input order.  ``member_fingerprints`` and the
    membership/semantic fingerprints let later versions identify overlap after
    a split or merge without asserting that the lineage is automatically true.
    """

    if not 0.0 <= minimum_similarity <= 1.0:
        raise ValueError("minimum_similarity must be between 0 and 1")
    ordered = tuple(sorted(signals, key=lambda signal: signal.signal_id))
    seen: set[str] = set()
    for signal in ordered:
        if signal.signal_id in seen:
            raise ValueError(f"duplicate signal_id: {signal.signal_id}")
        seen.add(signal.signal_id)
    if not ordered:
        return ()

    parent = list(range(len(ordered)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        parent[max(left_root, right_root)] = min(left_root, right_root)

    for left_index, left in enumerate(ordered):
        for right_index in range(left_index + 1, len(ordered)):
            right = ordered[right_index]
            if left.friction_type != right.friction_type:
                continue
            if signal_similarity(left, right) >= minimum_similarity:
                union(left_index, right_index)

    groups: dict[int, list[ProblemSignal]] = {}
    for index, signal in enumerate(ordered):
        groups.setdefault(find(index), []).append(signal)
    clusters = tuple(_cluster_record(group) for _, group in sorted(groups.items()))
    return tuple(sorted(clusters, key=lambda cluster: cluster.cluster_id))


def automatic_build_gate(cluster: ProblemCluster) -> tuple[bool, tuple[str, ...]]:
    """Apply the conservative evidence-or-procurement build gate."""

    independent_evidence = len(cluster.evidence_refs)
    source_class_count = len(cluster.source_classes)
    evidence_gate = independent_evidence >= 3 and source_class_count >= 2
    procurement_gate = bool(cluster.explicit_budgeted_procurement_signal_ids)
    reasons: list[str] = []
    if not (evidence_gate or procurement_gate):
        reasons.append("insufficient_independent_evidence_or_budgeted_procurement")
    if cluster.actor is None:
        reasons.append("actor_unknown")
    if cluster.workflow is None:
        reasons.append("workflow_unknown")
    if cluster.input_contract is None or cluster.output_contract is None:
        reasons.append("contract_unknown")
    if not cluster.oracle_refs:
        reasons.append("testable_oracle_unknown")
    return not reasons, tuple(reasons)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _effective_profile(profile: Mapping[str, Any] | None) -> dict[str, Any]:
    effective = json.loads(_canonical_json(DEFAULT_QUEUE_PROFILE))
    if profile:
        for section in ("normalizers", "weights", "penalty_weights"):
            if section in profile:
                if not isinstance(profile[section], Mapping):
                    raise ValueError(f"profile {section} must be a mapping")
                effective[section].update(profile[section])
        for key in ("version", "unknown_policy"):
            if key in profile:
                effective[key] = profile[key]
    for section in ("weights", "penalty_weights"):
        for name, weight in effective[section].items():
            number = float(weight)
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"profile weight {section}.{name} must be non-negative")
            effective[section][name] = number
    for name, cap in effective["normalizers"].items():
        number = float(cap)
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"profile normalizer {name} must be positive")
        effective["normalizers"][name] = number
    return effective


def assess_opportunity(
    cluster: ProblemCluster, *, profile: Mapping[str, Any] | None = None
) -> OpportunityAssessment:
    """Create a transparent score vector and conservative queue score."""

    effective = _effective_profile(profile)
    signal_count = len(cluster.member_signal_ids)
    evidence_count = len(cluster.evidence_refs)
    source_count = len(cluster.source_classes)
    impact_count = len(cluster.quantified_impacts)
    evidence_strength = min(
        evidence_count / effective["normalizers"]["evidence_count_cap"], 1.0
    )
    source_diversity = min(
        source_count / effective["normalizers"]["source_class_count_cap"], 1.0
    )
    buyer_intent = 1.0 if cluster.explicit_budgeted_procurement_signal_ids else 0.0
    severity = _mean(cluster.severity_values)
    momentum = _mean(cluster.momentum_values)
    solution_gap = _mean(cluster.solution_gap_values)
    actor_clarity = cluster.known_actor_count / signal_count if signal_count else 0.0
    workflow_clarity = cluster.known_workflow_count / signal_count if signal_count else 0.0
    contract_clarity = (
        1.0 if cluster.input_contract is not None and cluster.output_contract is not None else 0.0
    )
    oracle_clarity = cluster.known_oracle_count / signal_count if signal_count else 0.0
    friction_confidence = _mean(cluster.classification_confidences)
    impact_coverage = impact_count / signal_count if signal_count else 0.0
    contradiction_pressure = min(
        len(cluster.contradictions) / max(evidence_count, 1), 1.0
    )

    currencies = {currency for _, _, currency in cluster.budget_items if currency}
    budget_total = (
        sum(amount for _, amount, _ in cluster.budget_items)
        if cluster.budget_items
        and len(currencies) == 1
        and all(currency is not None for _, _, currency in cluster.budget_items)
        else None
    )
    impact_units = {unit for _, _, unit in cluster.quantified_impacts if unit}
    impact_total = (
        sum(value for _, value, _ in cluster.quantified_impacts)
        if cluster.quantified_impacts
        and len(impact_units) == 1
        and all(unit is not None for _, _, unit in cluster.quantified_impacts)
        else None
    )

    vector_values: dict[str, float | None] = {
        "signal_count": float(signal_count),
        "evidence_count": float(evidence_count),
        "source_class_count": float(source_count),
        "contradiction_count": float(len(cluster.contradictions)),
        "budgeted_procurement_count": float(
            len(cluster.explicit_budgeted_procurement_signal_ids)
        ),
        "budget_total": budget_total,
        "quantified_impact_total": impact_total,
        "evidence_strength": round(evidence_strength, 6),
        "source_diversity": round(source_diversity, 6),
        "buyer_intent": buyer_intent,
        "severity": round(severity, 6) if severity is not None else None,
        "momentum": round(momentum, 6) if momentum is not None else None,
        "solution_gap": round(solution_gap, 6) if solution_gap is not None else None,
        "actor_clarity": round(actor_clarity, 6),
        "workflow_clarity": round(workflow_clarity, 6),
        "contract_clarity": contract_clarity,
        "oracle_clarity": round(oracle_clarity, 6),
        "friction_confidence": (
            round(friction_confidence, 6) if friction_confidence is not None else None
        ),
        "impact_coverage": round(impact_coverage, 6),
        "contradiction_pressure": round(contradiction_pressure, 6),
    }
    unknown_dimensions = tuple(
        sorted(name for name, value in vector_values.items() if value is None)
    )

    components: list[tuple[str, float | None, float, float]] = []
    positive_total = 0.0
    for name, weight in effective["weights"].items():
        value = vector_values.get(name)
        contribution = weight * value if value is not None else 0.0
        positive_total += contribution
        components.append((name, value, weight, round(contribution, 8)))
    penalty_total = 0.0
    for name, weight in effective["penalty_weights"].items():
        value = vector_values.get(name)
        contribution = weight * value if value is not None else 0.0
        penalty_total += contribution
        components.append((f"penalty:{name}", value, weight, round(-contribution, 8)))
    queue_score = round(max(0.0, min(1.0, positive_total - penalty_total)), 6)
    gate_passed, gate_reasons = automatic_build_gate(cluster)
    profile_digest = _digest(effective)
    assessment_id = _stable_id(
        "problem.assessment",
        {
            "cluster_id": cluster.cluster_id,
            "profile_digest": profile_digest,
            "score_vector": vector_values,
        },
    )

    return OpportunityAssessment(
        assessment_id=assessment_id,
        cluster_id=cluster.cluster_id,
        score_vector=tuple(vector_values.items()),
        unknown_dimensions=unknown_dimensions,
        queue_score=queue_score,
        queue_components=tuple(components),
        queue_formula=(
            "clamp_0_1(sum(weight*known_value; unknown contributes 0) "
            "- sum(penalty_weight*known_value))"
        ),
        profile_digest=profile_digest,
        build_gate_passed=gate_passed,
        build_gate_reasons=gate_reasons,
    )


__all__ = [
    "DEFAULT_MAX_EXCERPT_CHARS",
    "DEFAULT_QUEUE_PROFILE",
    "FRICTION_ARCHETYPES",
    "FRICTION_VOCABULARY",
    "OpportunityAssessment",
    "ProblemCluster",
    "ProblemSignal",
    "UNKNOWN_FRICTION",
    "assess_opportunity",
    "automatic_build_gate",
    "bounded_excerpt",
    "classify_friction",
    "cluster_problem_signals",
    "extract_problem_signal",
    "redact_sensitive",
    "signal_similarity",
]
