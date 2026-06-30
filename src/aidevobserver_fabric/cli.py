"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import fabric, hybrid, registry, source_surfaces


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
    if data["counts"]["candidate_bundles"] < 4:
        print("self-test failed: expected four candidate bundles")
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

    sources = sub.add_parser("sources", help="print public source-surface catalog")
    sources.add_argument("--category", help="filter by exact source category")
    sources.add_argument("--limit", type=int, help="limit returned source records")
    sources.add_argument("--compact", action="store_true")
    sources.set_defaults(func=cmd_sources)

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
