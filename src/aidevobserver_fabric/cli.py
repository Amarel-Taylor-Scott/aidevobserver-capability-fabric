"""Command-line interface."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from . import credentials, e2e, fabric, hybrid, mcp_server, primitive_factory, registry, runtime, social_ingest, source_surfaces, webapp
from .api_client import APIError, FabricClient
from .paths import default_db as product_default_db


def default_db(path: str | None) -> Path:
    return Path(path).expanduser() if path else product_default_db()


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


def cmd_discover(args: argparse.Namespace) -> int:
    data = fabric.build_fabric(default_db(args.db))
    print(fabric.canonical_json({"query": args.query, "results": fabric.discover_services(data, args.query)}), end="")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    webapp.serve(
        args.host,
        args.port,
        default_db(args.db),
        public_url=args.public_url,
        secure_cookie=args.secure_cookie,
        signup_mode=args.signup_mode,
        bridge_install_command=args.bridge_install_command,
    )
    return 0


def cmd_prove_all(args: argparse.Namespace) -> int:
    result = runtime.prove_all()
    print(fabric.canonical_json(result), end="")
    return 0 if result["passed"] else 1


def cmd_mcp(args: argparse.Namespace) -> int:
    argv: list[str] = []
    if args.base_url:
        argv.extend(("--base-url", args.base_url))
    if args.workspace_root:
        argv.extend(("--workspace-root", args.workspace_root))
    return mcp_server.main(argv)


def cmd_e2e_demo(args: argparse.Namespace) -> int:
    return e2e.main(["--workspace-root", args.workspace_root])


def cmd_auth_login(args: argparse.Namespace) -> int:
    token = getpass.getpass("Paste the one-time AIDevObserver token: ")
    try:
        client = FabricClient(args.server, token)
        principal = client.me()
        path = credentials.save_token(args.server, token)
    except (APIError, ValueError) as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        return 1
    print(f"Authenticated {principal['email']} for {client.base_url}")
    print(f"Credential saved with mode 0600: {path}")
    return 0


def cmd_auth_logout(args: argparse.Namespace) -> int:
    try:
        removed = credentials.remove_token(args.server)
    except ValueError as exc:
        print(f"Could not update credentials: {exc}", file=sys.stderr)
        return 1
    print("Credential removed" if removed else "No stored credential for this server")
    return 0


def cmd_auth_status(args: argparse.Namespace) -> int:
    try:
        token = credentials.load_token(args.server)
        if token is None:
            print("No stored credential")
            return 1
        principal = FabricClient(args.server, token).me()
    except (APIError, ValueError) as exc:
        print(f"Stored credential is not usable: {exc}", file=sys.stderr)
        return 1
    print(f"Authenticated {principal['email']} for {args.server}")
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
        result = hybrid.search(con, "csv profile rows for warehouse ingestion", {"output_contract": "CsvProfileReport", "candidate_only": True})
    finally:
        con.close()
    if result["results"][0]["primitive_id"] != "candidate.csv.profile_columns.v0":
        print("self-test failed: CSV query did not rank candidate first")
        return 1
    if not fabric.discover_services(data, "find reusable primitive search route"):
        print("self-test failed: service discovery returned no hits")
        return 1
    proof = runtime.prove_all()
    if not proof["passed"] or proof["passed_count"] != 11:
        print("self-test failed: packaged primitive proof did not pass 11/11")
        return 1
    print("AIDevObserver capability fabric self-test ok")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aidevobserver-fabric")
    parser.add_argument("--db", help="SQLite DB path")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build and print service fabric")
    build.add_argument("--db", help="SQLite DB path", default=argparse.SUPPRESS)
    build.set_defaults(func=cmd_build)

    search = sub.add_parser("search", help="run hybrid primitive search")
    search.add_argument("--db", help="SQLite DB path", default=argparse.SUPPRESS)
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
    bundles.add_argument("--db", help="SQLite DB path", default=argparse.SUPPRESS)
    bundles.set_defaults(func=cmd_bundles)

    services = sub.add_parser("services", help="print service discovery")
    services.add_argument("--db", help="SQLite DB path", default=argparse.SUPPRESS)
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

    discover = sub.add_parser("discover", help="search services")
    discover.add_argument("--db", help="SQLite DB path", default=argparse.SUPPRESS)
    discover.add_argument("query")
    discover.set_defaults(func=cmd_discover)

    serve = sub.add_parser("serve", help="start authenticated website and JSON API")
    serve.add_argument("--db", help="SQLite DB path", default=argparse.SUPPRESS)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8766)
    serve.add_argument("--public-url", help="URL displayed in generated MCP install commands")
    serve.add_argument("--secure-cookie", action=argparse.BooleanOptionalAction, default=None)
    serve.add_argument(
        "--signup-mode",
        choices=("local", "open", "disabled"),
        help="local permits first-owner bootstrap; hosted defaults to disabled unless explicitly open",
    )
    serve.add_argument(
        "--bridge-install-command",
        help="published pipx/uv install command shown to remote website users",
    )
    serve.set_defaults(func=cmd_serve)

    prove_all = sub.add_parser("prove-all", help="run deterministic proofs for every executable primitive")
    prove_all.set_defaults(func=cmd_prove_all)

    mcp = sub.add_parser("mcp", help="run the authenticated MCP stdio bridge")
    mcp.add_argument("--base-url", help="website/API base URL (or AIDEVOBSERVER_URL)")
    mcp.add_argument("--workspace-root", help="bounded root for materialized primitive source")
    mcp.set_defaults(func=cmd_mcp)

    e2e_demo = sub.add_parser("e2e-demo", help="run the complete authenticated primitive-reuse demo")
    e2e_demo.add_argument("--workspace-root", default=".")
    e2e_demo.set_defaults(func=cmd_e2e_demo)

    auth_cmd = sub.add_parser("auth", help="store or remove an agent credential")
    auth_sub = auth_cmd.add_subparsers(dest="auth_command", required=True)
    default_server = os.environ.get("AIDEVOBSERVER_URL", "http://127.0.0.1:8766")
    auth_login = auth_sub.add_parser("login", help="validate and privately store a one-time PAT")
    auth_login.add_argument("--server", default=default_server)
    auth_login.set_defaults(func=cmd_auth_login)
    auth_logout = auth_sub.add_parser("logout", help="remove a stored PAT")
    auth_logout.add_argument("--server", default=default_server)
    auth_logout.set_defaults(func=cmd_auth_logout)
    auth_status = auth_sub.add_parser("status", help="validate the stored PAT")
    auth_status.add_argument("--server", default=default_server)
    auth_status.set_defaults(func=cmd_auth_status)

    self_test = sub.add_parser("self-test", help="run smoke tests")
    self_test.add_argument("--db", help="SQLite DB path", default=argparse.SUPPRESS)
    self_test.set_defaults(func=cmd_self_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
