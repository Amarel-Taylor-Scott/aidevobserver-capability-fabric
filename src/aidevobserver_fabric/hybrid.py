"""Hybrid search and CandidateBundle generation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import registry
from .models import CandidateBundle, TemplateSlot
from .seeds import TEMPLATE_IDS, TEMPLATE_SLOTS

RRF_K = 60


@dataclass(frozen=True)
class LaneHit:
    primitive_id: str
    score: float
    reason: str


def infer_template_role(query: str, blockers: dict[str, Any]) -> str:
    if blockers.get("output_contract") == "ColumnProfileSet":
        return "profile_tabular_data"
    if blockers.get("output_contract") == "AgentLoopFindingSet":
        return "review_agent_session"
    if blockers.get("output_contract") == "RawFieldSet":
        return "extract_schema_fields"
    terms = registry.expand_tokens(query)
    if {"csv", "table", "warehouse"} & terms:
        return "profile_tabular_data"
    if {"document", "schema", "fields"} & terms:
        return "extract_schema_fields"
    if {"agent", "loop", "retry", "session"} & terms:
        return "review_agent_session"
    return "normalize_regulatory_rates"


def candidate_rows(con: sqlite3.Connection, blockers: dict[str, Any]) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[Any] = []
    if blockers.get("input_contract"):
        clauses.append("input_contract = ?")
        params.append(blockers["input_contract"])
    if blockers.get("output_contract"):
        clauses.append("output_contract = ?")
        params.append(blockers["output_contract"])
    if blockers.get("trust"):
        clauses.append("trust = ?")
        params.append(blockers["trust"])
    if blockers.get("candidate_only"):
        clauses.append("trust = 'candidate'")
    if blockers.get("serves_truth") is not None:
        clauses.append("serves_truth = ?")
        params.append(int(blockers["serves_truth"]))
    sql = "SELECT * FROM primitives"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return list(con.execute(sql, params))


def sort_hits(hits: list[LaneHit]) -> list[LaneHit]:
    return sorted([hit for hit in hits if hit.score > 0], key=lambda item: (-item.score, item.primitive_id))


def rank_exact(rows: list[sqlite3.Row], blockers: dict[str, Any]) -> list[LaneHit]:
    hits: list[LaneHit] = []
    for row in rows:
        score = 0.0
        if blockers.get("input_contract") == row["input_contract"]:
            score += 1.0
        if blockers.get("output_contract") == row["output_contract"]:
            score += 1.0
        if blockers.get("trust") == row["trust"]:
            score += 0.3
        hits.append(LaneHit(row["primitive_id"], score, "hard_contract_match"))
    return sort_hits(hits)


def rank_fts(con: sqlite3.Connection, rows: list[sqlite3.Row], query: str) -> list[LaneHit]:
    allowed = {row["primitive_id"] for row in rows}
    terms = sorted(registry.normalize_tokens(query))
    if not terms:
        return []
    try:
        matches = con.execute(
            """
            SELECT primitive_id, bm25(primitive_search) AS rank_score
            FROM primitive_search
            WHERE primitive_search MATCH ?
            ORDER BY rank_score ASC
            """,
            (" OR ".join(terms),),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    hits = []
    for index, row in enumerate(matches, start=1):
        if row["primitive_id"] in allowed:
            hits.append(LaneHit(row["primitive_id"], 1.0 / index, "fts_bm25"))
    return sort_hits(hits)


def rank_semantic(rows: list[sqlite3.Row], query: str) -> list[LaneHit]:
    query_terms = registry.expand_tokens(query)
    hits: list[LaneHit] = []
    for row in rows:
        row_terms = set((row["semantic_terms"] or "").split())
        overlap = len(query_terms & row_terms)
        hits.append(LaneHit(row["primitive_id"], overlap / max(1, len(query_terms)), f"term_overlap:{overlap}"))
    return sort_hits(hits)


def rank_trust(rows: list[sqlite3.Row]) -> list[LaneHit]:
    hits: list[LaneHit] = []
    for row in rows:
        score = 0.05
        if row["trust"] == "verified":
            score += 0.75
        if row["serves_truth"]:
            score += 0.25
        if row["readiness"].startswith("R8"):
            score += 0.1
        hits.append(LaneHit(row["primitive_id"], score, "trust_proof"))
    return sort_hits(hits)


def rrf(rankings: dict[str, list[LaneHit]], k: int = RRF_K) -> dict[str, dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    for lane, hits in rankings.items():
        for rank, hit in enumerate(hits, start=1):
            entry = fused.setdefault(hit.primitive_id, {"score": 0.0, "lanes": [], "reasons": {}})
            entry["score"] += 1.0 / (k + rank)
            entry["lanes"].append(lane)
            entry["reasons"][lane] = hit.reason
    return fused


def list_inner(contract: str) -> str | None:
    if contract.startswith("list[") and contract.endswith("]"):
        return contract[5:-1]
    return None


def remix_fit(row: sqlite3.Row, slot: TemplateSlot) -> str | None:
    if "map_sequence" not in slot.allowed_remix:
        return None
    if list_inner(slot.input_contract) == row["input_contract"] and list_inner(slot.output_contract) == row["output_contract"]:
        return "map_sequence"
    return None


def slot_candidates(con: sqlite3.Connection, slot: TemplateSlot) -> list[dict[str, Any]]:
    rows = con.execute("SELECT * FROM primitives").fetchall()
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        direct = row["input_contract"] == slot.input_contract and row["output_contract"] == slot.output_contract
        remix = remix_fit(row, slot)
        if not direct and remix is None:
            continue
        score = 1.0 if direct else 0.82
        if row["trust"] == "verified":
            score += 0.2
        scored.append(
            (
                score,
                {
                    "primitive_id": row["primitive_id"],
                    "label": row["label"],
                    "input_contract": row["input_contract"],
                    "output_contract": row["output_contract"],
                    "fit": "direct" if direct else "remix",
                    "remix": remix,
                    "trust": row["trust"],
                    "serves_truth": bool(row["serves_truth"]),
                },
            )
        )
    scored.sort(key=lambda item: (-item[0], item[1]["primitive_id"]))
    return [item[1] for item in scored[:4]]


def build_bundle(con: sqlite3.Connection, query: str, role: str) -> CandidateBundle:
    slots = []
    for slot_index, slot in enumerate(TEMPLATE_SLOTS[role]):
        candidates = []
        for candidate_index, candidate in enumerate(slot_candidates(con, slot)):
            candidates.append({"alias": f"C{slot_index}.{candidate_index}", **candidate})
        slots.append({"slot_alias": f"S{slot_index}", **slot.to_dict(), "candidates": candidates})
    return CandidateBundle(
        bundle_id=f"bundle.{role}",
        query=query,
        template_id=TEMPLATE_IDS[role],
        template_role=role,
        slots=tuple(slots),
        plan_delta_shape={"v": 1, "p": "dense", "t": 0, "b": [0 for _ in slots], "r": []},
    )


def search(con: sqlite3.Connection, query: str, blockers: dict[str, Any], limit: int = 6) -> dict[str, Any]:
    rows = candidate_rows(con, blockers)
    row_by_id = {row["primitive_id"]: row for row in rows}
    rankings = {
        "exact_contract": rank_exact(rows, blockers),
        "fts": rank_fts(con, rows, query),
        "semantic": rank_semantic(rows, query),
        "trust": rank_trust(rows),
    }
    fused = rrf(rankings)
    results = []
    for primitive_id, item in fused.items():
        row = row_by_id[primitive_id]
        results.append(
            {
                "primitive_id": primitive_id,
                "label": row["label"],
                "input_contract": row["input_contract"],
                "output_contract": row["output_contract"],
                "trust": row["trust"],
                "serves_truth": bool(row["serves_truth"]),
                "rrf_score": round(item["score"], 6),
                "lanes": sorted(set(item["lanes"])),
            }
        )
    results.sort(key=lambda item: (-item["rrf_score"], item["primitive_id"]))
    role = infer_template_role(query, blockers)
    return {
        "query": query,
        "blockers": blockers,
        "results": results[:limit],
        "candidate_bundle": build_bundle(con, query, role).to_dict(),
    }


def compact_result(result: dict[str, Any]) -> str:
    lines = ["AIDevObserver hybrid search", f"Q {result['query']}"]
    for index, item in enumerate(result["results"][:3], start=1):
        truth = "T" if item["serves_truth"] else "C"
        lines.append(
            f"TOP{index} {item['primitive_id']} {item['input_contract']}>{item['output_contract']} "
            f"tr:{item['trust']} truth:{truth} score:{item['rrf_score']} lanes:{','.join(item['lanes'])}"
        )
    bundle = result["candidate_bundle"]
    lines.append(f"CB {bundle['bundle_id']} T {bundle['template_id']} role:{bundle['template_role']}")
    for slot in bundle["slots"]:
        lines.append(f"{slot['slot_alias']} {slot['slot_id']} {slot['input_contract']}>{slot['output_contract']}")
        for candidate in slot["candidates"][:2]:
            lines.append(f"{candidate['alias']} {candidate['primitive_id']} fit:{candidate['fit']} tr:{candidate['trust']}")
    return "\n".join(lines) + "\n"


def ensure_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        registry.build_db(path)
    return registry.connect(path)
