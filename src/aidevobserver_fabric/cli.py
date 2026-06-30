"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import fabric, hybrid, openwebui, primitive_factory, registry, social_ingest, source_surfaces


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
