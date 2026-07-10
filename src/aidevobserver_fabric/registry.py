"""SQLite primitive registry."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from pathlib import Path

from .models import PrimitiveRecord
from .seeds import SEED_PRIMITIVES

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")

SYNONYMS = {
    "document": {"doc", "schema", "fields", "extraction", "json"},
    "schema": {"fields", "contract", "json", "validation"},
    "loop": {"retry", "failure", "agent", "session"},
    "rate": {"interest", "jurisdiction", "normalize"},
    "registry": {"catalog", "metadata", "component"},
    "search": {"find", "retrieve", "lookup", "rank"},
    "email": {"address", "mailbox"},
    "phone": {"telephone", "e164", "mobile"},
    "luhn": {"credit", "card", "pan", "imei", "npi", "checksum", "mod10"},
    "credit": {"card", "luhn", "pan", "checksum"},
    "iban": {"bank", "account", "iso13616", "mod97"},
    "sha256": {"hash", "digest", "checksum", "crypto"},
    "cosine": {"vector", "similarity", "embedding"},
    "jaro": {"winkler", "fuzzy", "string", "similarity"},
    "csv": {"table", "rows", "file", "delimiter", "columns", "profile"},
    "date": {"calendar", "iso8601", "day", "month", "year"},
    "tokens": {"count", "approximate", "llm"},
}

STOPWORDS = {
    "a", "an", "and", "build", "code", "create", "data", "existing",
    "extract", "find", "for", "from", "function", "input", "make",
    "normalize", "number", "numbers", "or", "output", "primitive",
    "service", "text", "the", "to", "tool", "use", "using", "validate",
    "validation", "value", "with",
}


def normalize_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in TOKEN_RE.findall(text.replace(">", " ").replace("[", " ").replace("]", " ")):
        for part in raw.replace("__", "_").split("_"):
            if len(part) >= 2:
                tokens.add(part.lower())
        if len(raw) >= 2:
            tokens.add(raw.lower())
    return tokens


def expand_tokens(text: str) -> set[str]:
    tokens = normalize_tokens(text)
    expanded = set(tokens)
    for token in list(tokens):
        expanded.update(SYNONYMS.get(token, set()))
    return expanded


def meaningful_terms(text: str) -> set[str]:
    return expand_tokens(text) - STOPWORDS


def hashed_vector(terms: tuple[str, ...], dims: int = 16) -> tuple[float, ...]:
    values = [0.0 for _ in range(dims)]
    for term in terms:
        bucket = sum(ord(ch) for ch in term) % dims
        sign = -1.0 if sum(ord(ch) for ch in reversed(term)) % 2 else 1.0
        values[bucket] += sign
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return tuple(round(value / norm, 6) for value in values)


def semantic_terms(record: PrimitiveRecord) -> tuple[str, ...]:
    text = " ".join(
        [
            record.primitive_id,
            record.label,
            record.input_contract,
            record.output_contract,
            " ".join(record.effects),
            " ".join(record.remix_tools),
            record.search_text,
        ]
    )
    return tuple(sorted(expand_tokens(text)))


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.touch(mode=0o600, exist_ok=True)
    os.chmod(path, 0o600)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    for companion in (Path(f"{path}-wal"), Path(f"{path}-shm")):
        if companion.exists():
            os.chmod(companion, 0o600)
    return con


def create_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS primitives (
          primitive_id TEXT PRIMARY KEY,
          label TEXT NOT NULL,
          input_contract TEXT NOT NULL,
          output_contract TEXT NOT NULL,
          trust TEXT NOT NULL,
          readiness TEXT NOT NULL,
          effects_json TEXT NOT NULL,
          memory TEXT NOT NULL,
          cache TEXT NOT NULL,
          serves_truth INTEGER NOT NULL,
          remix_tools_json TEXT NOT NULL,
          proof_obligations_json TEXT NOT NULL,
          promotion_blockers_json TEXT NOT NULL,
          source_refs_json TEXT NOT NULL,
          search_text TEXT NOT NULL,
          semantic_terms TEXT NOT NULL,
          semantic_vector_json TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS primitive_search USING fts5(
          primitive_id UNINDEXED,
          label,
          input_contract,
          output_contract,
          search_text,
          semantic_terms
        );

        CREATE TABLE IF NOT EXISTS compatibility_edges (
          from_primitive_id TEXT NOT NULL,
          to_primitive_id TEXT NOT NULL,
          status TEXT NOT NULL,
          reason TEXT NOT NULL,
          PRIMARY KEY (from_primitive_id, to_primitive_id, status)
        );
        """
    )


def insert_records(con: sqlite3.Connection, records: tuple[PrimitiveRecord, ...]) -> None:
    for record in records:
        terms = semantic_terms(record)
        vector = hashed_vector(terms)
        con.execute(
            """
            INSERT INTO primitives VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(primitive_id) DO UPDATE SET
              label=excluded.label,
              input_contract=excluded.input_contract,
              output_contract=excluded.output_contract,
              trust=excluded.trust,
              readiness=excluded.readiness,
              effects_json=excluded.effects_json,
              memory=excluded.memory,
              cache=excluded.cache,
              serves_truth=excluded.serves_truth,
              remix_tools_json=excluded.remix_tools_json,
              proof_obligations_json=excluded.proof_obligations_json,
              promotion_blockers_json=excluded.promotion_blockers_json,
              source_refs_json=excluded.source_refs_json,
              search_text=excluded.search_text,
              semantic_terms=excluded.semantic_terms,
              semantic_vector_json=excluded.semantic_vector_json
            """,
            (
                record.primitive_id,
                record.label,
                record.input_contract,
                record.output_contract,
                record.trust,
                record.readiness,
                json.dumps(record.effects),
                record.memory,
                record.cache,
                int(record.serves_truth),
                json.dumps(record.remix_tools),
                json.dumps(record.proof_obligations),
                json.dumps(record.promotion_blockers),
                json.dumps(record.source_refs),
                record.search_text,
                " ".join(terms),
                json.dumps(vector),
            ),
        )
        con.execute("DELETE FROM primitive_search WHERE primitive_id = ?", (record.primitive_id,))
        con.execute(
            "INSERT INTO primitive_search VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.primitive_id,
                record.label,
                record.input_contract,
                record.output_contract,
                record.search_text,
                " ".join(terms),
            ),
        )


