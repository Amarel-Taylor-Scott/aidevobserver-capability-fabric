from __future__ import annotations

import json
import unittest

from aidevobserver_fabric.ocg_compatibility import (
    BenchmarkCase,
    CompatibilityStatus,
    check_json_schema_compatibility,
    held_out_benchmark_cases,
    run_held_out_benchmark,
)


class DirectionalCompatibilityTests(unittest.TestCase):
    def check(self, producer, consumer, **kwargs):
        return check_json_schema_compatibility(producer, consumer, **kwargs)

    def assert_status(self, expected, producer, consumer, **kwargs):
        result = self.check(producer, consumer, **kwargs)
        self.assertEqual(result.status, expected, result.to_dict())
        return result

    def test_identical_closed_object_is_safe(self) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        }
        self.assert_status(CompatibilityStatus.SAFE, schema, schema)

    def test_consumer_required_field_must_be_guaranteed(self) -> None:
        result = self.assert_status(
            CompatibilityStatus.INCOMPATIBLE,
            {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        )
        self.assertTrue(any("may omit" in reason for reason in result.counterexample_reasons))

    def test_extra_producer_requirement_is_safe(self) -> None:
        self.assert_status(
            CompatibilityStatus.SAFE,
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["id", "name"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        )

    def test_additional_properties_direction_is_enforced(self) -> None:
        result = self.assert_status(
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "object", "additionalProperties": True},
            {"type": "object", "additionalProperties": False},
        )
        self.assertTrue(
            any("undeclared properties" in reason for reason in result.counterexample_reasons)
        )

    def test_closed_producer_to_open_consumer_is_safe(self) -> None:
        self.assert_status(
            CompatibilityStatus.SAFE,
            {"type": "object", "additionalProperties": False},
            {"type": "object", "additionalProperties": True},
        )

    def test_optional_declared_extra_field_can_still_break_closed_consumer(self) -> None:
        self.assert_status(
            CompatibilityStatus.INCOMPATIBLE,
            {
                "type": "object",
                "properties": {"debug": {"type": "boolean"}},
                "additionalProperties": False,
            },
            {"type": "object", "additionalProperties": False},
        )

    def test_matching_unit_is_safe(self) -> None:
        self.assert_status(
            CompatibilityStatus.SAFE,
            {"type": "number"},
            {"type": "number"},
            producer_metadata={"unit": "m"},
            consumer_metadata={"unit": "m"},
        )

    def test_unit_mismatch_is_incompatible(self) -> None:
        result = self.assert_status(
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "number"},
            {"type": "number"},
            producer_metadata={"unit": "m"},
            consumer_metadata={"unit": "s"},
        )
        self.assertTrue(any("unit" in reason for reason in result.counterexample_reasons))

    def test_missing_required_unit_is_unknown(self) -> None:
        self.assert_status(
            CompatibilityStatus.UNKNOWN,
            {"type": "number"},
            {"type": "number"},
            consumer_metadata={"unit": "m"},
        )

    def test_semantic_concept_mismatch_is_incompatible(self) -> None:
        self.assert_status(
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "string"},
            {"type": "string"},
            producer_metadata={"semantic_concept": "urn:example:customer-id"},
            consumer_metadata={"semantic_concept": "urn:example:invoice-id"},
        )

    def test_enum_subset_is_safe(self) -> None:
        self.assert_status(
            CompatibilityStatus.SAFE,
            {"type": "string", "enum": ["a", "b"]},
            {"type": "string", "enum": ["a", "b", "c"]},
        )

    def test_enum_counterexample_is_reported(self) -> None:
        result = self.assert_status(
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "string", "enum": ["a", "b"]},
            {"type": "string", "enum": ["a"]},
        )
        self.assertTrue(any("'b'" in reason for reason in result.counterexample_reasons))

    def test_narrower_numeric_range_is_safe(self) -> None:
        self.assert_status(
            CompatibilityStatus.SAFE,
            {"type": "integer", "minimum": 1, "maximum": 9},
            {"type": "number", "minimum": 0, "maximum": 10},
        )

    def test_wider_numeric_range_is_incompatible(self) -> None:
        self.assert_status(
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "number", "minimum": -1, "maximum": 10},
            {"type": "number", "minimum": 0, "maximum": 10},
        )

    def test_exclusive_consumer_bound_rejects_inclusive_producer_bound(self) -> None:
        self.assert_status(
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "number", "minimum": 0},
            {"type": "number", "exclusiveMinimum": 0},
        )

    def test_producer_nullability_must_be_accepted(self) -> None:
        self.assert_status(
            CompatibilityStatus.INCOMPATIBLE,
            {"type": ["string", "null"]},
            {"type": "string"},
        )

    def test_consumer_may_be_more_nullable(self) -> None:
        self.assert_status(
            CompatibilityStatus.SAFE,
            {"type": "string"},
            {"type": ["string", "null"]},
        )

    def test_integer_is_directionally_compatible_with_number(self) -> None:
        self.assert_status(
            CompatibilityStatus.SAFE,
            {"type": "integer"},
            {"type": "number"},
        )
        self.assert_status(
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "number"},
            {"type": "integer"},
        )

    def test_unsupported_pattern_fails_closed_to_unknown(self) -> None:
        result = self.assert_status(
            CompatibilityStatus.UNKNOWN,
            {"type": "string", "pattern": "^[a-z]+$"},
            {"type": "string"},
        )
        self.assertTrue(any("pattern" in feature for feature in result.unsupported_features))

    def test_nested_unsupported_combinator_fails_closed(self) -> None:
        self.assert_status(
            CompatibilityStatus.UNKNOWN,
            {
                "type": "object",
                "properties": {
                    "value": {"anyOf": [{"type": "string"}, {"type": "integer"}]}
                },
            },
            {"type": "object"},
        )

    def test_non_2020_12_dialect_is_unknown(self) -> None:
        self.assert_status(
            CompatibilityStatus.UNKNOWN,
            {"$schema": "http://json-schema.org/draft-07/schema#", "type": "string"},
            {"type": "string"},
        )

    def test_unknown_port_metadata_is_unknown(self) -> None:
        self.assert_status(
            CompatibilityStatus.UNKNOWN,
            {"type": "string"},
            {"type": "string"},
            producer_metadata={"security_classification": "public"},
        )

    def test_malformed_semantic_metadata_is_unknown(self) -> None:
        self.assert_status(
            CompatibilityStatus.UNKNOWN,
            {"type": "string"},
            {"type": "string"},
            producer_metadata={"semantic_concepts": "not-an-array"},
        )

    def test_non_mapping_metadata_is_unknown_instead_of_raising(self) -> None:
        self.assert_status(
            CompatibilityStatus.UNKNOWN,
            {"type": "string"},
            {"type": "string"},
            producer_metadata=[{"embedding": [1.0]}],
        )

    def test_names_and_embeddings_cannot_authorize_bad_edge(self) -> None:
        metadata = {
            "name": "identical name",
            "embedding": [1.0, 0.0],
            "similarity": 1.0,
        }
        result = self.assert_status(
            CompatibilityStatus.INCOMPATIBLE,
            {"type": ["string", "null"]},
            {"type": "string"},
            producer_metadata=metadata,
            consumer_metadata=metadata,
        )
        self.assertEqual(
            result.ignored_retrieval_metadata,
            ("embedding", "name", "similarity"),
        )

    def test_homogeneous_array_items_are_directional(self) -> None:
        self.assert_status(
            CompatibilityStatus.SAFE,
            {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
                "minItems": 2,
                "maxItems": 4,
            },
            {
                "type": "array",
                "items": {"type": "number", "minimum": 0},
                "minItems": 1,
                "maxItems": 5,
            },
        )

    def test_false_producer_is_unknown_not_vacuously_safe(self) -> None:
        self.assert_status(CompatibilityStatus.UNKNOWN, False, {"type": "string"})

    def test_obviously_empty_integer_interval_is_not_vacuously_safe(self) -> None:
        self.assert_status(
            CompatibilityStatus.UNKNOWN,
            {"type": "integer", "minimum": 0.1, "maximum": 0.9},
            {"type": "integer"},
        )

    def test_required_impossible_child_is_not_vacuously_safe(self) -> None:
        self.assert_status(
            CompatibilityStatus.UNKNOWN,
            {
                "type": "object",
                "properties": {"id": False},
                "required": ["id"],
                "additionalProperties": False,
            },
            {"type": "object"},
        )


