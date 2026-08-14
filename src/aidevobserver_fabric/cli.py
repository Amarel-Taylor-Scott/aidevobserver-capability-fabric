"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (
    edge_catalog,
    fabric,
    hybrid,
    ollama,
    openwebui,
    primitive_factory,
    problem_loop,
    registry,
    social_ingest,
    source_surfaces,
)


def default_db(path: str | None) -> Path:
    return Path(path or "generated/primitive_search.sqlite")


def cmd_build(args: argparse.Namespace) -> int:
    data = fabric.build_fabric(default_db(args.db))
    print(fabric.canonical_json(data), end="")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    db_path = default_db(args.db)
    con = hybrid.ensure_db(db_path)
    try:
        result = hybrid.search(
            con,
            args.query,
            {
                "input_contract": args.input_contract,
                "output_contract": args.output_contract,
                "trust": args.trust,
                "candidate_only": args.candidate_only,
                "serves_truth": args.serves_truth,
            },
            limit=args.limit,
        )
    finally:
        con.close()
    if args.compact:
        print(hybrid.compact_result(result), end="")
    else:
        print(fabric.canonical_json(result), end="")
    return 0


def cmd_bundles(args: argparse.Namespace) -> int:
    data = fabric.build_fabric(default_db(args.db))
    print(fabric.canonical_json(data["candidate_bundles"]), end="")
    return 0


def cmd_services(args: argparse.Namespace) -> int:
    data = fabric.build_fabric(default_db(args.db))
    if args.compact:
        print(fabric.agent_discovery(data), end="")
    else:
        print(fabric.canonical_json(data), end="")
    return 0


def cmd_factory(args: argparse.Namespace) -> int:
    snapshot = primitive_factory.factory_snapshot()
    if args.compact:
        print(primitive_factory.compact_snapshot(snapshot, limit=args.limit), end="")
    else:
        print(fabric.canonical_json(snapshot), end="")
    return 0


def cmd_factory_lineage(args: argparse.Namespace) -> int:
    snapshot = primitive_factory.factory_snapshot()
    print(fabric.canonical_json(primitive_factory.lineage_for(args.primitive_id, snapshot)), end="")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    records = source_surfaces.SOURCE_SURFACES
    if args.category:
        records = tuple(surface for surface in records if surface.category == args.category)
    if args.limit is not None:
        records = records[: args.limit]
    if args.compact:
        print(source_surfaces.as_compact(records), end="")
    else:
        print(source_surfaces.as_json(records), end="")
    return 0


def cmd_problem_sources(args: argparse.Namespace) -> int:
    sources = (
        problem_loop.load_source_specs(Path(args.source_config))
        if args.source_config
        else problem_loop.DEFAULT_SOURCE_SPECS
    )
    data = problem_loop.source_catalog(compact=args.compact, sources=sources)
    if isinstance(data, str):
        print(data, end="")
    else:
        print(fabric.canonical_json(data), end="")
    return 0


def _problem_loop_config(args: argparse.Namespace) -> problem_loop.LoopConfig:
    return problem_loop.LoopConfig(
        output_root=Path(args.output_root),
        source_ids=tuple(args.source or ()),
        source_config=Path(args.source_config) if args.source_config else None,
        max_items=args.max_items,
        timeout_seconds=args.timeout,
        build_limit=args.build_limit,
        minimum_cluster_similarity=args.minimum_similarity,
        execute_candidate_tests=not args.no_execute_tests,
        candidate_test_timeout=args.candidate_test_timeout,
    )


def cmd_problem_loop(args: argparse.Namespace) -> int:
    config = _problem_loop_config(args)
    fixtures = problem_loop.load_fixture_map(Path(args.fixture) if args.fixture else None)
    result = problem_loop.run_loop(
        config,
        fixture_map=fixtures,
        cycles=args.cycles,
        interval_seconds=args.interval_seconds,
        max_runtime_seconds=args.max_runtime_seconds,
    )
    print(fabric.canonical_json(result), end="")
    return 1 if result["receipts"] and all(row["status"] == "failed" for row in result["receipts"]) else 0


def cmd_problem_status(args: argparse.Namespace) -> int:
    print(fabric.canonical_json(problem_loop.loop_status(Path(args.output_root))), end="")
    return 0


def cmd_problem_reconcile(args: argparse.Namespace) -> int:
    result = problem_loop.loop_reconcile(Path(args.output_root))
    print(fabric.canonical_json(result), end="")
    return 0 if result["clean"] else 1


