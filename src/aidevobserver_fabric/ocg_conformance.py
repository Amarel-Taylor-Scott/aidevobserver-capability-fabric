"""Conformance checks for the exploratory Open Capability Graph 0.1 draft.

The JSON Schema owns record shape.  This module owns cross-record invariants
that JSON Schema cannot express cleanly: reference integrity, action-port
direction, fail-closed compatibility, vector-space identity, and local digest
verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import base64
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import unquote, unquote_to_bytes, urlparse

import rfc8785


SPEC_VERSION = "0.1.0-draft"
DIGEST_RE = re.compile(r"^(sha256:[0-9a-fA-F]{64}|sha512:[0-9a-fA-F]{128})$")
TOP_LEVEL_COLLECTIONS = (
    "nodes",
    "actions",
    "relations",
    "adapters",
    "artifacts",
    "evidence",
    "representations",
    "search_profiles",
)
UNSAFE_ADMIT_RELATIONSHIPS = {
    "related",
    "unknown",
    "incompatible",
}
VECTOR_ENCODINGS = {
    "sparse_vector",
    "dense_vector",
    "multivector",
    "binary_vector",
}
CLAIM_BASE = "https://github.com/Amarel-Taylor-Scott/aidevobserver-capability-fabric/tree/main/spec/open-capability-graph/v0.1/claims/"
CLAIM_CONTRACT_IDENTITY = CLAIM_BASE + "contract-identity"
CLAIM_ACTION_CONFORMANCE = CLAIM_BASE + "action-contract-conformance"
CLAIM_ADAPTER_CONFORMANCE = CLAIM_BASE + "adapter-conformance"


@dataclass
class ConformanceResult:
    """Machine-readable validation result."""

    errors: list[str] = field(default_factory=list)
    eligibility_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    validated_profiles: list[str] = field(default_factory=list)
    schema_validation: str = "not_requested"
    evaluated_at: str | None = None
    eligibility_evaluated: bool = False

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def currently_eligible(self) -> bool | None:
        if not self.eligibility_evaluated:
            return None
        return self.valid and not self.eligibility_errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "currently_eligible": self.currently_eligible,
            "eligibility_evaluated": self.eligibility_evaluated,
            "errors": self.errors,
            "eligibility_errors": self.eligibility_errors,
            "warnings": self.warnings,
            "counts": self.counts,
            "validated_profiles": self.validated_profiles,
            "schema_validation": self.schema_validation,
            "evaluated_at": self.evaluated_at,
        }


def _digest_file(path: Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _local_path(uri: str, base_path: Path) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme:
        return None
    root = base_path.resolve()
    path = (root / unquote(parsed.path)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"local URI escapes document root: {uri}") from exc
    return path


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant {value!r}")


def _verify_digest(path: Path, digest: str) -> bool:
    algorithm, expected = digest.split(":", 1)
    return _digest_file(path, algorithm).lower() == expected.lower()


def _verify_payload(payload: bytes, digest: str) -> bool:
    algorithm, expected = digest.split(":", 1)
    return hashlib.new(algorithm, payload).hexdigest().lower() == expected.lower()


def _data_uri_payload(uri: str) -> bytes:
    if not uri.startswith("data:") or "," not in uri:
        raise ValueError("not a data URI")
    header, encoded = uri[5:].split(",", 1)
    if header.lower().endswith(";base64"):
        try:
            return base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError(f"invalid base64 payload: {exc}") from exc
    return unquote_to_bytes(encoded)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def record_digest(record: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(record)).hexdigest()


def _record_index(document: Mapping[str, Any], result: ConformanceResult) -> dict[str, tuple[str, Mapping[str, Any]]]:
    records: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for collection in TOP_LEVEL_COLLECTIONS:
        rows = document.get(collection, [])
        if not isinstance(rows, list):
            result.errors.append(f"{collection}: must be an array")
            continue
        result.counts[collection] = len(rows)
        for position, row in enumerate(rows):
            if not isinstance(row, Mapping):
                result.errors.append(f"{collection}[{position}]: must be an object")
                continue
            record_id = row.get("id")
            if not isinstance(record_id, str) or not record_id:
                result.errors.append(f"{collection}[{position}]: missing non-empty id")
                continue
            if record_id in records:
                prior = records[record_id][0]
                result.errors.append(f"{collection}[{position}]: duplicate id {record_id!r} (already in {prior})")
            else:
                records[record_id] = (collection, row)
    result.counts["records"] = len(records)
    return records


def _require_ref(
    reference: Any,
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    result: ConformanceResult,
    location: str,
    collection: str | None = None,
    node_kind: str | None = None,
) -> Mapping[str, Any] | None:
    if not isinstance(reference, str) or not reference:
        result.errors.append(f"{location}: missing reference")
        return None
    found = records.get(reference)
    if found is None:
        result.errors.append(f"{location}: unknown reference {reference!r}")
        return None
    found_collection, record = found
    if collection is not None and found_collection != collection:
        result.errors.append(
            f"{location}: {reference!r} is in {found_collection}, expected {collection}"
        )
    if node_kind is not None and (found_collection != "nodes" or record.get("kind") != node_kind):
        actual = record.get("kind") if found_collection == "nodes" else found_collection
        result.errors.append(f"{location}: {reference!r} is {actual!r}, expected node kind {node_kind!r}")
    return record


def _check_reference_list(
    owner_id: str,
    field_name: str,
    references: Any,
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    result: ConformanceResult,
    *,
    collection: str | None = None,
    node_kind: str | None = None,
) -> None:
    if references is None:
        return
    if not isinstance(references, list):
        result.errors.append(f"{owner_id}.{field_name}: must be an array")
        return
    for index, reference in enumerate(references):
        _require_ref(
            reference,
            records,
            result,
            f"{owner_id}.{field_name}[{index}]",
            collection=collection,
            node_kind=node_kind,
        )


def _contract_digest(node: Mapping[str, Any] | None) -> str | None:
    if node is None:
        return None
    native = node.get("native_contract")
    if isinstance(native, Mapping) and isinstance(native.get("digest"), str):
        return native["digest"]
    return None


def _check_document_shape(document: Mapping[str, Any], result: ConformanceResult) -> None:
    required = {"spec_version", "graph_id", "status", "profiles", "nodes", "actions", "relations"}
    for field_name in sorted(required - set(document)):
        result.errors.append(f"document: missing required field {field_name!r}")
    if document.get("spec_version") != SPEC_VERSION:
        result.errors.append(
            f"document.spec_version: expected {SPEC_VERSION!r}, got {document.get('spec_version')!r}"
        )
    profiles = document.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        result.errors.append("document.profiles: must be a non-empty array")
    elif "core" not in profiles:
        result.errors.append("document.profiles: core profile is required")


def _check_nodes(
    document: Mapping[str, Any],
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    result: ConformanceResult,
    base_path: Path | None,
) -> set[str]:
    known_digests: set[str] = set()
    for node in document.get("nodes", []):
        if not isinstance(node, Mapping) or not isinstance(node.get("id"), str):
            continue
        node_id = node["id"]
        if node.get("kind") == "contract":
            native = node.get("native_contract")
            if not isinstance(native, Mapping):
                result.errors.append(f"{node_id}: contract node requires native_contract")
                continue
            digest = native.get("digest")
            if not isinstance(digest, str) or not DIGEST_RE.match(digest):
                result.errors.append(f"{node_id}.native_contract.digest: invalid digest")
            else:
                known_digests.add(digest.lower())
            schema_uri = native.get("schema_uri")
            _check_reference_list(
                node_id,
                "native_contract.source_artifact_refs",
                native.get("source_artifact_refs"),
                records,
                result,
                collection="artifacts",
            )
            if native.get("normalizer_artifact_ref") is not None:
                _require_ref(
                    native.get("normalizer_artifact_ref"),
                    records,
                    result,
                    f"{node_id}.native_contract.normalizer_artifact_ref",
                    collection="artifacts",
                )
            if not isinstance(schema_uri, str):
                result.errors.append(f"{node_id}.native_contract.schema_uri: required in v0.1")
            elif schema_uri.startswith("data:"):
                try:
                    payload = _data_uri_payload(schema_uri)
                except ValueError as exc:
                    result.errors.append(f"{node_id}.native_contract.schema_uri: {exc}")
                else:
                    if isinstance(digest, str) and DIGEST_RE.match(digest) and not _verify_payload(payload, digest):
                        result.errors.append(
                            f"{node_id}.native_contract.digest: does not match data URI bytes"
                        )
                    if "schema" in native:
                        try:
                            referenced_schema = json.loads(
                                payload.decode("utf-8"),
                                parse_constant=_reject_json_constant,
                            )
                        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                            result.errors.append(
                                f"{node_id}.native_contract.schema: cannot compare inline mirror with data URI: {exc}"
                            )
                        else:
                            if native["schema"] != referenced_schema:
                                result.errors.append(
                                    f"{node_id}.native_contract.schema: inline mirror differs from data URI content"
                                )
            elif base_path is not None:
                try:
                    path = _local_path(schema_uri, base_path)
                except ValueError as exc:
                    result.errors.append(f"{node_id}.native_contract.schema_uri: {exc}")
                    path = None
                if path is not None:
                    if not path.is_file():
                        result.errors.append(f"{node_id}.native_contract.schema_uri: missing local file {path}")
                    elif isinstance(digest, str) and DIGEST_RE.match(digest) and not _verify_digest(path, digest):
                        result.errors.append(f"{node_id}.native_contract.digest: does not match {path}")
                    elif "schema" in native:
                        try:
                            referenced_schema = json.loads(
                                path.read_text(encoding="utf-8"),
                                parse_constant=_reject_json_constant,
                            )
                        except (OSError, ValueError, json.JSONDecodeError) as exc:
                            result.errors.append(
                                f"{node_id}.native_contract.schema: cannot compare inline mirror with {path}: {exc}"
                            )
                        else:
                            if native["schema"] != referenced_schema:
                                result.errors.append(
                                    f"{node_id}.native_contract.schema: inline mirror differs from schema_uri content"
                                )
        digest = node.get("digest")
        if isinstance(digest, str):
            if DIGEST_RE.match(digest):
                known_digests.add(digest.lower())
            else:
                result.errors.append(f"{node_id}.digest: invalid digest")
        # Ontology references are intentionally allowed to identify records in
        # external registries. They are not closed-bundle references.
    return known_digests


def _action_port_index(action: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        port["id"]: port
        for port in action.get("ports", [])
        if isinstance(port, Mapping) and isinstance(port.get("id"), str)
    }


def _check_actions(
    document: Mapping[str, Any],
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    result: ConformanceResult,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    ports: dict[tuple[str, str], Mapping[str, Any]] = {}
    for action in document.get("actions", []):
        if not isinstance(action, Mapping) or not isinstance(action.get("id"), str):
            continue
        action_id = action["id"]
        _require_ref(action.get("capability_ref"), records, result, f"{action_id}.capability_ref", node_kind="capability")
        _require_ref(
            action.get("implementation_ref"),
            records,
            result,
            f"{action_id}.implementation_ref",
            node_kind="implementation",
        )
        action_ports = action.get("ports")
        if not isinstance(action_ports, list):
            result.errors.append(f"{action_id}.ports: must be an array")
            continue
        directions: list[str] = []
        seen: set[str] = set()
        for index, port in enumerate(action_ports):
            if not isinstance(port, Mapping):
                result.errors.append(f"{action_id}.ports[{index}]: must be an object")
                continue
            port_id = port.get("id")
            if not isinstance(port_id, str) or not port_id:
                result.errors.append(f"{action_id}.ports[{index}]: missing id")
                continue
            if port_id in seen:
                result.errors.append(f"{action_id}.ports: duplicate port id {port_id!r}")
            seen.add(port_id)
            ports[(action_id, port_id)] = port
            direction = port.get("direction")
            if isinstance(direction, str):
                directions.append(direction)
            _require_ref(
                port.get("contract_ref"),
                records,
                result,
                f"{action_id}.ports[{port_id}].contract_ref",
                node_kind="contract",
            )
        if "input" not in directions:
            result.errors.append(f"{action_id}.ports: action needs at least one input port")
        if "output" not in directions:
            result.errors.append(f"{action_id}.ports: action needs at least one output port")
        _check_reference_list(action_id, "artifact_refs", action.get("artifact_refs"), records, result, collection="artifacts")
        _check_reference_list(action_id, "evidence_refs", action.get("evidence_refs"), records, result, collection="evidence")
        _check_reference_list(action_id, "environment_refs", action.get("environment_refs"), records, result, node_kind="environment")
        _check_reference_list(action_id, "policy_refs", action.get("policy_refs"), records, result, node_kind="policy")
    return ports


def _check_endpoint(
    endpoint: Any,
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    ports: Mapping[tuple[str, str], Mapping[str, Any]],
    result: ConformanceResult,
    location: str,
) -> Mapping[str, Any] | None:
    if not isinstance(endpoint, Mapping):
        result.errors.append(f"{location}: endpoint must be an object")
        return None
    subject_ref = endpoint.get("subject_ref")
    subject = _require_ref(subject_ref, records, result, f"{location}.subject_ref")
    port_id = endpoint.get("port_id")
    if port_id is not None:
        key = (subject_ref, port_id)
        if key not in ports:
            result.errors.append(f"{location}.port_id: unknown action port {subject_ref!r}.{port_id!r}")
            return None
        return ports[key]
    return subject


def _pass_evidence(
    references: Any,
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    *,
    subject_ref: str | None = None,
    as_of: datetime | None = None,
    accepted_claim_types: set[str] | None = None,
) -> bool:
    if not isinstance(references, list):
        return False
    for reference in references:
        if reference not in records or records[reference][0] != "evidence":
            continue
        evidence = records[reference][1]
        if evidence.get("result") != "pass":
            continue
        if accepted_claim_types is not None and evidence.get("claim_type") not in accepted_claim_types:
            continue
        if subject_ref is not None and not _evidence_binds_subject(evidence, subject_ref, records):
            continue
        if as_of is not None and not _evidence_current(evidence, as_of):
            continue
        return True
    return False


def _evidence_binds_subject(
    evidence: Mapping[str, Any],
    subject_ref: str,
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
) -> bool:
    if subject_ref not in evidence.get("subject_refs", []):
        return False
    found = records.get(subject_ref)
    if found is None:
        return False
    try:
        expected_digest = record_digest(found[1])
    except ValueError:
        return False
    return any(
        isinstance(binding, Mapping)
        and binding.get("subject_ref") == subject_ref
        and binding.get("canonicalization") == "rfc8785"
        and binding.get("digest") == expected_digest
        for binding in evidence.get("subject_digests", [])
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _evidence_current(evidence: Mapping[str, Any], as_of: datetime) -> bool:
    if evidence.get("revocation_ref") is not None:
        return False
    observed = _parse_datetime(evidence.get("observed_at"))
    if observed is None or observed > as_of:
        return False
    expiry = _parse_datetime(evidence.get("expires_at"))
    return expiry is None or expiry > as_of


def _relation_current(relation: Mapping[str, Any], as_of: datetime) -> bool:
    valid_from = _parse_datetime(relation.get("valid_from"))
    valid_until = _parse_datetime(relation.get("valid_until"))
    if valid_from is not None and as_of < valid_from:
        return False
    if valid_until is not None and as_of >= valid_until:
        return False
    return relation.get("status") not in {"rejected", "revoked", "deprecated"}


def _check_action_subject_current(
    relation_id: str,
    role: str,
    action_ref: Any,
    port_id: Any,
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    result: ConformanceResult,
    evidence_refs: Any = None,
    as_of: datetime | None = None,
    *,
    accepted_claim_types: set[str],
) -> None:
    found = records.get(action_ref)
    if found is None or found[0] != "actions":
        return
    action = found[1]
    evidence_subjects: list[tuple[str, Any]] = [(f"{role} action", action_ref)]
    if action.get("lifecycle") not in {"active", "verified"}:
        result.eligibility_errors.append(f"{relation_id}: {role} action is not currently active or verified")
    implementation = records.get(action.get("implementation_ref"))
    evidence_subjects.append((f"{role} implementation", action.get("implementation_ref")))
    if implementation is None or implementation[1].get("lifecycle") not in {"active", "verified"}:
        result.eligibility_errors.append(f"{relation_id}: {role} implementation is not currently active or verified")
    for artifact_ref in _as_list(action.get("artifact_refs")):
        evidence_subjects.append((f"{role} artifact", artifact_ref))
        artifact = records.get(artifact_ref)
        if artifact is None or artifact[1].get("lifecycle") not in {"active", "verified"}:
            result.eligibility_errors.append(f"{relation_id}: {role} artifact {artifact_ref!r} is not currently active or verified")
    for field_name in ("preconditions", "postconditions", "invariants", "effects"):
        declarations = action.get(field_name)
        if not isinstance(declarations, list):
            result.errors.append(
                f"{relation_id}: {role} action must explicitly declare {field_name} for v0.1 eligibility"
            )
        elif declarations:
            result.errors.append(
                f"{relation_id}: v0.1 cannot mark action-level {field_name} eligible; use requires_review"
            )
    if evidence_refs is not None:
        for subject_label, subject_ref in evidence_subjects:
            if not _pass_evidence(
                evidence_refs,
                records,
                subject_ref=subject_ref,
                accepted_claim_types=accepted_claim_types,
            ):
                result.errors.append(
                    f"{relation_id}: eligibility evidence must bind the exact {subject_label} record"
                )
            elif as_of is not None and not _pass_evidence(
                evidence_refs,
                records,
                subject_ref=subject_ref,
                as_of=as_of,
                accepted_claim_types=accepted_claim_types,
            ):
                result.eligibility_errors.append(f"{relation_id}: {subject_label} evidence is not current")
    if port_id is not None:
        port = _action_port_index(action).get(port_id)
        contract = records.get(port.get("contract_ref")) if isinstance(port, Mapping) else None
        if contract is None or contract[1].get("lifecycle") not in {"active", "verified"}:
            result.eligibility_errors.append(f"{relation_id}: {role} contract is not currently active or verified")


def _check_join_subjects_current(
    relation_id: str,
    source_endpoint: Mapping[str, Any],
    target_endpoint: Mapping[str, Any],
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    result: ConformanceResult,
    evidence_refs: Any,
    as_of: datetime,
) -> None:
    for role, endpoint in (("source", source_endpoint), ("target", target_endpoint)):
        _check_action_subject_current(
            relation_id,
            role,
            endpoint.get("subject_ref"),
            endpoint.get("port_id"),
            records,
            result,
            evidence_refs,
            as_of,
            accepted_claim_types={CLAIM_ACTION_CONFORMANCE},
        )


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _check_measure(measure: Mapping[str, Any], result: ConformanceResult, location: str) -> None:
    metric = measure.get("metric")
    if not isinstance(metric, str) or ":" not in metric:
        result.errors.append(f"{location}.metric: use a stable URI or namespaced identifier")
    value = measure.get("value")
    if isinstance(value, float) and not math.isfinite(value):
        result.errors.append(f"{location}.value: must be finite")
    if measure.get("provenance") == "measured":
        if not measure.get("evidence_refs") or not measure.get("observed_at") or not measure.get("procedure_ref"):
            result.errors.append(f"{location}: measured values require evidence_refs, observed_at, and procedure_ref")


def _port_flow_semantics(port: Mapping[str, Any], constraint_field: str) -> tuple[Any, ...]:
    concepts = port.get("semantic_concepts", [])
    constraints = port.get(constraint_field, [])
    return (
        port.get("contract_ref"),
        port.get("required"),
        _canonical(port.get("cardinality", {})),
        _canonical(port.get("protocol", {})),
        tuple(sorted(concepts)) if isinstance(concepts, list) else _canonical(concepts),
        port.get("unit"),
        tuple(sorted(_canonical(item) for item in constraints)) if isinstance(constraints, list) else _canonical(constraints),
    )


def _check_relations(
    document: Mapping[str, Any],
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    ports: Mapping[tuple[str, str], Mapping[str, Any]],
    result: ConformanceResult,
    as_of: datetime,
) -> None:
    eligible_pairs = {
        (
            relation.get("source", {}).get("subject_ref"),
            relation.get("source", {}).get("port_id"),
            relation.get("target", {}).get("subject_ref"),
            relation.get("target", {}).get("port_id"),
        )
        for relation in document.get("relations", [])
        if isinstance(relation, Mapping)
        and relation.get("kind") == "compatibility"
        and relation.get("status") == "verified"
        and isinstance(relation.get("source"), Mapping)
        and isinstance(relation.get("target"), Mapping)
        and isinstance(relation.get("compatibility"), Mapping)
        and relation.get("compatibility", {}).get("join_decision") in {"eligible_direct", "requires_adapter"}
    }
    for relation in document.get("relations", []):
        if not isinstance(relation, Mapping) or not isinstance(relation.get("id"), str):
            continue
        relation_id = relation["id"]
        source = _check_endpoint(relation.get("source"), records, ports, result, f"{relation_id}.source")
        target = _check_endpoint(relation.get("target"), records, ports, result, f"{relation_id}.target")
        _check_reference_list(relation_id, "evidence_refs", relation.get("evidence_refs"), records, result, collection="evidence")
        _check_reference_list(relation_id, "counterexample_refs", relation.get("counterexample_refs"), records, result)
        relation_measures = relation.get("measures") if isinstance(relation.get("measures"), list) else []
        for measure_index, measure in enumerate(relation_measures):
            if isinstance(measure, Mapping):
                _check_measure(measure, result, f"{relation_id}.measures[{measure_index}]")
                _check_reference_list(
                    relation_id,
                    f"measures[{measure_index}].evidence_refs",
                    measure.get("evidence_refs"),
                    records,
                    result,
                    collection="evidence",
                )
        relation_kind = relation.get("kind")
        source_endpoint = relation.get("source") if isinstance(relation.get("source"), Mapping) else {}
        target_endpoint = relation.get("target") if isinstance(relation.get("target"), Mapping) else {}
        if relation_kind == "implements":
            source_ref = source_endpoint.get("subject_ref")
            target_ref = target_endpoint.get("subject_ref")
            _require_ref(source_ref, records, result, f"{relation_id}.source", node_kind="implementation")
            _require_ref(target_ref, records, result, f"{relation_id}.target", node_kind="capability")
            if relation.get("direction") != "source_to_target":
                result.errors.append(f"{relation_id}: implements must be source_to_target")
        elif relation_kind == "flow":
            if not (isinstance(source, Mapping) and source.get("direction") == "output"):
                result.errors.append(f"{relation_id}: flow source must be an output port")
            if not (isinstance(target, Mapping) and target.get("direction") == "input"):
                result.errors.append(f"{relation_id}: flow target must be an input port")
            if relation.get("direction") != "source_to_target":
                result.errors.append(f"{relation_id}: flow must be source_to_target")
            pair = (
                source_endpoint.get("subject_ref"),
                source_endpoint.get("port_id"),
                target_endpoint.get("subject_ref"),
                target_endpoint.get("port_id"),
            )
            if relation.get("status") == "verified" and pair not in eligible_pairs:
                result.errors.append(f"{relation_id}: verified flow requires a matching verified compatibility relation")
        elif relation_kind == "adapter":
            source_ref = source_endpoint.get("subject_ref")
            target_ref = target_endpoint.get("subject_ref")
            _require_ref(source_ref, records, result, f"{relation_id}.source", node_kind="contract")
            _require_ref(target_ref, records, result, f"{relation_id}.target", node_kind="contract")
            adapter = _require_ref(
                relation.get("adapter_ref"),
                records,
                result,
                f"{relation_id}.adapter_ref",
                collection="adapters",
            )
            if isinstance(adapter, Mapping):
                if adapter.get("source_contract_ref") != source_ref or adapter.get("target_contract_ref") != target_ref:
                    result.errors.append(f"{relation_id}: adapter_ref contracts do not match relation endpoints")
            if relation.get("direction") != "source_to_target":
                result.errors.append(f"{relation_id}: adapter relation must be source_to_target")
        elif relation_kind == "evidence_for":
            source_ref = source_endpoint.get("subject_ref")
            _require_ref(source_ref, records, result, f"{relation_id}.source", collection="evidence")
        elif relation_kind == "embedding_transform":
            source_ref = source_endpoint.get("subject_ref")
            target_ref = target_endpoint.get("subject_ref")
            _require_ref(source_ref, records, result, f"{relation_id}.source", collection="representations")
            _require_ref(target_ref, records, result, f"{relation_id}.target", collection="representations")
            _require_ref(relation.get("transform_ref"), records, result, f"{relation_id}.transform_ref")
            if not _pass_evidence(relation.get("evidence_refs"), records, subject_ref=relation_id):
                result.errors.append(f"{relation_id}: embedding_transform requires digest-bound passing evidence")
        if relation_kind != "compatibility":
            continue
        if relation.get("direction") != "source_to_target":
            result.errors.append(f"{relation_id}: compatibility must be source_to_target")
        compatibility = relation.get("compatibility")
        if not isinstance(compatibility, Mapping):
            result.errors.append(f"{relation_id}: compatibility relation requires compatibility object")
            continue
        if not (isinstance(source, Mapping) and source.get("direction") == "output"):
            result.errors.append(f"{relation_id}: compatibility source must be an output port")
        if not (isinstance(target, Mapping) and target.get("direction") == "input"):
            result.errors.append(f"{relation_id}: compatibility target must be an input port")
        relationship = compatibility.get("relationship")
        mechanism = compatibility.get("mechanism")
        lossiness = compatibility.get("lossiness")
        assurance = compatibility.get("assurance", [])
        decision = compatibility.get("join_decision")
        eligibility_decision = decision in {"eligible_direct", "requires_adapter"}
        if eligibility_decision:
            relation_claims = (
                {CLAIM_CONTRACT_IDENTITY}
                if decision == "eligible_direct"
                else {CLAIM_ADAPTER_CONFORMANCE}
            )
            if relation.get("status") != "verified":
                result.errors.append(f"{relation_id}: {decision} compatibility must be verified")
            if relation.get("condition_refs") or compatibility.get("condition_refs"):
                result.errors.append(
                    f"{relation_id}: v0.1 cannot mark conditional compatibility eligible; use requires_review"
                )
            if not _pass_evidence(
                relation.get("evidence_refs"),
                records,
                subject_ref=relation_id,
                accepted_claim_types=relation_claims,
            ):
                result.errors.append(
                    f"{relation_id}: {decision} compatibility requires digest-bound passing evidence scoped to the relation"
                )
            elif not _pass_evidence(
                relation.get("evidence_refs"),
                records,
                subject_ref=relation_id,
                as_of=as_of,
                accepted_claim_types=relation_claims,
            ):
                result.eligibility_errors.append(
                    f"{relation_id}: eligibility evidence is expired or revoked or not yet observed"
                )
            if not _relation_current(relation, as_of):
                result.eligibility_errors.append(f"{relation_id}: relation is not currently valid")
            _check_join_subjects_current(
                relation_id,
                source_endpoint,
                target_endpoint,
                records,
                result,
                relation.get("evidence_refs"),
                as_of,
            )
            for field_name in ("source_contract_digest", "target_contract_digest", "checker_ref", "checker_digest"):
                if not compatibility.get(field_name):
                    result.errors.append(f"{relation_id}: {decision} compatibility requires {field_name}")
            checker = _require_ref(
                compatibility.get("checker_ref"),
                records,
                result,
                f"{relation_id}.compatibility.checker_ref",
                collection="artifacts",
            )
            if checker is not None:
                if compatibility.get("checker_digest") != checker.get("digest"):
                    result.errors.append(
                        f"{relation_id}: checker_digest does not match checker artifact digest"
                    )
                if checker.get("lifecycle") not in {"active", "verified"}:
                    result.errors.append(
                        f"{relation_id}: checker artifact is not active or verified"
                    )
        if decision == "eligible_direct":
            if relationship in UNSAFE_ADMIT_RELATIONSHIPS:
                result.errors.append(f"{relation_id}: relationship {relationship!r} cannot be eligible_direct")
            if mechanism != "direct":
                result.errors.append(f"{relation_id}: eligible_direct requires mechanism 'direct'")
            if lossiness != "none":
                result.errors.append(f"{relation_id}: eligible_direct requires lossiness 'none'")
            if "deterministically_checked" not in assurance and "formally_verified" not in assurance:
                result.errors.append(f"{relation_id}: eligible_direct requires deterministic or formal assurance")
        if relationship == "transformable" and mechanism != "adapter":
            result.errors.append(f"{relation_id}: transformable relationship requires adapter mechanism")
        if mechanism == "direct" and lossiness != "none":
            result.errors.append(f"{relation_id}: direct mechanism requires lossiness 'none'")
        if mechanism == "adapter" and decision != "requires_adapter":
            result.errors.append(f"{relation_id}: adapter mechanism requires join_decision 'requires_adapter'")
        if decision == "requires_adapter" and lossiness != "total_lossless":
            result.errors.append(
                f"{relation_id}: v0.1 requires_adapter is limited to total_lossless adapters; use requires_review"
            )
        source_contract = None
        target_contract = None
        if isinstance(source, Mapping):
            source_contract = _require_ref(
                source.get("contract_ref"), records, result, f"{relation_id}.source.contract_ref", node_kind="contract"
            )
        if isinstance(target, Mapping):
            target_contract = _require_ref(
                target.get("contract_ref"), records, result, f"{relation_id}.target.contract_ref", node_kind="contract"
            )
        actual_source_digest = _contract_digest(source_contract)
        actual_target_digest = _contract_digest(target_contract)
        claimed_source_digest = compatibility.get("source_contract_digest")
        claimed_target_digest = compatibility.get("target_contract_digest")
        if claimed_source_digest is not None and claimed_source_digest != actual_source_digest:
            result.errors.append(f"{relation_id}: source_contract_digest does not match source port contract")
        if claimed_target_digest is not None and claimed_target_digest != actual_target_digest:
            result.errors.append(f"{relation_id}: target_contract_digest does not match target port contract")
        if relationship == "identical" and actual_source_digest != actual_target_digest:
            result.errors.append(f"{relation_id}: identical relationship requires equal contract digests")
        if relationship == "identical" and isinstance(source, Mapping) and isinstance(target, Mapping):
            producer_semantics = _port_flow_semantics(source, "guarantees")
            consumer_semantics = _port_flow_semantics(target, "requirements")
            if producer_semantics != consumer_semantics:
                result.errors.append(
                    f"{relation_id}: identical relationship requires equal effective port semantics"
                )
        adapter_ref = compatibility.get("adapter_ref")
        if mechanism == "adapter" and adapter_ref is None:
            result.errors.append(f"{relation_id}: adapter mechanism requires adapter_ref")
        if decision == "requires_adapter" and mechanism != "adapter":
            result.errors.append(f"{relation_id}: requires_adapter decision requires adapter mechanism")
        if adapter_ref is not None:
            adapter = _require_ref(
                adapter_ref,
                records,
                result,
                f"{relation_id}.compatibility.adapter_ref",
                collection="adapters",
            )
            if mechanism == "adapter" and isinstance(adapter, Mapping):
                if adapter.get("lifecycle") != "verified":
                    result.errors.append(f"{relation_id}: adapter mechanism must reference a verified adapter")
                if isinstance(source, Mapping) and adapter.get("source_contract_ref") != source.get("contract_ref"):
                    result.errors.append(f"{relation_id}: adapter source contract does not match relation source")
                if isinstance(target, Mapping) and adapter.get("target_contract_ref") != target.get("contract_ref"):
                    result.errors.append(f"{relation_id}: adapter target contract does not match relation target")
                if adapter.get("classification") != lossiness:
                    result.errors.append(f"{relation_id}: compatibility lossiness does not match adapter classification")
                if eligibility_decision and adapter.get("guard_refs"):
                    result.errors.append(
                        f"{relation_id}: v0.1 cannot mark guarded adapter compatibility eligible; use requires_review"
                    )
                if eligibility_decision:
                    _check_action_subject_current(
                        relation_id,
                        "adapter",
                        adapter.get("action_ref"),
                        None,
                        records,
                        result,
                        relation.get("evidence_refs"),
                        as_of,
                        accepted_claim_types={CLAIM_ADAPTER_CONFORMANCE},
                    )


def _check_adapters(
    document: Mapping[str, Any],
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    result: ConformanceResult,
    as_of: datetime,
) -> None:
    for adapter in document.get("adapters", []):
        if not isinstance(adapter, Mapping) or not isinstance(adapter.get("id"), str):
            continue
        adapter_id = adapter["id"]
        source_ref = adapter.get("source_contract_ref")
        target_ref = adapter.get("target_contract_ref")
        _require_ref(source_ref, records, result, f"{adapter_id}.source_contract_ref", node_kind="contract")
        _require_ref(target_ref, records, result, f"{adapter_id}.target_contract_ref", node_kind="contract")
        action = None
        if adapter.get("action_ref") is not None:
            action = _require_ref(adapter.get("action_ref"), records, result, f"{adapter_id}.action_ref", collection="actions")
        _check_reference_list(adapter_id, "evidence_refs", adapter.get("evidence_refs"), records, result, collection="evidence")
        if adapter.get("lifecycle") == "verified":
            if action is None:
                result.errors.append(f"{adapter_id}: verified adapter requires action_ref")
            if not _pass_evidence(
                adapter.get("evidence_refs"),
                records,
                subject_ref=adapter_id,
                accepted_claim_types={CLAIM_ADAPTER_CONFORMANCE},
            ):
                result.errors.append(
                    f"{adapter_id}: verified adapter requires digest-bound passing evidence scoped to the adapter"
                )
            elif not _pass_evidence(
                adapter.get("evidence_refs"),
                records,
                subject_ref=adapter_id,
                as_of=as_of,
                accepted_claim_types={CLAIM_ADAPTER_CONFORMANCE},
            ):
                result.eligibility_errors.append(f"{adapter_id}: adapter evidence is expired or revoked")
            action_ref = adapter.get("action_ref")
            if isinstance(action_ref, str) and not _pass_evidence(
                adapter.get("evidence_refs"),
                records,
                subject_ref=action_ref,
                accepted_claim_types={CLAIM_ADAPTER_CONFORMANCE},
            ):
                result.errors.append(f"{adapter_id}: verified adapter evidence must bind the exact action record")
            elif isinstance(action_ref, str) and not _pass_evidence(
                adapter.get("evidence_refs"),
                records,
                subject_ref=action_ref,
                as_of=as_of,
                accepted_claim_types={CLAIM_ADAPTER_CONFORMANCE},
            ):
                result.eligibility_errors.append(f"{adapter_id}: adapter action evidence is not current")
            if isinstance(action_ref, str):
                _check_action_subject_current(
                    adapter_id,
                    "adapter",
                    action_ref,
                    None,
                    records,
                    result,
                    adapter.get("evidence_refs"),
                    as_of,
                    accepted_claim_types={CLAIM_ADAPTER_CONFORMANCE},
                )
        if isinstance(action, Mapping):
            input_contracts = {
                port.get("contract_ref")
                for port in action.get("ports", [])
                if isinstance(port, Mapping) and port.get("direction") == "input"
            }
            output_contracts = {
                port.get("contract_ref")
                for port in action.get("ports", [])
                if isinstance(port, Mapping) and port.get("direction") == "output"
            }
            if source_ref not in input_contracts:
                result.errors.append(f"{adapter_id}: action_ref has no input using source contract")
            if target_ref not in output_contracts:
                result.errors.append(f"{adapter_id}: action_ref has no output using target contract")


def _check_artifacts(
    document: Mapping[str, Any],
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    result: ConformanceResult,
    base_path: Path | None,
    known_digests: set[str],
) -> None:
    subject_digests: dict[str, set[str]] = {}
    for artifact in document.get("artifacts", []):
        if not isinstance(artifact, Mapping) or not isinstance(artifact.get("id"), str):
            continue
        artifact_id = artifact["id"]
        digest = artifact.get("digest")
        if not isinstance(digest, str) or not DIGEST_RE.match(digest):
            result.errors.append(f"{artifact_id}.digest: invalid digest")
        else:
            known_digests.add(digest.lower())
            for subject_ref in artifact.get("subject_refs", []):
                if isinstance(subject_ref, str):
                    subject_digests.setdefault(subject_ref, set()).add(digest.lower())
        _check_reference_list(artifact_id, "subject_refs", artifact.get("subject_refs"), records, result)
        _check_reference_list(artifact_id, "provenance_refs", artifact.get("provenance_refs"), records, result, collection="evidence")
        locators = _as_list(artifact.get("locators"))
        if not locators:
            result.errors.append(f"{artifact_id}.locators: at least one locator is required")
        for locator_index, locator in enumerate(locators):
            if not isinstance(locator, Mapping) or not isinstance(locator.get("uri"), str):
                continue
            uri = locator["uri"]
            if uri.startswith("data:"):
                try:
                    payload = _data_uri_payload(uri)
                except ValueError as exc:
                    result.errors.append(f"{artifact_id}.locators[{locator_index}]: {exc}")
                    continue
                if isinstance(digest, str) and DIGEST_RE.match(digest) and not _verify_payload(payload, digest):
                    result.errors.append(
                        f"{artifact_id}.digest: does not match data URI bytes"
                    )
                if isinstance(artifact.get("size_bytes"), int) and len(payload) != artifact["size_bytes"]:
                    result.errors.append(
                        f"{artifact_id}.size_bytes: does not match data URI bytes"
                    )
                continue
            if base_path is None:
                continue
            try:
                path = _local_path(uri, base_path)
            except ValueError as exc:
                result.errors.append(f"{artifact_id}.locators[{locator_index}]: {exc}")
                continue
            if path is None:
                continue
            if not path.is_file():
                result.errors.append(f"{artifact_id}.locators[{locator_index}]: missing local file {path}")
            elif isinstance(digest, str) and DIGEST_RE.match(digest) and not _verify_digest(path, digest):
                result.errors.append(f"{artifact_id}.digest: does not match {path}")
            elif isinstance(artifact.get("size_bytes"), int) and path.stat().st_size != artifact["size_bytes"]:
                result.errors.append(f"{artifact_id}.size_bytes: does not match {path}")
    for node in document.get("nodes", []):
        if not isinstance(node, Mapping) or node.get("kind") != "implementation":
            continue
        node_id = node.get("id")
        digest = node.get("digest")
        if isinstance(node_id, str) and isinstance(digest, str) and DIGEST_RE.match(digest):
            if digest.lower() not in subject_digests.get(node_id, set()):
                result.errors.append(
                    f"{node_id}.digest: no subject-linked artifact has the implementation digest"
                )


def _check_evidence(
    document: Mapping[str, Any],
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    result: ConformanceResult,
    contract_digests: set[str],
    artifact_digests: set[str],
) -> None:
    for evidence in document.get("evidence", []):
        if not isinstance(evidence, Mapping) or not isinstance(evidence.get("id"), str):
            continue
        evidence_id = evidence["id"]
        _check_reference_list(evidence_id, "subject_refs", evidence.get("subject_refs"), records, result)
        subject_refs = set(evidence.get("subject_refs", [])) if isinstance(evidence.get("subject_refs"), list) else set()
        seen_subject_digests: set[str] = set()
        for binding_index, binding in enumerate(_as_list(evidence.get("subject_digests"))):
            if not isinstance(binding, Mapping):
                result.errors.append(f"{evidence_id}.subject_digests[{binding_index}]: must be an object")
                continue
            subject_ref = binding.get("subject_ref")
            if subject_ref not in subject_refs:
                result.errors.append(
                    f"{evidence_id}.subject_digests[{binding_index}]: subject_ref is not listed in subject_refs"
                )
            if isinstance(subject_ref, str):
                if subject_ref in seen_subject_digests:
                    result.errors.append(f"{evidence_id}.subject_digests: duplicate binding for {subject_ref!r}")
                seen_subject_digests.add(subject_ref)
            if binding.get("canonicalization") != "rfc8785":
                result.errors.append(f"{evidence_id}.subject_digests[{binding_index}]: unsupported canonicalization")
            digest = binding.get("digest")
            if not isinstance(digest, str) or not DIGEST_RE.match(digest):
                result.errors.append(f"{evidence_id}.subject_digests[{binding_index}].digest: invalid digest")
            elif isinstance(subject_ref, str) and subject_ref in records:
                try:
                    actual_digest = record_digest(records[subject_ref][1])
                except (ValueError, rfc8785.CanonicalizationError) as exc:
                    result.errors.append(
                        f"{evidence_id}.subject_digests[{binding_index}]: cannot canonicalize subject: {exc}"
                    )
                else:
                    if digest != actual_digest:
                        result.errors.append(
                            f"{evidence_id}.subject_digests[{binding_index}].digest: does not match RFC 8785 subject digest"
                        )
        _check_reference_list(evidence_id, "parent_evidence_refs", evidence.get("parent_evidence_refs"), records, result, collection="evidence")
        if evidence.get("raw_result_ref") is not None:
            _require_ref(evidence.get("raw_result_ref"), records, result, f"{evidence_id}.raw_result_ref", collection="artifacts")
        if evidence.get("revocation_ref") is not None:
            _require_ref(evidence.get("revocation_ref"), records, result, f"{evidence_id}.revocation_ref")
        observed = _parse_datetime(evidence.get("observed_at"))
        expiry = _parse_datetime(evidence.get("expires_at"))
        if observed is not None and expiry is not None and expiry <= observed:
            result.errors.append(f"{evidence_id}: expires_at must be later than observed_at")
        for field_name in ("contract_digest", "artifact_digest", "environment_digest", "workload_digest", "policy_digest"):
            value = evidence.get(field_name)
            if value is not None and (not isinstance(value, str) or not DIGEST_RE.match(value)):
                result.errors.append(f"{evidence_id}.{field_name}: invalid digest")
        for measure_index, measure in enumerate(_as_list(evidence.get("measures"))):
            if isinstance(measure, Mapping):
                _check_measure(measure, result, f"{evidence_id}.measures[{measure_index}]")
        contract_digest = evidence.get("contract_digest")
        if isinstance(contract_digest, str) and contract_digest.lower() not in contract_digests:
            result.errors.append(f"{evidence_id}.contract_digest: no matching local contract digest")
        artifact_digest = evidence.get("artifact_digest")
        if isinstance(artifact_digest, str) and artifact_digest.lower() not in artifact_digests:
            result.errors.append(f"{evidence_id}.artifact_digest: no matching local artifact digest")


def _check_vector_payload(
    representation_id: str,
    encoding: str,
    embedding: Mapping[str, Any],
    result: ConformanceResult,
) -> None:
    dimensions = embedding.get("dimensions")
    vector = embedding.get("vector")
    vector_ref = embedding.get("vector_ref")
    if (vector is None) == (vector_ref is None):
        result.errors.append(f"{representation_id}.embedding: exactly one of vector or vector_ref is required")
        return
    if vector is None:
        return
    if not isinstance(dimensions, int) or dimensions < 1:
        result.errors.append(f"{representation_id}.embedding.dimensions: must be a positive integer")
        return
    if encoding in {"dense_vector", "binary_vector"}:
        if not isinstance(vector, list) or any(
            isinstance(value, list)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in vector
        ):
            result.errors.append(f"{representation_id}.embedding.vector: expected one numeric vector")
        elif len(vector) != dimensions:
            result.errors.append(
                f"{representation_id}.embedding.vector: length {len(vector)} does not match dimensions {dimensions}"
            )
        elif embedding.get("normalization") in {"l2", "unit"}:
            norm = math.sqrt(sum(float(value) ** 2 for value in vector))
            if not math.isclose(norm, 1.0, rel_tol=1e-6, abs_tol=1e-6):
                result.errors.append(f"{representation_id}.embedding.vector: declared l2/unit normalization is not applied")
    elif encoding == "multivector":
        if not isinstance(vector, list) or not vector or not all(isinstance(row, list) for row in vector):
            result.errors.append(f"{representation_id}.embedding.vector: expected a non-empty matrix")
        else:
            for row_index, row in enumerate(vector):
                if len(row) != dimensions or any(
                    not isinstance(value, (int, float)) or not math.isfinite(value)
                    for value in row
                ):
                    result.errors.append(
                        f"{representation_id}.embedding.vector[{row_index}]: expected {dimensions} numeric values"
                    )
                elif embedding.get("normalization") in {"l2", "unit"}:
                    norm = math.sqrt(sum(float(value) ** 2 for value in row))
                    if not math.isclose(norm, 1.0, rel_tol=1e-6, abs_tol=1e-6):
                        result.errors.append(
                            f"{representation_id}.embedding.vector[{row_index}]: declared l2/unit normalization is not applied"
                        )
    elif encoding == "sparse_vector":
        if not isinstance(vector, Mapping):
            result.errors.append(f"{representation_id}.embedding.vector: expected sparse indices/values object")
        else:
            indices = vector.get("indices")
            values = vector.get("values")
            if not isinstance(indices, list) or not isinstance(values, list) or len(indices) != len(values):
                result.errors.append(f"{representation_id}.embedding.vector: sparse indices and values must have equal length")
            elif any(not isinstance(index, int) or index < 0 or index >= dimensions for index in indices):
                result.errors.append(f"{representation_id}.embedding.vector: sparse index outside dimensions")
            elif any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
                result.errors.append(f"{representation_id}.embedding.vector: sparse values must be finite numbers")
            elif embedding.get("normalization") in {"l2", "unit"}:
                norm = math.sqrt(sum(float(value) ** 2 for value in values))
                if not math.isclose(norm, 1.0, rel_tol=1e-6, abs_tol=1e-6):
                    result.errors.append(f"{representation_id}.embedding.vector: declared l2/unit normalization is not applied")


def _embedding_signature(embedding: Mapping[str, Any]) -> tuple[Any, ...]:
    model = embedding.get("model", {})
    return (
        model.get("id"),
        model.get("revision"),
        model.get("digest"),
        model.get("base_model_ref"),
        json.dumps(model.get("tuning", {}), sort_keys=True, separators=(",", ":")),
        embedding.get("dimensions"),
        embedding.get("dtype"),
        embedding.get("normalization"),
        embedding.get("distance"),
        embedding.get("pooling"),
        embedding.get("quantization"),
        json.dumps(embedding.get("truncation", {}), sort_keys=True, separators=(",", ":")),
        json.dumps(embedding.get("chunking", {}), sort_keys=True, separators=(",", ":")),
    )


def _check_representations(
    document: Mapping[str, Any],
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    result: ConformanceResult,
    known_digests: set[str],
    artifact_digests: set[str],
) -> dict[str, str]:
    spaces: dict[str, tuple[Any, ...]] = {}
    representation_spaces: dict[str, str] = {}
    for representation in document.get("representations", []):
        if not isinstance(representation, Mapping) or not isinstance(representation.get("id"), str):
            continue
        representation_id = representation["id"]
        _require_ref(representation.get("subject_ref"), records, result, f"{representation_id}.subject_ref")
        _check_reference_list(
            representation_id,
            "evaluation_refs",
            representation.get("evaluation_refs"),
            records,
            result,
            collection="evidence",
        )
        source_digest = representation.get("source_digest")
        if not isinstance(source_digest, str) or not DIGEST_RE.match(source_digest):
            result.errors.append(f"{representation_id}.source_digest: invalid digest")
        elif source_digest.lower() not in known_digests:
            result.errors.append(f"{representation_id}.source_digest: no matching contract, node, or artifact digest")
        encoding = representation.get("encoding")
        embedding = representation.get("embedding")
        if encoding in VECTOR_ENCODINGS:
            projection_recipe = representation.get("projection_recipe")
            if not isinstance(projection_recipe, Mapping):
                result.errors.append(f"{representation_id}: vector representation requires projection_recipe")
            else:
                recipe_digest = projection_recipe.get("digest")
                if not isinstance(recipe_digest, str) or recipe_digest.lower() not in artifact_digests:
                    result.errors.append(f"{representation_id}.projection_recipe.digest: no matching artifact digest")
            if not isinstance(embedding, Mapping):
                result.errors.append(f"{representation_id}: {encoding} requires embedding")
                continue
            _check_vector_payload(representation_id, str(encoding), embedding, result)
            space_id = embedding.get("space_id")
            if not isinstance(space_id, str) or not space_id:
                result.errors.append(f"{representation_id}.embedding.space_id: missing")
                continue
            signature = _embedding_signature(embedding)
            if space_id in spaces and spaces[space_id] != signature:
                result.errors.append(f"{representation_id}: space_id {space_id!r} has inconsistent model/vector semantics")
            spaces[space_id] = signature
            representation_spaces[representation_id] = space_id
            model = embedding.get("model")
            if isinstance(model, Mapping) and isinstance(model.get("tuning"), Mapping):
                _check_reference_list(
                    representation_id,
                    "embedding.model.tuning.evaluation_refs",
                    model["tuning"].get("evaluation_refs"),
                    records,
                    result,
                    collection="evidence",
                )
                for field_name in ("adapter_digest", "training_data_digest", "training_recipe_digest"):
                    value = model["tuning"].get(field_name)
                    if isinstance(value, str) and value.lower() not in artifact_digests:
                        result.errors.append(
                            f"{representation_id}.embedding.model.tuning.{field_name}: no matching artifact digest"
                        )
        elif embedding is not None:
            result.errors.append(f"{representation_id}: non-vector encoding must not carry embedding")
    result.counts["embedding_spaces"] = len(spaces)
    return representation_spaces


def _check_search_profiles(
    document: Mapping[str, Any],
    records: Mapping[str, tuple[str, Mapping[str, Any]]],
    result: ConformanceResult,
    representation_spaces: Mapping[str, str],
) -> None:
    representation_by_id = {
        representation.get("id"): representation
        for representation in document.get("representations", [])
        if isinstance(representation, Mapping) and isinstance(representation.get("id"), str)
    }
    stage_encoding = {
        "lexical": "lexical",
        "sparse_vector": "sparse_vector",
        "dense_vector": "dense_vector",
        "multivector": "multivector",
        "fingerprint": "fingerprint",
        "graph": "graph_features",
    }
    for profile in document.get("search_profiles", []):
        if not isinstance(profile, Mapping) or not isinstance(profile.get("id"), str):
            continue
        profile_id = profile["id"]
        stages = profile.get("stages")
        if not isinstance(stages, list):
            result.errors.append(f"{profile_id}.stages: must be an array")
            continue
        stage_by_id: dict[str, Mapping[str, Any]] = {}
        for stage_index, stage in enumerate(stages):
            if not isinstance(stage, Mapping) or not isinstance(stage.get("id"), str):
                result.errors.append(f"{profile_id}.stages[{stage_index}]: missing id")
                continue
            stage_id = stage["id"]
            if stage_id in stage_by_id:
                result.errors.append(f"{profile_id}.stages: duplicate stage id {stage_id!r}")
            stage_by_id[stage_id] = stage
            for ref_index, representation_ref in enumerate(_as_list(stage.get("representation_refs"))):
                if representation_ref not in representation_by_id:
                    result.errors.append(
                        f"{profile_id}.{stage_id}.representation_refs[{ref_index}]: unknown representation {representation_ref!r}"
                    )
                elif stage.get("kind") in stage_encoding:
                    actual_encoding = representation_by_id[representation_ref].get("encoding")
                    expected_encoding = stage_encoding[stage["kind"]]
                    if actual_encoding != expected_encoding:
                        result.errors.append(
                            f"{profile_id}.{stage_id}: stage kind {stage['kind']!r} requires {expected_encoding!r}, got {actual_encoding!r}"
                        )
        fusion = profile.get("fusion")
        fusion_spaces: set[str] = set()
        if isinstance(fusion, Mapping):
            inputs = _as_list(fusion.get("inputs"))
            for input_index, fusion_input in enumerate(inputs):
                if not isinstance(fusion_input, Mapping):
                    result.errors.append(f"{profile_id}.fusion.inputs[{input_index}]: must be an object")
                    continue
                stage_ref = fusion_input.get("stage_ref")
                if stage_ref not in stage_by_id:
                    result.errors.append(f"{profile_id}.fusion.inputs[{input_index}]: unknown stage {stage_ref!r}")
                    continue
                stage = stage_by_id[stage_ref]
                calibration_ref = fusion_input.get("calibration_ref")
                if calibration_ref is not None:
                    _require_ref(
                        calibration_ref,
                        records,
                        result,
                        f"{profile_id}.fusion.inputs[{input_index}].calibration_ref",
                    )
                for representation_ref in _as_list(stage.get("representation_refs")):
                    if representation_ref in representation_spaces:
                        fusion_spaces.add(representation_spaces[representation_ref])
            if fusion.get("method") in {"weighted_sum", "weighted_normalized_sum"} and len(fusion_spaces) > 1:
                missing_calibration = [
                    item.get("stage_ref")
                    for item in inputs
                    if isinstance(item, Mapping) and not item.get("calibration_ref")
                ]
                if missing_calibration:
                    result.errors.append(
                        f"{profile_id}.fusion: cross-space score summation requires calibration_ref for every input"
                    )
        for rerank_ref in _as_list(profile.get("rerank_stage_refs")):
            if rerank_ref not in stage_by_id:
                result.errors.append(f"{profile_id}.rerank_stage_refs: unknown stage {rerank_ref!r}")
            elif stage_by_id[rerank_ref].get("kind") != "reranker":
                result.errors.append(f"{profile_id}.rerank_stage_refs: {rerank_ref!r} is not a reranker stage")
        if profile.get("eligibility_policy_ref") is not None:
            _require_ref(
                profile.get("eligibility_policy_ref"),
                records,
                result,
                f"{profile_id}.eligibility_policy_ref",
                node_kind="policy",
            )
        _check_reference_list(profile_id, "evaluation_refs", profile.get("evaluation_refs"), records, result, collection="evidence")


def _check_profiles(document: Mapping[str, Any], result: ConformanceResult) -> None:
    profiles = document.get("profiles", [])
    if not isinstance(profiles, list):
        return
    result.eligibility_evaluated = "contract" in profiles
    requirements = {
        "core": ("nodes", "actions", "relations"),
        "contract": ("nodes", "actions", "relations"),
        "evidence": ("artifacts", "evidence"),
        "retrieval": ("representations", "search_profiles"),
    }
    for profile in profiles:
        if profile == "execution":
            result.errors.append("document.profiles: execution profile is reserved and unsupported in v0.1")
            continue
        for collection in requirements.get(profile, ()):
            rows = document.get(collection)
            if not isinstance(rows, list) or not rows:
                result.errors.append(f"profile {profile!r} requires non-empty {collection}")
        if profile == "contract":
            if not any(isinstance(node, Mapping) and node.get("kind") == "contract" for node in document.get("nodes", [])):
                result.errors.append("profile 'contract' requires at least one contract node")
            if not any(
                isinstance(relation, Mapping) and relation.get("kind") == "compatibility"
                for relation in document.get("relations", [])
            ):
                result.errors.append("profile 'contract' requires at least one compatibility relation")
    if not result.errors:
        result.validated_profiles = [profile for profile in profiles if profile in requirements]


def validate_document(
    document: Mapping[str, Any],
    *,
    base_path: Path | None = None,
    as_of: datetime | None = None,
) -> ConformanceResult:
    """Validate OCG cross-record invariants without third-party dependencies."""

    evaluation_time = as_of or datetime.now(timezone.utc)
    if evaluation_time.tzinfo is None:
        evaluation_time = evaluation_time.replace(tzinfo=timezone.utc)
    evaluation_time = evaluation_time.astimezone(timezone.utc)
    result = ConformanceResult(evaluated_at=evaluation_time.isoformat().replace("+00:00", "Z"))
    if not isinstance(document, Mapping):
        result.errors.append("document: root must be an object")
        return result
    _check_document_shape(document, result)
    records = _record_index(document, result)
    safe_document = dict(document)
    for collection in TOP_LEVEL_COLLECTIONS:
        if not isinstance(safe_document.get(collection, []), list):
            safe_document[collection] = []
    known_digests = _check_nodes(safe_document, records, result, base_path)
    contract_digests = {
        digest.lower()
        for node in safe_document.get("nodes", [])
        if isinstance(node, Mapping) and node.get("kind") == "contract"
        for digest in [_contract_digest(node)]
        if isinstance(digest, str)
    }
    ports = _check_actions(safe_document, records, result)
    _check_relations(safe_document, records, ports, result, evaluation_time)
    _check_adapters(safe_document, records, result, evaluation_time)
    _check_artifacts(safe_document, records, result, base_path, known_digests)
    artifact_digests = {
        artifact["digest"].lower()
        for artifact in safe_document.get("artifacts", [])
        if isinstance(artifact, Mapping)
        and isinstance(artifact.get("digest"), str)
        and DIGEST_RE.match(artifact["digest"])
    }
    _check_evidence(safe_document, records, result, contract_digests, artifact_digests)
    representation_spaces = _check_representations(
        safe_document,
        records,
        result,
        known_digests,
        artifact_digests,
    )
    _check_search_profiles(safe_document, records, result, representation_spaces)
    _check_profiles(safe_document, result)
    return result


def validate_file(
    path: Path,
    *,
    schema_path: Path | None = None,
    as_of: datetime | None = None,
) -> ConformanceResult:
    """Load and validate an OCG JSON document, optionally applying JSON Schema."""

    path = path.resolve()
    try:
        document = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = ConformanceResult(errors=[f"{path}: cannot load JSON: {exc}"])
        return result
    result = validate_document(document, base_path=path.parent, as_of=as_of)
    if schema_path is None:
        return result
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result.errors.append(f"{schema_path}: cannot load JSON Schema: {exc}")
        result.schema_validation = "failed_to_load"
        return result
    try:
        import jsonschema  # type: ignore[import-not-found]
    except ImportError:
        result.schema_validation = "dependency_unavailable"
        result.errors.append("jsonschema is required for normative shape validation; install project dependencies")
        return result
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.exceptions.SchemaError as exc:
        result.errors.append(f"{schema_path}: invalid JSON Schema: {exc.message}")
        result.schema_validation = "invalid_schema"
        return result
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    schema_errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    for error in schema_errors:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        result.errors.append(f"schema:{location}: {error.message}")
    result.schema_validation = "passed" if not schema_errors else "failed"
    return result
