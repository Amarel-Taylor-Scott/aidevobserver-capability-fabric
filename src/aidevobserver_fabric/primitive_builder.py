"""Build receipt-bound candidate primitives from corroborated problem clusters.

The builder deliberately produces *candidate* implementations.  A passing
fixture test proves only that exact generated artifact against those exact
fixtures.  It never changes ``serves_truth`` and it never creates an eligible
compatibility edge.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Any, Mapping
from urllib.parse import quote

from . import edge_catalog
from .models import PrimitiveRecord


JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
BUILDER_ID = "aidevobserver.problem_primitive_builder.v1"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_bytes(value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "_" for character in value)
    return "_".join(part for part in cleaned.split("_") if part)[:96] or "candidate"


def _value(record: Any, field: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(field, default)
    return getattr(record, field, default)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n")


@dataclass(frozen=True, slots=True)
class PrimitiveDraft:
    draft_id: str
    cluster_id: str
    capability_id: str
    implementation_id: str
    label: str
    problem_statement: str
    archetype: str
    input_contract: str
    output_contract: str
    actor: str
    workflow: str
    source_refs: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    source_classes: tuple[str, ...]
    opportunity: dict[str, Any]
    coverage: dict[str, Any]
    build_gate: dict[str, Any]
    candidate_only: bool = True
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_primitive_record(self) -> PrimitiveRecord:
        return PrimitiveRecord(
            primitive_id=self.implementation_id,
            label=self.label,
            input_contract=self.input_contract,
            output_contract=self.output_contract,
            trust="candidate",
            readiness="R2_problem_evidence",
            effects=("effects_unknown",),
            memory="artifact_ref",
            cache="content_hash",
            serves_truth=False,
            remix_tools=("schema_gate", "deterministic_rewrite"),
            proof_obligations=(
                "domain_fixture_review",
                "negative_fixture",
                "hidden_oracle",
                "effect_declaration",
                "source_evidence_review",
            ),
            promotion_blockers=(
                "candidate_problem_interpretation",
                "domain_expert_review_missing",
                "effects_not_verified",
                "production_execution_receipts_missing",
            ),
            source_refs=self.source_refs,
            search_text=" ".join(
                (self.problem_statement, self.actor, self.workflow, self.archetype)
            ),
        )


@dataclass(frozen=True, slots=True)
class CandidateWorkspace:
    draft: PrimitiveDraft
    path: Path
    manifest: dict[str, Any]
    test_receipt: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft": self.draft.to_dict(),
            "path": str(self.path),
            "manifest": self.manifest,
            "test_receipt": self.test_receipt,
            "candidate_only": True,
            "serves_truth": False,
        }


ARCHETYPE_CONTRACTS: dict[str, tuple[str, str]] = {
    "adapter": ("RecordMappingRequest", "MappedRecordSet"),
    "reconciliation": ("ReconciliationRequest", "ReconciliationReport"),
    "validation": ("ValidationRequest", "ValidationReport"),
    "aggregation": ("AggregationRequest", "GroupedSummary"),
    "monitoring": ("MonitoringRequest", "PrioritizedAlertSet"),
    "lookup": ("LookupRequest", "RankedMatchSet"),
    "triage": ("TriageRequest", "PrioritizedWorkQueue"),
    "handoff": ("RoutingRequest", "AssignmentPlan"),
    "extraction": ("ExtractionRequest", "StructuredRecordSet"),
    "policy": ("PolicyEvaluationRequest", "PolicyDecisionSet"),
    "scheduling": ("SchedulingRequest", "CandidateSchedule"),
    "sync": ("SynchronizationRequest", "ChangePlan"),
    "workflow": ("WorkflowAutomationRequest", "AutomationPlan"),
}

ARCHETYPE_ALIASES = {
    "matcher_diff": "reconciliation",
    "validator": "validation",
    "aggregator": "aggregation",
    "monitor": "monitoring",
    "retriever": "lookup",
    "classifier_router": "triage",
    "orchestrator": "handoff",
    "extractor_normalizer": "extraction",
    "policy_evaluator": "policy",
    "synchronizer": "sync",
    "scheduler": "scheduling",
    "workflow_orchestrator": "workflow",
}


def _cluster_query(cluster: Any) -> str:
    parts = [
        _value(cluster, "canonical_statement", ""),
        _value(cluster, "problem_statement", ""),
        _value(cluster, "representative_excerpt", ""),
        _value(cluster, "actor", ""),
        _value(cluster, "workflow", ""),
        _value(cluster, "friction_type", ""),
        _value(cluster, "archetype", ""),
    ]
    return " ".join(str(part) for part in parts if part)


def evaluate_registry_coverage(
    cluster: Any,
    *,
    location: edge_catalog.CatalogLocation = edge_catalog.CatalogLocation(),
    limit: int = 3,
) -> dict[str, Any]:
    """Return retrieval overlap without claiming semantic compatibility."""

    return evaluate_registry_coverage_many(
        (cluster,),
        location=location,
        limit=limit,
    )[str(_value(cluster, "cluster_id", digest_json(_cluster_query(cluster))))]


def evaluate_registry_coverage_many(
    clusters: tuple[Any, ...] | list[Any],
    *,
    location: edge_catalog.CatalogLocation = edge_catalog.CatalogLocation(),
    limit: int = 3,
) -> dict[str, dict[str, Any]]:
    """Compare many clusters against one loaded catalog snapshot."""

    try:
        rows = edge_catalog.load_resolved(location)
        snapshot = edge_catalog.summary(location)
        snapshot_digest = digest_json(snapshot)
        error = None
    except (FileNotFoundError, KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        rows = []
        snapshot_digest = None
        error = {"class": type(exc).__name__, "digest": digest_bytes(str(exc).encode("utf-8"))}
    results: dict[str, dict[str, Any]] = {}
    for cluster in clusters:
        cluster_id = str(_value(cluster, "cluster_id", digest_json(_cluster_query(cluster))))
        query = _cluster_query(cluster)
        query_terms = edge_catalog.normalize_tokens(query)
        scored: list[tuple[float, str, dict[str, Any], list[str]]] = []
        for row in rows:
            score, reasons = edge_catalog.score_row(row, query_terms, {})
            if score > 0:
                scored.append((score, row["primitive_id"], row, reasons))
        scored.sort(key=lambda item: (-item[0], item[1]))
        matches = [
            {
                "primitive_id": row["primitive_id"],
                "title": row["title"],
                "input_edge": row["input_edge"],
                "output_edge": row["output_edge"],
                "runtime_targets": row["runtime_targets"],
                "effects": row["effects"],
                "proof_requirements": row["proof_requirements"],
                "score": round(score, 6),
                "reasons": reasons,
                "candidate": True,
                "serves_truth": False,
            }
            for score, _, row, reasons in scored[:limit]
        ]
        results[cluster_id] = {
            "cluster_id": cluster_id,
            "outcome": "retrieval_overlap" if matches else "unresolved_gap_candidate",
            "semantic_compatibility": "unknown",
            "execution_authorized": False,
            "query": query,
            "registry_snapshot_digest": snapshot_digest,
            "matches": matches,
            "error": error,
            "candidate_only": True,
            "serves_truth": False,
        }
    return results


def draft_from_problem(cluster: Any, *, coverage: dict[str, Any] | None = None) -> PrimitiveDraft:
    cluster_id = str(_value(cluster, "cluster_id", digest_json(_cluster_query(cluster))))
    archetype = str(_value(cluster, "archetype", "policy"))
    archetype = ARCHETYPE_ALIASES.get(archetype, archetype)
    if archetype not in ARCHETYPE_CONTRACTS:
        archetype = "policy"
    input_contract, output_contract = ARCHETYPE_CONTRACTS[archetype]
    topic = _slug(
        str(_value(cluster, "workflow", ""))
        or str(_value(cluster, "friction_type", ""))
        or str(_value(cluster, "canonical_statement", "problem"))
    )
    stable = hashlib.sha256(f"{cluster_id}|{archetype}|{topic}".encode("utf-8")).hexdigest()[:16]
    draft_id = f"draft.problem.{archetype}.{topic}.{stable}.v0"
    source_refs = tuple(
        sorted(
            set(
                _value(cluster, "source_refs", ())
                or _value(cluster, "evidence_refs", ())
                or ()
            )
        )
    )
    supplied_digests = tuple(_value(cluster, "evidence_digests", ()) or ())
    evidence_digests = tuple(
        sorted(
            {
                value if str(value).startswith("sha256:") else digest_bytes(str(value).encode("utf-8"))
                for value in (supplied_digests or source_refs)
            }
        )
    )
    source_classes = tuple(sorted(set(_value(cluster, "source_classes", ()) or ())))
    statement = str(
        _value(cluster, "canonical_statement", "")
        or _value(cluster, "problem_statement", "")
        or _value(cluster, "representative_excerpt", "")
        or "Unresolved business workflow friction"
    )
    actor = str(_value(cluster, "actor", "operator") or "operator")
    workflow = str(_value(cluster, "workflow", topic) or topic)
    opportunity = _value(cluster, "opportunity", None) or _value(cluster, "score_vector", {}) or {}
    if not isinstance(opportunity, Mapping):
        opportunity = dict(opportunity)
    gate = _value(cluster, "build_gate", None) or {
        "eligible": False,
        "reason": "cluster_did_not_supply_a_build_gate",
    }
    return PrimitiveDraft(
        draft_id=draft_id,
        cluster_id=cluster_id,
        capability_id=f"urn:aidevobserver:capability:{archetype}:{topic}",
        implementation_id=f"candidate.problem.{archetype}.{topic}.{stable}.v0",
        label=f"Candidate {archetype} for {workflow.replace('_', ' ')}",
        problem_statement=statement,
        archetype=archetype,
        input_contract=input_contract,
        output_contract=output_contract,
        actor=actor,
        workflow=workflow,
        source_refs=source_refs,
        evidence_digests=evidence_digests,
        source_classes=source_classes,
        opportunity=dict(opportunity),
        coverage=coverage or evaluate_registry_coverage(cluster),
        build_gate=dict(gate),
    )


def _schemas(draft: PrimitiveDraft) -> tuple[dict[str, Any], dict[str, Any]]:
    common_input = {
        "$schema": JSON_SCHEMA_DIALECT,
        "title": draft.input_contract,
        "type": "object",
        "additionalProperties": True,
    }
    common_output = {
        "$schema": JSON_SCHEMA_DIALECT,
        "title": draft.output_contract,
        "type": "object",
        "additionalProperties": True,
    }
    required_by_archetype = {
        "adapter": ["records", "field_map"],
        "reconciliation": ["left", "right", "key"],
        "validation": ["records", "required_fields"],
        "aggregation": ["items", "group_by"],
        "monitoring": ["events", "rules"],
        "lookup": ["records", "query"],
        "triage": ["items", "priority_terms"],
        "handoff": ["items", "routing_rules"],
        "extraction": ["records", "field_map"],
        "policy": ["records", "rules"],
        "scheduling": ["tasks", "slots"],
        "sync": ["source", "target", "key"],
        "workflow": ["steps", "triggers"],
    }
    common_input["required"] = required_by_archetype[draft.archetype]
    return common_input, common_output


IMPLEMENTATION_SOURCE = '''"""Generated deterministic candidate primitive.

