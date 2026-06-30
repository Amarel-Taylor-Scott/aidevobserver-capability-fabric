"""Evolutionary primitive factory records and deterministic lifecycle passes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .models import PrimitiveRecord
from .seeds import SEED_PRIMITIVES


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    return (
        value.replace("candidate.", "")
        .replace("prim.", "")
        .replace(".", "_")
        .replace(":", "_")
        .replace("/", "_")
        .replace("[", "")
        .replace("]", "")
        .lower()
    )


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    observation_id: str
    source_ref: str
    signal: str
    summary: str
    extracted_problem: str
    candidate_only: bool = True
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PrimitiveGenome:
    primitive_id: str
    label: str
    input_contract: str
    output_contract: str
    effects: tuple[str, ...]
    memory: str
    cache: str
    trust: str
    readiness: str
    determinism: str
    mutators: tuple[str, ...]
    proof_obligations: tuple[str, ...]
    promotion_blockers: tuple[str, ...]
    source_refs: tuple[str, ...]
    dna_hash: str
    candidate_only: bool
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MutationRecord:
    mutation_id: str
    parent_primitive_id: str
    tool: str
    contract_before: str
    contract_after: str
    effect_delta: str
    memory_delta: str
    cache_delta: str
    proof_obligations: tuple[str, ...]
    auto_apply_policy: str
    status: str = "candidate"
    candidate_only: bool = True
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CrossoverRecord:
    crossover_id: str
    left_primitive_id: str
    right_primitive_id: str
    child_label: str
    input_contract: str
    output_contract: str
    route: tuple[str, ...]
    proof_obligations: tuple[str, ...]
    status: str = "candidate"
    candidate_only: bool = True
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BenchmarkRecord:
    benchmark_id: str
    primitive_id: str
    latency_class: str
    cost_class: str
    determinism_score: float
    reliability_score: float
    proof_score: float
    benchmark_obligations: tuple[str, ...]
    candidate_only: bool = True
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FitnessRecord:
    fitness_id: str
    primitive_id: str
    score: float
    reuse_score: float
    correctness_score: float
    determinism_score: float
    reliability_score: float
    proof_score: float
    cost_penalty: float
    latency_penalty: float
    failure_penalty: float
    recommendation: str
    candidate_only: bool = True
    serves_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def infer_determinism(record: PrimitiveRecord) -> str:
    effects = set(record.effects)
    if "llm_candidate_summary" in effects:
        return "llm_assisted_candidate"
    if effects & {"external_api_call", "network_write"}:
        return "external_nondeterministic"
    if "network_read" in effects:
        return "external_read"
    return "deterministic"


def infer_mutators(record: PrimitiveRecord) -> tuple[str, ...]:
    mutators = set(record.remix_tools)
    if not record.input_contract.startswith("list[") and not record.output_contract.startswith("list["):
        mutators.add("map_sequence")
    if record.input_contract.startswith("list[") or record.output_contract.startswith("list["):
        mutators.update({"chunk_sequence", "parallel_map"})
    if "network_read" in record.effects or "external_api_call" in record.effects:
        mutators.update({"retry_wrapper", "ttl_cache", "provider_fallback"})
    if record.output_contract.endswith("Set") or record.output_contract.endswith("Table"):
        mutators.add("schema_gate")
    if record.memory != "artifact_ref" and (
        "Artifact" in record.input_contract
        or "Artifact" in record.output_contract
        or record.output_contract.endswith("Set")
    ):
        mutators.add("artifact_materialize")
    if "llm_candidate_summary" in record.effects:
        mutators.update({"deterministic_rewrite", "rule_extractor", "embedding_filter"})
    return tuple(sorted(mutators))


def genome_from_primitive(record: PrimitiveRecord) -> PrimitiveGenome:
    material = {
        "primitive_id": record.primitive_id,
        "input": record.input_contract,
        "output": record.output_contract,
        "effects": record.effects,
        "memory": record.memory,
        "cache": record.cache,
        "proof": record.proof_obligations,
    }
    return PrimitiveGenome(
        primitive_id=record.primitive_id,
        label=record.label,
        input_contract=record.input_contract,
        output_contract=record.output_contract,
        effects=record.effects,
        memory=record.memory,
        cache=record.cache,
        trust=record.trust,
        readiness=record.readiness,
        determinism=infer_determinism(record),
        mutators=infer_mutators(record),
        proof_obligations=record.proof_obligations,
        promotion_blockers=record.promotion_blockers,
        source_refs=record.source_refs,
        dna_hash=_digest(material),
        candidate_only=not record.serves_truth,
        serves_truth=False,
    )


def observation_from_primitive(record: PrimitiveRecord) -> ObservationRecord:
    source_ref = record.source_refs[0] if record.source_refs else "seed:unknown"
    return ObservationRecord(
        observation_id=f"obs.{_slug(record.primitive_id)}",
        source_ref=source_ref,
        signal="registry_seed",
        summary=f"{record.label} maps {record.input_contract} to {record.output_contract}",
        extracted_problem=f"Need capability for {record.search_text or record.label}",
    )


def mutation_records(genome: PrimitiveGenome) -> tuple[MutationRecord, ...]:
    records: list[MutationRecord] = []
    for tool in genome.mutators:
        contract_after = f"{genome.input_contract}>{genome.output_contract}"
        effect_delta = "preserve"
        memory_delta = "preserve"
        cache_delta = "preserve"
        proof = ("schema_validation",)
        policy = "manual_review"

        if tool == "map_sequence":
            contract_after = f"list[{genome.input_contract}]>list[{genome.output_contract}]"
            proof = ("singleton_equivalence", "order_preserved", "error_mapping_preserved")
            policy = "auto_if_parent_verified_and_pure"
        elif tool == "chunk_sequence":
            contract_after = f"{genome.input_contract}>Chunked[{genome.output_contract}]"
            proof = ("chunk_boundary_equivalence", "order_preserved")
        elif tool == "parallel_map":
            contract_after = f"{genome.input_contract}>Parallel[{genome.output_contract}]"
            proof = ("order_preserved", "side_effect_safe")
        elif tool == "retry_wrapper":
            effect_delta = "adds_retry_control"
            proof = ("idempotency_or_receipt", "retry_budget", "error_classification")
        elif tool == "ttl_cache":
            cache_delta = "ttl"
            proof = ("cache_key_stable", "freshness_policy", "no_secret_cache_key")
        elif tool == "provider_fallback":
            effect_delta = "adds_provider_route"
            proof = ("provider_equivalence_fixture", "failure_failover_fixture")
        elif tool == "schema_gate":
            contract_after = f"{genome.input_contract}>Validated[{genome.output_contract}]"
            proof = ("schema_validation", "negative_fixture")
        elif tool == "artifact_materialize":
            memory_delta = "artifact_ref"
            proof = ("artifact_hash_stable", "large_value_not_inline")
        elif tool == "deterministic_rewrite":
            effect_delta = "remove_or_reduce_llm"
            proof = ("golden_fixture_equivalence", "false_positive_control")
        elif tool == "rule_extractor":
            effect_delta = "candidate_rules"
            proof = ("rule_precision_recall_fixture",)
        elif tool == "embedding_filter":
            effect_delta = "adds_embedding_prefilter"
            proof = ("retrieval_eval", "threshold_sweep")

        records.append(
            MutationRecord(
                mutation_id=f"mut.{_slug(genome.primitive_id)}.{tool}.v0",
                parent_primitive_id=genome.primitive_id,
                tool=tool,
                contract_before=f"{genome.input_contract}>{genome.output_contract}",
                contract_after=contract_after,
                effect_delta=effect_delta,
                memory_delta=memory_delta,
                cache_delta=cache_delta,
                proof_obligations=proof,
                auto_apply_policy=policy,
            )
        )
    return tuple(records)


def crossover_records(genomes: Iterable[PrimitiveGenome], limit: int = 24) -> tuple[CrossoverRecord, ...]:
    genome_tuple = tuple(genomes)
    records: list[CrossoverRecord] = []
    for left in genome_tuple:
        for right in genome_tuple:
            if left.primitive_id == right.primitive_id:
                continue
            if left.output_contract != right.input_contract:
                continue
            records.append(
                CrossoverRecord(
                    crossover_id=f"cross.{_slug(left.primitive_id)}__{_slug(right.primitive_id)}.v0",
                    left_primitive_id=left.primitive_id,
                    right_primitive_id=right.primitive_id,
                    child_label=f"{left.label} >> {right.label}",
                    input_contract=left.input_contract,
                    output_contract=right.output_contract,
                    route=(left.primitive_id, right.primitive_id),
                    proof_obligations=("composition_contract_check", "fixture_end_to_end"),
                )
            )
            if len(records) >= limit:
                return tuple(records)
    return tuple(records)


def benchmark_record(genome: PrimitiveGenome) -> BenchmarkRecord:
    effects = set(genome.effects)
    latency_class = "low"
    cost_class = "low"
    reliability = 0.82
    if "network_read" in effects:
        latency_class = "medium"
        reliability -= 0.12
    if "external_api_call" in effects:
        latency_class = "high"
        cost_class = "variable"
        reliability -= 0.16
    if "llm_candidate_summary" in effects:
        latency_class = "high"
        cost_class = "variable"
        reliability -= 0.22

    determinism = {
        "deterministic": 1.0,
        "external_read": 0.72,
        "external_nondeterministic": 0.54,
        "llm_assisted_candidate": 0.36,
    }[genome.determinism]
    proof = 0.92 if genome.trust == "verified" else 0.42
    if genome.proof_obligations:
        proof = min(proof, 0.64)
    obligations = tuple(genome.proof_obligations or ("golden_fixture", "schema_validation"))
    return BenchmarkRecord(
        benchmark_id=f"bench.{_slug(genome.primitive_id)}.v0",
        primitive_id=genome.primitive_id,
        latency_class=latency_class,
        cost_class=cost_class,
        determinism_score=round(determinism, 3),
        reliability_score=round(max(0.0, reliability), 3),
        proof_score=round(proof, 3),
        benchmark_obligations=obligations,
    )


def fitness_record(genome: PrimitiveGenome, benchmark: BenchmarkRecord) -> FitnessRecord:
    reuse = 0.65 if genome.serves_truth or genome.trust == "verified" else 0.25
    correctness = 0.88 if genome.trust == "verified" else 0.5
    cost_penalty = {"low": 0.04, "variable": 0.18}.get(benchmark.cost_class, 0.12)
    latency_penalty = {"low": 0.03, "medium": 0.1, "high": 0.2}.get(benchmark.latency_class, 0.12)
    failure_penalty = 0.18 if genome.promotion_blockers else 0.04
    score = (
        correctness * 0.26
        + reuse * 0.14
        + benchmark.determinism_score * 0.2
        + benchmark.reliability_score * 0.16
        + benchmark.proof_score * 0.18
        - cost_penalty
        - latency_penalty
        - failure_penalty
    )
    recommendation = "promote_candidate_after_proof"
    if genome.trust == "verified":
        recommendation = "prefer_as_baseline"
    if "deterministic_rewrite" in genome.mutators:
        recommendation = "prioritize_determinization"
    elif genome.promotion_blockers:
        recommendation = "keep_candidate_until_blockers_clear"
    return FitnessRecord(
        fitness_id=f"fit.{_slug(genome.primitive_id)}.v0",
        primitive_id=genome.primitive_id,
        score=round(max(0.0, score), 4),
        reuse_score=round(reuse, 3),
        correctness_score=round(correctness, 3),
        determinism_score=benchmark.determinism_score,
        reliability_score=benchmark.reliability_score,
        proof_score=benchmark.proof_score,
        cost_penalty=cost_penalty,
        latency_penalty=latency_penalty,
        failure_penalty=failure_penalty,
        recommendation=recommendation,
    )


def factory_snapshot(records: tuple[PrimitiveRecord, ...] = SEED_PRIMITIVES) -> dict[str, Any]:
    observations = tuple(observation_from_primitive(record) for record in records)
    genomes = tuple(genome_from_primitive(record) for record in records)
    mutations = tuple(mutation for genome in genomes for mutation in mutation_records(genome))
    crossovers = crossover_records(genomes)
    benchmarks = tuple(benchmark_record(genome) for genome in genomes)
    fitness_by_id = {
        benchmark.primitive_id: fitness_record(
            next(genome for genome in genomes if genome.primitive_id == benchmark.primitive_id),
            benchmark,
        )
        for benchmark in benchmarks
    }
    fitness = tuple(sorted(fitness_by_id.values(), key=lambda item: (-item.score, item.primitive_id)))
    return {
        "factory_id": "factory.aidevobserver.evolutionary_primitive.v0",
        "serves_truth": False,
        "candidate_only": True,
        "counts": {
            "observations": len(observations),
            "genomes": len(genomes),
            "mutations": len(mutations),
            "crossovers": len(crossovers),
            "benchmarks": len(benchmarks),
            "fitness": len(fitness),
        },
        "observations": [record.to_dict() for record in observations],
        "genomes": [record.to_dict() for record in genomes],
        "mutations": [record.to_dict() for record in mutations],
        "crossovers": [record.to_dict() for record in crossovers],
        "benchmarks": [record.to_dict() for record in benchmarks],
        "fitness": [record.to_dict() for record in fitness],
    }


def lineage_for(primitive_id: str, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    data = snapshot or factory_snapshot()
    mutations = [
        mutation
        for mutation in data["mutations"]
        if mutation["parent_primitive_id"] == primitive_id
    ]
    crossovers = [
        crossover
        for crossover in data["crossovers"]
        if primitive_id in {crossover["left_primitive_id"], crossover["right_primitive_id"]}
    ]
    genome = next((item for item in data["genomes"] if item["primitive_id"] == primitive_id), None)
    return {
        "primitive_id": primitive_id,
        "genome": genome,
        "children": mutations,
        "crossovers": crossovers,
        "serves_truth": False,
    }


def compact_snapshot(snapshot: dict[str, Any], limit: int = 10) -> str:
    counts = snapshot["counts"]
    lines = [
        "AIDevObserver evolutionary primitive factory",
        "BOUNDARY candidate_only=true serves_truth=false",
        (
            "COUNTS "
            f"obs:{counts['observations']} genome:{counts['genomes']} "
            f"mut:{counts['mutations']} cross:{counts['crossovers']} "
            f"bench:{counts['benchmarks']} fit:{counts['fitness']}"
        ),
    ]
    lines.append("")
    lines.append("TOP_FITNESS")
    for row in snapshot["fitness"][:limit]:
        lines.append(
            f"FIT {row['primitive_id']} score:{row['score']} "
            f"det:{row['determinism_score']} proof:{row['proof_score']} rec:{row['recommendation']}"
        )
    lines.append("")
    lines.append("MUTATIONS")
    for row in snapshot["mutations"][:limit]:
        lines.append(
            f"MUT {row['mutation_id']} parent:{row['parent_primitive_id']} "
            f"tool:{row['tool']} after:{row['contract_after']}"
        )
    lines.append("")
    lines.append("CROSSOVERS")
    for row in snapshot["crossovers"][:limit]:
        lines.append(
            f"CROSS {row['crossover_id']} route:{'>>'.join(row['route'])} "
            f"{row['input_contract']}>{row['output_contract']}"
        )
    return "\n".join(lines) + "\n"

