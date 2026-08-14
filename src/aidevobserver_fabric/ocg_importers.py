"""Loss-aware native-format importers for Open Capability Graph 0.1.

These importers deliberately produce *candidate* Core-profile graphs.  They
preserve native JSON values behind digest-bound data-URI references, but do
not claim that a native schema, workflow port, or API operation is compatible
with any other record.  Unsupported semantics are reported as structured
warnings and the document-wide planning decision remains ``unknown``.

The module is standard-library first.  JSON Schema validation and semantic OCG
validation remain the responsibility of :mod:`ocg_conformance` and its normal
project dependencies.
"""

from __future__ import annotations

from base64 import b64encode
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5


SPEC_VERSION = "0.1.0-draft"
SCHEMA_URI = (
    "https://github.com/Amarel-Taylor-Scott/"
    "aidevobserver-capability-fabric/raw/main/spec/open-capability-graph/"
    "v0.1/schemas/open-capability-graph.schema.json"
)
IMPORT_EXTENSION = (
    "https://github.com/Amarel-Taylor-Scott/"
    "aidevobserver-capability-fabric/tree/main/spec/open-capability-graph/"
    "v0.1/extensions/native-import-report"
)
UNKNOWN_DIALECT = (
    "https://github.com/Amarel-Taylor-Scott/"
    "aidevobserver-capability-fabric/tree/main/spec/open-capability-graph/"
    "v0.1/dialects/unknown"
)

_HTTP_METHODS = {
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
}
_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class ImportWarning:
    """One explicit loss, unsupported construct, or unknown semantic."""

    code: str
    message: str
    source_pointer: str
    outcome: str = "unknown"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class NativePort:
    """A native contract value that will become one candidate OCG port.

    This small public data object and :class:`CandidateGraphBuilder` are kept
    format-neutral so additional importers can reuse the same fail-closed
    construction path.
    """

    name: str
    direction: str
    native_value: Any
    dialect: str
    source_pointer: str
    label: str | None = None
    required: bool = True
    media_type: str = "application/json"
    native_bytes: bytes | None = None
    unknown_reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OCGImportResult:
    """Candidate OCG document plus its structured loss report."""

    document: dict[str, Any]
    warnings: tuple[ImportWarning, ...]
    source_format: str
    source_digest: str
    planning_eligibility: str = "unknown"


