"""Allowlisted execution and deterministic proof for packaged primitives.

This module intentionally has no dynamic import, ``eval``, shell, or arbitrary
path mechanism.  Only the module objects named in ``_ALLOWED_MODULES`` can be
materialized or executed.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType, ModuleType
from typing import Any, Callable, Mapping

from .primitives import (
    cosine_similarity,
    count_tokens_approx,
    csv_profile_columns,
    extract_email,
    extract_phone_e164,
    extract_url,
    fuzzy_jaro_winkler,
    normalize_date,
    sha256_hash,
    validate_iban,
    validate_luhn,
)

JsonObject = dict[str, Any]
Runner = Callable[[dict[str, Any]], dict[str, Any]]

MATERIALIZED_VALIDATOR_SOURCE = r'''# Self-contained contract wrapper added by AIDevObserver materialization.
import copy as _ado_copy
import json as _ado_json
import math as _ado_math
import re as _ado_re


class PrimitiveContractError(ValueError):
    pass


def _ado_type(expected, value):
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    raise PrimitiveContractError(f"{expected!r} is not a supported schema type")


def _ado_validate(schema, value, path="$"):
    expected = schema.get("type")
    if expected is not None:
        types = [expected] if isinstance(expected, str) else list(expected)
        if not any(_ado_type(item, value) for item in types):
            raise PrimitiveContractError(f"{path}: contract type mismatch")
        if value is None:
            return
    if "enum" in schema and value not in schema["enum"]:
        raise PrimitiveContractError(f"{path}: value is not in enum")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise PrimitiveContractError(f"{path}: missing required property {key!r}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise PrimitiveContractError(f"{path}: unexpected properties {extras!r}")
        for key, item in value.items():
            if key in properties:
                _ado_validate(properties[key], item, f"{path}.{key}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise PrimitiveContractError(f"{path}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise PrimitiveContractError(f"{path}: too many items")
        if schema.get("uniqueItems"):
            encoded = [_ado_json.dumps(item, allow_nan=False, sort_keys=True) for item in value]
            if len(encoded) != len(set(encoded)):
                raise PrimitiveContractError(f"{path}: items must be unique")
        if schema.get("items"):
            for index, item in enumerate(value):
                _ado_validate(schema["items"], item, f"{path}[{index}]")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise PrimitiveContractError(f"{path}: string is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise PrimitiveContractError(f"{path}: string is too long")
        if "pattern" in schema and _ado_re.search(schema["pattern"], value) is None:
            raise PrimitiveContractError(f"{path}: string format is invalid")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not _ado_math.isfinite(value):
            raise PrimitiveContractError(f"{path}: number must be finite")
        if "minimum" in schema and value < schema["minimum"]:
            raise PrimitiveContractError(f"{path}: number is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise PrimitiveContractError(f"{path}: number is above maximum")


_ado_run_unchecked = run


def execute(inputs):
    if not isinstance(inputs, dict):
        raise PrimitiveContractError("$: input must be an object")
    copied = _ado_copy.deepcopy(inputs)
    _ado_validate(INPUT_SCHEMA, copied)
    output = _ado_run_unchecked(copied)
    _ado_validate(OUTPUT_SCHEMA, output, "output $")
    return _ado_copy.deepcopy(output)


# Preserve the familiar callable name without exposing an unchecked path.
run = execute
'''


class SchemaValidationError(ValueError):
    """Raised when a primitive payload violates its declared JSON schema."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_type_matches(expected: str, value: Any) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    raise SchemaValidationError(f"unsupported JSON schema type {expected!r}")


