"""Synthetic public-safe seed records."""

from __future__ import annotations

from .models import PrimitiveRecord, ServiceEndpoint, ServiceRecord, TemplateSlot


SEED_PRIMITIVES: tuple[PrimitiveRecord, ...] = (
    PrimitiveRecord(
        primitive_id="prim.web.discover_pages.v1",
        label="web.discover_pages",
        input_contract="QuerySpec",
        output_contract="SourcePageSet",
        trust="verified",
        readiness="R8",
        effects=("network_read",),
        serves_truth=True,
        source_refs=("seed:web.discover",),
        search_text="discover authoritative web source pages query source pages",
    ),
    PrimitiveRecord(
        primitive_id="prim.web.fetch_documents.v1",
        label="web.fetch_documents",
        input_contract="SourcePageSet",
        output_contract="HtmlDocumentSet",
        trust="verified",
        readiness="R8",
        effects=("network_read",),
        serves_truth=True,
        source_refs=("seed:web.fetch",),
        search_text="fetch html documents from source pages",
    ),
    PrimitiveRecord(
        primitive_id="prim.html.extract_rate_texts.v1",
        label="html.extract_rate_texts",
        input_contract="HtmlDocumentSet",
        output_contract="list[RawRateText]",
        trust="verified",
        readiness="R8",
        serves_truth=True,
        source_refs=("seed:html.extract",),
        search_text="extract interest rate text from html tables jurisdiction rates",
    ),
    PrimitiveRecord(
        primitive_id="prim.rate.normalize_one.v1",
        label="rate.normalize_one",
        input_contract="RawRateText",
        output_contract="NormalizedRate",
        trust="verified",
        readiness="R8",
        serves_truth=True,
        remix_tools=("map_sequence",),
        source_refs=("seed:rate.normalize_one",),
        search_text="normalize one interest rate text jurisdiction normalized rate",
    ),
    PrimitiveRecord(
        primitive_id="prim.rate.normalize_batch.v1",
        label="rate.normalize_batch",
        input_contract="list[RawRateText]",
        output_contract="list[NormalizedRate]",
        trust="verified",
        readiness="R8",
        serves_truth=True,
        source_refs=("seed:rate.normalize_batch",),
        search_text="batch normalize interest rate texts jurisdiction normalized rates",
    ),
    PrimitiveRecord(
        primitive_id="prim.validation.crosscheck_rates.v1",
        label="validation.crosscheck_rates",
        input_contract="list[NormalizedRate]",
        output_contract="ProvenancedRateTable",
        trust="verified",
        readiness="R8",
        serves_truth=True,
        source_refs=("seed:validation.crosscheck",),
        search_text="crosscheck normalized rates provenance source validation",
    ),
    PrimitiveRecord(
        primitive_id="prim.output.emit_json.v1",
        label="output.emit_json",
        input_contract="ProvenancedRateTable",
        output_contract="OutputArtifact",
        trust="verified",
        readiness="R8",
        serves_truth=True,
        source_refs=("seed:output.emit_json",),
        search_text="emit json output artifact provenanced table",
    ),
    PrimitiveRecord(
        primitive_id="candidate.csv.profile_columns.v0",
        label="csv.profile_columns",
        input_contract="CsvArtifact",
        output_contract="ColumnProfileSet",
        proof_obligations=("fixture_csv_profile", "schema_validation"),
        promotion_blockers=("candidate_only", "needs_fixture_proof"),
        source_refs=("seed:csv.profile",),
        search_text="csv profile rows columns warehouse ingestion delimiter table",
    ),
    PrimitiveRecord(
        primitive_id="candidate.document.extract_schema_fields.v0",
        label="document.extract_schema_fields",
        input_contract="ParsedDocument",
        output_contract="RawFieldSet",
        proof_obligations=("source_span_fixture", "schema_validation"),
        promotion_blockers=("candidate_only", "needs_license_review"),
        source_refs=("seed:document.schema",),
        search_text="document schema field extraction json source spans parsed document",
    ),
    PrimitiveRecord(
        primitive_id="candidate.agent.detect_retry_loop.v0",
        label="observer.detect_retry_loop",
        input_contract="SessionEventSet",
        output_contract="AgentLoopFindingSet",
        proof_obligations=("session_fixture", "false_positive_control"),
        promotion_blockers=("candidate_only", "needs_benchmark"),
        source_refs=("seed:observer.loop",),
        search_text="detect repeated coding agent retry loop session failure wasted context",
    ),
)