This module is candidate material.  It performs no network, filesystem,
subprocess, secret, clock, or random operation.
"""

from __future__ import annotations

from typing import Any


def _require_payload(payload: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ValueError("missing required fields: " + ",".join(missing))
    return payload


def adapter(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("records", "field_map"))
    if not isinstance(data["records"], list) or not isinstance(data["field_map"], dict):
        raise ValueError("records must be a list and field_map must be an object")
    rows = [{target: record.get(source) for source, target in sorted(data["field_map"].items())}
            for record in data["records"] if isinstance(record, dict)]
    return {"records": rows, "record_count": len(rows)}


def reconciliation(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("left", "right", "key"))
    if not isinstance(data["left"], list) or not isinstance(data["right"], list) or not isinstance(data["key"], str):
        raise ValueError("left/right must be lists and key must be text")
    key = data["key"]
    left = {row.get(key): row for row in data["left"] if isinstance(row, dict) and key in row}
    right = {row.get(key): row for row in data["right"] if isinstance(row, dict) and key in row}
    shared = sorted(set(left) & set(right), key=str)
    return {
        "matched": [{"key": value, "left": left[value], "right": right[value]} for value in shared],
        "left_only": [left[value] for value in sorted(set(left) - set(right), key=str)],
        "right_only": [right[value] for value in sorted(set(right) - set(left), key=str)],
    }


def validation(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("records", "required_fields"))
    if not isinstance(data["records"], list) or not isinstance(data["required_fields"], list):
        raise ValueError("records and required_fields must be lists")
    errors = []
    valid = []
    for index, record in enumerate(data["records"]):
        if not isinstance(record, dict):
            errors.append({"index": index, "missing": [], "error": "not_an_object"})
            continue
        missing = [field for field in data["required_fields"] if record.get(field) in (None, "")]
        if missing:
            errors.append({"index": index, "missing": missing, "error": "required_field_missing"})
        else:
            valid.append(record)
    return {"valid_records": valid, "errors": errors, "valid": not errors}


def aggregation(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("items", "group_by"))
    if not isinstance(data["items"], list) or not isinstance(data["group_by"], str):
        raise ValueError("items must be a list and group_by must be text")
    value_field = data.get("value_field")
    groups: dict[str, dict[str, Any]] = {}
    for item in data["items"]:
        if not isinstance(item, dict):
            continue
        group = str(item.get(data["group_by"], "unknown"))
        bucket = groups.setdefault(group, {"group": group, "count": 0, "sum": 0.0})
        bucket["count"] += 1
        if value_field and isinstance(item.get(value_field), (int, float)):
            bucket["sum"] += float(item[value_field])
    return {"groups": [groups[key] for key in sorted(groups)], "group_count": len(groups)}


def monitoring(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("events", "rules"))
    if not isinstance(data["events"], list) or not isinstance(data["rules"], list):
        raise ValueError("events and rules must be lists")
    alerts = []
    for index, event in enumerate(data["events"]):
        text = " ".join(str(value) for value in event.values()).lower() if isinstance(event, dict) else str(event).lower()
        matched = sorted({str(rule).lower() for rule in data["rules"] if str(rule).lower() in text})
        if matched:
            alerts.append({"event_index": index, "matched_rules": matched, "event": event})
    return {"alerts": alerts, "alert_count": len(alerts)}


def lookup(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("records", "query"))
    if not isinstance(data["records"], list) or not isinstance(data["query"], str):
        raise ValueError("records must be a list and query must be text")
    query = data["query"].casefold()
    fields = data.get("fields") or []
    matches = []
    for index, record in enumerate(data["records"]):
        if not isinstance(record, dict):
            continue
        values = [record.get(field, "") for field in fields] if fields else record.values()
        haystack = " ".join(str(value) for value in values).casefold()
        if query in haystack:
            matches.append({"index": index, "record": record})
    return {"matches": matches, "match_count": len(matches)}


def triage(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("items", "priority_terms"))
    if not isinstance(data["items"], list) or not isinstance(data["priority_terms"], dict):
        raise ValueError("items must be a list and priority_terms must be an object")
    ranked = []
    for index, item in enumerate(data["items"]):
        text = " ".join(str(value) for value in item.values()).casefold() if isinstance(item, dict) else str(item).casefold()
        score = sum(float(weight) for term, weight in data["priority_terms"].items() if str(term).casefold() in text)
        ranked.append({"source_index": index, "priority_score": score, "item": item})
    ranked.sort(key=lambda row: (-row["priority_score"], row["source_index"]))
    return {"queue": ranked, "item_count": len(ranked)}


def handoff(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("items", "routing_rules"))
    if not isinstance(data["items"], list) or not isinstance(data["routing_rules"], list):
        raise ValueError("items and routing_rules must be lists")
    assignments, unrouted = [], []
    for index, item in enumerate(data["items"]):
        matched = None
        for rule in data["routing_rules"]:
            if not isinstance(rule, dict):
                continue
            field, equals = rule.get("field"), rule.get("equals")
            if isinstance(item, dict) and item.get(field) == equals:
                matched = rule.get("destination")
                break
        target = {"source_index": index, "item": item}
        if matched is None:
            unrouted.append(target)
        else:
            assignments.append({**target, "destination": matched})
    return {"assignments": assignments, "unrouted": unrouted}


def extraction(payload: Any) -> dict[str, Any]:
    return adapter(payload)


def policy(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("records", "rules"))
    if not isinstance(data["records"], list) or not isinstance(data["rules"], list):
        raise ValueError("records and rules must be lists")
    decisions = []
    for index, record in enumerate(data["records"]):
        failures = []
        for rule in data["rules"]:
            if isinstance(rule, dict) and isinstance(record, dict):
                field = rule.get("field")
                if "equals" in rule and record.get(field) != rule["equals"]:
                    failures.append(rule.get("id", field))
                if "required" in rule and rule["required"] and record.get(field) in (None, ""):
                    failures.append(rule.get("id", field))
        decisions.append({"source_index": index, "allow": not failures, "failed_rules": sorted(set(failures))})
    return {"decisions": decisions, "all_allowed": all(row["allow"] for row in decisions)}


def scheduling(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("tasks", "slots"))
    if not isinstance(data["tasks"], list) or not isinstance(data["slots"], list):
        raise ValueError("tasks and slots must be lists")
    assignments = [{"task": task, "slot": data["slots"][index]}
                   for index, task in enumerate(data["tasks"]) if index < len(data["slots"])]
    return {"assignments": assignments, "unscheduled": data["tasks"][len(assignments):]}


def sync(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("source", "target", "key"))
    if not isinstance(data["source"], list) or not isinstance(data["target"], list) or not isinstance(data["key"], str):
        raise ValueError("source/target must be lists and key must be text")
    key = data["key"]
    source = {row.get(key): row for row in data["source"] if isinstance(row, dict) and key in row}
    target = {row.get(key): row for row in data["target"] if isinstance(row, dict) and key in row}
    creates = [source[value] for value in sorted(set(source) - set(target), key=str)]
    updates = [{"before": target[value], "after": source[value]} for value in sorted(set(source) & set(target), key=str)
               if source[value] != target[value]]
    deletes = [target[value] for value in sorted(set(target) - set(source), key=str)]
    return {"creates": creates, "updates": updates, "deletes": deletes}


def workflow(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("steps", "triggers"))
    if not isinstance(data["steps"], list) or not isinstance(data["triggers"], list):
        raise ValueError("steps and triggers must be lists")
    ordered_steps = []
    seen = set()
    for index, step in enumerate(data["steps"]):
        if not isinstance(step, dict) or not step.get("id") or not step.get("action"):
            raise ValueError("every step requires id and action")
        if step["id"] in seen:
            raise ValueError("step ids must be unique")
        seen.add(step["id"])
        ordered_steps.append({"index": index, "id": step["id"], "action": step["action"], "after": step.get("after")})
    missing_dependencies = sorted({row["after"] for row in ordered_steps if row["after"] and row["after"] not in seen})
    return {"ordered_steps": ordered_steps, "triggers": data["triggers"], "missing_dependencies": missing_dependencies,
            "ready_for_domain_review": not missing_dependencies}


FUNCTION = __ARCHETYPE__


def run(payload: Any) -> dict[str, Any]:
    """Run the selected deterministic candidate operation."""
    return FUNCTION(payload)
'''


POSITIVE_FIXTURES: dict[str, dict[str, Any]] = {
    "adapter": {"records": [{"old": 1}], "field_map": {"old": "new"}},
    "reconciliation": {"left": [{"id": 1}, {"id": 2}], "right": [{"id": 2}, {"id": 3}], "key": "id"},
    "validation": {"records": [{"id": 1}, {"id": None}], "required_fields": ["id"]},
    "aggregation": {"items": [{"team": "a", "amount": 2}, {"team": "a", "amount": 3}], "group_by": "team", "value_field": "amount"},
    "monitoring": {"events": [{"message": "payment timeout"}, {"message": "ok"}], "rules": ["timeout"]},
    "lookup": {"records": [{"name": "Northwind"}, {"name": "Contoso"}], "query": "north"},
    "triage": {"items": [{"text": "urgent outage"}, {"text": "question"}], "priority_terms": {"urgent": 3, "outage": 2}},
    "handoff": {"items": [{"type": "billing"}], "routing_rules": [{"field": "type", "equals": "billing", "destination": "finance"}]},
    "extraction": {"records": [{"Invoice Number": "A1"}], "field_map": {"Invoice Number": "invoice_id"}},
    "policy": {"records": [{"status": "active"}], "rules": [{"id": "active", "field": "status", "equals": "active"}]},
    "scheduling": {"tasks": ["a", "b"], "slots": ["09:00", "10:00"]},
    "sync": {"source": [{"id": 1, "v": 2}], "target": [{"id": 1, "v": 1}, {"id": 2}], "key": "id"},
    "workflow": {"steps": [{"id": "download", "action": "download_report"}, {"id": "review", "action": "review_exceptions", "after": "download"}], "triggers": ["daily"]},
}


TEST_SOURCE = '''from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("candidate_primitive", ROOT / "src" / "primitive.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CandidateContractTest(unittest.TestCase):
    def test_positive_fixture_is_deterministic(self) -> None:
        payload = json.loads((ROOT / "fixtures" / "positive.json").read_text(encoding="utf-8"))
        first = MODULE.run(payload)
        second = MODULE.run(payload)
        self.assertIsInstance(first, dict)
        self.assertEqual(first, second)

    def test_negative_fixture_is_rejected(self) -> None:
        payload = json.loads((ROOT / "fixtures" / "negative.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            MODULE.run(payload)


if __name__ == "__main__":
    unittest.main()
'''


def _data_schema_uri(schema: dict[str, Any]) -> tuple[str, str]:
    payload = canonical_bytes(schema)
    return "data:application/schema+json," + quote(payload.decode("utf-8"), safe=""), digest_bytes(payload)


def project_ocg(draft: PrimitiveDraft, input_schema: dict[str, Any], output_schema: dict[str, Any], source_digest: str) -> dict[str, Any]:
    base = _slug(draft.draft_id).replace("_", "-")
    input_id = f"urn:aidevobserver:contract:{base}:input"
    output_id = f"urn:aidevobserver:contract:{base}:output"
    action_id = f"urn:aidevobserver:action:{base}"
    input_uri, input_digest = _data_schema_uri(input_schema)
    output_uri, output_digest = _data_schema_uri(output_schema)
    implementation_urn = "urn:aidevobserver:implementation:" + draft.implementation_id.replace(".", ":")
    return {
        "spec_version": "0.1.0-draft",
        "graph_id": f"urn:aidevobserver:graph:{base}",
        "title": draft.label,
        "description": "Candidate primitive derived from attributed business-friction evidence.",
        "status": "candidate",
        "profiles": ["core"],
        "created_at": _now(),
        "publisher": {"name": "AIDevObserver Capability Fabric"},
        "nodes": [
            {"id": draft.capability_id, "kind": "capability", "label": draft.label, "description": draft.problem_statement, "lifecycle": "candidate"},
            {"id": input_id, "kind": "contract", "label": draft.input_contract, "lifecycle": "candidate", "native_contract": {"dialect": JSON_SCHEMA_DIALECT, "digest": input_digest, "schema_uri": input_uri, "schema": input_schema, "media_type": "application/schema+json"}},
            {"id": output_id, "kind": "contract", "label": draft.output_contract, "lifecycle": "candidate", "native_contract": {"dialect": JSON_SCHEMA_DIALECT, "digest": output_digest, "schema_uri": output_uri, "schema": output_schema, "media_type": "application/schema+json"}},
            {
                "id": implementation_urn,
                "kind": "implementation",
                "label": draft.label + " Python candidate",
                "lifecycle": "candidate",
                "metadata": {"source_artifact_digest": source_digest},
            },
        ],
        "actions": [
            {
                "id": action_id,
                "label": draft.label,
                "capability_ref": draft.capability_id,
                "implementation_ref": implementation_urn,
                "ports": [
                    {"id": "input", "direction": "input", "contract_ref": input_id, "required": True, "protocol": {"mode": "sync"}},
                    {"id": "output", "direction": "output", "contract_ref": output_id, "required": True, "protocol": {"mode": "sync"}},
                ],
                "preconditions": [],
                "postconditions": [],
                "invariants": [],
                "effects": [{"kind": "custom", "target": "unverified_generated_candidate", "certainty": "unknown"}],
                "protocol": {"mode": "sync"},
                "retry": {"idempotency": "unknown", "automatic_retry": False, "maximum_attempts": 1},
                "transaction": {"mode": "unknown"},
                "lifecycle": "candidate",
            }
        ],
        "relations": [
            {
                "id": f"urn:aidevobserver:relation:{base}:implements",
                "kind": "implements",
                "source": {"subject_ref": implementation_urn},
                "target": {"subject_ref": draft.capability_id},
                "direction": "source_to_target",
                "status": "candidate",
            }
        ],
        "extensions": {
            "aidevobserver": {
                "cluster_id": draft.cluster_id,
                "evidence_digests": list(draft.evidence_digests),
                "source_artifact_digest": source_digest,
                "compatibility": "unknown",
                "execution_authorized": False,
                "candidate_only": True,
                "serves_truth": False,
            }
        },
    }


def scaffold_candidate(draft: PrimitiveDraft, candidates_root: Path) -> CandidateWorkspace:
    workspace = candidates_root / _slug(draft.draft_id)
    source = IMPLEMENTATION_SOURCE.replace("__ARCHETYPE__", draft.archetype).encode("utf-8")
    input_schema, output_schema = _schemas(draft)
    positive = POSITIVE_FIXTURES[draft.archetype]
    negative = {}
    source_evidence = {
        "cluster_id": draft.cluster_id,
        "source_refs": list(draft.source_refs),
        "evidence_digests": list(draft.evidence_digests),
        "source_classes": list(draft.source_classes),
        "problem_statement": draft.problem_statement,
        "interpretation_status": "candidate",
        "candidate_only": True,
        "serves_truth": False,
    }
    files: dict[str, bytes] = {
        "primitive.json": json.dumps(draft.to_dict(), indent=2, sort_keys=True).encode("utf-8") + b"\n",
        "source-evidence.json": json.dumps(source_evidence, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        "contracts/input.schema.json": json.dumps(input_schema, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        "contracts/output.schema.json": json.dumps(output_schema, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        "src/primitive.py": source,
        "tests/test_contract.py": TEST_SOURCE.encode("utf-8"),
        "fixtures/positive.json": json.dumps(positive, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        "fixtures/negative.json": json.dumps(negative, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        "README.md": (f"# {draft.label}\n\nCandidate only. Derived from `{draft.cluster_id}`. A fixture pass does not promote or authorize this primitive.\n").encode("utf-8"),
    }
    source_digest = digest_bytes(source)
    ocg = project_ocg(draft, input_schema, output_schema, source_digest)
    files["ocg.json"] = json.dumps(ocg, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    for relative, payload in files.items():
        _atomic_write(workspace / relative, payload)
    manifest = {
        "draft_id": draft.draft_id,
        "builder_id": BUILDER_ID,
        "builder_digest": digest_bytes(Path(__file__).read_bytes()),
        "created_at": _now(),
        "candidate_only": True,
        "serves_truth": False,
        "files": {
            relative: {"digest": digest_bytes(payload), "bytes": len(payload)}
            for relative, payload in sorted(files.items())
        },
    }
    manifest["manifest_digest"] = digest_json(manifest)
    _write_json(workspace / "manifest.json", manifest)
    return CandidateWorkspace(draft=draft, path=workspace, manifest=manifest, test_receipt=None)


def execute_candidate_tests(workspace: CandidateWorkspace, *, timeout: float = 20.0) -> CandidateWorkspace:
    started_at = _now()
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    try:
        completed = subprocess.run(
            command,
            cwd=workspace.path,
            check=False,
            capture_output=True,
            text=False,
            timeout=timeout,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "LANG": "C.UTF-8"},
        )
        result = "pass" if completed.returncode == 0 else "fail"
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        error = None
    except subprocess.TimeoutExpired as exc:
        result = "timeout"
        returncode = None
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        error = {"class": "TimeoutExpired", "timeout_seconds": timeout}
    receipt = {
        "receipt_id": "receipt.test." + _slug(workspace.draft.draft_id),
        "claim_type": "fixture_contract_test",
        "result": result,
        "returncode": returncode,
        "artifact_digest": workspace.manifest["files"]["src/primitive.py"]["digest"],
        "contract_digests": [
            workspace.manifest["files"]["contracts/input.schema.json"]["digest"],
            workspace.manifest["files"]["contracts/output.schema.json"]["digest"],
        ],
        "fixture_digests": [
            workspace.manifest["files"]["fixtures/positive.json"]["digest"],
            workspace.manifest["files"]["fixtures/negative.json"]["digest"],
        ],
        "test_digest": workspace.manifest["files"]["tests/test_contract.py"]["digest"],
        "environment": {"python": platform.python_version(), "implementation": platform.python_implementation(), "platform": platform.platform()},
        "environment_digest": digest_json({"python": platform.python_version(), "implementation": platform.python_implementation(), "platform": platform.platform()}),
        "command": command,
        "stdout_digest": digest_bytes(stdout),
        "stderr_digest": digest_bytes(stderr),
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "error": error,
        "started_at": started_at,
        "finished_at": _now(),
        "scope": "generated_positive_and_negative_fixtures_only",
        "candidate_only": True,
        "serves_truth": False,
        "promotion_decision": "none",
    }
    _write_json(workspace.path / "receipts" / "test.json", receipt)
    return CandidateWorkspace(draft=workspace.draft, path=workspace.path, manifest=workspace.manifest, test_receipt=receipt)


def build_candidate(
    draft: PrimitiveDraft,
    candidates_root: Path,
    *,
    execute_tests: bool = True,
    timeout: float = 20.0,
) -> CandidateWorkspace:
    workspace = scaffold_candidate(draft, candidates_root)
    if execute_tests:
        workspace = execute_candidate_tests(workspace, timeout=timeout)
    return workspace