def _edge_location(args: argparse.Namespace) -> edge_catalog.CatalogLocation:
    return edge_catalog.CatalogLocation(
        root=Path(args.catalog_dir),
        archive=Path(args.catalog_zip),
    )


def cmd_edge_summary(args: argparse.Namespace) -> int:
    print(fabric.canonical_json(edge_catalog.summary(_edge_location(args))), end="")
    return 0


def cmd_edge_search(args: argparse.Namespace) -> int:
    result = edge_catalog.search_primitives(
        args.query,
        domain=args.domain,
        data_shape=args.data_shape,
        operation=args.operation,
        runtime_target=args.runtime_target,
        limit=args.limit,
        location=_edge_location(args),
    )
    if args.compact:
        print(edge_catalog.compact_search(result), end="")
    else:
        print(fabric.canonical_json(result), end="")
    return 0


def cmd_edge_routes(args: argparse.Namespace) -> int:
    result = edge_catalog.search_routes(
        args.query,
        domain=args.domain,
        data_shape=args.data_shape,
        pattern=args.pattern,
        limit=args.limit,
        location=_edge_location(args),
    )
    print(fabric.canonical_json(result), end="")
    return 0


def cmd_edge_planlock(args: argparse.Namespace) -> int:
    result = edge_catalog.best_route_planlock(
        args.query,
        domain=args.domain,
        data_shape=args.data_shape,
        pattern=args.pattern,
        location=_edge_location(args),
    )
    print(fabric.canonical_json(result), end="")
    return 0


def cmd_edge_graph_route(args: argparse.Namespace) -> int:
    result = edge_catalog.graph_route(
        args.start_type,
        args.end_type,
        max_depth=args.max_depth,
        limit=args.limit,
        location=_edge_location(args),
    )
    print(fabric.canonical_json(result), end="")
    return 0


def cmd_social_sources(args: argparse.Namespace) -> int:
    sources = social_ingest.load_social_sources(Path(args.sources) if args.sources else None)
    if args.compact:
        print(social_ingest.compact_sources(sources), end="")
    else:
        print(social_ingest.sources_json(sources), end="")
    return 0


def cmd_rapidapi_plan(args: argparse.Namespace) -> int:
    provider = social_ingest.load_provider_spec(Path(args.provider_config))
    sources = social_ingest.load_social_sources(Path(args.sources) if args.sources else None)
    sources = social_ingest.select_source(sources, args.source_index)
    data = {
        "boundary": "candidate_request_plan",
        "serves_truth": False,
        "provider": provider.to_dict(),
        "plans": social_ingest.request_plans(provider, sources, limit=args.limit),
    }
    print(fabric.canonical_json(data), end="")
    return 0


def cmd_rapidapi_validate(args: argparse.Namespace) -> int:
    provider = social_ingest.load_provider_spec(Path(args.provider_config))
    print(fabric.canonical_json(social_ingest.validate_provider_spec(provider)), end="")
    return 0


def cmd_rapidapi_key_status(args: argparse.Namespace) -> int:
    provider = social_ingest.load_provider_spec(Path(args.provider_config))
    print(fabric.canonical_json(social_ingest.rapidapi_key_status(provider, args.key_env)), end="")
    return 0


def cmd_rapidapi_normalize_fixture(args: argparse.Namespace) -> int:
    provider = social_ingest.load_provider_spec(Path(args.provider_config))
    sources = social_ingest.load_social_sources(Path(args.sources) if args.sources else None)
    source = social_ingest.select_source(sources, args.source_index)[0]
    data = social_ingest.normalize_fixture(provider, source, Path(args.fixture))
    print(fabric.canonical_json(data), end="")
    return 0


def cmd_rapidapi_live_test(args: argparse.Namespace) -> int:
    provider = social_ingest.load_provider_spec(Path(args.provider_config))
    validation = social_ingest.validate_provider_spec(provider)
    if not validation["valid"]:
        print(fabric.canonical_json({"error": "invalid_provider_config", "validation": validation}), end="")
        return 1
    key_status = social_ingest.rapidapi_key_status(provider, args.key_env)
    if not key_status["present"]:
        print(fabric.canonical_json({"error": "missing_key", "key_status": key_status}), end="")
        return 1
    sources = social_ingest.load_social_sources(Path(args.sources) if args.sources else None)
    source = social_ingest.select_source(sources, args.source_index)[0]
    data = social_ingest.live_smoke_test(
        provider,
        source,
        limit=args.limit,
        key_env=args.key_env,
        timeout=args.timeout,
        include_comments=args.include_comments,
    )
    print(fabric.canonical_json(data), end="")
    return 0


