from __future__ import annotations

from base64 import b64decode
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

import jsonschema

from aidevobserver_fabric.ocg_conformance import validate_document
from aidevobserver_fabric.ocg_importers import (
    IMPORT_EXTENSION,
    UNKNOWN_DIALECT,
    import_cwl,
    import_mcp_tools,
    import_openapi,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "spec/open-capability-graph/v0.1/interoperability/fixtures"
SCHEMA_PATH = REPO_ROOT / "spec/open-capability-graph/v0.1/schemas/open-capability-graph.schema.json"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def native_value(contract: dict) -> object:
    uri = contract["native_contract"]["schema_uri"]
    header, encoded = uri.split(",", 1)
    if ";base64" not in header:
        raise AssertionError(f"not a base64 data URI: {uri[:80]}")
    payload = b64decode(encoded)
    expected = "sha256:" + hashlib.sha256(payload).hexdigest()
    if contract["native_contract"]["digest"] != expected:
        raise AssertionError("contract digest does not bind data-URI bytes")
    return json.loads(payload.decode("utf-8"))


class OCGImporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.schema_validator = jsonschema.Draft202012Validator(
            cls.schema,
            format_checker=jsonschema.FormatChecker(),
        )

    def assert_candidate_document(self, document: dict) -> None:
        schema_errors = sorted(
            self.schema_validator.iter_errors(document),
            key=lambda error: list(error.absolute_path),
        )
        self.assertEqual([error.message for error in schema_errors], [])
        conformance = validate_document(document)
        self.assertEqual(conformance.errors, [])
        self.assertEqual(conformance.eligibility_errors, [])
        self.assertFalse(conformance.eligibility_evaluated)
        self.assertIsNone(conformance.currently_eligible)
        self.assertEqual(conformance.validated_profiles, ["core"])
        self.assertEqual(document["status"], "candidate")
        self.assertEqual(document["profiles"], ["core"])
        self.assertEqual(document["extensions"][IMPORT_EXTENSION]["planning_eligibility"], "unknown")
        self.assertFalse(document["extensions"][IMPORT_EXTENSION]["contract_profile_claimed"])
        self.assertFalse(any(relation["kind"] == "compatibility" for relation in document["relations"]))
        self.assertTrue(all(relation["status"] == "candidate" for relation in document["relations"]))
        self.assertTrue(all(action["lifecycle"] == "candidate" for action in document["actions"]))
        self.assertTrue(all(action["metadata"]["planning_eligibility"] == "unknown" for action in document["actions"]))
        self.assertTrue(
            all(
                action["effects"] == [
                    {
                        "kind": "custom",
                        "certainty": "unknown",
                        "metadata": {
                            "reason": "native import does not establish a complete effect set"
                        },
                    }
                ]
                for action in document["actions"]
            )
        )

    def contract_for_port(self, document: dict, action: dict, port_id: str) -> dict:
        port = next(row for row in action["ports"] if row["id"] == port_id)
        return next(row for row in document["nodes"] if row["id"] == port["contract_ref"])

    def test_mcp_fixture_preserves_input_and_output_schemas_without_trusting_annotations(self) -> None:
        source = load_fixture("mcp-tools.json")
        result = import_mcp_tools(source, source_uri="https://catalog.example/mcp-tools.json")
        document = result.document
        self.assert_candidate_document(document)
        self.assertEqual(len(document["actions"]), 2)
        first_action = document["actions"][0]
        input_contract = self.contract_for_port(document, first_action, "input")
        output_contract = self.contract_for_port(document, first_action, "output")
        self.assertEqual(native_value(input_contract), source["tools"][0]["inputSchema"])
        self.assertEqual(native_value(output_contract), source["tools"][0]["outputSchema"])
        self.assertEqual(
            input_contract["native_contract"]["metadata"]["source_document_uri"],
            "https://catalog.example/mcp-tools.json",
        )
        codes = [warning.code for warning in result.warnings]
        self.assertIn("mcp_annotations_not_guarantees", codes)
        self.assertIn("behavior_semantics_unknown", codes)
        self.assertEqual(result.planning_eligibility, "unknown")

    def test_mcp_missing_schemas_become_explicit_unknown_contracts(self) -> None:
        result = import_mcp_tools([{"name": "opaque_tool"}])
        document = result.document
        self.assert_candidate_document(document)
        action = document["actions"][0]
        for port_id in ("input", "output"):
            contract = self.contract_for_port(document, action, port_id)
            self.assertEqual(contract["native_contract"]["dialect"], UNKNOWN_DIALECT)
            self.assertEqual(native_value(contract)["ocg_import_status"], "unknown")
            self.assertEqual(contract["native_contract"]["metadata"]["semantic_status"], "unknown")
        self.assertEqual(
            {warning.code for warning in result.warnings},
            {
                "mcp_input_schema_unknown",
                "mcp_output_schema_unknown",
                "behavior_semantics_unknown",
            },
        )

    def test_openapi_fixture_preserves_request_response_projections_and_refs(self) -> None:
        source = load_fixture("openapi-customer.json")
        result = import_openapi(source, source_uri="https://api.example/openapi.json")
        document = result.document
        self.assert_candidate_document(document)
        self.assertEqual(len(document["actions"]), 1)
        action = document["actions"][0]
        request = native_value(self.contract_for_port(document, action, "request"))
        response = native_value(self.contract_for_port(document, action, "response"))
        operation = source["paths"]["/customers/export"]["post"]
        self.assertEqual(request["requestBody"], operation["requestBody"])
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["path"], "/customers/export")
        self.assertEqual(response, {"responses": operation["responses"]})
        ref_warnings = [warning for warning in result.warnings if warning.code == "openapi_ref_unresolved"]
        self.assertGreaterEqual(len(ref_warnings), 3)
        self.assertTrue(all(warning.outcome == "unknown" for warning in ref_warnings))

    def test_openapi_links_callbacks_security_and_servers_are_reported_not_promoted(self) -> None:
        source = load_fixture("openapi-customer.json")
        operation = source["paths"]["/customers/export"]["post"]
        source["security"] = [{"oauth": ["export"]}]
        operation["servers"] = [{"url": "https://api.example"}]
        operation["callbacks"] = {"done": {"{$request.body#/callback}": {}}}
        operation["responses"]["200"]["links"] = {
            "next": {"operationId": "other", "parameters": {"id": "$response.body#/id"}}
        }
        result = import_openapi(source)
        self.assert_candidate_document(result.document)
        codes = {warning.code for warning in result.warnings}
        self.assertIn("openapi_security_not_authorization", codes)
        self.assertIn("openapi_operation_servers_not_resolved", codes)
        self.assertIn("openapi_callbacks_not_imported", codes)
        self.assertIn("openapi_links_not_promoted", codes)
        self.assertFalse(any(row["kind"] in {"flow", "compatibility"} for row in result.document["relations"]))

    def test_cwl_operation_fixture_preserves_each_native_port_and_stays_abstract(self) -> None:
        source = load_fixture("cwl-emit-json.json")
        result = import_cwl(source, source_uri="https://workflows.example/emit-json.cwl")
        document = result.document
        self.assert_candidate_document(document)
        self.assertEqual(len(document["actions"]), 1)
        action = document["actions"][0]
        self.assertEqual([port["id"] for port in action["ports"]], ["customer", "json_artifact"])
        customer = self.contract_for_port(document, action, "customer")
        output = self.contract_for_port(document, action, "json_artifact")
        self.assertEqual(native_value(customer), source["inputs"]["customer"])
        self.assertEqual(native_value(output), source["outputs"]["json_artifact"])
        self.assertNotIn("protocol", action)
        codes = {warning.code for warning in result.warnings}
        self.assertIn("cwl_operation_abstract", codes)
        self.assertIn("behavior_semantics_unknown", codes)

    def test_cwl_command_line_tool_maps_only_explicit_optional_syntax(self) -> None:
        source = {
            "cwlVersion": "v1.2",
            "class": "CommandLineTool",
            "id": "optional-input-tool",
            "baseCommand": "example",
            "inputs": {
                "optional_value": {"type": ["null", "string"]},
                "expression_value": {"type": "string", "inputBinding": {"valueFrom": "$(self)"}},
            },
            "outputs": {"result": {"type": "stdout"}},
            "requirements": {"ShellCommandRequirement": {}},
        }
        result = import_cwl(source)
        document = result.document
        self.assert_candidate_document(document)
        action = document["actions"][0]
        optional = next(port for port in action["ports"] if port["id"] == "optional_value")
        expression = next(port for port in action["ports"] if port["id"] == "expression_value")
        self.assertFalse(optional["required"])
        self.assertTrue(expression["required"])
        self.assertEqual(action["protocol"], {"mode": "batch"})
        codes = {warning.code for warning in result.warnings}
        self.assertIn("cwl_execution_binding_not_authorized", codes)
        self.assertIn("cwl_requirements_not_interpreted", codes)
        self.assertIn("cwl_expression_not_evaluated", codes)

    def test_imports_are_deterministic_and_do_not_mutate_sources(self) -> None:
        source = load_fixture("openapi-customer.json")
        original = deepcopy(source)
        first = import_openapi(source)
        second = import_openapi(source)
        self.assertEqual(first.document, second.document)
        self.assertEqual(first.source_digest, second.source_digest)
        self.assertEqual(source, original)

    def test_conformance_verifies_imported_data_uri_bytes_and_inline_mirror(self) -> None:
        document = import_mcp_tools(load_fixture("mcp-tools.json")).document
        contract = next(row for row in document["nodes"] if row["kind"] == "contract")
        contract["native_contract"]["digest"] = "sha256:" + ("0" * 64)
        result = validate_document(document)
        self.assertTrue(any("does not match data URI bytes" in row for row in result.errors))

        document = import_mcp_tools(load_fixture("mcp-tools.json")).document
        contract = next(row for row in document["nodes"] if row["kind"] == "contract")
        contract["native_contract"]["schema"] = {}
        result = validate_document(document)
        self.assertTrue(any("inline mirror differs from data URI" in row for row in result.errors))

    def test_wrong_top_level_formats_fail_explicitly(self) -> None:
        with self.assertRaisesRegex(ValueError, "OpenAPI 3.0.x and 3.1.x"):
            import_openapi({"swagger": "2.0", "paths": {}})
        with self.assertRaisesRegex(ValueError, "OpenAPI 3.0.x and 3.1.x"):
            import_openapi({"openapi": "3.99.0", "paths": {}})
        with self.assertRaisesRegex(ValueError, "no supported actions"):
            import_cwl({"cwlVersion": "v1.2", "class": "Workflow", "inputs": [], "outputs": []})


if __name__ == "__main__":
    unittest.main()
