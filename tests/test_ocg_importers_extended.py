from __future__ import annotations

from base64 import b64decode, b64encode
import hashlib
import json
from pathlib import Path
import unittest

import jsonschema

from aidevobserver_fabric.ocg_conformance import validate_document
from aidevobserver_fabric.ocg_importers import IMPORT_EXTENSION, import_agent_spec, import_wit_json


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "spec/open-capability-graph/v0.1/interoperability/fixtures"
SCHEMA_PATH = REPO_ROOT / "spec/open-capability-graph/v0.1/schemas/open-capability-graph.schema.json"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def decode_contract(contract: dict):
    uri = contract["native_contract"]["schema_uri"]
    payload = b64decode(uri.split(",", 1)[1])
    assert contract["native_contract"]["digest"] == "sha256:" + hashlib.sha256(payload).hexdigest()
    return json.loads(payload)


class ExtendedOCGImporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.FormatChecker(),
        )

    def assert_candidate(self, document: dict) -> None:
        errors = sorted(self.validator.iter_errors(document), key=lambda row: list(row.absolute_path))
        self.assertEqual([row.message for row in errors], [])
        result = validate_document(document)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.eligibility_errors, [])
        self.assertFalse(result.eligibility_evaluated)
        self.assertIsNone(result.currently_eligible)
        self.assertEqual(result.validated_profiles, ["core"])
        self.assertEqual(document["status"], "candidate")
        self.assertFalse(any(row["kind"] == "compatibility" for row in document["relations"]))

    def test_wit_json_import_preserves_resolved_types_and_raw_source_digest(self) -> None:
        normalized = load_json("customer.wit.json")
        raw = (FIXTURES / "customer.wit").read_bytes()
        result = import_wit_json(
            normalized,
            source_uri="urn:example:interop:wit:customer",
            raw_wit=raw,
        )
        self.assert_candidate(result.document)
        normalized_payload = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(result.source_digest, "sha256:" + hashlib.sha256(normalized_payload).hexdigest())
        provenance = result.document["extensions"][IMPORT_EXTENSION]["source_provenance"]
        self.assertEqual(
            provenance["raw_source"]["digest"],
            "sha256:" + hashlib.sha256(raw).hexdigest(),
        )
        self.assertEqual(provenance["normalized_projection"]["digest"], result.source_digest)
        self.assertEqual(len(result.document["artifacts"]), 2)
        self.assertEqual(
            {row["metadata"]["role"] for row in result.document["artifacts"]},
            {"normalized-interface-projection", "authoritative-raw-wit-source"},
        )
        contract = next(row for row in result.document["nodes"] if row["kind"] == "contract")
        self.assertEqual(len(contract["native_contract"]["source_artifact_refs"]), 2)
        relation = next(
            row for row in result.document["relations"] if row["kind"] == "derives_from"
        )
        self.assertIn(
            relation["source"]["subject_ref"],
            contract["native_contract"]["source_artifact_refs"],
        )
        self.assertEqual(len(result.document["actions"]), 1)
        action = result.document["actions"][0]
        self.assertEqual([row["id"] for row in action["ports"]], ["customer", "result"])
        result_port = next(row for row in action["ports"] if row["id"] == "result")
        contract = next(
            row for row in result.document["nodes"] if row["id"] == result_port["contract_ref"]
        )
        projected = decode_contract(contract)
        self.assertEqual(projected["type_ref"], 2)
        self.assertIn("result", projected["resolved_type"]["kind"])
        codes = {warning.code for warning in result.warnings}
        self.assertIn("wit_result_not_split", codes)
        self.assertIn("wit_behavior_not_defined", codes)

    def test_agent_spec_import_preserves_tool_property_contracts(self) -> None:
        source = load_json("agent-spec-customer.json")
        result = import_agent_spec(source, source_uri="urn:example:interop:agentspec:customer")
        self.assert_candidate(result.document)
        self.assertEqual(len(result.document["actions"]), 1)
        action = result.document["actions"][0]
        self.assertEqual([row["id"] for row in action["ports"]], ["customer", "valid"])
        input_port = next(row for row in action["ports"] if row["id"] == "customer")
        input_contract = next(
            row for row in result.document["nodes"] if row["id"] == input_port["contract_ref"]
        )
        self.assertEqual(decode_contract(input_contract), source["tools"][0]["inputs"][0])
        implementation = next(row for row in result.document["nodes"] if row["kind"] == "implementation")
        self.assertEqual(implementation["metadata"]["binding"]["component_type"], "ServerTool")
        codes = {warning.code for warning in result.warnings}
        self.assertIn("agentspec_code_not_present", codes)
        self.assertIn("behavior_semantics_unknown", codes)

    def test_agent_spec_without_supported_tools_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(ValueError, "no supported actions"):
            import_agent_spec(
                {
                    "component_type": "Agent",
                    "name": "empty",
                    "tools": [{"component_type": "CustomTool", "name": "unsupported"}],
                }
            )

    def test_conformance_verifies_artifact_data_uri_digest_and_size(self) -> None:
        document = import_wit_json(
            load_json("customer.wit.json"),
            source_uri="urn:example:interop:wit:customer",
            raw_wit=(FIXTURES / "customer.wit").read_bytes(),
        ).document
        artifact = next(
            row
            for row in document["artifacts"]
            if row["metadata"]["role"] == "normalized-interface-projection"
        )
        artifact["locators"] = [
            {
                "uri": "data:application/json;base64," + b64encode(b"{}").decode("ascii"),
                "priority": 0,
            }
        ]
        artifact["digest"] = "sha256:" + ("0" * 64)
        artifact["size_bytes"] = 3
        result = validate_document(document)
        self.assertTrue(any("does not match data URI bytes" in row for row in result.errors))
        self.assertTrue(any("size_bytes" in row for row in result.errors))


if __name__ == "__main__":
    unittest.main()
