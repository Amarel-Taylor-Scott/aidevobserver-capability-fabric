"""Conservative directional compatibility checks for a JSON Schema subset.

The question answered here is deliberately narrow::

    Are all values admitted by the producer schema also admitted by the
    consumer schema, under the declared port metadata?

``safe`` means that inclusion was established for the subset implemented by
this module.  It is planning evidence, not execution authorization.  ``unknown``
is the fail-closed answer whenever the checker encounters a keyword, dialect,
or metadata constraint it does not understand.  ``incompatible`` means the
checker found a reason that the producer admits at least one value rejected by
the consumer.

Supported Draft 2020-12 validation keywords are:

* ``type``, ``enum``, and ``const``;
* ``minimum``, ``exclusiveMinimum``, ``maximum``, and
  ``exclusiveMaximum``;
* ``minLength`` and ``maxLength``;
* ``properties``, ``required``, and ``additionalProperties``;
* homogeneous ``items``, ``minItems``, and ``maxItems``.

The standard identification and annotation keywords ``$schema``, ``$id``,
``$comment``, ``title``, and ``description`` are accepted but do not affect
compatibility.  Boolean schemas are supported.  Every other schema keyword,
including ``$ref``, combinators, conditionals, regex/format constraints,
``patternProperties``, and ``unevaluatedProperties``, produces ``unknown``.

Port metadata supports exact consumer requirements for ``unit``,
``semantic_concept``/``semantic_concepts``, ``media_type``, ``encoding``, and
``protocol``.  Names, labels, descriptions, aliases, embeddings, similarity,
and search scores are explicitly retrieval-only and are ignored.  They can
never turn an unknown or incompatible edge into a safe edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
import math
from statistics import fmean, median
from time import perf_counter_ns
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


CHECKER_ID = "ocg-json-schema-directional-subset"
CHECKER_VERSION = "0.1.0"
HELD_OUT_BENCHMARK_ID = "ocg-json-schema-held-out-v0.1"


class CompatibilityStatus(str, Enum):
    """A fail-closed directional compatibility outcome."""

    SAFE = "safe"
    UNKNOWN = "unknown"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class CompatibilityResult:
    """Result of a producer-to-consumer compatibility check."""

    status: CompatibilityStatus
    reasons: tuple[str, ...]
    counterexample_reasons: tuple[str, ...] = ()
    unsupported_features: tuple[str, ...] = ()
    ignored_retrieval_metadata: tuple[str, ...] = ()
    checker_id: str = CHECKER_ID
    checker_version: str = CHECKER_VERSION

    @property
    def safe(self) -> bool:
        return self.status is CompatibilityStatus.SAFE

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reasons": list(self.reasons),
            "counterexample_reasons": list(self.counterexample_reasons),
            "unsupported_features": list(self.unsupported_features),
            "ignored_retrieval_metadata": list(self.ignored_retrieval_metadata),
            "checker": {"id": self.checker_id, "version": self.checker_version},
        }


@dataclass(frozen=True)
class BenchmarkCase:
    """One labeled case kept separate from the checker implementation."""

    case_id: str
    label: CompatibilityStatus
    producer_schema: Any
    consumer_schema: Any
    producer_metadata: Mapping[str, Any] = field(default_factory=dict)
    consumer_metadata: Mapping[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class BenchmarkCaseReceipt:
    case_id: str
    expected: CompatibilityStatus
    predicted: CompatibilityStatus
    latency_ms: float
    reasons: tuple[str, ...]
    counterexample_reasons: tuple[str, ...]
    description: str = ""

    @property
    def correct(self) -> bool:
        return self.expected is self.predicted

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "expected": self.expected.value,
            "predicted": self.predicted.value,
            "correct": self.correct,
            "latency_ms": self.latency_ms,
            "reasons": list(self.reasons),
            "counterexample_reasons": list(self.counterexample_reasons),
            "description": self.description,
        }


@dataclass(frozen=True)
class BenchmarkReceipt:
    """Executed quality and latency receipt for labeled compatibility cases."""

    benchmark_id: str
    checker_id: str
    checker_version: str
    generated_at: str
    case_count: int
    label_counts: Mapping[str, int]
    prediction_counts: Mapping[str, int]
    safe_edge_precision: float | None
    incompatible_recall: float | None
    abstention_rate: float
    exact_accuracy: float
    unsafe_safe_edges: int
    latency_ms: Mapping[str, float]
    cases: tuple[BenchmarkCaseReceipt, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "checker": {"id": self.checker_id, "version": self.checker_version},
            "generated_at": self.generated_at,
            "case_count": self.case_count,
            "label_counts": dict(self.label_counts),
            "prediction_counts": dict(self.prediction_counts),
            "metrics": {
                "safe_edge_precision": self.safe_edge_precision,
                "incompatible_recall": self.incompatible_recall,
                "abstention_rate": self.abstention_rate,
                "exact_accuracy": self.exact_accuracy,
                "unsafe_safe_edges": self.unsafe_safe_edges,
            },
            "latency_ms": dict(self.latency_ms),
            "cases": [case.to_dict() for case in self.cases],
        }


_SCHEMA_KEYWORDS = {
    "$schema",
    "$id",
    "$comment",
    "title",
    "description",
    "type",
    "enum",
    "const",
    "minimum",
    "exclusiveMinimum",
    "maximum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
}
_SCHEMA_CHILD_MAPS = {"properties"}
_SCHEMA_CHILDREN = {"additionalProperties", "items"}
_DRAFT_2020_12_URIS = {
    "https://json-schema.org/draft/2020-12/schema",
    "https://json-schema.org/draft/2020-12/schema#",
}
_JSON_TYPES = ("null", "boolean", "object", "array", "number", "integer", "string")
_SEMANTIC_METADATA = {
    "unit",
    "semantic_concept",
    "semantic_concepts",
    "media_type",
    "encoding",
    "protocol",
}
_RETRIEVAL_ONLY_METADATA = {
    "name",
    "label",
    "description",
    "aliases",
    "keywords",
    "embedding",
    "embeddings",
    "embedding_space",
    "similarity",
    "similarity_score",
    "search_score",
}


@dataclass
class _Findings:
    unknown: list[str] = field(default_factory=list)
    incompatible: list[str] = field(default_factory=list)

    def extend(self, other: "_Findings") -> None:
        self.unknown.extend(other.unknown)
        self.incompatible.extend(other.incompatible)


def check_json_schema_compatibility(
    producer_schema: Any,
    consumer_schema: Any,
    *,
    producer_metadata: Mapping[str, Any] | None = None,
    consumer_metadata: Mapping[str, Any] | None = None,
) -> CompatibilityResult:
    """Check directional inclusion for the documented Draft 2020-12 subset.

    The function never considers a name, embedding, similarity score, or other
    retrieval signal when determining the status.
    """

    producer_metadata = producer_metadata or {}
    consumer_metadata = consumer_metadata or {}

    unsupported = sorted(
        set(_unsupported_schema_features(producer_schema, "/producer"))
        | set(_unsupported_schema_features(consumer_schema, "/consumer"))
        | set(_unsupported_metadata_features(producer_metadata, "/producer_metadata"))
        | set(_unsupported_metadata_features(consumer_metadata, "/consumer_metadata"))
    )
    producer_metadata_keys = (
        set(producer_metadata) if isinstance(producer_metadata, Mapping) else set()
    )
    consumer_metadata_keys = (
        set(consumer_metadata) if isinstance(consumer_metadata, Mapping) else set()
    )
    ignored = tuple(
        sorted(
            (producer_metadata_keys | consumer_metadata_keys)
            & _RETRIEVAL_ONLY_METADATA
        )
    )
    if unsupported:
        return CompatibilityResult(
            status=CompatibilityStatus.UNKNOWN,
            reasons=("unsupported schema or port-metadata features require abstention",),
            unsupported_features=tuple(unsupported),
            ignored_retrieval_metadata=ignored,
        )

    schema_errors = _schema_errors(producer_schema, "/producer") + _schema_errors(
        consumer_schema, "/consumer"
    )
    if schema_errors:
        return CompatibilityResult(
            status=CompatibilityStatus.UNKNOWN,
            reasons=tuple(schema_errors),
            ignored_retrieval_metadata=ignored,
        )

    unsatisfiable = _obvious_unsatisfiable(producer_schema, "/producer")
    if unsatisfiable:
        return CompatibilityResult(
            status=CompatibilityStatus.UNKNOWN,
            reasons=(
                "the producer is obviously unsatisfiable; "
                "vacuous inclusion is not promoted to safe",
                *unsatisfiable,
            ),
            ignored_retrieval_metadata=ignored,
        )

    findings = _compare_metadata(producer_metadata, consumer_metadata)
    findings.extend(_compare_schemas(producer_schema, consumer_schema, "$"))

    if findings.incompatible:
        return CompatibilityResult(
            status=CompatibilityStatus.INCOMPATIBLE,
            reasons=("producer admits a value or meaning rejected by the consumer",),
            counterexample_reasons=tuple(_dedupe(findings.incompatible)),
            ignored_retrieval_metadata=ignored,
        )
    if findings.unknown:
        return CompatibilityResult(
            status=CompatibilityStatus.UNKNOWN,
            reasons=tuple(_dedupe(findings.unknown)),
            ignored_retrieval_metadata=ignored,
        )
    return CompatibilityResult(
        status=CompatibilityStatus.SAFE,
        reasons=(
            "all producer-admitted values satisfy the consumer constraints in the supported subset",
            "retrieval metadata did not participate in the decision",
        ),
        ignored_retrieval_metadata=ignored,
    )


def _unsupported_schema_features(schema: Any, path: str) -> list[str]:
    if isinstance(schema, bool):
        return []
    if not isinstance(schema, Mapping):
        return [f"{path}: schema must be an object or boolean"]

    issues: list[str] = []
    for key in schema:
        if key not in _SCHEMA_KEYWORDS:
            issues.append(f"{path}/{_pointer(key)}: unsupported keyword {key!r}")
    dialect = schema.get("$schema")
    if dialect is not None and dialect not in _DRAFT_2020_12_URIS:
        issues.append(f"{path}/$schema: unsupported dialect {dialect!r}")

    for key in _SCHEMA_CHILD_MAPS:
        children = schema.get(key)
        if isinstance(children, Mapping):
            for name, child in children.items():
                issues.extend(
                    _unsupported_schema_features(
                        child, f"{path}/{key}/{_pointer(str(name))}"
                    )
                )
    for key in _SCHEMA_CHILDREN:
        if key in schema:
            issues.extend(_unsupported_schema_features(schema[key], f"{path}/{key}"))
    return issues


def _unsupported_metadata_features(metadata: Mapping[str, Any], path: str) -> list[str]:
    if not isinstance(metadata, Mapping):
        return [f"{path}: port metadata must be an object"]
    supported = _SEMANTIC_METADATA | _RETRIEVAL_ONLY_METADATA
    issues = [
        f"{path}/{_pointer(str(key))}: unsupported port metadata {key!r}"
        for key in metadata
        if key not in supported
    ]
    for key in ("unit", "semantic_concept", "media_type", "encoding", "protocol"):
        if key in metadata and not isinstance(metadata[key], str):
            issues.append(f"{path}/{key}: semantic metadata value must be a string")
    if "semantic_concepts" in metadata:
        concepts = metadata["semantic_concepts"]
        if (
            not isinstance(concepts, Sequence)
            or isinstance(concepts, (str, bytes))
            or not all(isinstance(value, str) for value in concepts)
        ):
            issues.append(
                f"{path}/semantic_concepts: value must be an array of strings"
            )
    return issues


def _schema_errors(schema: Any, path: str) -> list[str]:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        location = "/".join(str(part) for part in exc.absolute_path)
        suffix = f"/{location}" if location else ""
        return [f"{path}{suffix}: invalid Draft 2020-12 schema: {exc.message}"]
    return []


def _compare_metadata(
    producer: Mapping[str, Any], consumer: Mapping[str, Any]
) -> _Findings:
    findings = _Findings()
    for key in ("unit", "media_type", "encoding", "protocol"):
        if key not in consumer:
            continue
        if key not in producer:
            findings.unknown.append(
                f"port metadata: consumer requires {key}={consumer[key]!r}, "
                "but producer does not declare it"
            )
        elif producer[key] != consumer[key]:
            findings.incompatible.append(
                f"port metadata: producer {key}={producer[key]!r} differs from "
                f"consumer {key}={consumer[key]!r}"
            )

    producer_concepts = _concepts(producer)
    consumer_concepts = _concepts(consumer)
    if consumer_concepts is not None:
        if producer_concepts is None:
            findings.unknown.append(
                "port metadata: consumer declares semantic concepts, but producer does not"
            )
        elif producer_concepts != consumer_concepts:
            findings.incompatible.append(
                "port metadata: producer semantic concepts "
                f"{sorted(producer_concepts)!r} differ from consumer concepts "
                f"{sorted(consumer_concepts)!r}"
            )
    return findings


def _concepts(metadata: Mapping[str, Any]) -> frozenset[str] | None:
    singular = metadata.get("semantic_concept")
    plural = metadata.get("semantic_concepts")
    if singular is None and plural is None:
        return None
    values: list[Any] = []
    if singular is not None:
        values.append(singular)
    if plural is not None:
        if not isinstance(plural, Sequence) or isinstance(plural, (str, bytes)):
            return frozenset({repr(plural)})
        values.extend(plural)
    return frozenset(str(value) for value in values)


def _compare_schemas(producer: Any, consumer: Any, path: str) -> _Findings:
    findings = _Findings()
    if producer is False:
        findings.unknown.append(
            f"{path}: false producer schema is vacuous and is not promoted to safe"
        )
        return findings
    if consumer is True:
        return findings
    if consumer is False:
        findings.incompatible.append(
            f"{path}: consumer rejects every value while producer admits values"
        )
        return findings
    if producer is True:
        producer = {}

    producer_values = _finite_values(producer)
    if producer_values is not None:
        valid_values = [
            value
            for value in producer_values
            if Draft202012Validator(producer).is_valid(value)
        ]
        if not valid_values:
            findings.unknown.append(
                f"{path}: producer finite domain is empty; vacuous inclusion is not promoted"
            )
            return findings
        rejected = [
            value for value in valid_values if not Draft202012Validator(consumer).is_valid(value)
        ]
        if rejected:
            findings.incompatible.append(
                f"{path}: producer finite value {rejected[0]!r} is rejected by consumer"
            )
        return findings

    consumer_values = _finite_values(consumer)
    if consumer_values is not None:
        witness = _find_witness(producer, consumer)
        if witness.found:
            findings.incompatible.append(
                f"{path}: producer value {witness.value!r} is outside consumer finite domain"
            )
        else:
            findings.unknown.append(
                f"{path}: consumer has a finite domain but no counterexample was established"
            )
        return findings

    producer_types = _schema_types(producer)
    consumer_types = _schema_types(consumer)
    for producer_type in producer_types:
        if _branch_obviously_empty(producer, producer_type):
            continue
        if not _consumer_accepts_type(consumer_types, producer_type):
            findings.incompatible.append(
                f"{path}: producer admits JSON type {producer_type!r}, which consumer rejects"
            )
            continue
        if producer_type in {"number", "integer"}:
            findings.extend(_compare_numeric(producer, consumer, path, producer_type))
        elif producer_type == "string":
            findings.extend(_compare_string(producer, consumer, path))
        elif producer_type == "object":
            findings.extend(_compare_object(producer, consumer, path))
        elif producer_type == "array":
            findings.extend(_compare_array(producer, consumer, path))
    return findings


def _compare_numeric(
    producer: Mapping[str, Any],
    consumer: Mapping[str, Any],
    path: str,
    producer_type: str,
) -> _Findings:
    findings = _Findings()
    producer_lower, producer_upper = _numeric_bounds(producer)
    consumer_lower, consumer_upper = _numeric_bounds(consumer)
    if not _lower_subset(producer_lower, consumer_lower):
        findings.incompatible.append(
            f"{path}: producer {producer_type} lower bound {_bound_text(producer_lower, True)} "
            f"is wider than consumer lower bound {_bound_text(consumer_lower, True)}"
        )
    if not _upper_subset(producer_upper, consumer_upper):
        findings.incompatible.append(
            f"{path}: producer {producer_type} upper bound {_bound_text(producer_upper, False)} "
            f"is wider than consumer upper bound {_bound_text(consumer_upper, False)}"
        )
    return findings


def _compare_string(
    producer: Mapping[str, Any], consumer: Mapping[str, Any], path: str
) -> _Findings:
    findings = _Findings()
    producer_min = int(producer.get("minLength", 0))
    consumer_min = int(consumer.get("minLength", 0))
    producer_max = producer.get("maxLength")
    consumer_max = consumer.get("maxLength")
    if producer_min < consumer_min:
        findings.incompatible.append(
            f"{path}: producer minLength {producer_min} is weaker than "
            f"consumer minLength {consumer_min}"
        )
    if consumer_max is not None and (
        producer_max is None or int(producer_max) > int(consumer_max)
    ):
        findings.incompatible.append(
            f"{path}: producer maxLength {producer_max!r} is weaker than "
            f"consumer maxLength {consumer_max}"
        )
    return findings


def _compare_object(
    producer: Mapping[str, Any], consumer: Mapping[str, Any], path: str
) -> _Findings:
    findings = _Findings()
    producer_properties = producer.get("properties", {})
    consumer_properties = consumer.get("properties", {})
    producer_required = set(producer.get("required", []))
    consumer_required = set(consumer.get("required", []))

    for name in sorted(consumer_required - producer_required):
        findings.incompatible.append(
            f"{path}: producer may omit consumer-required property {name!r}"
        )

    producer_additional = producer.get("additionalProperties", True)
    consumer_additional = consumer.get("additionalProperties", True)
    property_names = set(producer_properties) | set(consumer_properties)
    for name in sorted(property_names):
        producer_child = _effective_property_schema(
            producer_properties, producer_additional, name
        )
        consumer_child = _effective_property_schema(
            consumer_properties, consumer_additional, name
        )
        if producer_child is False:
            continue
        child_path = f"{path}/properties/{_pointer(name)}"
        if consumer_child is False:
            findings.incompatible.append(
                f"{child_path}: producer may emit property {name!r}, but consumer forbids it"
            )
            continue
        findings.extend(_compare_schemas(producer_child, consumer_child, child_path))

    if producer_additional is not False:
        additional_path = f"{path}/additionalProperties"
        if consumer_additional is False:
            findings.incompatible.append(
                f"{additional_path}: producer permits undeclared properties, "
                "but consumer forbids them"
            )
        else:
            findings.extend(
                _compare_schemas(
                    producer_additional, consumer_additional, additional_path
                )
            )
    return findings


def _compare_array(
    producer: Mapping[str, Any], consumer: Mapping[str, Any], path: str
) -> _Findings:
    findings = _Findings()
    producer_min = int(producer.get("minItems", 0))
    consumer_min = int(consumer.get("minItems", 0))
    producer_max = producer.get("maxItems")
    consumer_max = consumer.get("maxItems")
    if producer_min < consumer_min:
        findings.incompatible.append(
            f"{path}: producer minItems {producer_min} is weaker than "
            f"consumer minItems {consumer_min}"
        )
    if consumer_max is not None and (
        producer_max is None or int(producer_max) > int(consumer_max)
    ):
        findings.incompatible.append(
            f"{path}: producer maxItems {producer_max!r} is weaker than "
            f"consumer maxItems {consumer_max}"
        )
    if producer_max != 0:
        findings.extend(
            _compare_schemas(
                producer.get("items", True),
                consumer.get("items", True),
                f"{path}/items",
            )
        )
    return findings


def _effective_property_schema(
    properties: Mapping[str, Any], additional: Any, name: str
) -> Any:
    return properties[name] if name in properties else additional


def _finite_values(schema: Any) -> list[Any] | None:
    if not isinstance(schema, Mapping):
        return None
    if "const" in schema:
        return [schema["const"]]
    if "enum" in schema:
        return list(schema["enum"])
    return None


def _schema_types(schema: Mapping[str, Any]) -> tuple[str, ...]:
    declared = schema.get("type")
    if declared is None:
        return _JSON_TYPES
    if isinstance(declared, str):
        return (declared,)
    return tuple(declared)


def _consumer_accepts_type(consumer_types: Sequence[str], producer_type: str) -> bool:
    return producer_type in consumer_types or (
        producer_type == "integer" and "number" in consumer_types
    )


def _branch_obviously_empty(schema: Mapping[str, Any], branch: str) -> bool:
    if branch in {"number", "integer"}:
        lower, upper = _numeric_bounds(schema)
        if lower is not None and upper is not None:
            if lower[0] > upper[0]:
                return True
            if lower[0] == upper[0] and (lower[1] or upper[1]):
                return True
        if branch == "integer" and not _integer_interval_has_value(lower, upper):
            return True
    elif branch == "string":
        if schema.get("maxLength") is not None and int(
            schema.get("minLength", 0)
        ) > int(schema["maxLength"]):
            return True
    elif branch == "array":
        if schema.get("maxItems") is not None and int(
            schema.get("minItems", 0)
        ) > int(schema["maxItems"]):
            return True
        if int(schema.get("minItems", 0)) > 0 and schema.get("items", True) is False:
            return True
    elif branch == "object":
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for name in schema.get("required", []):
            child = _effective_property_schema(properties, additional, name)
            if child is False or _obvious_unsatisfiable(
                child, f"/properties/{_pointer(name)}"
            ):
                return True
    return False


def _integer_interval_has_value(
    lower: tuple[Decimal, bool] | None, upper: tuple[Decimal, bool] | None
) -> bool:
    if lower is None:
        minimum = None
    else:
        minimum = math.floor(lower[0]) + 1 if lower[1] else math.ceil(lower[0])
    if upper is None:
        maximum = None
    else:
        maximum = math.ceil(upper[0]) - 1 if upper[1] else math.floor(upper[0])
    return minimum is None or maximum is None or minimum <= maximum


def _obvious_unsatisfiable(schema: Any, path: str) -> list[str]:
    if schema is False:
        return [f"{path}: false schema admits no values"]
    if schema is True:
        return []
    finite = _finite_values(schema)
    if finite is not None and not any(
        Draft202012Validator(schema).is_valid(value) for value in finite
    ):
        return [f"{path}: no enum/const value satisfies the producer schema"]
    declared = _schema_types(schema)
    if declared and all(_branch_obviously_empty(schema, branch) for branch in declared):
        return [f"{path}: every declared type branch is obviously empty"]
    return []


def _numeric_bounds(
    schema: Mapping[str, Any]
) -> tuple[tuple[Decimal, bool] | None, tuple[Decimal, bool] | None]:
    lower: tuple[Decimal, bool] | None = None
    upper: tuple[Decimal, bool] | None = None
    if "minimum" in schema:
        lower = (Decimal(str(schema["minimum"])), False)
    if "exclusiveMinimum" in schema:
        candidate = (Decimal(str(schema["exclusiveMinimum"])), True)
        if lower is None or candidate[0] > lower[0] or (
            candidate[0] == lower[0] and candidate[1]
        ):
            lower = candidate
    if "maximum" in schema:
        upper = (Decimal(str(schema["maximum"])), False)
    if "exclusiveMaximum" in schema:
        candidate = (Decimal(str(schema["exclusiveMaximum"])), True)
        if upper is None or candidate[0] < upper[0] or (
            candidate[0] == upper[0] and candidate[1]
        ):
            upper = candidate
    return lower, upper


def _lower_subset(
    producer: tuple[Decimal, bool] | None,
    consumer: tuple[Decimal, bool] | None,
) -> bool:
    if consumer is None:
        return True
    if producer is None:
        return False
    if producer[0] > consumer[0]:
        return True
    if producer[0] < consumer[0]:
        return False
    return not (consumer[1] and not producer[1])


def _upper_subset(
    producer: tuple[Decimal, bool] | None,
    consumer: tuple[Decimal, bool] | None,
) -> bool:
    if consumer is None:
        return True
    if producer is None:
        return False
    if producer[0] < consumer[0]:
        return True
    if producer[0] > consumer[0]:
        return False
    return not (consumer[1] and not producer[1])


def _bound_text(bound: tuple[Decimal, bool] | None, lower: bool) -> str:
    if bound is None:
        return "-infinity" if lower else "+infinity"
    operator = ">" if lower and bound[1] else ">=" if lower else "<" if bound[1] else "<="
    return f"{operator} {bound[0]}"


@dataclass(frozen=True)
class _Witness:
    found: bool
    value: Any = None


def _find_witness(producer: Mapping[str, Any], consumer: Mapping[str, Any]) -> _Witness:
    producer_validator = Draft202012Validator(producer)
    consumer_validator = Draft202012Validator(consumer)
    for value in _candidate_values(producer):
        if producer_validator.is_valid(value) and not consumer_validator.is_valid(value):
            return _Witness(True, value)
    return _Witness(False)


def _candidate_values(schema: Mapping[str, Any]) -> Iterable[Any]:
    types = _schema_types(schema)
    if "null" in types:
        yield None
    if "boolean" in types:
        yield False
        yield True
    if "string" in types:
        minimum = int(schema.get("minLength", 0))
        yield "x" * minimum
        yield "x" * max(minimum, 1)
        maximum = schema.get("maxLength")
        if maximum is not None:
            yield "x" * int(maximum)
    if "integer" in types or "number" in types:
        yield from _numeric_candidates(schema, integers="number" not in types)
    if "array" in types:
        minimum = int(schema.get("minItems", 0))
        item = _first_candidate(schema.get("items", True))
        yield [item for _ in range(minimum)]
    if "object" in types:
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        value: dict[str, Any] = {}
        possible = True
        for name in schema.get("required", []):
            child = _effective_property_schema(properties, additional, name)
            if child is False:
                possible = False
                break
            value[name] = _first_candidate(child)
        if possible:
            yield value


def _numeric_candidates(schema: Mapping[str, Any], *, integers: bool) -> Iterable[Any]:
    lower, upper = _numeric_bounds(schema)
    raw: list[Decimal] = [Decimal(-1), Decimal(0), Decimal(1)]
    for bound in (lower, upper):
        if bound is not None:
            raw.extend((bound[0] - 1, bound[0], bound[0] + 1))
    for value in raw:
        if integers:
            if value == value.to_integral_value():
                yield int(value)
        else:
            yield int(value) if value == value.to_integral_value() else float(value)


def _first_candidate(schema: Any) -> Any:
    if schema is True or schema == {}:
        return None
    if schema is False:
        return None
    finite = _finite_values(schema)
    if finite:
        return finite[0]
    return next(iter(_candidate_values(schema)), None)


def held_out_benchmark_cases() -> tuple[BenchmarkCase, ...]:
    """Return fixed, labeled cases that are not consulted by checker logic."""

    closed_person = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"name": {"type": "string", "minLength": 1}},
        "required": ["name"],
        "additionalProperties": False,
    }
    return (
        BenchmarkCase(
            "safe-identical-closed-object",
            CompatibilityStatus.SAFE,
            closed_person,
            closed_person,
        ),
        BenchmarkCase(
            "safe-integer-refinement",
            CompatibilityStatus.SAFE,
            {"type": "integer", "minimum": 1, "maximum": 5},
            {"type": "number", "minimum": 0, "maximum": 10},
        ),
        BenchmarkCase(
            "safe-enum-subset",
            CompatibilityStatus.SAFE,
            {"type": "string", "enum": ["red", "blue"]},
            {"type": "string", "enum": ["red", "blue", "green"]},
        ),
        BenchmarkCase(
            "safe-consumer-nullability",
            CompatibilityStatus.SAFE,
            {"type": "string"},
            {"type": ["string", "null"]},
        ),
        BenchmarkCase(
            "incompatible-required-field",
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
        ),
        BenchmarkCase(
            "incompatible-additional-properties",
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "object", "additionalProperties": True},
            {"type": "object", "additionalProperties": False},
        ),
        BenchmarkCase(
            "incompatible-enum",
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "string", "enum": ["red", "blue"]},
            {"type": "string", "enum": ["red"]},
        ),
        BenchmarkCase(
            "incompatible-range",
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "number", "minimum": -1, "maximum": 5},
            {"type": "number", "minimum": 0, "maximum": 5},
        ),
        BenchmarkCase(
            "incompatible-nullability",
            CompatibilityStatus.INCOMPATIBLE,
            {"type": ["string", "null"]},
            {"type": "string"},
        ),
        BenchmarkCase(
            "incompatible-units",
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "number"},
            {"type": "number"},
            {"unit": "m"},
            {"unit": "s"},
        ),
        BenchmarkCase(
            "incompatible-semantics",
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "string"},
            {"type": "string"},
            {"semantic_concept": "urn:example:customer-id"},
            {"semantic_concept": "urn:example:invoice-id"},
        ),
        BenchmarkCase(
            "retrieval-cannot-override-required-field",
            CompatibilityStatus.INCOMPATIBLE,
            {"type": "object", "additionalProperties": False},
            {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
            {"name": "same", "embedding": [1.0, 0.0], "similarity": 1.0},
            {"name": "same", "embedding": [1.0, 0.0], "similarity": 1.0},
        ),
        BenchmarkCase(
            "unknown-pattern",
            CompatibilityStatus.UNKNOWN,
            {"type": "string", "pattern": "^[a-z]+$"},
            {"type": "string"},
        ),
        BenchmarkCase(
            "unknown-combinator",
            CompatibilityStatus.UNKNOWN,
            {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            {"type": ["string", "integer"]},
        ),
        BenchmarkCase(
            "unknown-missing-unit",
            CompatibilityStatus.UNKNOWN,
            {"type": "number"},
            {"type": "number"},
            {},
            {"unit": "m"},
        ),
    )


def run_held_out_benchmark(
    cases: Iterable[BenchmarkCase] | None = None,
    *,
    benchmark_id: str = HELD_OUT_BENCHMARK_ID,
) -> BenchmarkReceipt:
    """Execute labeled cases and return quality plus per-call latency metrics."""

    selected = tuple(cases if cases is not None else held_out_benchmark_cases())
    if not selected:
        raise ValueError("benchmark requires at least one case")
    receipts: list[BenchmarkCaseReceipt] = []
    for case in selected:
        if not isinstance(case.label, CompatibilityStatus):
            raise TypeError(f"case {case.case_id!r} label must be CompatibilityStatus")
        started = perf_counter_ns()
        result = check_json_schema_compatibility(
            case.producer_schema,
            case.consumer_schema,
            producer_metadata=case.producer_metadata,
            consumer_metadata=case.consumer_metadata,
        )
        elapsed_ms = (perf_counter_ns() - started) / 1_000_000
        receipts.append(
            BenchmarkCaseReceipt(
                case_id=case.case_id,
                expected=case.label,
                predicted=result.status,
                latency_ms=elapsed_ms,
                reasons=result.reasons,
                counterexample_reasons=result.counterexample_reasons,
                description=case.description,
            )
        )

    labels = _status_counts(case.label for case in selected)
    predictions = _status_counts(receipt.predicted for receipt in receipts)
    predicted_safe = predictions[CompatibilityStatus.SAFE.value]
    true_safe_predictions = sum(
        receipt.expected is CompatibilityStatus.SAFE
        and receipt.predicted is CompatibilityStatus.SAFE
        for receipt in receipts
    )
    labeled_incompatible = labels[CompatibilityStatus.INCOMPATIBLE.value]
    found_incompatible = sum(
        receipt.expected is CompatibilityStatus.INCOMPATIBLE
        and receipt.predicted is CompatibilityStatus.INCOMPATIBLE
        for receipt in receipts
    )
    unsafe_safe_edges = sum(
        receipt.predicted is CompatibilityStatus.SAFE
        and receipt.expected is not CompatibilityStatus.SAFE
        for receipt in receipts
    )
    latencies = [receipt.latency_ms for receipt in receipts]
    return BenchmarkReceipt(
        benchmark_id=benchmark_id,
        checker_id=CHECKER_ID,
        checker_version=CHECKER_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
        case_count=len(receipts),
        label_counts=labels,
        prediction_counts=predictions,
        safe_edge_precision=(
            true_safe_predictions / predicted_safe if predicted_safe else None
        ),
        incompatible_recall=(
            found_incompatible / labeled_incompatible if labeled_incompatible else None
        ),
        abstention_rate=predictions[CompatibilityStatus.UNKNOWN.value] / len(receipts),
        exact_accuracy=sum(receipt.correct for receipt in receipts) / len(receipts),
        unsafe_safe_edges=unsafe_safe_edges,
        latency_ms={
            "mean": fmean(latencies),
            "p50": median(latencies),
            "p95": _percentile_nearest_rank(latencies, 0.95),
            "max": max(latencies),
        },
        cases=tuple(receipts),
    )


def _status_counts(statuses: Iterable[CompatibilityStatus]) -> dict[str, int]:
    counts = {status.value: 0 for status in CompatibilityStatus}
    for status in statuses:
        counts[status.value] += 1
    return counts


def _percentile_nearest_rank(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


if __name__ == "__main__":
    print(json.dumps(run_held_out_benchmark().to_dict(), indent=2, sort_keys=True))
