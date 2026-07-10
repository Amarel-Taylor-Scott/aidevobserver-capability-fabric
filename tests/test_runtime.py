from __future__ import annotations

import hashlib
import json
import math
import runpy
import tempfile
import unittest
from pathlib import Path

from aidevobserver_fabric import runtime


EXPECTED_IDS = {
    "candidate.csv.profile_columns.v0",
    "prim.crypto.sha256.v1",
    "prim.date.normalize.v1",
    "prim.finance.validate_iban.v1",
    "prim.similarity.cosine.v1",
    "prim.similarity.jaro_winkler.v1",
    "prim.text.count_tokens_approx.v1",
    "prim.text.extract_email.v1",
    "prim.text.extract_phone_e164.v1",
    "prim.text.extract_url.v1",
    "prim.validation.luhn.v1",
}


class RuntimeTests(unittest.TestCase):
    def test_fixed_allowlist_has_exactly_eleven_unique_primitives(self) -> None:
        self.assertEqual(set(runtime.EXECUTABLE_PRIMITIVES), EXPECTED_IDS)
        self.assertEqual(len(runtime.list_primitives()), 11)
        with self.assertRaises(TypeError):
            runtime.EXECUTABLE_PRIMITIVES["injected"] = runtime.get_primitive("prim.crypto.sha256.v1")  # type: ignore[index]

    def test_unknown_primitive_cannot_resolve_or_execute(self) -> None:
        with self.assertRaisesRegex(KeyError, "unknown executable primitive"):
            runtime.get_primitive("prim.not.allowlisted.v1")
        with self.assertRaisesRegex(KeyError, "unknown executable primitive"):
            runtime.execute("prim.not.allowlisted.v1", {})

    def test_materialize_returns_exact_source_contracts_and_digest(self) -> None:
        materialized = runtime.materialize("prim.text.extract_email.v1")
        self.assertEqual(materialized["primitive_id"], "prim.text.extract_email.v1")
        self.assertEqual(materialized["runtime"], "python_stdlib")
        self.assertEqual(materialized["license_spdx"], "MIT")
        self.assertIn("def run(inputs:", materialized["source"])
        self.assertEqual(
            materialized["source_sha256"],
            hashlib.sha256(materialized["source"].encode("utf-8")).hexdigest(),
        )
        self.assertEqual(materialized["input_schema"]["required"], ["text"])
        self.assertEqual(len(materialized["proof_fixtures"]), 2)
        self.assertIn("def execute(inputs):", materialized["source"])
        json.dumps(materialized)

    def test_every_materialized_module_carries_and_enforces_its_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for primitive_id in sorted(EXPECTED_IDS):
                with self.subTest(primitive_id=primitive_id):
                    artifact = runtime.materialize(primitive_id)
                    path = Path(tmp) / f"{primitive_id.replace('.', '_')}.py"
                    path.write_text(artifact["source"], encoding="utf-8")
                    module = runpy.run_path(str(path))
                    execute = module["execute"]
                    for fixture in artifact["proof_fixtures"]:
                        self.assertEqual(execute(fixture["input"]), fixture["expected"])
                    invalid = dict(artifact["proof_fixtures"][0]["input"])
                    invalid["__unexpected_contract_field"] = True
                    with self.assertRaises(module["PrimitiveContractError"]):
                        execute(invalid)

            jaro = runpy.run_path(str(Path(tmp) / "prim_similarity_jaro_winkler_v1.py"))
            with self.assertRaises(jaro["PrimitiveContractError"]):
                jaro["execute"]({"a": "x" * 2049, "b": "y"})
            cosine = runpy.run_path(str(Path(tmp) / "prim_similarity_cosine_v1.py"))
            with self.assertRaises(cosine["PrimitiveContractError"]):
                cosine["execute"]({"a": [10**400], "b": [1]})

    def test_execute_validates_required_types_and_extra_fields(self) -> None:
        with self.assertRaisesRegex(runtime.SchemaValidationError, "missing required property 'text'"):
            runtime.execute("prim.text.extract_email.v1", {})
        with self.assertRaisesRegex(runtime.SchemaValidationError, "expected string"):
            runtime.execute("prim.text.extract_email.v1", {"text": 5})
        with self.assertRaisesRegex(runtime.SchemaValidationError, "unexpected properties"):
            runtime.execute("prim.text.extract_email.v1", {"text": "x", "surprise": True})

    def test_execute_does_not_mutate_input(self) -> None:
        payload = {"text": "alice@example.com and ALICE@example.com"}
        original = dict(payload)
        result = runtime.execute("prim.text.extract_email.v1", payload)
        self.assertEqual(payload, original)
        self.assertEqual(result, {"emails": ["alice@example.com"], "count": 1})

    def test_ported_primitives_execute_known_examples(self) -> None:
        cases = {
            "prim.text.extract_url.v1": (
                {"text": "Read https://example.com/a)."},
                {"urls": ["https://example.com/a"], "count": 1},
            ),
            "prim.date.normalize.v1": (
                {"date": "09/07/2026"},
                {"input": "09/07/2026", "iso8601": "2026-07-09", "ok": True},
            ),
            "prim.validation.luhn.v1": (
                {"value": "4539-1488-0343-6467"},
                {"value": "4539-1488-0343-6467", "digits": "4539148803436467", "valid": True, "digit_count": 16},
            ),
            "prim.similarity.cosine.v1": (
                {"a": [1, 0], "b": [-1, 0]},
                {"score": -1.0, "dim": 2},
            ),
            "prim.crypto.sha256.v1": (
                {"payload": "abc"},
                {"sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "byte_count": 3},
            ),
        }
        for primitive_id, (payload, expected) in cases.items():
            with self.subTest(primitive_id=primitive_id):
                self.assertEqual(runtime.execute(primitive_id, payload), expected)

    def test_runner_domain_errors_remain_explicit(self) -> None:
        with self.assertRaisesRegex(ValueError, "length mismatch: 2 vs 1"):
            runtime.execute("prim.similarity.cosine.v1", {"a": [1, 2], "b": [1]})

    def test_non_finite_numbers_and_unknown_encodings_fail_contract_validation(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaisesRegex(runtime.SchemaValidationError, "number must be finite"):
                runtime.execute("prim.similarity.cosine.v1", {"a": [value], "b": [1.0]})
        with self.assertRaisesRegex(runtime.SchemaValidationError, "not in enum"):
            runtime.execute("prim.crypto.sha256.v1", {"payload": "x", "encoding": "unknown-codec"})
        with self.assertRaisesRegex(runtime.SchemaValidationError, "above maximum"):
            runtime.execute("prim.similarity.cosine.v1", {"a": [10**400], "b": [1]})
        with self.assertRaisesRegex(runtime.SchemaValidationError, "longer than 2048"):
            runtime.execute("prim.similarity.jaro_winkler.v1", {"a": "x" * 2049, "b": "y"})
        with self.assertRaisesRegex(runtime.SchemaValidationError, "longer than 10000"):
            runtime.execute("prim.validation.luhn.v1", {"value": "1" * 10_001})

    def test_cosine_is_stable_for_extreme_finite_values(self) -> None:
        result = runtime.execute("prim.similarity.cosine.v1", {"a": [1e308], "b": [-1e308]})
        self.assertEqual(result, {"score": -1.0, "dim": 1})

    def test_iban_rejects_checksum_valid_unsupported_country(self) -> None:
        result = runtime.execute("prim.finance.validate_iban.v1", {"iban": "ZZ92ABCD1234567890"})
        self.assertFalse(result["valid"])
        self.assertIn("country_unsupported", result["reasons"])

    def test_iban_accepts_current_swift_registry_country_formats(self) -> None:
        official_examples = {
            "DJ": "DJ2100010000000154000100186",
            "OM": "OM810180000001299123456",
            "SC": "SC18SSCB11010000000000001497USD",
            "SD": "SD2129010501234001",
        }
        for country, iban in official_examples.items():
            with self.subTest(country=country):
                self.assertEqual(
                    runtime.execute("prim.finance.validate_iban.v1", {"iban": iban}),
                    {"iban": iban, "valid": True, "reasons": [], "country": country},
                )

    def test_token_approximation_rounds_non_cjk_text_up(self) -> None:
        method = "ceil(non-cjk-chars/4) + 1-per-cjk-char"
        cases = {
            "": (0, 0),
            "a": (0, 1),
            "abcd": (0, 1),
            "abcde": (0, 2),
            "hello世界": (2, 4),
        }
        for text, (cjk_count, approx_tokens) in cases.items():
            with self.subTest(text=text):
                self.assertEqual(
                    runtime.execute("prim.text.count_tokens_approx.v1", {"text": text}),
                    {
                        "char_count": len(text),
                        "cjk_char_count": cjk_count,
                        "approx_tokens": approx_tokens,
                        "method": method,
                    },
                )

    def test_phone_and_luhn_reject_non_ascii_digits(self) -> None:
        for value in ("Call +1 ٢١٢ ٥٥٥ ٠١٠٠", "Call +１ ２１２ ５５５ ０１００"):
            result = runtime.execute("prim.text.extract_phone_e164.v1", {"text": value})
            self.assertEqual(result, {"phones_e164": [], "count": 0})
        self.assertEqual(
            runtime.execute("prim.text.extract_phone_e164.v1", {"text": "+0 123 456 7890"}),
            {"phones_e164": [], "count": 0},
        )
        luhn = runtime.execute("prim.validation.luhn.v1", {"value": "٤٥٣٩١٤٨٨٠٣٤٣٦٤٦٧"})
        self.assertFalse(luhn["valid"])

    def test_url_extraction_rejects_missing_hosts_and_preserves_balanced_paths(self) -> None:
        invalid = runtime.execute("prim.text.extract_url.v1", {"text": "See http://. and https://? now"})
        self.assertEqual(invalid, {"urls": [], "count": 0})
        balanced = runtime.execute(
            "prim.text.extract_url.v1",
            {"text": "See https://example.com/path_(x) and (https://example.org/a)."},
        )
        self.assertEqual(
            balanced["urls"],
            ["https://example.com/path_(x)", "https://example.org/a"],
        )

    def test_runtime_metadata_and_source_are_captured_immutably(self) -> None:
        spec = runtime.get_primitive("prim.text.extract_email.v1")
        schema = spec.input_schema
        schema["required"].clear()
        self.assertEqual(spec.input_schema["required"], ["text"])
        self.assertEqual(spec.source(), spec.source_text)
        proof = spec.prove()
        self.assertEqual(proof["proof_subject"], "loaded_callable_bound_to_captured_source")
        self.assertRegex(proof["runner_source_sha256"], r"^[a-f0-9]{64}$")

    def test_csv_profiler_is_executable_and_profiles_ragged_rows(self) -> None:
        result = runtime.execute(
            "candidate.csv.profile_columns.v0",
            {"csv_text": "id,id,score\n1,A,2.5\n2,,3.5\n3,B\n"},
        )
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["column_count"], 3)
        self.assertEqual([column["name"] for column in result["columns"]], ["id", "id_2", "score"])
        self.assertEqual(result["columns"][0]["inferred_type"], "integer")
        self.assertEqual(result["columns"][1]["null_count"], 1)
        self.assertEqual(result["columns"][2]["inferred_type"], "number")
        self.assertEqual(result["columns"][2]["null_count"], 1)

    def test_csv_profiler_empty_input_is_well_formed(self) -> None:
        self.assertEqual(
            runtime.execute("candidate.csv.profile_columns.v0", {"csv_text": ""}),
            {"delimiter": ",", "row_count": 0, "sampled_row_count": 0, "column_count": 0, "columns": []},
        )

    def test_csv_profiler_accepts_declared_large_field(self) -> None:
        value = "x" * 140_000
        result = runtime.execute("candidate.csv.profile_columns.v0", {"csv_text": f"payload\n{value}\n"})
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["columns"][0]["examples"], [value])

    def test_csv_profiler_rejects_column_amplification(self) -> None:
        csv_text = ",".join([""] * 4097) + "\n"
        with self.assertRaisesRegex(ValueError, "maximum is 4096"):
            runtime.execute("candidate.csv.profile_columns.v0", {"csv_text": csv_text})
        work_bomb = ",".join([f"c{index}" for index in range(4096)]) + "\n" + ("\n" * 1221)
        with self.assertRaisesRegex(ValueError, "sampled cells; maximum is 5000000"):
            runtime.execute("candidate.csv.profile_columns.v0", {"csv_text": work_bomb})

    def test_csv_profiler_streams_newline_heavy_inputs(self) -> None:
        result = runtime.execute("candidate.csv.profile_columns.v0", {"csv_text": "\n" * 100_000})
        self.assertEqual(result["row_count"], 99_999)
        self.assertEqual(result["column_count"], 0)

    def test_each_proof_receipt_is_passing_and_reproducible(self) -> None:
        for primitive_id in sorted(EXPECTED_IDS):
            with self.subTest(primitive_id=primitive_id):
                first = runtime.prove(primitive_id)
                second = runtime.prove(primitive_id)
                self.assertTrue(first["passed"], first["failures"])
                self.assertTrue(first["deterministic"])
                self.assertEqual(first, second)
                self.assertEqual(first["cases_run"], first["cases_passed"])
                self.assertRegex(first["receipt_id"], r"^proof\.[a-f0-9]{64}$")
                self.assertRegex(first["source_sha256"], r"^[a-f0-9]{64}$")
                self.assertRegex(first["fixture_sha256"], r"^[a-f0-9]{64}$")

    def test_prove_all_reports_eleven_passing_receipts(self) -> None:
        proof = runtime.prove_all()
        self.assertTrue(proof["passed"])
        self.assertEqual(proof["primitive_count"], 11)
        self.assertEqual(proof["passed_count"], 11)
        self.assertEqual(len(proof["receipts"]), 11)


if __name__ == "__main__":
    unittest.main()