def cmd_rapidapi_scrape(args: argparse.Namespace) -> int:
    provider = social_ingest.load_provider_spec(Path(args.provider_config))
    validation = social_ingest.validate_provider_spec(provider)
    if not validation["valid"]:
        print(fabric.canonical_json({"error": "invalid_provider_config", "validation": validation}), end="")
        return 1
    sources = social_ingest.load_social_sources(Path(args.sources) if args.sources else None)
    sources = social_ingest.select_source(sources, args.source_index)
    if args.dry_run:
        data = {
            "boundary": "candidate_request_plan",
            "serves_truth": False,
            "provider": provider.to_dict(),
            "plans": social_ingest.request_plans(provider, sources, limit=args.limit),
        }
    else:
        data = social_ingest.scrape_sources(
            provider,
            sources,
            limit=args.limit,
            key_env=args.key_env,
            timeout=args.timeout,
            include_comments=args.include_comments,
        )
    rendered = fabric.canonical_json(data)
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def _openwebui_config(args: argparse.Namespace) -> openwebui.OpenWebUIConfig:
    return openwebui.OpenWebUIConfig(
        base_url=args.base_url,
        endpoint=args.endpoint,
        model=args.model,
        token_env=args.token_env,
        cdp_url=args.cdp_url,
    )


def _ollama_config(args: argparse.Namespace) -> ollama.OllamaConfig:
    return ollama.OllamaConfig(
        host=args.host,
        model=args.model,
    )


def cmd_ollama_plan(args: argparse.Namespace) -> int:
    print(fabric.canonical_json(ollama.redacted_plan(_ollama_config(args))), end="")
    return 0


def cmd_ollama_models(args: argparse.Namespace) -> int:
    print(fabric.canonical_json(ollama.list_models(_ollama_config(args), timeout=args.timeout)), end="")
    return 0