class HeldOutBenchmarkTests(unittest.TestCase):
    def test_default_benchmark_has_no_unsafe_safe_edges(self) -> None:
        receipt = run_held_out_benchmark()
        self.assertEqual(receipt.case_count, len(held_out_benchmark_cases()))
        self.assertEqual(receipt.safe_edge_precision, 1.0)
        self.assertEqual(receipt.incompatible_recall, 1.0)
        self.assertEqual(receipt.exact_accuracy, 1.0)
        self.assertEqual(receipt.unsafe_safe_edges, 0)
        self.assertGreater(receipt.abstention_rate, 0.0)
        self.assertGreaterEqual(receipt.latency_ms["p95"], 0.0)

    def test_benchmark_receipt_is_json_serializable(self) -> None:
        payload = run_held_out_benchmark().to_dict()
        encoded = json.dumps(payload, sort_keys=True)
        self.assertIn("safe_edge_precision", encoded)
        self.assertIn("incompatible_recall", encoded)

    def test_safe_precision_detects_an_unsafe_safe_prediction(self) -> None:
        mislabeled = BenchmarkCase(
            "mislabeled-safe-output",
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "string"},
            {"type": "string"},
        )
        receipt = run_held_out_benchmark([mislabeled])
        self.assertEqual(receipt.safe_edge_precision, 0.0)
        self.assertEqual(receipt.unsafe_safe_edges, 1)

    def test_empty_benchmark_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            run_held_out_benchmark([])


if __name__ == "__main__":
    unittest.main()