def compatibility_status(left: PrimitiveRecord, right: PrimitiveRecord) -> tuple[str, str] | None:
    if left.primitive_id == right.primitive_id:
        return None
    if left.output_contract == right.input_contract:
        return ("direct", "output_contract_equals_input_contract")
    if right.input_contract.startswith("list[") and right.input_contract.endswith("]"):
        if right.input_contract[5:-1] == left.output_contract:
            return ("candidate_with_map_sequence", "scalar_output_can_feed_list_slot_with_map_sequence")
    return None


def insert_edges(con: sqlite3.Connection, records: tuple[PrimitiveRecord, ...]) -> None:
    ids = tuple(record.primitive_id for record in records)
    if ids:
        placeholders = ",".join("?" for _ in ids)
        con.execute(
            f"DELETE FROM compatibility_edges WHERE from_primitive_id IN ({placeholders}) "
            f"AND to_primitive_id IN ({placeholders})",
            (*ids, *ids),
        )
    rows: list[tuple[str, str, str, str]] = []
    for left in records:
        for right in records:
            status = compatibility_status(left, right)
            if status is None:
                continue
            rows.append((left.primitive_id, right.primitive_id, status[0], status[1]))
    con.executemany("INSERT OR REPLACE INTO compatibility_edges VALUES (?, ?, ?, ?)", rows)


def builtin_records() -> tuple[PrimitiveRecord, ...]:
    """Return advisory seeds plus every packaged executable implementation."""

    # Kept lazy so registry token helpers remain cheap to import and runtime
    # never gains a dependency on the storage layer.
    from . import runtime

    runtime_ids = set(runtime.EXECUTABLE_PRIMITIVES)
    executable: list[PrimitiveRecord] = []
    for spec in runtime.EXECUTABLE_PRIMITIVES.values():
        proof = spec.prove()
        governed_candidate = spec.primitive_id.startswith("candidate.")
        verified = bool(proof["passed"]) and not governed_candidate
        if spec.primitive_id == "candidate.csv.profile_columns.v0":
            input_contract = "CsvProfileInput"
            output_contract = "CsvProfileReport"
        else:
            input_contract = f"{spec.primitive_id}.input"
            output_contract = f"{spec.primitive_id}.output"
        executable.append(
            PrimitiveRecord(
                primitive_id=spec.primitive_id,
                label=spec.label,
                input_contract=input_contract,
                output_contract=output_contract,
                trust="verified" if verified else "candidate",
                readiness="R8_executable" if verified else "R6_executable_proven" if proof["passed"] else "R4_proof_failed",
                serves_truth=verified,
                proof_obligations=("packaged_fixture_proof", "source_digest"),
                promotion_blockers=() if verified else ("governance_promotion_required",) if proof["passed"] else ("packaged_fixture_failed",),
                source_refs=(f"python:{spec.module.__name__}",),
                search_text=f"{spec.label} {spec.description}",
            )
        )
    advisory = tuple(record for record in SEED_PRIMITIVES if record.primitive_id not in runtime_ids)
    return advisory + tuple(executable)


def build_db(path: Path, records: tuple[PrimitiveRecord, ...] | None = None) -> dict[str, int]:
    """Initialize and synchronize built-in records without deleting user data.

    Earlier versions dropped every registry table during service startup.  The
    product database also contains accounts, API tokens, receipts, and imported
    primitives, so startup must be an idempotent upsert operation.
    """
    if records is None:
        records = builtin_records()
    con = connect(path)
    with con:
        create_schema(con)
        insert_records(con, records)
        insert_edges(con, records)
    primitive_count = int(con.execute("SELECT COUNT(*) FROM primitives").fetchone()[0])
    edge_count = int(con.execute("SELECT COUNT(*) FROM compatibility_edges").fetchone()[0])
    con.close()
    return {"primitive_records": primitive_count, "compatibility_edges": edge_count}


def get_primitive(con: sqlite3.Connection, primitive_id: str) -> dict | None:
    row = con.execute("SELECT * FROM primitives WHERE primitive_id = ?", (primitive_id,)).fetchone()
    return row_to_dict(row) if row is not None else None


def row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "primitive_id": row["primitive_id"],
        "label": row["label"],
        "input_contract": row["input_contract"],
        "output_contract": row["output_contract"],
        "trust": row["trust"],
        "readiness": row["readiness"],
        "effects": json.loads(row["effects_json"]),
        "memory": row["memory"],
        "cache": row["cache"],
        "serves_truth": bool(row["serves_truth"]),
        "remix_tools": json.loads(row["remix_tools_json"]),
        "proof_obligations": json.loads(row["proof_obligations_json"]),
        "promotion_blockers": json.loads(row["promotion_blockers_json"]),
        "source_refs": json.loads(row["source_refs_json"]),
        "semantic_terms": (row["semantic_terms"] or "").split(),
        "search_text": row["search_text"],
    }
