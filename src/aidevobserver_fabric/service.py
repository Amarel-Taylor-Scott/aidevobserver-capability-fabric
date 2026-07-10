"""Product operations shared by the HTTP API and browser UI."""

from __future__ import annotations

import time
import json
import csv
from pathlib import Path
from typing import Any

from . import hybrid, registry, runtime


RECEIPT_FIELDS = {
    "primitive_id",
    "action",
    "outcome",
}
RECEIPT_OUTCOMES = {"accepted", "rejected", "passed", "failed", "used"}
RECEIPT_ACTIONS = {"searched", "inspected", "executed", "materialized", "reused"}


class ServiceError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def validate_reuse_payload(payload: Any) -> dict[str, Any]:
    """Validate a compact receipt without accepting prompts, source, or secrets."""

    if not isinstance(payload, dict):
        raise ServiceError(400, "invalid_receipt", "receipt payload must be a JSON object")
    unknown = set(payload) - RECEIPT_FIELDS
    if unknown:
        raise ServiceError(400, "invalid_receipt", f"unknown receipt fields: {', '.join(sorted(unknown))}")
    primitive_id = payload.get("primitive_id")
    if not isinstance(primitive_id, str) or not primitive_id or len(primitive_id) > 256:
        raise ServiceError(400, "invalid_receipt", "primitive_id must be a non-empty string")
    if primitive_id not in runtime.EXECUTABLE_PRIMITIVES:
        raise ServiceError(400, "invalid_receipt", "primitive_id is not an executable registry primitive")
    action = payload.get("action")
    outcome = payload.get("outcome")
    if outcome is None:
        raise ServiceError(400, "invalid_receipt", "receipt requires outcome")
    if action is not None and action not in RECEIPT_ACTIONS:
        raise ServiceError(400, "invalid_receipt", "action is not supported")
    if outcome is not None and outcome not in RECEIPT_OUTCOMES:
        raise ServiceError(400, "invalid_receipt", "outcome is not supported")
    if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) > 4096:
        raise ServiceError(400, "invalid_receipt", "receipt payload must be at most 4 KB")
    return dict(payload)


