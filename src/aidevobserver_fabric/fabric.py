"""Read-only capability service fabric."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import hybrid, primitive_factory, registry
from .paths import default_db
from .seeds import SERVICES, TEMPLATE_SLOTS

DEFAULT_DB = default_db()


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def service_records() -> list[dict[str, Any]]:
    return [service.to_dict() for service in SERVICES]


def build_fabric(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    counts = registry.build_db(db_path)
    factory = primitive_factory.factory_snapshot()
    con = registry.connect(db_path)
    try:
        bundles = [
            hybrid.build_bundle(con, role.replace("_", " "), role).to_dict()
            for role in TEMPLATE_SLOTS
        ]
    finally:
        con.close()
    return {
        "fabric_id": "fabric.aidevobserver.capability.v0",
        "serves_truth": False,
        "mode": "local_readonly",
        "counts": {
            **counts,
            "candidate_bundles": len(bundles),
            "services": len(SERVICES),
            "factory_genomes": factory["counts"]["genomes"],
            "factory_mutations": factory["counts"]["mutations"],
        },
        "factory": {
            "factory_id": factory["factory_id"],
            "serves_truth": False,
            "candidate_only": True,
            "counts": factory["counts"],
        },
        "services": service_records(),
        "candidate_bundles": bundles,
        "truth_boundary": "candidate_advice_only_planlock_proof_promotion_required",
    }


def agent_discovery(fabric: dict[str, Any]) -> str:
    lines = [
        "AIDevObserver capability fabric agent discovery",
        "BOUNDARY discovery=awareness authorization=false serves_truth=false",
        f"REGISTRY primitive_records={fabric['counts']['primitive_records']} candidate_bundles={fabric['counts']['candidate_bundles']}",
    ]
    for service in fabric["services"]:
        lines.append("")
        lines.append(f"SVC {service['service_id']} {service['label']} mode:{service['mode']} readiness:{service['readiness']}")
        lines.append(f"DO {service['purpose']}")
        lines.append(f"IO in:{','.join(service['consumes'])} out:{','.join(service['produces'])}")
        lines.append(f"GATES {','.join(service['gates'])}")
        for endpoint in service["endpoints"]:
            lines.append(
                f"EP {endpoint['method']} {endpoint['route']} {endpoint['input_contract']}>{endpoint['output_contract']} "
                f"cmd:{endpoint['command'] or '-'}"
            )
    return "\n".join(lines) + "\n"


def openapi_stub(fabric: dict[str, Any]) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for service in fabric["services"]:
        for endpoint in service["endpoints"]:
            paths.setdefault(endpoint["route"], {})[endpoint["method"].lower()] = {
                "summary": endpoint["description"],
                "x-service-id": service["service_id"],
                "x-input-contract": endpoint["input_contract"],
                "x-output-contract": endpoint["output_contract"],
                "responses": {"200": {"description": "Candidate advisory response"}},
            }
    return {
        "openapi": "3.1.0",
        "info": {"title": "AIDevObserver Capability Fabric", "version": "0.2.0"},
        "paths": paths,
        "x-truth-boundary": fabric["truth_boundary"],
    }


def discover_services(fabric: dict[str, Any], query: str, limit: int = 5) -> list[dict[str, Any]]:
    query_terms = registry.expand_tokens(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    for service in fabric["services"]:
        haystack = " ".join(
            [
                service["service_id"],
                service["label"],
                service["purpose"],
                " ".join(service["consumes"]),
                " ".join(service["produces"]),
            ]
        )
        terms = registry.expand_tokens(haystack)
        overlap = len(query_terms & terms)
        if overlap:
            scored.append((overlap / max(1, len(query_terms)), service))
    scored.sort(key=lambda item: (-item[0], item[1]["service_id"]))
    return [
        {
            "service_id": service["service_id"],
            "label": service["label"],
            "purpose": service["purpose"],
            "score": round(score, 4),
            "endpoints": service["endpoints"],
            "serves_truth": service["serves_truth"],
        }
        for score, service in scored[:limit]
    ]


class FabricHandler(BaseHTTPRequestHandler):
    server_version = "AIDevObserverFabric/0.1"

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = canonical_json(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, payload: str, status: int = 200) -> None:
        body = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        fabric = self.server.fabric  # type: ignore[attr-defined]
        db_path = self.server.db_path  # type: ignore[attr-defined]
        if parsed.path == "/health":
            self.send_json({"status": "ok", "serves_truth": False})
            return
        if parsed.path == "/services":
            self.send_json(fabric)
            return
        if parsed.path == "/agents/discovery":
            self.send_text(agent_discovery(fabric))
            return
        if parsed.path == "/openapi.json":
            self.send_json(openapi_stub(fabric))
            return
        if parsed.path == "/bundles":
            self.send_json(fabric["candidate_bundles"])
            return
        if parsed.path == "/factory":
            snapshot = primitive_factory.factory_snapshot()
            if params.get("compact", ["0"])[0] in {"1", "true", "True"}:
                self.send_text(primitive_factory.compact_snapshot(snapshot))
            else:
                self.send_json(snapshot)
            return
        if parsed.path == "/factory/lineage":
            primitive_id = params.get("id", [""])[0]
            if not primitive_id:
                self.send_json({"error": "missing_id", "serves_truth": False}, status=400)
                return
            self.send_json(primitive_factory.lineage_for(primitive_id))
            return
        if parsed.path == "/services/discover":
            self.send_json({"query": params.get("q", [""])[0], "results": discover_services(fabric, params.get("q", [""])[0])})
            return
        if parsed.path == "/capabilities/search":
            query = params.get("q", [""])[0]
            blockers = {
                "input_contract": params.get("input_contract", [None])[0],
                "output_contract": params.get("output_contract", [None])[0],
                "trust": params.get("trust", [None])[0],
                "candidate_only": params.get("candidate_only", ["0"])[0] in {"1", "true", "True"},
            }
            con = hybrid.ensure_db(db_path)
            try:
                result = hybrid.search(con, query, blockers)
            finally:
                con.close()
            self.send_json(result)
            return
        self.send_json({"error": "not_found", "path": parsed.path}, status=404)

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(host: str, port: int, db_path: Path = DEFAULT_DB) -> None:
    fabric = build_fabric(db_path)
    server = ThreadingHTTPServer((host, port), FabricHandler)
    server.fabric = fabric  # type: ignore[attr-defined]
    server.db_path = db_path  # type: ignore[attr-defined]
    print(f"AIDevObserver capability fabric serving http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