def _json_bytes(value: Any) -> bytes:
    """Serialize a parsed JSON value deterministically with only stdlib JSON."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"native input is not a finite JSON value: {exc}") from exc


def _digest_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _data_uri(payload: bytes, media_type: str = "application/json") -> str:
    return f"data:{media_type};base64,{b64encode(payload).decode('ascii')}"


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _slug(value: str, fallback: str) -> str:
    candidate = _SLUG_RE.sub("-", value.strip()).strip("-.")
    return candidate or fallback


def _as_sequence(value: Any, *, field_name: str) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    raise TypeError(f"{field_name} must be a JSON array")


class CandidateGraphBuilder:
    """Reusable fail-closed builder for native-format candidate actions."""

    def __init__(
        self,
        *,
        source_format: str,
        source_document: Any,
        title: str,
        source_uri: str | None = None,
        format_reference: str | None = None,
        source_payload: bytes | None = None,
        source_media_type: str = "application/json",
        source_provenance: Mapping[str, Any] | None = None,
    ) -> None:
        self.source_format = source_format
        self.source_document = deepcopy(source_document)
        self.source_bytes = (
            bytes(source_payload)
            if source_payload is not None
            else _json_bytes(self.source_document)
        )
        self.source_digest = _digest_bytes(self.source_bytes)
        self.normalized_payload_uri = _data_uri(self.source_bytes, source_media_type)
        self.source_uri = source_uri or self.normalized_payload_uri
        self.source_provenance = deepcopy(dict(source_provenance or {}))
        self.contract_source_artifact_refs: list[str] = []
        self.contract_normalizer_artifact_ref: str | None = None
        self.format_reference = format_reference
        self._root_uuid = uuid5(NAMESPACE_URL, f"ocg-import\x00{source_format}\x00{self.source_digest}")
        self._warnings: list[ImportWarning] = []
        self._document: dict[str, Any] = {
            "$schema": SCHEMA_URI,
            "spec_version": SPEC_VERSION,
            "graph_id": f"urn:uuid:{self._root_uuid}",
            "title": title,
            "description": (
                f"Loss-aware {source_format} import. Native values are preserved; "
                "compatibility and execution authorization are not established."
            ),
            "status": "candidate",
            "profiles": ["core"],
            "nodes": [],
            "actions": [],
            "relations": [],
        }

    @property
    def warnings(self) -> tuple[ImportWarning, ...]:
        return tuple(self._warnings)

    def warn(self, code: str, message: str, source_pointer: str) -> None:
        warning = ImportWarning(code=code, message=message, source_pointer=source_pointer)
        if warning not in self._warnings:
            self._warnings.append(warning)

    def _id(self, kind: str, key: str) -> str:
        identity_key = f"{kind}\x00{key}"
        return f"urn:uuid:{uuid5(self._root_uuid, identity_key)}"

    def unknown_port(
        self,
        *,
        name: str,
        direction: str,
        source_pointer: str,
        reason: str,
        label: str | None = None,
    ) -> NativePort:
        """Create an explicit unknown placeholder without inventing a schema."""

        return NativePort(
            name=name,
            direction=direction,
            native_value={
                "ocg_import_status": "unknown",
                "reason": reason,
                "source_format": self.source_format,
            },
            dialect=UNKNOWN_DIALECT,
            source_pointer=source_pointer,
            label=label,
            unknown_reason=reason,
        )

    def _add_contract(self, action_key: str, port: NativePort) -> str:
        contract_key = f"{action_key}\x00{port.direction}\x00{port.name}"
        contract_id = self._id("contract", contract_key)
        payload = (
            bytes(port.native_bytes)
            if port.native_bytes is not None
            else _json_bytes(port.native_value)
        )
        native_metadata: dict[str, Any] = {
            "source_format": self.source_format,
            "source_document_uri": self.source_uri,
            "source_document_digest": self.source_digest,
            "source_pointer": port.source_pointer,
            "preservation": (
                "exact-native-bytes"
                if port.native_bytes is not None
                else "deterministic-json-projection"
            ),
            "projection_kind": (
                "synthetic-unknown"
                if port.unknown_reason is not None
                else port.metadata.get("projection_kind", "native-value")
            ),
            "serialization": (
                "native-bytes"
                if port.native_bytes is not None
                else "stdlib-json-sort-keys-v1-not-rfc8785"
            ),
            "role": port.direction,
        }
        if self.source_provenance:
            native_metadata["source_provenance"] = deepcopy(self.source_provenance)
        native_metadata.update(deepcopy(dict(port.metadata)))
        if port.unknown_reason is not None:
            native_metadata["semantic_status"] = "unknown"
            native_metadata["unknown_reason"] = port.unknown_reason
        native_contract: dict[str, Any] = {
            "dialect": port.dialect,
            "digest": _digest_bytes(payload),
            "schema_uri": _data_uri(payload, port.media_type),
            "schema": deepcopy(port.native_value),
            "media_type": port.media_type,
            "encoding": "utf-8",
            "metadata": native_metadata,
        }
        if self.contract_source_artifact_refs:
            native_contract["source_artifact_refs"] = list(
                self.contract_source_artifact_refs
            )
        if self.contract_normalizer_artifact_ref is not None:
            native_contract["normalizer_artifact_ref"] = (
                self.contract_normalizer_artifact_ref
            )
        self._document["nodes"].append(
            {
                "id": contract_id,
                "kind": "contract",
                "label": port.label or f"{port.name} {port.direction} contract",
                "lifecycle": "candidate",
                "native_contract": native_contract,
            }
        )
        return contract_id

    def add_candidate_action(
        self,
        *,
        key: str,
        label: str,
        description: str,
        inputs: Sequence[NativePort],
        outputs: Sequence[NativePort],
        source_pointer: str,
        binding: Mapping[str, Any],
        protocol_mode: str | None = None,
    ) -> str:
        """Add one action while keeping every trust-sensitive status candidate."""

        if not inputs or not outputs:
            raise ValueError("candidate actions require at least one input and one output port")
        if any(port.direction != "input" for port in inputs):
            raise ValueError("all inputs must use direction='input'")
        if any(port.direction != "output" for port in outputs):
            raise ValueError("all outputs must use direction='output'")

        action_id = self._id("action", key)
        capability_id = self._id("capability", key)
        implementation_id = self._id("implementation", key)
        self._document["nodes"].extend(
            [
                {
                    "id": capability_id,
                    "kind": "capability",
                    "label": label,
                    "description": description,
                    "lifecycle": "candidate",
                    "metadata": {
                        "source_format": self.source_format,
                        "source_pointer": source_pointer,
                        "semantic_status": "candidate",
                    },
                },
                {
                    "id": implementation_id,
                    "kind": "implementation",
                    "label": f"Native {self.source_format} binding for {label}",
                    "lifecycle": "candidate",
                    "metadata": {
                        "source_format": self.source_format,
                        "source_document_uri": self.source_uri,
                        "source_document_digest": self.source_digest,
                        "source_pointer": source_pointer,
                        "binding": deepcopy(dict(binding)),
                        "execution_authorization": "not_established",
                    },
                },
            ]
        )

        ports: list[dict[str, Any]] = []
        seen_port_ids: set[str] = set()
        for index, port in enumerate([*inputs, *outputs]):
            fallback = f"{port.direction}-{index + 1}"
            port_id = _slug(port.name, fallback)
            if port_id in seen_port_ids:
                suffix = hashlib.sha256(f"{port.source_pointer}\x00{index}".encode()).hexdigest()[:8]
                port_id = f"{port_id}-{suffix}"
            seen_port_ids.add(port_id)
            contract_id = self._add_contract(key, NativePort(**{**port.__dict__, "name": port_id}))
            port_record: dict[str, Any] = {
                "id": port_id,
                "label": port.label or port.name,
                "direction": port.direction,
                "contract_ref": contract_id,
                "required": port.required,
                "metadata": {
                    "source_pointer": port.source_pointer,
                    "semantic_status": "unknown" if port.unknown_reason else "native-preserved",
                },
            }
            ports.append(port_record)

        action: dict[str, Any] = {
            "id": action_id,
            "label": label,
            "description": description,
            "capability_ref": capability_id,
            "implementation_ref": implementation_id,
            "ports": ports,
            # A non-empty unknown effect is deliberate: changing only a
            # relation to eligible cannot accidentally bypass the v0.1 gate.
            "effects": [
                {
                    "kind": "custom",
                    "certainty": "unknown",
                    "metadata": {
                        "reason": "native import does not establish a complete effect set"
                    },
                }
            ],
            "retry": {"idempotency": "unknown", "automatic_retry": False},
            "transaction": {"mode": "unknown"},
            "lifecycle": "candidate",
            "metadata": {
                "source_format": self.source_format,
                "source_pointer": source_pointer,
                "planning_eligibility": "unknown",
                "effects": "unknown",
                "preconditions": "unknown",
                "postconditions": "unknown",
            },
        }
        if protocol_mode is not None:
            action["protocol"] = {"mode": protocol_mode}
        self._document["actions"].append(action)
        self._document["relations"].append(
            {
                "id": self._id("relation", f"{key}\x00implements"),
                "kind": "implements",
                "source": {"subject_ref": implementation_id},
                "target": {"subject_ref": capability_id},
                "direction": "source_to_target",
                "status": "candidate",
                "metadata": {
                    "planning_eligibility": "unknown",
                    "reason": "native declaration is unverified OCG candidate inventory",
                },
            }
        )
        self.warn(
            "behavior_semantics_unknown",
            "Effects, preconditions, postconditions, and execution authorization were not inferred.",
            source_pointer,
        )
        return action_id

    def build(self) -> OCGImportResult:
        if not self._document["actions"]:
            raise ValueError(f"{self.source_format} source contains no supported actions")
        report: dict[str, Any] = {
            "source_format": self.source_format,
            "source_uri": self.source_uri,
            "normalized_payload_uri": self.normalized_payload_uri,
            "source_digest": self.source_digest,
            "planning_eligibility": "unknown",
            "execution_authorization": "not_established",
            "contract_profile_claimed": False,
            "warnings": [warning.to_dict() for warning in self._warnings],
        }
        if self.format_reference is not None:
            report["format_reference"] = self.format_reference
        if self.source_provenance:
            report["source_provenance"] = deepcopy(self.source_provenance)
        document = deepcopy(self._document)
        document["extensions"] = {IMPORT_EXTENSION: report}
        return OCGImportResult(
            document=document,
            warnings=tuple(self._warnings),
            source_format=self.source_format,
            source_digest=self.source_digest,
        )


def _mcp_unknown_schema(builder: CandidateGraphBuilder, role: str, pointer: str) -> NativePort:
    reason = f"MCP tool has no usable {role}Schema; its {role} contract is unknown"
    builder.warn(f"mcp_{role}_schema_unknown", reason, pointer)
    return builder.unknown_port(
        name=role,
        direction="input" if role == "input" else "output",
        source_pointer=pointer,
        reason=reason,
        label=f"Unknown MCP {role}",
    )


def import_mcp_tools(
    source: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    source_uri: str | None = None,
) -> OCGImportResult:
    """Import MCP Tool definitions without treating annotations as guarantees."""

    if isinstance(source, Mapping) and "tools" in source:
        source_document: Any = deepcopy(dict(source))
        tools = _as_sequence(source.get("tools"), field_name="MCP tools")
        pointer_prefix = "/tools"
        protocol_version = source.get("protocol_version")
    elif isinstance(source, Mapping):
        source_document = {"tools": [deepcopy(dict(source))]}
        tools = [source]
        pointer_prefix = "/tools"
        protocol_version = None
    else:
        tools = _as_sequence(source, field_name="MCP tools")
        source_document = {"tools": deepcopy(tools)}
        pointer_prefix = "/tools"
        protocol_version = None

    builder = CandidateGraphBuilder(
        source_format="mcp-tools",
        source_document=source_document,
        title="MCP tool candidate import",
        source_uri=source_uri,
        format_reference="https://modelcontextprotocol.io/specification/2025-06-18/server/tools",
    )
    for index, tool_value in enumerate(tools):
        pointer = f"{pointer_prefix}/{index}"
        if not isinstance(tool_value, Mapping):
            builder.warn("mcp_tool_invalid", "Non-object MCP tool was skipped.", pointer)
            continue
        tool = dict(tool_value)
        raw_name = tool.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            name = f"unnamed-tool-{index + 1}"
            builder.warn(
                "mcp_tool_name_unknown",
                "Missing MCP tool name was replaced by a local candidate label.",
                pointer,
            )
        else:
            name = raw_name
        label_value = tool.get("title")
        label = label_value if isinstance(label_value, str) and label_value else name
        description_value = tool.get("description")
        description = description_value if isinstance(description_value, str) else "Imported MCP tool candidate."

        input_schema = tool.get("inputSchema")
        if isinstance(input_schema, Mapping):
            input_port = NativePort(
                name="input",
                direction="input",
                native_value=deepcopy(dict(input_schema)),
                dialect=str(
                    input_schema.get("$schema")
                    or "https://modelcontextprotocol.io/specification/2025-06-18/schema#Tool.inputSchema"
                ),
                source_pointer=f"{pointer}/inputSchema",
                label=f"{label} input",
            )
        else:
            input_port = _mcp_unknown_schema(builder, "input", f"{pointer}/inputSchema")

        output_schema = tool.get("outputSchema")
        if isinstance(output_schema, Mapping):
            output_port = NativePort(
                name="output",
                direction="output",
                native_value=deepcopy(dict(output_schema)),
                dialect=str(
                    output_schema.get("$schema")
                    or "https://modelcontextprotocol.io/specification/2025-06-18/schema#Tool.outputSchema"
                ),
                source_pointer=f"{pointer}/outputSchema",
                label=f"{label} structured output",
            )
        else:
            output_port = _mcp_unknown_schema(builder, "output", f"{pointer}/outputSchema")

        if "annotations" in tool:
            builder.warn(
                "mcp_annotations_not_guarantees",
                "MCP ToolAnnotations are preserved as source hints but do not establish effects or idempotency.",
                f"{pointer}/annotations",
            )
        if "execution" in tool:
            builder.warn(
                "mcp_execution_not_mapped",
                "MCP execution/task-support metadata is preserved but not mapped to OCG execution semantics.",
                f"{pointer}/execution",
            )
        if "_meta" in tool:
            builder.warn(
                "mcp_meta_not_interpreted",
                "MCP _meta content is preserved but not interpreted.",
                f"{pointer}/_meta",
            )
        known_tool_fields = {
            "name",
            "title",
            "description",
            "inputSchema",
            "outputSchema",
            "annotations",
            "execution",
            "icons",
            "_meta",
        }
        unmapped_fields = sorted(str(field) for field in set(tool) - known_tool_fields)
        if unmapped_fields:
            builder.warn(
                "mcp_fields_not_interpreted",
                f"Unrecognized MCP tool fields are preserved but not interpreted: {', '.join(unmapped_fields)}.",
                pointer,
            )
        builder.add_candidate_action(
            key=f"{index}:{name}",
            label=label,
            description=description,
            inputs=[input_port],
            outputs=[output_port],
            source_pointer=pointer,
            binding={
                "kind": "mcp-tool",
                "name": name,
                "protocol_version": protocol_version,
            },
        )
    return builder.build()


def _walk_refs(value: Any, pointer: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_pointer = f"{pointer}/{_pointer_token(str(key))}"
            if key == "$ref" and isinstance(child, str):
                yield child_pointer, child
            else:
                yield from _walk_refs(child, child_pointer)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_refs(child, f"{pointer}/{index}")


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, Mapping):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False


def import_openapi(
    source: Mapping[str, Any],
    *,
    source_uri: str | None = None,
) -> OCGImportResult:
    """Import OpenAPI 3.x operations as candidate actions.

    Request and response objects are preserved in role-specific native
    projections.  References, callbacks, links, security, and server binding
    are not resolved or promoted into executable OCG relations.
    """

    if not isinstance(source, Mapping):
        raise TypeError("OpenAPI source must be a JSON object")
    version = source.get("openapi")
    if not isinstance(version, str) or re.fullmatch(r"3\.(?:0|1)\.\d+(?:[-+][0-9A-Za-z.-]+)?", version) is None:
        raise ValueError("only explicit OpenAPI 3.0.x and 3.1.x documents are supported")
    info = source.get("info") if isinstance(source.get("info"), Mapping) else {}
    title = info.get("title") if isinstance(info.get("title"), str) else "OpenAPI operation candidate import"
    builder = CandidateGraphBuilder(
        source_format="openapi",
        source_document=source,
        title=f"{title} OCG candidate import",
        source_uri=source_uri,
        format_reference=f"https://spec.openapis.org/oas/v{version}.html",
    )
    if source.get("security") is not None:
        builder.warn(
            "openapi_security_not_authorization",
            "Global OpenAPI security requirements are preserved but do not authorize OCG execution.",
            "/security",
        )
    if source.get("servers") is not None:
        builder.warn(
            "openapi_servers_not_resolved",
            "Global OpenAPI server selection and variables are preserved but not resolved.",
            "/servers",
        )
    if source.get("webhooks") is not None:
        builder.warn(
            "openapi_webhooks_not_imported",
            "OpenAPI webhooks are preserved in the source document but are not imported as actions.",
            "/webhooks",
        )

    paths = source.get("paths")
    if not isinstance(paths, Mapping):
        raise ValueError("OpenAPI document requires an object-valued paths field")
    operation_index = 0
    dialect = f"https://spec.openapis.org/oas/v{version}.html#operation-object"
    for path, path_item_value in paths.items():
        path_pointer = f"/paths/{_pointer_token(str(path))}"
        if not isinstance(path_item_value, Mapping):
            builder.warn("openapi_path_item_invalid", "Non-object Path Item was skipped.", path_pointer)
            continue
        path_item = dict(path_item_value)
        if "$ref" in path_item:
            builder.warn(
                "openapi_path_ref_unresolved",
                "Path Item $ref is preserved but was not resolved.",
                f"{path_pointer}/$ref",
            )
        if "servers" in path_item:
            builder.warn(
                "openapi_path_servers_not_resolved",
                "Path-level server selection is preserved but not resolved.",
                f"{path_pointer}/servers",
            )
        for method, operation_value in path_item.items():
            method_lower = str(method).lower()
            if method_lower not in _HTTP_METHODS:
                continue
            operation_pointer = f"{path_pointer}/{method_lower}"
            if not isinstance(operation_value, Mapping):
                builder.warn("openapi_operation_invalid", "Non-object operation was skipped.", operation_pointer)
                continue
            operation = dict(operation_value)
            operation_index += 1
            operation_id_value = operation.get("operationId")
            if isinstance(operation_id_value, str) and operation_id_value:
                operation_id = operation_id_value
            else:
                operation_id = f"{method_lower}-{_slug(str(path), 'root')}-{operation_index}"
                builder.warn(
                    "openapi_operation_id_unknown",
                    "Missing operationId was replaced by a local candidate label.",
                    operation_pointer,
                )
            summary = operation.get("summary")
            description = operation.get("description")
            label = summary if isinstance(summary, str) and summary else operation_id
            action_description = (
                description
                if isinstance(description, str)
                else f"Imported {method_lower.upper()} {path} OpenAPI operation candidate."
            )

            request_projection = {
                "path": path,
                "method": method_lower.upper(),
                "pathItemParameters": deepcopy(path_item.get("parameters", [])),
                "operationParameters": deepcopy(operation.get("parameters", [])),
                "requestBody": deepcopy(operation.get("requestBody")),
            }
            responses = operation.get("responses")
            if not isinstance(responses, Mapping):
                output_port = builder.unknown_port(
                    name="response",
                    direction="output",
                    source_pointer=f"{operation_pointer}/responses",
                    reason="OpenAPI operation has no usable Responses Object",
                    label=f"{label} unknown response",
                )
                builder.warn(
                    "openapi_responses_unknown",
                    "Operation has no usable Responses Object; output contract is unknown.",
                    f"{operation_pointer}/responses",
                )
            else:
                output_port = NativePort(
                    name="response",
                    direction="output",
                    native_value={"responses": deepcopy(dict(responses))},
                    dialect=dialect,
                    source_pointer=f"{operation_pointer}/responses",
                    label=f"{label} responses",
                    metadata={
                        "projection": "responses-preserved-no-status-selection",
                        "projection_kind": "openapi-operation-response-wrapper",
                    },
                )
            input_port = NativePort(
                name="request",
                direction="input",
                native_value=request_projection,
                dialect=dialect,
                source_pointer=operation_pointer,
                label=f"{label} request",
                metadata={
                    "projection": "request-fields-preserved-no-serialization-resolution",
                    "projection_kind": "openapi-operation-request-wrapper",
                },
            )

            builder.warn(
                "openapi_serialization_not_resolved",
                "Parameter styles, encodings, media negotiation, and runtime "
                "expressions are preserved but not resolved.",
                operation_pointer,
            )
            if isinstance(responses, Mapping) and len(responses) != 1:
                builder.warn(
                    "openapi_response_selection_unknown",
                    "Multiple/default response branches are preserved; no single output branch is asserted.",
                    f"{operation_pointer}/responses",
                )

            for ref_pointer, ref_value in _walk_refs(operation, operation_pointer):
                builder.warn(
                    "openapi_ref_unresolved",
                    f"OpenAPI reference {ref_value!r} is preserved but was not resolved.",
                    ref_pointer,
                )
            for ref_pointer, ref_value in _walk_refs(
                path_item.get("parameters", []),
                f"{path_pointer}/parameters",
            ):
                builder.warn(
                    "openapi_ref_unresolved",
                    f"OpenAPI reference {ref_value!r} is preserved but was not resolved.",
                    ref_pointer,
                )
            if operation.get("security") is not None:
                builder.warn(
                    "openapi_operation_security_not_authorization",
                    "Operation security requirements are preserved but do not authorize OCG execution.",
                    f"{operation_pointer}/security",
                )
            if operation.get("servers") is not None:
                builder.warn(
                    "openapi_operation_servers_not_resolved",
                    "Operation server selection is preserved but not resolved.",
                    f"{operation_pointer}/servers",
                )
            if operation.get("callbacks") is not None:
                builder.warn(
                    "openapi_callbacks_not_imported",
                    "Callbacks are preserved but not imported as actions or flow relations.",
                    f"{operation_pointer}/callbacks",
                )
            if operation.get("deprecated") is True:
                builder.warn(
                    "openapi_deprecation_not_promoted",
                    "OpenAPI deprecated=true is preserved, but the imported OCG lifecycle remains candidate.",
                    f"{operation_pointer}/deprecated",
                )
            if _contains_key(responses, "links"):
                builder.warn(
                    "openapi_links_not_promoted",
                    "OpenAPI Links are preserved but not promoted to OCG edges without target and expression checks.",
                    f"{operation_pointer}/responses",
                )
            builder.add_candidate_action(
                key=f"{operation_index}:{method_lower}:{path}:{operation_id}",
                label=label,
                description=action_description,
                inputs=[input_port],
                outputs=[output_port],
                source_pointer=operation_pointer,
                binding={
                    "kind": "openapi-operation",
                    "openapi_version": version,
                    "operation_id": operation_id,
                    "method": method_lower.upper(),
                    "path": path,
                },
            )
    return builder.build()


def _cwl_records(source: Any) -> tuple[Any, list[tuple[Any, str]], str | None]:
    if isinstance(source, Mapping) and "$graph" in source:
        graph = _as_sequence(source.get("$graph"), field_name="CWL $graph")
        records = [(record, f"/$graph/{index}") for index, record in enumerate(graph)]
        inherited = source.get("cwlVersion")
        version = inherited if isinstance(inherited, str) else None
        return deepcopy(dict(source)), records, version
    if isinstance(source, Mapping):
        inherited = source.get("cwlVersion")
        version = inherited if isinstance(inherited, str) else None
        return deepcopy(dict(source)), [(source, "")], version
    values = _as_sequence(source, field_name="CWL records")
    records = [(record, f"/{index}") for index, record in enumerate(values)]
    return deepcopy(values), records, None


def _cwl_items(value: Any, pointer: str) -> list[tuple[str, Any, str]]:
    if isinstance(value, Mapping):
        return [
            (str(name), definition, f"{pointer}/{_pointer_token(str(name))}")
            for name, definition in value.items()
        ]
    if isinstance(value, list):
        rows: list[tuple[str, Any, str]] = []
        for index, definition in enumerate(value):
            item_pointer = f"{pointer}/{index}"
            name = definition.get("id") if isinstance(definition, Mapping) else None
            rows.append((str(name) if name else f"value-{index + 1}", definition, item_pointer))
        return rows
    return []


def _cwl_input_optional(definition: Any) -> tuple[bool, bool]:
    """Return (optional, known) using only explicit CWL null/default syntax."""

    if isinstance(definition, Mapping):
        if "default" in definition:
            return True, True
        return _cwl_input_optional(definition.get("type"))
    if isinstance(definition, str):
        if definition.endswith("?") or definition == "null":
            return True, True
        return False, True
    if isinstance(definition, list):
        return "null" in definition, True
    return False, False


def _has_cwl_expression(value: Any) -> bool:
    if isinstance(value, str):
        return "$(" in value or "${" in value
    if isinstance(value, Mapping):
        return any(_has_cwl_expression(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_cwl_expression(child) for child in value)
    return False


def import_cwl(
    source: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    source_uri: str | None = None,
) -> OCGImportResult:
    """Import CWL CommandLineTool and Operation records as candidates."""

    source_document, records, inherited_version = _cwl_records(source)
    builder = CandidateGraphBuilder(
        source_format="cwl",
        source_document=source_document,
        title="CWL tool and operation candidate import",
        source_uri=source_uri,
        format_reference="https://www.commonwl.org/v1.2/Workflow.html",
    )
    for index, (record_value, pointer) in enumerate(records):
        if not isinstance(record_value, Mapping):
            builder.warn(
                "cwl_record_invalid",
                "Non-object CWL record was skipped.",
                pointer or "/",
            )
            continue
        record = dict(record_value)
        class_name = record.get("class")
        if class_name not in {"CommandLineTool", "Operation"}:
            builder.warn(
                "cwl_class_unsupported",
                f"CWL class {class_name!r} was skipped; only CommandLineTool and Operation are imported.",
                pointer or "/class",
            )
            continue
        version = record.get("cwlVersion") if isinstance(record.get("cwlVersion"), str) else inherited_version
        if version is None:
            version = "unknown"
            builder.warn("cwl_version_unknown", "CWL version is missing; dialect version is unknown.", pointer or "/")
        dialect = f"https://w3id.org/cwl/{version}/"
        identifier = record.get("id")
        name = str(identifier) if identifier else f"{class_name.lower()}-{index + 1}"
        label_value = record.get("label")
        label = label_value if isinstance(label_value, str) and label_value else name
        doc_value = record.get("doc")
        if isinstance(doc_value, str):
            description = doc_value
        elif isinstance(doc_value, list):
            description = "\n".join(str(row) for row in doc_value)
        else:
            description = f"Imported CWL {class_name} candidate."

        inputs: list[NativePort] = []
        input_rows = _cwl_items(record.get("inputs"), f"{pointer}/inputs")
        if not input_rows:
            reason = "CWL record has no usable inputs; invocation contract is unknown"
            builder.warn("cwl_inputs_unknown", reason, f"{pointer}/inputs")
            inputs.append(
                builder.unknown_port(
                    name="input",
                    direction="input",
                    source_pointer=f"{pointer}/inputs",
                    reason=reason,
                    label=f"{label} unknown input",
                )
            )
        else:
            for port_name, definition, port_pointer in input_rows:
                optional, known = _cwl_input_optional(definition)
                if not known:
                    builder.warn(
                        "cwl_requiredness_conservative",
                        "CWL input requiredness was not understood; OCG required=true is conservative.",
                        port_pointer,
                    )
                inputs.append(
                    NativePort(
                        name=port_name,
                        direction="input",
                        native_value=deepcopy(definition),
                        dialect=dialect,
                        source_pointer=port_pointer,
                        label=port_name,
                        required=not optional,
                        metadata={"cwl_record_class": "InputParameter"},
                    )
                )

        outputs: list[NativePort] = []
        output_rows = _cwl_items(record.get("outputs"), f"{pointer}/outputs")
        if not output_rows:
            reason = "CWL record has no usable outputs; result contract is unknown"
            builder.warn("cwl_outputs_unknown", reason, f"{pointer}/outputs")
            outputs.append(
                builder.unknown_port(
                    name="output",
                    direction="output",
                    source_pointer=f"{pointer}/outputs",
                    reason=reason,
                    label=f"{label} unknown output",
                )
            )
        else:
            for port_name, definition, port_pointer in output_rows:
                outputs.append(
                    NativePort(
                        name=port_name,
                        direction="output",
                        native_value=deepcopy(definition),
                        dialect=dialect,
                        source_pointer=port_pointer,
                        label=port_name,
                        metadata={"cwl_record_class": "OutputParameter"},
                    )
                )

        if class_name == "Operation":
            builder.warn(
                "cwl_operation_abstract",
                "CWL Operation declares an abstract operation and does not establish an executable implementation.",
                pointer or "/",
            )
        else:
            builder.warn(
                "cwl_execution_binding_not_authorized",
                "CommandLineTool execution fields are preserved but not promoted "
                "to an authorized OCG execution binding.",
                pointer or "/",
            )
        if "requirements" in record or "hints" in record:
            builder.warn(
                "cwl_requirements_not_interpreted",
                "CWL requirements and hints are preserved but not translated into OCG environment/effect guarantees.",
                pointer or "/",
            )
        if _has_cwl_expression(record):
            builder.warn(
                "cwl_expression_not_evaluated",
                "CWL expressions are preserved but were not evaluated or translated into constraints.",
                pointer or "/",
            )
        builder.add_candidate_action(
            key=f"{index}:{name}",
            label=label,
            description=description,
            inputs=inputs,
            outputs=outputs,
            source_pointer=pointer or "/",
            binding={
                "kind": "cwl-record",
                "class": class_name,
                "id": identifier,
                "cwl_version": version,
            },
            protocol_mode="batch" if class_name == "CommandLineTool" else None,
        )
    return builder.build()


def _wit_type_projection(source: Mapping[str, Any], type_ref: Any) -> dict[str, Any]:
    """Preserve a wasm-tools WIT JSON type reference and its resolved row."""

    projection: dict[str, Any] = {"type_ref": deepcopy(type_ref)}
    if isinstance(type_ref, int):
        types = source.get("types")
        if isinstance(types, list) and 0 <= type_ref < len(types):
            projection["resolved_type"] = deepcopy(types[type_ref])
        else:
            projection["resolution_status"] = "unknown"
    elif isinstance(type_ref, str):
        projection["primitive_type"] = type_ref
    else:
        projection["resolution_status"] = "unknown"
    return projection


def import_wit_json(
    source: Mapping[str, Any],
    *,
    source_uri: str | None = None,
    raw_wit: bytes | None = None,
    normalizer: Mapping[str, Any] | None = None,
) -> OCGImportResult:
    """Import the canonical JSON emitted by ``wasm-tools component wit --json``.

    WIT remains the authoritative interface definition.  This importer does
    not claim that WIT types describe behavior, effects, or cross-package
    substitutability.  ``raw_wit`` can be supplied so the import report binds
    the original WIT bytes rather than only the normalized JSON projection.
    """

    if not isinstance(source, Mapping):
        raise TypeError("wasm-tools WIT JSON must be an object")
    interfaces = source.get("interfaces")
    if not isinstance(interfaces, list):
        raise ValueError("wasm-tools WIT JSON requires an interfaces array")
    packages = source.get("packages") if isinstance(source.get("packages"), list) else []
    package_name = None
    if packages and isinstance(packages[0], Mapping) and isinstance(packages[0].get("name"), str):
        package_name = packages[0]["name"]
    normalized_payload = _json_bytes(source)
    projection_uri = (
        f"{source_uri}#wasm-tools-json-projection"
        if source_uri is not None
        else _data_uri(normalized_payload)
    )
    provenance: dict[str, Any] = {
        "normalized_projection": {
            "uri": projection_uri,
            "digest": _digest_bytes(normalized_payload),
            "media_type": "application/json",
            "serialization": "stdlib-json-sort-keys-v1",
        },
        "normalizer": deepcopy(
            dict(
                normalizer
                or {
                    "id": "wasm-tools component wit --json",
                    "version": "unknown",
                    "binary_digest": "unknown",
                }
            )
        ),
    }
    if raw_wit is not None:
        provenance["raw_source"] = {
            "uri": source_uri or _data_uri(raw_wit, "text/wit"),
            "digest": _digest_bytes(raw_wit),
            "media_type": "text/wit",
        }
    builder = CandidateGraphBuilder(
        source_format="wit",
        source_document=source,
        title=f"WIT {package_name or 'package'} candidate import",
        source_uri=projection_uri,
        format_reference="https://github.com/WebAssembly/component-model/blob/main/design/mvp/WIT.md",
        source_provenance=provenance,
    )
    projection_artifact_id = builder._id("artifact", "normalized-wit-json")
    artifacts = [
        {
            "id": projection_artifact_id,
            "digest": builder.source_digest,
            "media_type": "application/json",
            "size_bytes": len(normalized_payload),
            "locators": [{"uri": builder.normalized_payload_uri, "priority": 0}],
            "lifecycle": "candidate",
            "metadata": {
                "role": "normalized-interface-projection",
                "normalizer": deepcopy(provenance["normalizer"]),
            },
        }
    ]
    source_artifact_refs = [projection_artifact_id]
    if raw_wit is not None:
        raw_artifact_id = builder._id("artifact", "raw-wit")
        artifacts.append(
            {
                "id": raw_artifact_id,
                "digest": _digest_bytes(raw_wit),
                "media_type": "text/wit",
                "size_bytes": len(raw_wit),
                "locators": [
                    {"uri": source_uri or _data_uri(raw_wit, "text/wit"), "priority": 0}
                ],
                "lifecycle": "candidate",
                "metadata": {"role": "authoritative-raw-wit-source"},
            }
        )
        source_artifact_refs.append(raw_artifact_id)
        builder._document["relations"].append(
            {
                "id": builder._id("relation", "normalized-wit-derives-from-raw-wit"),
                "kind": "derives_from",
                "source": {"subject_ref": projection_artifact_id},
                "target": {"subject_ref": raw_artifact_id},
                "direction": "source_to_target",
                "status": "candidate",
                "metadata": {"planning_eligibility": "unknown"},
            }
        )
    normalizer_artifact_ref = None
    normalizer_value = provenance["normalizer"]
    normalizer_digest = normalizer_value.get("binary_digest")
    normalizer_size = normalizer_value.get("binary_size_bytes")
    normalizer_uri = normalizer_value.get("binary_uri")
    if (
        isinstance(normalizer_digest, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", normalizer_digest)
        and isinstance(normalizer_size, int)
        and normalizer_size >= 0
        and isinstance(normalizer_uri, str)
    ):
        normalizer_artifact_ref = builder._id("artifact", "wit-normalizer-binary")
        artifacts.append(
            {
                "id": normalizer_artifact_ref,
                "digest": normalizer_digest,
                "media_type": "application/octet-stream",
                "size_bytes": normalizer_size,
                "locators": [{"uri": normalizer_uri, "priority": 0}],
                "lifecycle": "candidate",
                "metadata": {
                    "role": "wit-normalizer-binary",
                    "tool": normalizer_value.get("id"),
                    "version": normalizer_value.get("version"),
                },
            }
        )
        builder._document["relations"].append(
            {
                "id": builder._id("relation", "normalized-wit-depends-on-normalizer"),
                "kind": "depends_on",
                "source": {"subject_ref": projection_artifact_id},
                "target": {"subject_ref": normalizer_artifact_ref},
                "direction": "source_to_target",
                "status": "candidate",
                "metadata": {"planning_eligibility": "unknown"},
            }
        )
    provenance["authority"] = (
        "informational summary; artifact records, typed relations, and native-contract "
        "artifact references are the machine-verifiable provenance view"
    )
    builder.source_provenance = deepcopy(provenance)
    builder.contract_source_artifact_refs = source_artifact_refs
    builder.contract_normalizer_artifact_ref = normalizer_artifact_ref
    builder._document["artifacts"] = artifacts
    if source.get("worlds"):
        builder.warn(
            "wit_worlds_not_imported",
            "WIT worlds are preserved but this v0.1 importer only materializes interface functions.",
            "/worlds",
        )
    for interface_index, interface_value in enumerate(interfaces):
        interface_pointer = f"/interfaces/{interface_index}"
        if not isinstance(interface_value, Mapping):
            builder.warn("wit_interface_invalid", "Non-object WIT interface was skipped.", interface_pointer)
            continue
        interface = dict(interface_value)
        interface_name = str(interface.get("name") or f"interface-{interface_index + 1}")
        functions = interface.get("functions")
        if not isinstance(functions, Mapping):
            builder.warn(
                "wit_interface_has_no_functions",
                "WIT interface contains no function map and produced no OCG actions.",
                f"{interface_pointer}/functions",
            )
            continue
        for function_name, function_value in functions.items():
            function_pointer = f"{interface_pointer}/functions/{_pointer_token(str(function_name))}"
            if not isinstance(function_value, Mapping):
                builder.warn("wit_function_invalid", "Non-object WIT function was skipped.", function_pointer)
                continue
            function = dict(function_value)
            inputs: list[NativePort] = []
            params = function.get("params")
            if isinstance(params, list) and params:
                for param_index, param_value in enumerate(params):
                    param_pointer = f"{function_pointer}/params/{param_index}"
                    if not isinstance(param_value, Mapping):
                        inputs.append(
                            builder.unknown_port(
                                name=f"input-{param_index + 1}",
                                direction="input",
                                source_pointer=param_pointer,
                                reason="WIT parameter row is not an object",
                            )
                        )
                        continue
                    param_name = str(param_value.get("name") or f"input-{param_index + 1}")
                    inputs.append(
                        NativePort(
                            name=param_name,
                            direction="input",
                            native_value=_wit_type_projection(source, param_value.get("type")),
                            dialect="https://github.com/WebAssembly/component-model/blob/main/design/mvp/WIT.md",
                            source_pointer=param_pointer,
                            label=param_name,
                            metadata={
                                "wit_interface": interface_name,
                                "wit_function": str(function_name),
                                "projection_kind": "wit-resolved-type-projection",
                            },
                        )
                    )
            else:
                inputs.append(
                    NativePort(
                        name="unit-input",
                        direction="input",
                        native_value={"wit_type": "unit", "synthetic_port_reason": "OCG v0.1 action requires an input port"},
                        dialect="https://github.com/WebAssembly/component-model/blob/main/design/mvp/WIT.md",
                        source_pointer=f"{function_pointer}/params",
                        label="Unit input",
                        required=False,
                        metadata={
                            "wit_synthetic_unit_port": True,
                            "projection_kind": "wit-synthetic-unit-port",
                        },
                    )
                )
                builder.warn(
                    "wit_unit_input_projected",
                    "A synthetic optional unit port represents a zero-parameter WIT function.",
                    f"{function_pointer}/params",
                )

            result_ref = function.get("result")
            if result_ref is None:
                result_value = {"wit_type": "unit", "synthetic_port_reason": "OCG v0.1 action requires an output port"}
                result_metadata = {
                    "wit_synthetic_unit_port": True,
                    "projection_kind": "wit-synthetic-unit-port",
                }
                builder.warn(
                    "wit_unit_output_projected",
                    "A synthetic unit port represents a WIT function with no result.",
                    f"{function_pointer}/result",
                )
            else:
                result_value = _wit_type_projection(source, result_ref)
                result_metadata = {
                    "wit_interface": interface_name,
                    "wit_function": str(function_name),
                    "projection_kind": "wit-resolved-type-projection",
                }
                resolved = result_value.get("resolved_type")
                if isinstance(resolved, Mapping) and isinstance(resolved.get("kind"), Mapping) and "result" in resolved["kind"]:
                    builder.warn(
                        "wit_result_not_split",
                        "WIT result<ok,err> is preserved as one native output contract; no OCG error edge is inferred.",
                        f"{function_pointer}/result",
                    )
            output = NativePort(
                name="result",
                direction="output",
                native_value=result_value,
                dialect="https://github.com/WebAssembly/component-model/blob/main/design/mvp/WIT.md",
                source_pointer=f"{function_pointer}/result",
                label=f"{function_name} result",
                metadata=result_metadata,
            )
            builder.add_candidate_action(
                key=f"{interface_index}:{interface_name}:{function_name}",
                label=str(function_name),
                description=f"Imported WIT function {interface_name}.{function_name} candidate.",
                inputs=inputs,
                outputs=[output],
                source_pointer=function_pointer,
                binding={
                    "kind": "wit-interface-function",
                    "package": package_name,
                    "interface": interface_name,
                    "function": str(function_name),
                    "function_kind": function.get("kind"),
                },
            )
            builder.warn(
                "wit_behavior_not_defined",
                "WIT establishes interface types, not behavioral compatibility or execution admission.",
                function_pointer,
            )
    return builder.build()


def _agentspec_ports(
    builder: CandidateGraphBuilder,
    values: Any,
    *,
    direction: str,
    pointer: str,
    tool_name: str,
    dialect: str,
) -> list[NativePort]:
    if not isinstance(values, list) or not values:
        reason = f"Agent Spec tool has no declared {direction} properties"
        builder.warn(f"agentspec_{direction}s_unknown", reason, pointer)
        return [
            builder.unknown_port(
                name=direction,
                direction=direction,
                source_pointer=pointer,
                reason=reason,
                label=f"Unknown Agent Spec {direction}",
            )
        ]
    ports: list[NativePort] = []
    for index, value in enumerate(values):
        value_pointer = f"{pointer}/{index}"
        if not isinstance(value, Mapping):
            ports.append(
                builder.unknown_port(
                    name=f"{direction}-{index + 1}",
                    direction=direction,
                    source_pointer=value_pointer,
                    reason="Agent Spec property is not an object",
                )
            )
            continue
        property_value = deepcopy(dict(value))
        title = property_value.get("title")
        port_name = str(title) if isinstance(title, str) and title else f"{direction}-{index + 1}"
        ports.append(
            NativePort(
                name=port_name,
                direction=direction,
                native_value=property_value,
                dialect=dialect,
                source_pointer=value_pointer,
                label=port_name,
                required="default" not in property_value,
                metadata={"agentspec_tool": tool_name, "agentspec_property_index": index},
            )
        )
    return ports


def import_agent_spec(
    source: Mapping[str, Any],
    *,
    source_uri: str | None = None,
) -> OCGImportResult:
    """Import Agent Spec Tool components without importing runtime code."""

    if not isinstance(source, Mapping):
        raise TypeError("Agent Spec source must be a JSON object")
    version = str(source.get("agentspec_version") or "unknown")
    component_type = source.get("component_type")
    if isinstance(component_type, str) and component_type.endswith("Tool"):
        tools: list[Any] = [source]
        pointer_prefix = ""
    else:
        raw_tools = source.get("tools")
        tools = list(raw_tools) if isinstance(raw_tools, list) else []
        pointer_prefix = "/tools"
    builder = CandidateGraphBuilder(
        source_format="agent-spec",
        source_document=source,
        title=f"Agent Spec {source.get('name') or component_type or 'component'} candidate import",
        source_uri=source_uri,
        format_reference="https://github.com/oracle/agent-spec",
    )
    dialect = f"https://oracle.github.io/agent-spec/{version}/"
    supported_tools = {"ServerTool", "ClientTool", "RemoteTool"}
    for index, tool_value in enumerate(tools):
        pointer = f"{pointer_prefix}/{index}" if pointer_prefix else "/"
        if not isinstance(tool_value, Mapping):
            builder.warn("agentspec_tool_invalid", "Non-object Agent Spec tool was skipped.", pointer)
            continue
        tool = dict(tool_value)
        tool_type = tool.get("component_type")
        if tool_type not in supported_tools:
            builder.warn(
                "agentspec_tool_type_unsupported",
                f"Agent Spec component type {tool_type!r} was skipped.",
                f"{pointer}/component_type",
            )
            continue
        tool_name = str(tool.get("name") or tool.get("id") or f"tool-{index + 1}")
        description = str(tool.get("description") or f"Imported Agent Spec {tool_type} candidate.")
        inputs = _agentspec_ports(
            builder,
            tool.get("inputs"),
            direction="input",
            pointer=f"{pointer}/inputs",
            tool_name=tool_name,
            dialect=dialect,
        )
        outputs = _agentspec_ports(
            builder,
            tool.get("outputs"),
            direction="output",
            pointer=f"{pointer}/outputs",
            tool_name=tool_name,
            dialect=dialect,
        )
        if tool_type == "RemoteTool":
            builder.warn(
                "agentspec_remote_binding_not_authorized",
                "RemoteTool connection metadata is preserved but does not authorize network execution.",
                pointer,
            )
        builder.add_candidate_action(
            key=f"{index}:{tool_name}:{tool.get('id')}",
            label=tool_name,
            description=description,
            inputs=inputs,
            outputs=outputs,
            source_pointer=pointer,
            binding={
                "kind": "agent-spec-tool",
                "component_type": tool_type,
                "id": tool.get("id"),
                "agentspec_version": version,
                "parent_component_id": source.get("id"),
            },
        )
        builder.warn(
            "agentspec_code_not_present",
            "Agent Spec describes the tool but intentionally does not carry its implementation code.",
            pointer,
        )
    return builder.build()


__all__ = [
    "CandidateGraphBuilder",
    "ImportWarning",
    "NativePort",
    "OCGImportResult",
    "import_cwl",
    "import_agent_spec",
    "import_mcp_tools",
    "import_openapi",
    "import_wit_json",
]