class ProductService:
    """Safe allowlisted primitive discovery, execution and proof."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        registry.build_db(db_path)

    @property
    def executable_count(self) -> int:
        return len(runtime.EXECUTABLE_PRIMITIVES)

    @staticmethod
    def _spec_summary(primitive_id: str) -> dict[str, Any]:
        spec = runtime.get_primitive(primitive_id)
        return {
            "primitive_id": spec.primitive_id,
            "label": spec.label,
            "description": spec.description,
            "input_schema": spec.input_schema,
            "output_schema": spec.output_schema,
            "source_sha256": spec.source_sha256,
            "license": spec.license_spdx,
            "executable": True,
            "proof_case_count": len(spec.proof_fixtures),
        }

    @staticmethod
    def _governance(spec: runtime.ExecutablePrimitive) -> tuple[dict[str, Any], bool]:
        proof = spec.prove()
        serves_truth = bool(proof["passed"]) and not spec.primitive_id.startswith("candidate.")
        return proof, serves_truth

    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise ServiceError(400, "invalid_query", "query must be a non-empty string")
        if len(query) > 4000:
            raise ServiceError(400, "invalid_query", "query must be at most 4000 characters")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ServiceError(400, "invalid_limit", "limit must be between 1 and 20")
        if filters is None:
            filters = {}
        if not isinstance(filters, dict):
            raise ServiceError(400, "invalid_filters", "filters must be a JSON object")
        allowed_filters = {
            "input_contract",
            "output_contract",
            "trust",
            "candidate_only",
            "serves_truth",
            "executable_only",
        }
        unknown = set(filters) - allowed_filters
        if unknown:
            raise ServiceError(400, "invalid_filters", f"unknown filters: {', '.join(sorted(unknown))}")
        for key in ("input_contract", "output_contract"):
            value = filters.get(key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ServiceError(400, "invalid_filters", f"{key} must be a non-empty string")
        trust = filters.get("trust")
        if trust is not None and trust not in {"candidate", "verified"}:
            raise ServiceError(400, "invalid_filters", "trust must be candidate or verified")
        for key in ("candidate_only", "serves_truth", "executable_only"):
            value = filters.get(key)
            if value is not None and not isinstance(value, bool):
                raise ServiceError(400, "invalid_filters", f"{key} must be a boolean")
        if filters.get("candidate_only") and trust == "verified":
            raise ServiceError(400, "invalid_filters", "candidate_only conflicts with trust=verified")
        blockers = {key: value for key, value in filters.items() if key != "executable_only"}
        executable_only = filters.get("executable_only", True)
        allowed_ids = set(runtime.EXECUTABLE_PRIMITIVES) if executable_only else None
        con = registry.connect(self.db_path)
        try:
            result = hybrid.search(con, query, blockers, limit=limit, allowed_ids=allowed_ids)
        finally:
            con.close()
        enriched: list[dict[str, Any]] = []
        for row in result["results"]:
            is_executable = row["primitive_id"] in runtime.EXECUTABLE_PRIMITIVES
            if executable_only and not is_executable:
                continue
            item = {**row, "executable": is_executable}
            if is_executable:
                item.update(self._spec_summary(row["primitive_id"]))
            enriched.append(item)
            if len(enriched) >= limit:
                break
        return {
            "query": query,
            "filters": filters,
            "results": enriched,
            "result_count": len(enriched),
            "executable_primitive_count": self.executable_count,
            "candidate_bundle": None if executable_only else result["candidate_bundle"],
        }

    def get(self, primitive_id: str) -> dict[str, Any]:
        try:
            spec = runtime.get_primitive(primitive_id)
        except KeyError:
            raise ServiceError(404, "primitive_not_found", "Executable primitive not found") from None
        proof, serves_truth = self._governance(spec)
        artifact = spec.materialize()
        filename = f"{spec.module.__name__.rsplit('.', 1)[-1]}.py"
        artifact["module_filename"] = f".aidevobserver/primitives/{filename}"
        artifact["suggested_usage"] = {
            "kind": "python_runpy",
            "example": f"runpy.run_path('.aidevobserver/primitives/{filename}')['execute'](inputs)",
        }
        return {
            "primitive": {
                **artifact,
                "primitive_id": spec.primitive_id,
                "label": spec.label,
                "description": spec.description,
                "trust": "verified" if serves_truth else "candidate",
                "readiness": "R8_executable" if serves_truth else "R6_executable_proven" if proof["passed"] else "R4_proof_failed",
                "serves_truth": serves_truth,
                "executable": True,
                "proof_passed": bool(proof["passed"]),
            }
        }

    def execute(self, primitive_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(inputs, dict):
            raise ServiceError(400, "invalid_inputs", "inputs must be a JSON object")
        try:
            spec = runtime.get_primitive(primitive_id)
            started = time.perf_counter()
            output = spec.execute(inputs)
        except KeyError:
            raise ServiceError(404, "primitive_not_found", "Executable primitive not found") from None
        except runtime.SchemaValidationError as exc:
            code = "output_contract_failed" if str(exc).startswith("output $") else "input_contract_failed"
            raise ServiceError(400, code, str(exc)) from None
        except (TypeError, ValueError, LookupError, csv.Error, OverflowError) as exc:
            raise ServiceError(400, "execution_rejected", str(exc)) from None
        _, serves_truth = self._governance(spec)
        return {
            "primitive_id": primitive_id,
            "output": output,
            "source_sha256": spec.source_sha256,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "serves_truth": serves_truth,
        }

    def prove(self, primitive_id: str) -> dict[str, Any]:
        try:
            proof = runtime.prove(primitive_id)
        except KeyError:
            raise ServiceError(404, "primitive_not_found", "Executable primitive not found") from None
        return {"primitive_id": primitive_id, "proof": proof}