TEMPLATE_SLOTS: dict[str, tuple[TemplateSlot, ...]] = {
    "profile_tabular_data": (
        TemplateSlot("profile", "profile tabular columns", "CsvArtifact", "ColumnProfileSet"),
    ),
    "normalize_regulatory_rates": (
        TemplateSlot("discover", "discover source pages", "QuerySpec", "SourcePageSet"),
        TemplateSlot("fetch", "fetch documents", "SourcePageSet", "HtmlDocumentSet"),
        TemplateSlot("extract", "extract raw rate text", "HtmlDocumentSet", "list[RawRateText]"),
        TemplateSlot("normalize", "normalize rate texts", "list[RawRateText]", "list[NormalizedRate]", ("map_sequence",)),
        TemplateSlot("validate", "crosscheck provenance", "list[NormalizedRate]", "ProvenancedRateTable"),
        TemplateSlot("emit", "emit artifact", "ProvenancedRateTable", "OutputArtifact"),
    ),
    "extract_schema_fields": (
        TemplateSlot("extract_fields", "extract fields with spans", "ParsedDocument", "RawFieldSet"),
    ),
    "review_agent_session": (
        TemplateSlot("detect_loop", "detect agent retry loop", "SessionEventSet", "AgentLoopFindingSet"),
    ),
}


TEMPLATE_IDS = {
    "profile_tabular_data": "template.data.profile_csv_artifact.v0",
    "normalize_regulatory_rates": "template.web.scrape_provenanced_rates.v0",
    "extract_schema_fields": "template.document.extract_schema_fields.v0",
    "review_agent_session": "template.observer.review_agent_session.v0",
}


SERVICES: tuple[ServiceRecord, ...] = (
    ServiceRecord(
        service_id="svc.primitive_search.v0",
        label="Primitive Search",
        purpose="Search primitive records with blockers, hybrid lanes, and RRF.",
        readiness="R6_searchable",
        mode="local_readonly",
        consumes=("PrimitiveSearchQuery",),
        produces=("HybridPrimitiveSearchResult", "CandidateBundle"),
        gates=("read_only", "candidate_advice_only"),
        endpoints=(
            ServiceEndpoint(
                route="/capabilities/search",
                method="GET",
                input_contract="PrimitiveSearchQuery",
                output_contract="HybridPrimitiveSearchResult",
                command="aidevobserver-fabric search --query TEXT",
                description="Run blocker-first hybrid primitive search.",
            ),
        ),
    ),
    ServiceRecord(
        service_id="svc.route_bundles.v0",
        label="Route Bundles",
        purpose="Return template-slot candidate bundles for compact LLM planning.",
        readiness="R6_searchable",
        mode="local_readonly",
        consumes=("BundleListQuery",),
        produces=("CandidateBundleSet",),
        gates=("read_only", "compiler_validation_required"),
        endpoints=(
            ServiceEndpoint(
                route="/bundles",
                method="GET",
                input_contract="BundleListQuery",
                output_contract="CandidateBundleSet",
                command="aidevobserver-fabric bundles",
                description="List materialized candidate bundles.",
            ),
        ),
    ),
    ServiceRecord(
        service_id="svc.agent_discovery.v0",
        label="Agent Discovery",
        purpose="Expose compact service awareness to agents.",
        readiness="R6_searchable",
        mode="local_readonly",
        consumes=("AgentDiscoveryQuery",),
        produces=("AgentDiscoveryView",),
        gates=("read_only", "awareness_not_authorization"),
        endpoints=(
            ServiceEndpoint(
                route="/agents/discovery",
                method="GET",
                input_contract="AgentDiscoveryQuery",
                output_contract="AgentDiscoveryView",
                command="aidevobserver-fabric services --compact",
                description="Return compact service discovery view.",
            ),
        ),
    ),
)
