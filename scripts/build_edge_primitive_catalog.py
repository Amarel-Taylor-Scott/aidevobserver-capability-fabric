#!/usr/bin/env python3
"""Build a large edge-compatible primitive catalog.

This generator intentionally creates candidate route contracts, not promoted
truth. The rows are useful because they expose compact input/output edges,
effects, proofs, wrappers, and route templates that a planner can compose
without reading implementation internals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_OUT = Path("generated/edge_primitive_catalog")


@dataclass(frozen=True)
class Domain:
    key: str
    title: str
    actor: str
    object_name: str
    risk: str


@dataclass(frozen=True)
class DataShape:
    key: str
    title: str
    input_format: str
    schema_family: str


@dataclass(frozen=True)
class Operation:
    key: str
    verb: str
    stage_in: str
    stage_out: str
    policy: str
    receipt: str
    wrapper_group: str
    effect_classes: tuple[str, ...]
    proof_classes: tuple[str, ...]
    common_failure: str


@dataclass(frozen=True)
class Wrapper:
    key: str
    title: str
    input_policy: str
    output_artifact: str
    runtime_target: str
    effects: tuple[str, ...]
    proofs: tuple[str, ...]
    wrapper_group: str


DOMAINS = (
    Domain("auth_identity", "Auth and identity", "identity_engineer", "account", "high"),
    Domain("crud_admin", "CRUD and admin surfaces", "backend_engineer", "business_record", "medium"),
    Domain("data_ingest", "Data ingestion", "data_engineer", "record_batch", "medium"),
    Domain("data_quality", "Data quality", "analytics_engineer", "dataset", "medium"),
    Domain("format_conversion", "Format conversion", "integration_engineer", "artifact", "low"),
    Domain("schema_mapping", "Schema mapping", "data_architect", "schema_contract", "medium"),
    Domain("entity_resolution", "Entity resolution", "data_steward", "entity", "high"),
    Domain("enrichment_verification", "Enrichment and verification", "research_analyst", "fact_set", "high"),
    Domain("document_intelligence", "Document intelligence", "document_engineer", "document", "high"),
    Domain("rag_grounding", "RAG and citation grounding", "ai_engineer", "answer", "high"),
    Domain("api_integration", "API integration", "platform_engineer", "api_operation", "medium"),
    Domain("async_workflows", "Async workflows", "systems_engineer", "event", "medium"),
    Domain("email_human_actions", "Email and human actions", "ops_lead", "human_task", "medium"),
    Domain("devops_deployment", "DevOps and deployment", "sre", "deployment", "high"),
    Domain("observability_incident", "Observability and incidents", "incident_commander", "signal", "medium"),
    Domain("security_guardrails", "Security guardrails", "security_engineer", "policy_decision", "high"),
    Domain("geospatial_open_data", "Geospatial and open data", "gis_analyst", "place", "medium"),
    Domain("browser_automation", "Browser automation", "automation_engineer", "browser_trace", "medium"),
    Domain("ml_data_science", "ML and data science", "ml_engineer", "experiment", "medium"),
    Domain("visualization_media", "Visualization and media", "frontend_engineer", "visual_artifact", "low"),
    Domain("repo_package_mining", "Repo and package mining", "developer_tools_engineer", "code_surface", "medium"),
    Domain("marketplace_packaging", "Marketplace packaging", "solutions_architect", "package_listing", "medium"),
)


DATA_SHAPES = (
    DataShape("json_object", "JSON object", "json", "json_schema"),
    DataShape("jsonl_stream", "JSONL stream", "jsonl", "json_schema"),
    DataShape("csv_table", "CSV table", "csv", "csvw"),
    DataShape("xlsx_workbook", "XLSX workbook", "xlsx", "spreadsheet_schema"),
    DataShape("parquet_dataset", "Parquet dataset", "parquet", "arrow_schema"),
    DataShape("sql_rowset", "SQL rowset", "sql", "relational_schema"),
    DataShape("html_page", "HTML page", "html", "dom_schema"),
    DataShape("pdf_document", "PDF document", "pdf", "source_span_schema"),
    DataShape("markdown_doc", "Markdown document", "markdown", "section_schema"),
    DataShape("api_payload", "API request/response", "http_json", "openapi_schema"),
    DataShape("queue_event", "Queue event", "event_json", "asyncapi_message"),
    DataShape("webhook_event", "Webhook event", "webhook_json", "webhook_schema"),
    DataShape("image_asset", "Image asset", "image", "media_metadata"),
    DataShape("vector_index", "Vector index", "embedding_index", "vector_schema"),
    DataShape("graph_edges", "Graph edge list", "graph", "graph_schema"),
    DataShape("infra_manifest", "Infrastructure manifest", "iac", "deployment_schema"),
)


OPERATIONS = (
    Operation(
        "discover_source",
        "discover",
        "request",
        "source_surface",
        "SourceDiscoveryPolicy",
        "SourceDiscoveryReceipt",
        "read",
        ("network_read_optional", "artifact_write"),
        ("source_policy_check", "catalog_schema_validation"),
        "source surface is stale or outside policy",
    ),
    Operation(
        "fetch_extract",
        "fetch and extract",
        "source_surface",
        "raw",
        "FetchExtractionPolicy",
        "SnapshotReceipt",
        "read",
        ("network_read_optional", "file_read_optional", "artifact_write"),
        ("snapshot_hash_check", "license_policy_check", "robots_or_terms_review"),
        "source changed shape after discovery",
    ),
    Operation(
        "parse_ingest",
        "parse and ingest",
        "raw",
        "parsed",
        "ParsePolicy",
        "ParseReceipt",
        "pure",
        ("file_read_optional", "artifact_write"),
        ("parser_fixture_test", "lossiness_report", "schema_fingerprint"),
        "parser silently drops nested or malformed fields",
    ),
    Operation(
        "validate_contract",
        "validate",
        "parsed",
        "validated",
        "ValidationPolicy",
        "ValidationReceipt",
        "pure",
        ("artifact_write",),
        ("schema_validation", "failure_row_artifact_test", "contract_test"),
        "validator accepts incomplete records",
    ),
    Operation(
        "clean_normalize",
        "clean and normalize",
        "validated",
        "normalized",
        "NormalizationPolicy",
        "NormalizationReceipt",
        "pure",
        ("artifact_write",),
        ("normalization_fixture_test", "roundtrip_or_lossiness_test", "idempotency_test"),
        "normalization changes meaning while fixing format",
    ),
    Operation(
        "resolve_dedupe",
        "resolve and dedupe",
        "normalized",
        "canonical",
        "ResolutionPolicy",
        "MatchDecisionReceipt",
        "pure",
        ("artifact_write",),
        ("pairwise_match_fixture", "threshold_sensitivity_test", "clerical_review_gate"),
        "near-duplicate entities are over-merged",
    ),
    Operation(
        "enrich_join",
        "enrich and join",
        "canonical",
        "enriched",
        "EnrichmentPolicy",
        "EvidenceBundle",
        "read",
        ("network_read_optional", "database_read_optional", "artifact_write"),
        ("source_ref_required", "field_lineage_test", "freshness_policy_check"),
        "enrichment source is authoritative for one field but not another",
    ),
    Operation(
        "transform_remix",
        "transform and remix",
        "enriched",
        "transformed",
        "TransformPolicy",
        "TransformReceipt",
        "pure",
        ("artifact_write",),
        ("field_mapping_test", "lossiness_report", "metamorphic_test"),
        "field mapping is syntactically valid but semantically inverted",
    ),
    Operation(
        "compile_plan",
        "compile",
        "transformed",
        "plan",
        "CompilePolicy",
        "PlanLock",
        "compile",
        ("artifact_write",),
        ("planlock_schema_test", "effect_policy_check", "route_hash_recompute"),
        "plan compiles with an undeclared side effect",
    ),
    Operation(
        "package_runtime",
        "package",
        "plan",
        "packaged",
        "PackagePolicy",
        "PackageReceipt",
        "package",
        ("artifact_write", "container_build_optional"),
        ("manifest_schema_test", "sbom_required", "package_smoke_test"),
        "package artifact omits runtime dependency metadata",
    ),
    Operation(
        "execute_action",
        "execute",
        "packaged",
        "receipt",
        "ExecutionPolicy",
        "ExecutionReceipt",
        "write",
        ("network_write_optional", "database_write_optional", "audit_log_write"),
        ("sandbox_smoke_test", "state_diff_test", "audit_receipt_schema_test"),
        "execution succeeds but writes outside approved scope",
    ),
    Operation(
        "observe_report",
        "observe and report",
        "receipt",
        "monitor",
        "ObservationPolicy",
        "Scorecard",
        "observe",
        ("log_read_optional", "artifact_write"),
        ("telemetry_schema_test", "scorecard_recompute", "negative_memory_check"),
        "scorecard hides partial proof failure",
    ),
    Operation(
        "human_review",
        "queue human review",
        "monitor",
        "review",
        "ReviewPolicy",
        "HumanReviewReceipt",
        "human",
        ("human_review_required", "notification_write_optional", "audit_log_write"),
        ("review_packet_schema_test", "assignment_policy_test", "decision_receipt_test"),
        "human review packet lacks enough evidence to decide",
    ),
)


WRAPPERS = (
    Wrapper(
        "python_function",
        "Python function",
        "PythonInvocationPolicy",
        "PythonFunctionArtifact",
        "python_function",
        (),
        ("unit_test", "type_check"),
        "pure",
    ),
    Wrapper(
        "typescript_function",
        "TypeScript function",
        "TypeScriptInvocationPolicy",
        "TypeScriptFunctionArtifact",
        "typescript_function",
        (),
        ("unit_test", "type_check"),
        "pure",
    ),
    Wrapper(
        "fastapi_endpoint",
        "FastAPI endpoint",
        "HttpRequestPolicy",
        "OpenApiEndpointArtifact",
        "fastapi_endpoint",
        ("network_bind_optional",),
        ("openapi_contract_test", "request_response_test"),
        "read",
    ),
    Wrapper(
        "mcp_tool",
        "MCP tool",
        "ToolInvocationPolicy",
        "McpToolArtifact",
        "mcp_tool",
        ("tool_call_exposed",),
        ("tool_schema_test", "tool_call_fixture_test"),
        "read",
    ),
    Wrapper(
        "cli_command",
        "CLI command",
        "CliInvocationPolicy",
        "CliCommandArtifact",
        "cli_command",
        ("process_spawn_optional",),
        ("exit_code_test", "stdout_schema_test"),
        "pure",
    ),
    Wrapper(
        "queue_worker",
        "Queue worker",
        "QueueDeliveryPolicy",
        "QueueWorkerArtifact",
        "queue_worker",
        ("queue_read", "queue_write_optional"),
        ("idempotency_test", "dead_letter_route_test", "retry_policy_test"),
        "write",
    ),
    Wrapper(
        "cron_job",
        "Cron job",
        "SchedulePolicy",
        "ScheduledJobArtifact",
        "cron_job",
        ("schedule_bind",),
        ("schedule_policy_test", "replay_window_test"),
        "observe",
    ),
    Wrapper(
        "cloud_function",
        "Cloud function",
        "CloudFunctionPolicy",
        "CloudFunctionArtifact",
        "cloud_function",
        ("cloud_runtime_bind", "network_bind_optional"),
        ("cloud_smoke_test", "iam_policy_test"),
        "write",
    ),
    Wrapper(
        "kubernetes_job",
        "Kubernetes job",
        "KubernetesJobPolicy",
        "KubernetesJobManifest",
        "kubernetes_job",
        ("kubernetes_write_optional",),
        ("manifest_schema_test", "dry_run_apply_test"),
        "package",
    ),
    Wrapper(
        "github_action",
        "GitHub Action",
        "GithubActionPolicy",
        "GithubActionWorkflow",
        "github_action",
        ("ci_write_optional",),
        ("workflow_syntax_test", "permissions_minimum_test"),
        "package",
    ),
    Wrapper(
        "airflow_task",
        "Airflow task",
        "AirflowTaskPolicy",
        "AirflowTaskArtifact",
        "airflow_task",
        ("dag_bind",),
        ("dag_parse_test", "task_retry_policy_test"),
        "pure",
    ),
    Wrapper(
        "browser_worker",
        "Browser worker",
        "BrowserAutomationPolicy",
        "BrowserRecipeArtifact",
        "browser_worker",
        ("browser_read_optional", "browser_write_optional"),
        ("selector_fixture_test", "screenshot_diff_test"),
        "read",
    ),
    Wrapper(
        "terraform_module",
        "Terraform module",
        "TerraformModulePolicy",
        "TerraformModuleArtifact",
        "terraform_module",
        ("iac_write_optional",),
        ("terraform_validate", "plan_snapshot_test"),
        "package",
    ),
    Wrapper(
        "human_review_task",
        "Human review task",
        "HumanAssignmentPolicy",
        "ReviewQueueArtifact",
        "human_review_task",
        ("human_review_required", "notification_write_optional"),
        ("review_packet_schema_test", "decision_receipt_test"),
        "human",
    ),
)


WRAPPER_GROUPS = {
    "pure": {"python_function", "typescript_function", "cli_command", "mcp_tool", "airflow_task"},
    "read": {"python_function", "fastapi_endpoint", "mcp_tool", "queue_worker", "cron_job", "cloud_function", "browser_worker"},
    "compile": {"python_function", "cli_command", "mcp_tool", "github_action", "airflow_task"},
    "package": {"cli_command", "github_action", "kubernetes_job", "terraform_module", "cloud_function"},
    "write": {"fastapi_endpoint", "queue_worker", "cloud_function", "kubernetes_job", "github_action", "mcp_tool"},
    "observe": {"python_function", "mcp_tool", "cron_job", "queue_worker", "fastapi_endpoint", "cli_command"},
    "human": {"human_review_task", "fastapi_endpoint", "mcp_tool", "queue_worker"},
}


ROUTE_PATTERNS = (
    ("full_proof_route", ("discover_source", "fetch_extract", "parse_ingest", "validate_contract", "clean_normalize", "resolve_dedupe", "enrich_join", "transform_remix", "compile_plan", "package_runtime", "execute_action", "observe_report", "human_review")),
    ("compact_data_route", ("parse_ingest", "validate_contract", "clean_normalize", "resolve_dedupe", "enrich_join", "transform_remix", "compile_plan", "package_runtime", "execute_action", "observe_report")),
    ("source_to_evidence_route", ("discover_source", "fetch_extract", "parse_ingest", "validate_contract", "clean_normalize", "resolve_dedupe", "enrich_join")),
    ("deployment_route", ("transform_remix", "compile_plan", "package_runtime", "execute_action", "observe_report")),
    ("review_safe_write_route", ("validate_contract", "clean_normalize", "resolve_dedupe", "enrich_join", "transform_remix", "compile_plan", "package_runtime", "execute_action", "observe_report", "human_review")),
)


def artifact(domain: Domain, shape: DataShape, stage: str) -> str:
    return f"{stage.title().replace('_', '')}[{domain.key}.{shape.key}]"


def stable_id(*parts: str, length: int = 12) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:length]


def json_dumps(row: Any) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json_dumps(row) + "\n")
            count += 1
    return count


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def family_id(domain: Domain, shape: DataShape, op: Operation) -> str:
    return f"fam:{domain.key}.{shape.key}.{op.key}@candidate"


def primitive_id(fid: str, wrapper: Wrapper) -> str:
    base = fid.removeprefix("fam:").removesuffix("@candidate")
    return f"prim:{base}.{wrapper.key}@candidate"


def applicable_wrappers(op: Operation) -> tuple[Wrapper, ...]:
    keys = WRAPPER_GROUPS[op.wrapper_group]
    return tuple(wrapper for wrapper in WRAPPERS if wrapper.key in keys)


def build_families() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for domain in DOMAINS:
        for shape in DATA_SHAPES:
            for op in OPERATIONS:
                input_type = artifact(domain, shape, op.stage_in)
                output_type = artifact(domain, shape, op.stage_out)
                fid = family_id(domain, shape, op)
                rows.append(
                    {
                        "family_id": fid,
                        "record_type": "primitive_family",
                        "domain": domain.key,
                        "domain_title": domain.title,
                        "data_shape": shape.key,
                        "input_format": shape.input_format,
                        "schema_family": shape.schema_family,
                        "operation": op.key,
                        "title": f"{op.verb.title()} {shape.title} for {domain.title}",
                        "input_edge": f"{input_type}+{op.policy}+ProjectContext",
                        "output_edge": f"{output_type}+{op.receipt}",
                        "edge_signature": {
                            "input_types": [input_type, op.policy, "ProjectContext"],
                            "output_types": [output_type, op.receipt],
                            "effect_classes": list(op.effect_classes),
                            "proof_classes": list(op.proof_classes),
                        },
                        "blackbox": {
                            "does": f"{op.verb.title()}s {domain.object_name} material in {shape.title} form and emits {op.receipt}.",
                            "llm_context_policy": "show_edge_first; drilldown_on_contract_or_proof_need",
                        },
                        "problem_solution": {
                            "problem": f"{domain.title} workflows repeatedly need {op.verb} over {shape.title} artifacts.",
                            "naive_agent_failure": "A coding agent usually rereads source/docs and rewrites glue instead of selecting a proven edge-compatible capability.",
                            "solution": "Expose a compact contract so a route compiler can compose this step with neighboring stages.",
                            "core_components": [op.policy, shape.schema_family, op.receipt],
                            "common_inputs": [input_type, op.policy],
                            "common_outputs": [output_type, op.receipt],
                            "known_pitfalls": [op.common_failure],
                            "success_signals": list(op.proof_classes),
                        },
                        "applicable_wrappers": [wrapper.key for wrapper in applicable_wrappers(op)],
                        "effects": list(op.effect_classes),
                        "proof_requirements": list(op.proof_classes),
                        "runtime_targets": [wrapper.runtime_target for wrapper in applicable_wrappers(op)],
                        "source_ref_policy": "source_refs_required_before_promotion",
                        "promotion_blockers": [
                            "source_refs_missing",
                            "implementation_missing",
                            "fixture_receipts_missing",
                            "effect_audit_missing",
                        ],
                        "risk": domain.risk,
                        "candidate": True,
                        "serves_truth": False,
                    }
                )
    return rows


def build_wrappers() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for wrapper in WRAPPERS:
        rows.append(
            {
                "wrapper_id": f"wrap:{wrapper.key}@candidate",
                "record_type": "runtime_wrapper",
                "title": wrapper.title,
                "input_policy": wrapper.input_policy,
                "output_artifact": wrapper.output_artifact,
                "runtime_target": wrapper.runtime_target,
                "wrapper_group": wrapper.wrapper_group,
                "effects": list(wrapper.effects),
                "proof_requirements": list(wrapper.proofs),
                "candidate": True,
                "serves_truth": False,
            }
        )
    return rows


def build_resolved(families: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wrapper_by_key = {wrapper.key: wrapper for wrapper in WRAPPERS}
    rows: list[dict[str, Any]] = []
    for family in families:
        for wrapper_key in family["applicable_wrappers"]:
            wrapper = wrapper_by_key[wrapper_key]
            pid = primitive_id(family["family_id"], wrapper)
            rows.append(
                {
                    "primitive_id": pid,
                    "record_type": "resolved_primitive",
                    "family_id": family["family_id"],
                    "wrapper_id": f"wrap:{wrapper.key}@candidate",
                    "title": f"{family['title']} as {wrapper.title}",
                    "input_edge": f"{family['input_edge']}+{wrapper.input_policy}",
                    "output_edge": f"{family['output_edge']}+{wrapper.output_artifact}",
                    "edge_signature": {
                        "input_types": family["edge_signature"]["input_types"] + [wrapper.input_policy],
                        "output_types": family["edge_signature"]["output_types"] + [wrapper.output_artifact],
                        "effect_classes": sorted(set(family["effects"]) | set(wrapper.effects)),
                        "proof_classes": sorted(set(family["proof_requirements"]) | set(wrapper.proofs)),
                    },
                    "blackbox": family["blackbox"],
                    "problem_solution": family["problem_solution"],
                    "effects": sorted(set(family["effects"]) | set(wrapper.effects)),
                    "proof_requirements": sorted(set(family["proof_requirements"]) | set(wrapper.proofs)),
                    "runtime_targets": [wrapper.runtime_target],
                    "source_ref_policy": family["source_ref_policy"],
                    "promotion_blockers": family["promotion_blockers"],
                    "candidate": True,
                    "serves_truth": False,
                }
            )
    return rows


def build_compatibility_edges(resolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_input: dict[str, list[dict[str, Any]]] = {}
    for row in resolved:
        for input_type in row["edge_signature"]["input_types"][:1]:
            by_input.setdefault(input_type, []).append(row)

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for left in resolved:
        output_type = left["edge_signature"]["output_types"][0]
        candidates = by_input.get(output_type, [])
        for right in candidates[:12]:
            key = (left["primitive_id"], right["primitive_id"])
            if key in seen or left["primitive_id"] == right["primitive_id"]:
                continue
            seen.add(key)
            edges.append(
                {
                    "edge_id": f"edge:{stable_id(left['primitive_id'], right['primitive_id'])}",
                    "record_type": "compatibility_edge",
                    "from_primitive_id": left["primitive_id"],
                    "to_primitive_id": right["primitive_id"],
                    "from_output_type": output_type,
                    "to_input_type": right["edge_signature"]["input_types"][0],
                    "status": "direct_type_compatible",
                    "reason": "primary output type equals primary input type",
                    "candidate": True,
                    "serves_truth": False,
                }
            )
    return edges


def pick_primitive(resolved_by_family: dict[str, list[dict[str, Any]]], fid: str, preferred: tuple[str, ...]) -> str:
    rows = resolved_by_family[fid]
    for wrapper in preferred:
        suffix = f".{wrapper}@candidate"
        for row in rows:
            if row["primitive_id"].endswith(suffix):
                return row["primitive_id"]
    return rows[0]["primitive_id"]


def build_route_templates(resolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolved_by_family: dict[str, list[dict[str, Any]]] = {}
    for row in resolved:
        resolved_by_family.setdefault(row["family_id"], []).append(row)
    resolved_by_id = {row["primitive_id"]: row for row in resolved}

    op_by_key = {op.key: op for op in OPERATIONS}
    rows: list[dict[str, Any]] = []
    for domain in DOMAINS:
        for shape in DATA_SHAPES:
            for pattern_name, ops in ROUTE_PATTERNS:
                step_ids = []
                stages = []
                for op_key in ops:
                    fid = family_id(domain, shape, op_by_key[op_key])
                    step_ids.append(pick_primitive(resolved_by_family, fid, ("python_function", "mcp_tool", "queue_worker", "cli_command", "fastapi_endpoint")))
                    stages.append(op_key)
                route_input = artifact(domain, shape, op_by_key[ops[0]].stage_in)
                route_output = artifact(domain, shape, op_by_key[ops[-1]].stage_out)
                rows.append(
                    {
                        "route_template_id": f"route:{domain.key}.{shape.key}.{pattern_name}@candidate",
                        "record_type": "route_template",
                        "domain": domain.key,
                        "data_shape": shape.key,
                        "pattern": pattern_name,
                        "title": f"{pattern_name.replace('_', ' ').title()} for {domain.title} {shape.title}",
                        "input_edge": f"{route_input}+RoutePolicy+ProjectContext",
                        "output_edge": f"{route_output}+RouteReceipt",
                        "route_steps": step_ids,
                        "stage_sequence": stages,
                        "required_proofs": sorted(
                            {
                                proof
                                for step_id in step_ids
                                for proof in resolved_by_id[step_id]["proof_requirements"]
                            }
                        )[:24],
                        "compile_policy": "PlanLock required before execution; source fallback only when candidate bundle score is insufficient.",
                        "candidate": True,
                        "serves_truth": False,
                    }
                )
    return rows


def build_candidate_bundles(
    route_templates: list[dict[str, Any]],
    resolved_by_id: dict[str, dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for route in route_templates[:limit]:
        candidates = []
        for index, primitive_id in enumerate(route["route_steps"][:8]):
            primitive = resolved_by_id[primitive_id]
            candidates.append(
                {
                    "slot_alias": f"S{index}",
                    "primitive_id": primitive_id,
                    "input_edge": primitive["input_edge"],
                    "output_edge": primitive["output_edge"],
                    "fit": "direct_edge",
                    "candidate": True,
                    "serves_truth": False,
                }
            )
        rows.append(
            {
                "candidate_bundle_id": f"cb:{stable_id(route['route_template_id'])}",
                "record_type": "candidate_bundle_example",
                "query": f"compile a {route['pattern']} for {route['domain']} using {route['data_shape']}",
                "route_template_id": route["route_template_id"],
                "candidate_primitives": candidates,
                "plan_delta_shape": {
                    "v": 1,
                    "selected_slots": [item["slot_alias"] for item in candidates],
                    "mutators": ["edge_signature_check", "proof_requirement_union", "planlock_canonicalizer"],
                },
                "candidate": True,
                "serves_truth": False,
            }
        )
    return rows


def write_readme(out: Path, counts: dict[str, int]) -> None:
    lines = [
        "# Edge Primitive Catalog",
        "",
        "Generated candidate catalog for edge-first graph compilation.",
        "",
        "Rows are not promoted truth. Every row is `candidate=true` and `serves_truth=false`.",
        "Promotion requires source refs, implementation, effect audit, fixture receipts, and benchmark evidence.",
        "",
        "## Counts",
        "",
    ]
    for key, value in counts.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Files",
            "",
            "- `primitive_families.jsonl`: reusable capability families.",
            "- `runtime_wrappers.jsonl`: runtime packaging surfaces.",
            "- `resolved_primitives.jsonl`: family plus wrapper edge contracts.",
            "- `compatibility_edges.jsonl`: direct output-to-input graph edges.",
            "- `route_templates.jsonl`: reusable route skeletons.",
            "- `candidate_bundle_examples.jsonl`: compact planner inputs.",
            "- `manifest.json`: row counts and hashes.",
            "",
            "Use `python3 scripts/check_edge_primitive_catalog.py` after generation.",
            "",
        ]
    )
    out.joinpath("README.md").write_text("\n".join(lines), encoding="utf-8")


def build(out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    families = build_families()
    wrappers = build_wrappers()
    resolved = build_resolved(families)
    edges = build_compatibility_edges(resolved)
    routes = build_route_templates(resolved)
    resolved_by_id = {row["primitive_id"]: row for row in resolved}
    bundles = build_candidate_bundles(routes, resolved_by_id, limit=600)

    file_rows = {
        "primitive_families.jsonl": families,
        "runtime_wrappers.jsonl": wrappers,
        "resolved_primitives.jsonl": resolved,
        "compatibility_edges.jsonl": edges,
        "route_templates.jsonl": routes,
        "candidate_bundle_examples.jsonl": bundles,
    }
    counts = {name.removesuffix(".jsonl"): len(rows) for name, rows in file_rows.items()}
    write_readme(out, counts)
    manifest: dict[str, Any] = {
        "pack_id": "edge_primitive_catalog",
        "version": 1,
        "candidate": True,
        "serves_truth": False,
        "generation_policy": "deterministic_lattice; no generated row is promoted truth",
        "files": {},
    }
    for filename, rows in file_rows.items():
        path = out / filename
        count = write_jsonl(path, rows)
        manifest["files"][filename] = {"rows": count, "sha256": sha256_file(path)}
    write_readme(out, counts)
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    manifest = build(args.out)
    print(json.dumps({"ok": True, "out": str(args.out), "files": manifest["files"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