def validate_json(schema: Mapping[str, Any], value: Any, path: str = "$") -> None:
    """Validate the JSON-Schema subset used by packaged primitive contracts."""

    expected_types = schema.get("type")
    if expected_types is not None:
        types = [expected_types] if isinstance(expected_types, str) else list(expected_types)
        if not any(_json_type_matches(expected, value) for expected in types):
            rendered = "|".join(types)
            raise SchemaValidationError(f"{path}: expected {rendered}, got {type(value).__name__}")
        if value is None:
            return

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{path}: value is not in enum {schema['enum']!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise SchemaValidationError(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unexpected = sorted(set(value) - set(properties))
            if unexpected:
                raise SchemaValidationError(f"{path}: unexpected properties {unexpected!r}")
        for key, item in value.items():
            if key in properties:
                validate_json(properties[key], item, f"{path}.{key}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaValidationError(f"{path}: expected at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaValidationError(f"{path}: expected at most {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            encoded = [_canonical_json(item) for item in value]
            if len(encoded) != len(set(encoded)):
                raise SchemaValidationError(f"{path}: items must be unique")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_json(item_schema, item, f"{path}[{index}]")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SchemaValidationError(f"{path}: string is shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SchemaValidationError(f"{path}: string is longer than {schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise SchemaValidationError(f"{path}: string does not match {schema['pattern']!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise SchemaValidationError(f"{path}: number must be finite")
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaValidationError(f"{path}: value is below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaValidationError(f"{path}: value is above maximum {schema['maximum']}")


@dataclass(frozen=True, slots=True)
class ExecutablePrimitive:
    """A packaged implementation with contracts and deterministic oracles."""

    primitive_id: str
    label: str
    description: str
    module: ModuleType
    runner: Runner
    source_text: str
    runner_source_sha256: str
    _input_schema_json: str
    _output_schema_json: str
    _proof_fixtures_json: str
    license_spdx: str = "MIT"

    @property
    def input_schema(self) -> Mapping[str, Any]:
        return json.loads(self._input_schema_json)

    @property
    def output_schema(self) -> Mapping[str, Any]:
        return json.loads(self._output_schema_json)

    @property
    def proof_fixtures(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(json.loads(self._proof_fixtures_json))

    @property
    def entrypoint(self) -> str:
        return f"{self.module.__name__}:run"

    def source(self) -> str:
        """Return exact source for this fixed, packaged module."""

        return self.source_text

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.source().encode("utf-8")).hexdigest()

    @property
    def fixture_sha256(self) -> str:
        return hashlib.sha256(self._proof_fixtures_json.encode("utf-8")).hexdigest()

    def materialize(self) -> dict[str, Any]:
        """Return source, contracts, provenance, and public proof fixtures."""

        return {
            "primitive_id": self.primitive_id,
            "label": self.label,
            "description": self.description,
            "runtime": "python_stdlib",
            "entrypoint": self.entrypoint,
            "license_spdx": self.license_spdx,
            "source_sha256": self.source_sha256,
            "fixture_sha256": self.fixture_sha256,
            "runner_source_sha256": self.runner_source_sha256,
            "proof_subject": "loaded_callable_bound_to_captured_source",
            "source": self.source(),
            "input_schema": copy.deepcopy(dict(self.input_schema)),
            "output_schema": copy.deepcopy(dict(self.output_schema)),
            "proof_fixtures": copy.deepcopy(list(self.proof_fixtures)),
        }

    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate, copy, run, and validate one JSON-compatible payload."""

        if not isinstance(payload, Mapping):
            raise SchemaValidationError(f"$: expected object, got {type(payload).__name__}")
        input_value = copy.deepcopy(dict(payload))
        validate_json(self.input_schema, input_value)
        output = self.runner(input_value)
        if not isinstance(output, dict):
            raise SchemaValidationError(f"output $: expected object, got {type(output).__name__}")
        validate_json(self.output_schema, output, path="output $")
        return copy.deepcopy(output)

    def prove(self) -> dict[str, Any]:
        """Execute each oracle twice and return a reproducible proof receipt."""

        failures: list[dict[str, str]] = []
        passed = 0
        fixtures = self.proof_fixtures
        for fixture in fixtures:
            name = str(fixture["name"])
            try:
                expected = copy.deepcopy(fixture["expected"])
                first = self.execute(fixture["input"])
                second = self.execute(fixture["input"])
                if first != second:
                    failures.append({"fixture": name, "error": "nondeterministic_output"})
                elif first != expected:
                    failures.append(
                        {
                            "fixture": name,
                            "error": f"oracle_mismatch expected={_canonical_json(expected)} actual={_canonical_json(first)}",
                        }
                    )
                else:
                    passed += 1
            except Exception as exc:  # receipt captures the bounded fixture failure
                failures.append({"fixture": name, "error": f"{type(exc).__name__}: {exc}"})

        receipt_material = {
            "primitive_id": self.primitive_id,
            "source_sha256": self.source_sha256,
            "fixture_sha256": self.fixture_sha256,
            "runner_source_sha256": self.runner_source_sha256,
            "proof_subject": "loaded_callable_bound_to_captured_source",
            "proof_version": 1,
            "cases_run": len(fixtures),
            "cases_passed": passed,
            "failures": failures,
        }
        receipt_id = "proof." + hashlib.sha256(_canonical_json(receipt_material).encode("utf-8")).hexdigest()
        return {
            "receipt_id": receipt_id,
            **receipt_material,
            "passed": not failures and passed == len(fixtures),
            "deterministic": not any(item["error"] == "nondeterministic_output" for item in failures),
            "license_spdx": self.license_spdx,
        }


_ALLOWED_MODULES = (
    extract_email,
    extract_url,
    extract_phone_e164,
    normalize_date,
    validate_iban,
    validate_luhn,
    count_tokens_approx,
    fuzzy_jaro_winkler,
    cosine_similarity,
    sha256_hash,
    csv_profile_columns,
)


def _spec_from_module(module: ModuleType) -> ExecutablePrimitive:
    source_text = inspect.getsource(module).rstrip() + "\n\n" + MATERIALIZED_VALIDATOR_SOURCE
    runner_source = inspect.getsource(module.run)
    return ExecutablePrimitive(
        primitive_id=module.PRIMITIVE_ID,
        label=module.LABEL,
        description=module.DESCRIPTION,
        module=module,
        runner=module.run,
        source_text=source_text,
        runner_source_sha256=hashlib.sha256(runner_source.encode("utf-8")).hexdigest(),
        _input_schema_json=_canonical_json(module.INPUT_SCHEMA),
        _output_schema_json=_canonical_json(module.OUTPUT_SCHEMA),
        _proof_fixtures_json=_canonical_json(module.PROOF_FIXTURES),
        license_spdx=module.LICENSE_SPDX,
    )


_specs = tuple(_spec_from_module(module) for module in _ALLOWED_MODULES)
if len({spec.primitive_id for spec in _specs}) != len(_specs):
    raise RuntimeError("duplicate executable primitive_id in fixed allowlist")

EXECUTABLE_PRIMITIVES: Mapping[str, ExecutablePrimitive] = MappingProxyType(
    {spec.primitive_id: spec for spec in _specs}
)


def get_primitive(primitive_id: str) -> ExecutablePrimitive:
    try:
        return EXECUTABLE_PRIMITIVES[primitive_id]
    except KeyError:
        raise KeyError(f"unknown executable primitive: {primitive_id}") from None


def list_primitives() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "primitive_id": spec.primitive_id,
            "label": spec.label,
            "description": spec.description,
            "runtime": "python_stdlib",
            "entrypoint": spec.entrypoint,
            "license_spdx": spec.license_spdx,
            "source_sha256": spec.source_sha256,
            "fixture_sha256": spec.fixture_sha256,
            "proof_fixture_count": len(spec.proof_fixtures),
        }
        for spec in sorted(EXECUTABLE_PRIMITIVES.values(), key=lambda item: item.primitive_id)
    )


def materialize(primitive_id: str) -> dict[str, Any]:
    return get_primitive(primitive_id).materialize()


def execute(primitive_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return get_primitive(primitive_id).execute(payload)


def prove(primitive_id: str) -> dict[str, Any]:
    return get_primitive(primitive_id).prove()


def prove_all() -> dict[str, Any]:
    receipts = [prove(primitive_id) for primitive_id in sorted(EXECUTABLE_PRIMITIVES)]
    return {
        "primitive_count": len(receipts),
        "passed_count": sum(1 for receipt in receipts if receipt["passed"]),
        "passed": all(receipt["passed"] for receipt in receipts),
        "receipts": receipts,
    }


__all__ = [
    "EXECUTABLE_PRIMITIVES",
    "ExecutablePrimitive",
    "SchemaValidationError",
    "execute",
    "get_primitive",
    "list_primitives",
    "materialize",
    "prove",
    "prove_all",
    "validate_json",
]
