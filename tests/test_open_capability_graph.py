from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from aidevobserver_fabric.ocg_conformance import record_digest, validate_document, validate_file


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "spec/open-capability-graph/v0.1/examples"
EXAMPLE = EXAMPLE_DIR / "customer-record-pipeline.ocg.json"
SCHEMA = REPO_ROOT / "spec/open-capability-graph/v0.1/schemas/open-capability-graph.schema.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refresh_subject_binding(document: dict, subject_id: str) -> None:
    collections = ("nodes", "actions", "relations", "adapters", "artifacts", "representations", "search_profiles")
    subject = next(row for collection in collections for row in document.get(collection, []) if row.get("id") == subject_id)
    evidence = next(row for row in document["evidence"] if subject_id in row.get("subject_refs", []))
    bindings = evidence.setdefault("subject_digests", [])
    binding = next((row for row in bindings if row.get("subject_ref") == subject_id), None)
    if binding is None:
        binding = {"subject_ref": subject_id, "canonicalization": "rfc8785"}
        bindings.append(binding)
    binding["digest"] = record_digest(subject)


class OpenCapabilityGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.as_of = datetime(2026, 7, 11, 1, 0, tzinfo=timezone.utc)

    def validate(self, document: dict):
        return validate_document(document, base_path=EXAMPLE_DIR, as_of=self.as_of)

    def test_reference_example_conforms(self) -> None:
        result = validate_file(EXAMPLE, schema_path=SCHEMA, as_of=self.as_of)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.eligibility_errors, [])
        self.assertTrue(result.valid)
        self.assertTrue(result.currently_eligible)
        self.assertEqual(result.validated_profiles, ["core", "contract", "evidence", "retrieval"])
        self.assertEqual(result.counts["embedding_spaces"], 3)
        self.assertGreaterEqual(result.counts["relations"], 8)

    def test_related_candidate_cannot_be_directly_eligible(self) -> None:
        document = deepcopy(self.document)
        relation = next(row for row in document["relations"] if row["kind"] == "compatibility")
        relation["compatibility"]["relationship"] = "related"
        relation["compatibility"]["join_decision"] = "eligible_direct"
        result = self.validate(document)
        self.assertTrue(any("cannot be eligible_direct" in error for error in result.errors))

    def test_vector_dimension_mismatch_is_rejected(self) -> None:
        document = deepcopy(self.document)
        representation = next(row for row in document["representations"] if row["encoding"] == "dense_vector")
        representation["embedding"]["dimensions"] += 1
        result = self.validate(document)
        self.assertTrue(any("does not match dimensions" in error for error in result.errors))

    def test_dangling_action_contract_is_rejected(self) -> None:
        document = deepcopy(self.document)
        document["actions"][0]["ports"][0]["contract_ref"] = "urn:example:ocg:missing:contract"
        result = self.validate(document)
        self.assertTrue(any("unknown reference 'urn:example:ocg:missing:contract'" in error for error in result.errors))

    def test_cross_space_weighted_sum_requires_calibration(self) -> None:
        document = deepcopy(self.document)
        document["search_profiles"][0]["fusion"]["method"] = "weighted_sum"
        result = self.validate(document)
        self.assertTrue(any("requires calibration_ref" in error for error in result.errors))

    def test_global_record_ids_must_be_unique(self) -> None:
        document = deepcopy(self.document)
        document["actions"][0]["id"] = document["nodes"][0]["id"]
        result = self.validate(document)
        self.assertTrue(any("duplicate id" in error for error in result.errors))

    def test_directly_eligible_compatibility_must_be_verified(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "eligible_direct"
        )
        relation["status"] = "candidate"
        result = self.validate(document)
        self.assertTrue(any("eligible_direct compatibility must be verified" in error for error in result.errors))

    def test_directly_eligible_compatibility_needs_passing_evidence(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "eligible_direct"
        )
        evidence_id = relation["evidence_refs"][0]
        evidence = next(row for row in document["evidence"] if row["id"] == evidence_id)
        evidence["result"] = "inconclusive"
        result = self.validate(document)
        self.assertTrue(any("requires digest-bound passing evidence" in error for error in result.errors))

    def test_identical_contracts_must_have_equal_digests(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("relationship") == "identical"
        )
        relation["compatibility"]["target_contract_digest"] = (
            "sha256:" + ("7" * 64)
        )
        result = self.validate(document)
        self.assertTrue(any("target_contract_digest does not match" in error for error in result.errors))

    def test_verified_adapter_needs_action_and_evidence(self) -> None:
        document = deepcopy(self.document)
        adapter = document["adapters"][0]
        adapter.pop("action_ref")
        adapter["evidence_refs"] = []
        result = self.validate(document)
        self.assertTrue(any("verified adapter requires action_ref" in error for error in result.errors))
        self.assertTrue(any("verified adapter requires digest-bound passing evidence" in error for error in result.errors))

    def test_one_space_id_cannot_hide_different_model_semantics(self) -> None:
        document = deepcopy(self.document)
        dense = [row for row in document["representations"] if row["encoding"] == "dense_vector"]
        dense[1]["embedding"]["space_id"] = dense[0]["embedding"]["space_id"]
        result = self.validate(document)
        self.assertTrue(any("inconsistent model/vector semantics" in error for error in result.errors))

    def test_local_artifact_digest_is_verified(self) -> None:
        document = deepcopy(self.document)
        document["artifacts"][0]["digest"] = "sha256:" + ("0" * 64)
        result = self.validate(document)
        self.assertTrue(any("does not match" in error for error in result.errors))

    def test_fusion_cannot_reference_missing_stage(self) -> None:
        document = deepcopy(self.document)
        document["search_profiles"][0]["fusion"]["inputs"][0]["stage_ref"] = "missing-stage"
        result = self.validate(document)
        self.assertTrue(any("unknown stage 'missing-stage'" in error for error in result.errors))

    def test_effective_port_semantics_participate_in_identity(self) -> None:
        document = deepcopy(self.document)
        document["actions"][1]["ports"][0]["unit"] = "http://qudt.org/vocab/unit/KiloGM"
        result = self.validate(document)
        self.assertTrue(any("equal effective port semantics" in error for error in result.errors))

    def test_direct_eligibility_requires_pinned_checker_digest(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "eligible_direct"
        )
        relation["compatibility"].pop("checker_digest", None)
        result = self.validate(document)
        self.assertTrue(any("requires checker_digest" in error for error in result.errors))

    def test_eligible_relation_checker_must_resolve_to_matching_artifact(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "eligible_direct"
        )
        relation["compatibility"]["checker_ref"] = "urn:example:ocg:artifact:forged-checker"
        relation["compatibility"]["checker_digest"] = "sha256:" + ("0" * 64)
        result = self.validate(document)
        self.assertTrue(any("unknown reference 'urn:example:ocg:artifact:forged-checker'" in error for error in result.errors))

    def test_eligible_relation_checker_digest_must_match_artifact(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "eligible_direct"
        )
        relation["compatibility"]["checker_digest"] = "sha256:" + ("0" * 64)
        result = self.validate(document)
        self.assertTrue(any("checker_digest does not match checker artifact digest" in error for error in result.errors))

    def test_transformable_relationship_requires_adapter_mechanism(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("relationship") == "transformable"
        )
        relation["compatibility"]["mechanism"] = "direct"
        relation["compatibility"]["lossiness"] = "none"
        relation["compatibility"]["join_decision"] = "eligible_direct"
        result = self.validate(document)
        self.assertTrue(any("transformable relationship requires adapter mechanism" in error for error in result.errors))

    def test_compatibility_lossiness_must_match_adapter(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("mechanism") == "adapter"
        )
        relation["compatibility"]["lossiness"] = "total_lossy"
        result = self.validate(document)
        self.assertTrue(any("lossiness does not match adapter classification" in error for error in result.errors))

    def test_lossy_adapter_route_cannot_be_planning_eligible(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "requires_adapter"
        )
        relation["compatibility"]["lossiness"] = "total_lossy"
        adapter = next(
            row for row in document["adapters"] if row["id"] == relation["compatibility"]["adapter_ref"]
        )
        adapter["classification"] = "total_lossy"
        refresh_subject_binding(document, relation["id"])
        refresh_subject_binding(document, adapter["id"])
        result = self.validate(document)
        self.assertTrue(any("limited to total_lossless adapters" in error for error in result.errors))

    def test_requires_adapter_relation_is_eligibility_gated(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "requires_adapter"
        )
        relation["status"] = "candidate"
        result = self.validate(document)
        self.assertTrue(any("requires_adapter compatibility must be verified" in error for error in result.errors))

    def test_requires_adapter_relation_needs_own_digest_bound_evidence(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "requires_adapter"
        )
        relation["evidence_refs"] = []
        result = self.validate(document)
        self.assertTrue(any("requires_adapter compatibility requires digest-bound" in error for error in result.errors))

    def test_conditional_join_cannot_be_marked_eligible_in_v01(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "eligible_direct"
        )
        relation["compatibility"]["condition_refs"] = ["urn:example:ocg:condition:unresolved"]
        refresh_subject_binding(document, relation["id"])
        result = self.validate(document)
        self.assertTrue(any("cannot mark conditional compatibility eligible" in error for error in result.errors))

    def test_revoked_endpoint_implementation_blocks_current_eligibility(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "eligible_direct"
        )
        source_action_id = relation["source"]["subject_ref"]
        source_action = next(row for row in document["actions"] if row["id"] == source_action_id)
        implementation = next(row for row in document["nodes"] if row["id"] == source_action["implementation_ref"])
        implementation["lifecycle"] = "revoked"
        refresh_subject_binding(document, implementation["id"])
        result = self.validate(document)
        self.assertEqual(result.errors, [])
        self.assertTrue(any("implementation is not currently active or verified" in error for error in result.eligibility_errors))

    def test_action_level_precondition_requires_review_in_v01(self) -> None:
        document = deepcopy(self.document)
        document["actions"][1]["preconditions"] = [
            {
                "id": "urn:example:ocg:constraint:requires-tenant",
                "scope": "action",
                "language": "urn:example:ocg:constraint-language:expression",
                "expression": "tenant_is_authorized",
                "severity": "must"
            }
        ]
        result = self.validate(document)
        self.assertTrue(any("action-level preconditions" in error for error in result.errors))

    def test_revoked_adapter_implementation_blocks_adapter_route(self) -> None:
        document = deepcopy(self.document)
        adapter = document["adapters"][0]
        adapter_action = next(row for row in document["actions"] if row["id"] == adapter["action_ref"])
        implementation = next(row for row in document["nodes"] if row["id"] == adapter_action["implementation_ref"])
        implementation["lifecycle"] = "revoked"
        refresh_subject_binding(document, implementation["id"])
        result = self.validate(document)
        self.assertTrue(any("adapter implementation is not currently active or verified" in error for error in result.eligibility_errors))

    def test_unrelated_passing_claim_cannot_qualify_action(self) -> None:
        document = deepcopy(self.document)
        evidence = next(
            row
            for row in document["evidence"]
            if row["claim_type"].endswith("action-contract-conformance")
        )
        evidence["claim_type"] = "urn:example:ocg:claim:embedding-lineage-recorded"
        result = self.validate(document)
        self.assertTrue(any("eligibility evidence must bind the exact source action" in error for error in result.errors))

    def test_adapter_claim_cannot_qualify_ordinary_endpoint_action(self) -> None:
        document = deepcopy(self.document)
        evidence = next(
            row
            for row in document["evidence"]
            if row["claim_type"].endswith("action-contract-conformance")
        )
        evidence["claim_type"] = evidence["claim_type"].replace(
            "action-contract-conformance", "adapter-conformance"
        )
        result = self.validate(document)
        self.assertTrue(any("eligibility evidence must bind the exact source action" in error for error in result.errors))

    def test_expired_evidence_preserves_history_but_blocks_current_eligibility(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "eligible_direct"
        )
        evidence = next(row for row in document["evidence"] if row["id"] == relation["evidence_refs"][0])
        evidence["expires_at"] = "2026-07-11T00:50:00Z"
        result = self.validate(document)
        self.assertEqual(result.errors, [])
        self.assertFalse(result.currently_eligible)
        self.assertTrue(any("expired or revoked" in error for error in result.eligibility_errors))

    def test_relation_validity_window_is_evaluated_separately(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "eligible_direct"
        )
        relation["valid_until"] = "2026-07-11T00:55:00Z"
        refresh_subject_binding(document, relation["id"])
        result = self.validate(document)
        self.assertEqual(result.errors, [])
        self.assertTrue(any("relation is not currently valid" in error for error in result.eligibility_errors))

    def test_future_observation_cannot_support_current_eligibility(self) -> None:
        document = deepcopy(self.document)
        relation = next(
            row
            for row in document["relations"]
            if row.get("compatibility", {}).get("join_decision") == "eligible_direct"
        )
        evidence = next(row for row in document["evidence"] if row["id"] == relation["evidence_refs"][0])
        evidence["observed_at"] = "2026-07-11T02:00:00Z"
        result = self.validate(document)
        self.assertEqual(result.errors, [])
        self.assertTrue(any("expired or revoked" in error for error in result.eligibility_errors))

    def test_implementation_digest_must_match_subject_linked_artifact(self) -> None:
        document = deepcopy(self.document)
        implementation = next(row for row in document["nodes"] if row["kind"] == "implementation")
        implementation["digest"] = "sha256:" + ("1" * 64)
        result = self.validate(document)
        self.assertTrue(any("no subject-linked artifact" in error for error in result.errors))

    def test_evidence_artifact_digest_must_resolve_to_artifact(self) -> None:
        document = deepcopy(self.document)
        evidence = next(row for row in document["evidence"] if "artifact_digest" in row)
        evidence["artifact_digest"] = "sha256:" + ("2" * 64)
        result = self.validate(document)
        self.assertTrue(any("no matching local artifact digest" in error for error in result.errors))

    def test_evidence_contract_digest_must_resolve_to_contract(self) -> None:
        document = deepcopy(self.document)
        evidence = next(row for row in document["evidence"] if "contract_digest" in row)
        evidence["contract_digest"] = "sha256:" + ("3" * 64)
        result = self.validate(document)
        self.assertTrue(any("no matching local contract digest" in error for error in result.errors))

    def test_search_stage_kind_must_match_representation_encoding(self) -> None:
        document = deepcopy(self.document)
        lexical_id = next(row["id"] for row in document["representations"] if row["encoding"] == "lexical")
        dense_stage = next(row for row in document["search_profiles"][0]["stages"] if row["kind"] == "dense_vector")
        dense_stage["representation_refs"] = [lexical_id]
        result = self.validate(document)
        self.assertTrue(any("requires 'dense_vector', got 'lexical'" in error for error in result.errors))

    def test_cross_space_calibration_reference_must_resolve(self) -> None:
        document = deepcopy(self.document)
        fusion = document["search_profiles"][0]["fusion"]
        fusion["method"] = "weighted_sum"
        for item in fusion["inputs"]:
            item["calibration_ref"] = "urn:example:ocg:missing:calibration"
        result = self.validate(document)
        self.assertTrue(any("unknown reference 'urn:example:ocg:missing:calibration'" in error for error in result.errors))

    def test_tuning_digest_must_be_an_artifact_not_a_contract(self) -> None:
        document = deepcopy(self.document)
        tuned = next(row for row in document["representations"] if row["id"].endswith("normalize-intent-tuned"))
        contract_digest = next(row["native_contract"]["digest"] for row in document["nodes"] if row["kind"] == "contract")
        tuned["embedding"]["model"]["tuning"]["adapter_digest"] = contract_digest
        result = self.validate(document)
        self.assertTrue(any("no matching artifact digest" in error for error in result.errors))

    def test_inline_contract_mirror_cannot_disagree_with_referenced_bytes(self) -> None:
        document = deepcopy(self.document)
        contract = next(row for row in document["nodes"] if row["kind"] == "contract")
        contract["native_contract"]["schema"] = {"type": "integer"}
        result = self.validate(document)
        self.assertTrue(any("inline mirror differs" in error for error in result.errors))

    def test_malformed_collections_report_errors_without_crashing(self) -> None:
        document = deepcopy(self.document)
        document["actions"] = None
        result = self.validate(document)
        self.assertTrue(any("actions: must be an array" in error for error in result.errors))

    def test_false_subject_digest_is_rejected(self) -> None:
        document = deepcopy(self.document)
        evidence = next(row for row in document["evidence"] if row.get("subject_digests"))
        evidence["subject_digests"][0]["digest"] = "sha256:" + ("4" * 64)
        result = self.validate(document)
        self.assertTrue(any("does not match RFC 8785 subject digest" in error for error in result.errors))

    def test_verified_flow_must_connect_output_to_input(self) -> None:
        document = deepcopy(self.document)
        flow = next(row for row in document["relations"] if row["kind"] == "flow")
        flow["source"]["port_id"] = "record-in"
        result = self.validate(document)
        self.assertTrue(any("flow source must be an output port" in error for error in result.errors))

    def test_declared_l2_normalization_must_be_applied(self) -> None:
        document = deepcopy(self.document)
        representation = next(row for row in document["representations"] if row["encoding"] == "dense_vector")
        representation["embedding"]["normalization"] = "l2"
        result = self.validate(document)
        self.assertTrue(any("normalization is not applied" in error for error in result.errors))

    def test_claimed_retrieval_profile_requires_records(self) -> None:
        document = deepcopy(self.document)
        document["representations"] = []
        result = self.validate(document)
        self.assertTrue(any("profile 'retrieval' requires non-empty representations" in error for error in result.errors))

    def test_local_artifact_locator_cannot_escape_bundle_root(self) -> None:
        document = deepcopy(self.document)
        document["artifacts"][0]["locators"][0]["uri"] = "../../../../../../pyproject.toml"
        result = self.validate(document)
        self.assertTrue(any("escapes document root" in error for error in result.errors))

    def test_nonstandard_nan_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.ocg.json"
            path.write_text('{"spec_version":"0.1.0-draft","score":NaN}', encoding="utf-8")
            result = validate_file(path)
        self.assertFalse(result.valid)
        self.assertTrue(any("non-standard JSON numeric constant" in error for error in result.errors))

    def test_example_implementations_execute_end_to_end(self) -> None:
        normalize = load_module("ocg_example_normalize", EXAMPLE_DIR / "implementations/normalize_customer.py")
        export = load_module("ocg_example_export", EXAMPLE_DIR / "implementations/export_customer.py")
        emitter = load_module("ocg_example_emit", EXAMPLE_DIR / "implementations/emit_json.py")
        normalized = normalize.normalize_customer({"full_name": "  Ada   Lovelace ", "email": " ADA@EXAMPLE.ORG "})
        self.assertEqual(normalized, {"name": "Ada Lovelace", "email": "ADA@example.org"})
        exported = export.export_customer(normalized)
        self.assertEqual(exported, {"name": "Ada Lovelace", "email_address": "ADA@example.org"})
        artifact = emitter.emit_json(exported)
        self.assertEqual(
            artifact,
            {
                "media_type": "application/json",
                "body": '{"email_address":"ADA@example.org","name":"Ada Lovelace"}',
            },
        )


if __name__ == "__main__":
    unittest.main()
