"""Shared data models for the capability fabric."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PrimitiveRecord:
    primitive_id: str
    label: str
    input_contract: str
    output_contract: str
    trust: str = "candidate"
    readiness: str = "R3_contract_known"
    effects: tuple[str, ...] = ()
    memory: str = "inline"
    cache: str = "content_hash"
    serves_truth: bool = False
    remix_tools: tuple[str, ...] = ()
    proof_obligations: tuple[str, ...] = ()
    promotion_blockers: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    search_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TemplateSlot:
    slot_id: str
    role: str
    input_contract: str
    output_contract: str
    allowed_remix: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CandidateBundle:
    bundle_id: str
    query: str
    template_id: str
    template_role: str
    slots: tuple[dict[str, Any], ...]
    graph_edges: tuple[dict[str, Any], ...] = ()
    serves_truth: bool = False
    plan_delta_shape: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ServiceEndpoint:
    route: str
    method: str
    input_contract: str
    output_contract: str
    command: str | None
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ServiceRecord:
    service_id: str
    label: str
    purpose: str
    readiness: str
    mode: str
    consumes: tuple[str, ...]
    produces: tuple[str, ...]
    endpoints: tuple[ServiceEndpoint, ...]
    gates: tuple[str, ...]
    serves_truth: bool = False
    agent_visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "endpoints": [endpoint.to_dict() for endpoint in self.endpoints],
        }