def cmd_ollama_chat(args: argparse.Namespace) -> int:
    result = ollama.chat(
        _ollama_config(args),
        args.prompt,
        timeout=args.timeout,
        system=args.system,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    rendered = fabric.canonical_json(result)
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def cmd_openwebui_plan(args: argparse.Namespace) -> int:
    print(fabric.canonical_json(openwebui.redacted_plan(_openwebui_config(args), mode=args.mode)), end="")
    return 0


def cmd_openwebui_chat(args: argparse.Namespace) -> int:
    config = _openwebui_config(args)
    if args.mode == "direct":
        result = openwebui.direct_chat(
            config,
            args.prompt,
            timeout=args.timeout,
            system=args.system,
        )
    else:
        result = openwebui.cdp_chat(
            config,
            args.prompt,
            timeout=args.timeout,
            system=args.system,
        )
    rendered = fabric.canonical_json(result)
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    data = fabric.build_fabric(default_db(args.db))
    print(fabric.canonical_json({"query": args.query, "results": fabric.discover_services(data, args.query)}), end="")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    fabric.serve(args.host, args.port, default_db(args.db))
    return 0


def cmd_self_test(args: argparse.Namespace) -> int:
    db_path = default_db(args.db)
    counts = registry.build_db(db_path)
    if counts["primitive_records"] < 10:
        print("self-test failed: expected at least ten primitive records")
        return 1
    data = fabric.build_fabric(db_path)
    if data["counts"]["candidate_bundles"] < 5:
        print("self-test failed: expected five candidate bundles")
        return 1
    con = hybrid.ensure_db(db_path)
    try:
        result = hybrid.search(con, "csv profile rows for warehouse ingestion", {"output_contract": "ColumnProfileSet", "candidate_only": True})
    finally:
        con.close()
    if result["results"][0]["primitive_id"] != "candidate.csv.profile_columns.v0":
        print("self-test failed: CSV query did not rank candidate first")
        return 1
    if not fabric.discover_services(data, "find reusable primitive search route"):
        print("self-test failed: service discovery returned no hits")
        return 1
    print("AIDevObserver capability fabric self-test ok")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aidevobserver-fabric")
    parser.add_argument("--db", help="SQLite DB path")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build and print service fabric")
    build.add_argument("--db", help="SQLite DB path")
    build.set_defaults(func=cmd_build)

    search = sub.add_parser("search", help="run hybrid primitive search")
    search.add_argument("--db", help="SQLite DB path")
    search.add_argument("--query", required=True)
    search.add_argument("--input-contract")
    search.add_argument("--output-contract")
    search.add_argument("--trust")
    search.add_argument("--candidate-only", action="store_true")
    search.add_argument("--serves-truth", action=argparse.BooleanOptionalAction, default=None)
    search.add_argument("--limit", type=int, default=6)
    search.add_argument("--compact", action="store_true")
    search.set_defaults(func=cmd_search)

    bundles = sub.add_parser("bundles", help="print candidate bundles")
    bundles.add_argument("--db", help="SQLite DB path")
    bundles.set_defaults(func=cmd_bundles)

    services = sub.add_parser("services", help="print service discovery")
    services.add_argument("--db", help="SQLite DB path")
    services.add_argument("--compact", action="store_true")
    services.set_defaults(func=cmd_services)

    factory_cmd = sub.add_parser("factory", help="print evolutionary primitive factory snapshot")
    factory_cmd.add_argument("--compact", action="store_true")
    factory_cmd.add_argument("--limit", type=int, default=10)
    factory_cmd.set_defaults(func=cmd_factory)

    factory_lineage = sub.add_parser("factory-lineage", help="print primitive lineage and mutation children")
    factory_lineage.add_argument("primitive_id")
    factory_lineage.set_defaults(func=cmd_factory_lineage)

    sources = sub.add_parser("sources", help="print public source-surface catalog")
    sources.add_argument("--category", help="filter by exact source category")
    sources.add_argument("--limit", type=int, help="limit returned source records")
    sources.add_argument("--compact", action="store_true")
    sources.set_defaults(func=cmd_sources)

    problem_sources = sub.add_parser(
        "problem-sources",
        help="print policy-approved business-friction source adapters",
    )
    problem_sources.add_argument("--compact", action="store_true")
    problem_sources.add_argument("--source-config", help="validated JSON source portfolio")
    problem_sources.set_defaults(func=cmd_problem_sources)

    problem_run = sub.add_parser(
        "problem-loop",
        help="discover public business friction and build receipt-bound candidate primitives",
    )
    problem_run.add_argument("--output-root", default=str(problem_loop.DEFAULT_OUTPUT_ROOT))
    problem_run.add_argument("--source", action="append", help="source ID; repeat to select several")
    problem_run.add_argument("--source-config", help="validated JSON source portfolio")
    problem_run.add_argument("--fixture", help="offline JSON fixture keyed by source ID")
    problem_run.add_argument("--cycles", type=int, default=1)
    problem_run.add_argument("--interval-seconds", type=float, default=0.0)
    problem_run.add_argument("--max-runtime-seconds", type=float)
    problem_run.add_argument("--max-items", type=int, default=20)
    problem_run.add_argument("--timeout", type=float, default=15.0)
    problem_run.add_argument("--build-limit", type=int, default=10)
    problem_run.add_argument("--minimum-similarity", type=float, default=0.30)
    problem_run.add_argument("--candidate-test-timeout", type=float, default=20.0)
    problem_run.add_argument("--no-execute-tests", action="store_true")
    problem_run.set_defaults(func=cmd_problem_loop)

    problem_status = sub.add_parser("problem-status", help="print durable problem-loop state")
    problem_status.add_argument("--output-root", default=str(problem_loop.DEFAULT_OUTPUT_ROOT))
    problem_status.set_defaults(func=cmd_problem_status)

    problem_reconcile = sub.add_parser(
        "problem-reconcile",
        help="audit problem-loop ledger and CAS without deleting or repairing data",
    )
    problem_reconcile.add_argument("--output-root", default=str(problem_loop.DEFAULT_OUTPUT_ROOT))
    problem_reconcile.set_defaults(func=cmd_problem_reconcile)

    def add_edge_catalog_args(command: argparse.ArgumentParser) -> None:
        command.add_argument("--catalog-dir", default=str(edge_catalog.DEFAULT_CATALOG_DIR))
        command.add_argument("--catalog-zip", default=str(edge_catalog.DEFAULT_CATALOG_ZIP))

    edge_summary = sub.add_parser("edge-summary", help="print edge primitive catalog summary")
    add_edge_catalog_args(edge_summary)
    edge_summary.set_defaults(func=cmd_edge_summary)

    edge_search = sub.add_parser("edge-search", help="search resolved edge primitive contracts")
    add_edge_catalog_args(edge_search)
    edge_search.add_argument("--query", required=True)
    edge_search.add_argument("--domain")
    edge_search.add_argument("--data-shape")
    edge_search.add_argument("--operation")
    edge_search.add_argument("--runtime-target")
    edge_search.add_argument("--limit", type=int, default=10)
    edge_search.add_argument("--compact", action="store_true")
    edge_search.set_defaults(func=cmd_edge_search)

    edge_routes = sub.add_parser("edge-routes", help="search route templates in the edge catalog")
    add_edge_catalog_args(edge_routes)
    edge_routes.add_argument("--query", required=True)
    edge_routes.add_argument("--domain")
    edge_routes.add_argument("--data-shape")
    edge_routes.add_argument("--pattern")
    edge_routes.add_argument("--limit", type=int, default=10)
    edge_routes.set_defaults(func=cmd_edge_routes)

    edge_planlock = sub.add_parser("edge-planlock", help="compile the best route template into a PlanLock-shaped object")
    add_edge_catalog_args(edge_planlock)
    edge_planlock.add_argument("--query", required=True)
    edge_planlock.add_argument("--domain")
    edge_planlock.add_argument("--data-shape")
    edge_planlock.add_argument("--pattern")
    edge_planlock.set_defaults(func=cmd_edge_planlock)

    edge_graph_route = sub.add_parser("edge-graph-route", help="find primitive graph paths by typed artifact edges")
    add_edge_catalog_args(edge_graph_route)
    edge_graph_route.add_argument("--start-type", required=True)
    edge_graph_route.add_argument("--end-type", required=True)
    edge_graph_route.add_argument("--max-depth", type=int, default=8)
    edge_graph_route.add_argument("--limit", type=int, default=3)
    edge_graph_route.set_defaults(func=cmd_edge_graph_route)

    social_sources = sub.add_parser("social-sources", help="print default social source pages")
    social_sources.add_argument("--sources", help="JSON source list")
    social_sources.add_argument("--compact", action="store_true")
    social_sources.set_defaults(func=cmd_social_sources)

    rapidapi_plan = sub.add_parser("rapidapi-plan", help="print redacted RapidAPI request plans")
    rapidapi_plan.add_argument("--provider-config", required=True)
    rapidapi_plan.add_argument("--sources", help="JSON source list")
    rapidapi_plan.add_argument("--source-index", type=int)
    rapidapi_plan.add_argument("--limit", type=int)
    rapidapi_plan.set_defaults(func=cmd_rapidapi_plan)

    rapidapi_validate = sub.add_parser("rapidapi-validate", help="validate a RapidAPI provider config")
    rapidapi_validate.add_argument("--provider-config", required=True)
    rapidapi_validate.set_defaults(func=cmd_rapidapi_validate)

    rapidapi_key_status = sub.add_parser("rapidapi-key-status", help="check RapidAPI key presence without printing it")
    rapidapi_key_status.add_argument("--provider-config", required=True)
    rapidapi_key_status.add_argument("--key-env", help="environment variable containing the RapidAPI key")
    rapidapi_key_status.set_defaults(func=cmd_rapidapi_key_status)

    rapidapi_fixture = sub.add_parser("rapidapi-normalize-fixture", help="normalize a saved provider JSON fixture")
    rapidapi_fixture.add_argument("--provider-config", required=True)
    rapidapi_fixture.add_argument("--sources", help="JSON source list")
    rapidapi_fixture.add_argument("--source-index", type=int, default=0)
    rapidapi_fixture.add_argument("--fixture", required=True)
    rapidapi_fixture.set_defaults(func=cmd_rapidapi_normalize_fixture)

    rapidapi_live = sub.add_parser("rapidapi-live-test", help="run a one-source RapidAPI smoke test without printing raw posts")
    rapidapi_live.add_argument("--provider-config", required=True)
    rapidapi_live.add_argument("--sources", help="JSON source list")
    rapidapi_live.add_argument("--source-index", type=int, default=0)
    rapidapi_live.add_argument("--limit", type=int, default=1)
    rapidapi_live.add_argument("--key-env", help="environment variable containing the RapidAPI key")
    rapidapi_live.add_argument("--timeout", type=float, default=30.0)
    rapidapi_live.add_argument("--include-comments", action="store_true", help="also fetch post comments when supported")
    rapidapi_live.set_defaults(func=cmd_rapidapi_live_test)

    rapidapi_scrape = sub.add_parser("rapidapi-scrape", help="scrape social sources through a RapidAPI provider")
    rapidapi_scrape.add_argument("--provider-config", required=True)
    rapidapi_scrape.add_argument("--sources", help="JSON source list")
    rapidapi_scrape.add_argument("--source-index", type=int)
    rapidapi_scrape.add_argument("--limit", type=int)
    rapidapi_scrape.add_argument("--key-env", help="environment variable containing the RapidAPI key")
    rapidapi_scrape.add_argument("--timeout", type=float, default=30.0)
    rapidapi_scrape.add_argument("--out", help="write normalized JSON to this path")
    rapidapi_scrape.add_argument("--dry-run", action="store_true")
    rapidapi_scrape.add_argument("--include-comments", action="store_true", help="also fetch post comments when supported")
    rapidapi_scrape.set_defaults(func=cmd_rapidapi_scrape)

    ollama_plan = sub.add_parser("ollama-plan", help="print a redacted local Ollama chat request plan")
    ollama_plan.add_argument("--host", default=ollama.DEFAULT_HOST)
    ollama_plan.add_argument("--model", default=ollama.DEFAULT_MODEL)
    ollama_plan.set_defaults(func=cmd_ollama_plan)

    ollama_models = sub.add_parser("ollama-models", help="list local Ollama models")
    ollama_models.add_argument("--host", default=ollama.DEFAULT_HOST)
    ollama_models.add_argument("--model", default=ollama.DEFAULT_MODEL)
    ollama_models.add_argument("--timeout", type=float, default=10.0)
    ollama_models.set_defaults(func=cmd_ollama_models)

    ollama_chat = sub.add_parser("ollama-chat", help="send one candidate-only local Ollama chat request")
    ollama_chat.add_argument("--prompt", required=True)
    ollama_chat.add_argument("--system")
    ollama_chat.add_argument("--host", default=ollama.DEFAULT_HOST)
    ollama_chat.add_argument("--model", default=ollama.DEFAULT_MODEL)
    ollama_chat.add_argument("--timeout", type=float, default=120.0)
    ollama_chat.add_argument("--max-tokens", type=int, default=512)
    ollama_chat.add_argument("--temperature", type=float, default=0.0)
    ollama_chat.add_argument("--out", help="write normalized result JSON to this path")
    ollama_chat.set_defaults(func=cmd_ollama_chat)

    openwebui_plan = sub.add_parser("openwebui-plan", help="print a redacted Open WebUI chat request plan")
    openwebui_plan.add_argument("--base-url", default=openwebui.DEFAULT_BASE_URL)
    openwebui_plan.add_argument("--endpoint", default=openwebui.DEFAULT_ENDPOINT)
    openwebui_plan.add_argument("--model", default=openwebui.DEFAULT_MODEL)
    openwebui_plan.add_argument("--token-env", default=openwebui.DEFAULT_TOKEN_ENV)
    openwebui_plan.add_argument("--cdp-url", default=openwebui.DEFAULT_CDP_URL)
    openwebui_plan.add_argument("--mode", choices=("direct", "cdp"), default="direct")
    openwebui_plan.set_defaults(func=cmd_openwebui_plan)

    openwebui_chat = sub.add_parser("openwebui-chat", help="send one candidate-only Open WebUI chat request")
    openwebui_chat.add_argument("--prompt", required=True)
    openwebui_chat.add_argument("--system")
    openwebui_chat.add_argument("--base-url", default=openwebui.DEFAULT_BASE_URL)
    openwebui_chat.add_argument("--endpoint", default=openwebui.DEFAULT_ENDPOINT)
    openwebui_chat.add_argument("--model", default=openwebui.DEFAULT_MODEL)
    openwebui_chat.add_argument("--token-env", default=openwebui.DEFAULT_TOKEN_ENV)
    openwebui_chat.add_argument("--cdp-url", default=openwebui.DEFAULT_CDP_URL)
    openwebui_chat.add_argument("--mode", choices=("direct", "cdp"), default="direct")
    openwebui_chat.add_argument("--timeout", type=float, default=120.0)
    openwebui_chat.add_argument("--out", help="write normalized result JSON to this path")
    openwebui_chat.set_defaults(func=cmd_openwebui_chat)

    discover = sub.add_parser("discover", help="search services")
    discover.add_argument("--db", help="SQLite DB path")
    discover.add_argument("query")
    discover.set_defaults(func=cmd_discover)

    serve = sub.add_parser("serve", help="start local read-only HTTP server")
    serve.add_argument("--db", help="SQLite DB path")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8766)
    serve.set_defaults(func=cmd_serve)

    self_test = sub.add_parser("self-test", help="run smoke tests")
    self_test.add_argument("--db", help="SQLite DB path")
    self_test.set_defaults(func=cmd_self_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
