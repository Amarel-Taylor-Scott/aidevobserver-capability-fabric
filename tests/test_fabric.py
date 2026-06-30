from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from aidevobserver_fabric import fabric, hybrid, openwebui, primitive_factory, registry, social_ingest, source_surfaces


class FabricTests(unittest.TestCase):
    def test_registry_builds_seed_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "primitive_search.sqlite"
            counts = registry.build_db(db)
            self.assertGreaterEqual(counts["primitive_records"], 10)
            self.assertGreaterEqual(counts["compatibility_edges"], 4)

    def test_hybrid_search_respects_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "primitive_search.sqlite"
            registry.build_db(db)
            con = registry.connect(db)
            try:
                result = hybrid.search(
                    con,
                    "csv profile rows for warehouse ingestion",
                    {"output_contract": "ColumnProfileSet", "candidate_only": True},
                )
            finally:
                con.close()
            self.assertEqual(result["results"][0]["primitive_id"], "candidate.csv.profile_columns.v0")
            self.assertFalse(result["results"][0]["serves_truth"])
            self.assertEqual(result["candidate_bundle"]["template_role"], "profile_tabular_data")

    def test_rate_bundle_includes_remix_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "primitive_search.sqlite"
            registry.build_db(db)
            con = registry.connect(db)
            try:
                bundle = hybrid.build_bundle(con, "normalize interest rates", "normalize_regulatory_rates").to_dict()
            finally:
                con.close()
            normalize_slot = [slot for slot in bundle["slots"] if slot["slot_id"] == "normalize"][0]
            fits = {candidate["fit"] for candidate in normalize_slot["candidates"]}
            self.assertIn("direct", fits)
            self.assertIn("remix", fits)

    def test_fabric_discovery_is_candidate_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "primitive_search.sqlite"
            data = fabric.build_fabric(db)
            self.assertFalse(data["serves_truth"])
            self.assertGreaterEqual(data["counts"]["candidate_bundles"], 5)
            hits = fabric.discover_services(data, "find reusable primitive search route")
            self.assertTrue(hits)
            self.assertFalse(hits[0]["serves_truth"])
            discovery = fabric.agent_discovery(data)
            self.assertIn("BOUNDARY discovery=awareness authorization=false serves_truth=false", discovery)
            self.assertIn("SVC svc.primitive_search.v0", discovery)
            self.assertIn("SVC svc.primitive_factory.v0", discovery)
            self.assertEqual(data["factory"]["counts"]["genomes"], data["counts"]["factory_genomes"])
            openapi = fabric.openapi_stub(data)
            self.assertIn("/factory", openapi["paths"])

    def test_source_surfaces_catalog_is_candidate_only(self) -> None:
        records = source_surfaces.SOURCE_SURFACES
        self.assertGreaterEqual(len(records), 60)
        self.assertTrue(all(surface.candidate_only for surface in records))
        self.assertTrue(all(surface.url.startswith("https://") for surface in records))
        categories = {surface.category for surface in records}
        self.assertIn("startup_directory", categories)
        self.assertIn("repo_directory", categories)
        self.assertIn("newsletter", categories)
        self.assertIn("model_benchmark", categories)

    def test_source_surfaces_render_compact_and_json(self) -> None:
        compact = source_surfaces.as_compact(source_surfaces.SOURCE_SURFACES[:2])
        self.assertIn("BOUNDARY candidate_intake=true serves_truth=false", compact)
        self.assertIn("SRC startup.yc.ai", compact)
        rendered = source_surfaces.as_json(source_surfaces.SOURCE_SURFACES[:1])
        self.assertIn('"serves_truth": false', rendered)
        self.assertIn('"record_count": 1', rendered)

    def test_social_sources_render_candidate_only(self) -> None:
        sources = social_ingest.load_social_sources()
        self.assertEqual(len(sources), 5)
        self.assertTrue(all(source.candidate_only for source in sources))
        compact = social_ingest.compact_sources(sources[:1])
        self.assertIn("BOUNDARY candidate_intake=true serves_truth=false", compact)
        self.assertIn("SOC facebook.deeprepo", compact)

    def test_rapidapi_request_plan_redacts_key(self) -> None:
        provider = social_ingest.RapidApiProviderSpec(
            provider_id="test.provider",
            name="Test Provider",
            host="example.p.rapidapi.com",
            path="/posts",
            url_param="page",
            limit_param="count",
            static_query={"sort": "new"},
        )
        source = social_ingest.DEFAULT_FACEBOOK_SOURCES[0]
        plan = social_ingest.build_request_plan(provider, source, limit=3, key_value="secret")
        self.assertIn("page=https%3A%2F%2Fwww.facebook.com%2FDeepRepo", plan.url)
        self.assertIn("count=3", plan.url)
        self.assertEqual(plan.headers["X-RapidAPI-Key"], "<redacted>")
        self.assertFalse(plan.serves_truth)

    def test_rapidapi_provider_validation_and_key_status_are_redacted(self) -> None:
        provider = social_ingest.RapidApiProviderSpec(
            provider_id="test.provider",
            name="Test Provider",
            host="example.p.rapidapi.com",
            path="/posts",
            key_env="TEST_RAPIDAPI_KEY",
        )
        validation = social_ingest.validate_provider_spec(provider)
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["errors"], [])
        os.environ["TEST_RAPIDAPI_KEY"] = "secret-value"
        try:
            status = social_ingest.rapidapi_key_status(provider)
        finally:
            os.environ.pop("TEST_RAPIDAPI_KEY", None)
        self.assertTrue(status["present"])
        self.assertEqual(status["value"], "<redacted>")
        self.assertEqual(status["length"], len("secret-value"))

    def test_facebook_scraper3_provider_config_is_valid_and_plannable(self) -> None:
        provider = social_ingest.load_provider_spec(Path("examples/rapidapi_facebook_scraper3_provider.example.json"))
        validation = social_ingest.validate_provider_spec(provider)
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["errors"], [])
        page_plan = social_ingest.build_request_plan(
            provider,
            social_ingest.DEFAULT_FACEBOOK_SOURCES[0],
        )
        self.assertIn("/page/posts", page_plan.url)
        self.assertIn("page_id=%3Cresolved%3Apage_id%3E", page_plan.url)
        profile_plan = social_ingest.build_request_plan(
            provider,
            social_ingest.DEFAULT_FACEBOOK_SOURCES[3],
        )
        self.assertIn("/profile/posts", profile_plan.url)
        self.assertIn("profile_id=%3Cresolved%3Aprofile_id%3E", profile_plan.url)
        self.assertEqual(page_plan.headers["X-RapidAPI-Key"], "<redacted>")

    def test_social_source_selection(self) -> None:
        sources = social_ingest.load_social_sources()
        selected = social_ingest.select_source(sources, 1)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].source_id, "facebook.aidev_repo")
        with self.assertRaises(IndexError):
            social_ingest.select_source(sources, 999)

    def test_social_post_normalization_common_shapes(self) -> None:
        payload = {
            "data": [
                {
                    "post_id": "abc",
                    "permalink_url": "https://www.facebook.com/example/posts/abc",
                    "message": "New AI tooling post https://github.com/example/project",
                    "created_time": "2026-06-30T00:00:00Z",
                    "like_count": 12,
                    "comment_count": 3,
                }
            ]
        }
        posts = social_ingest.normalize_posts(payload, social_ingest.DEFAULT_FACEBOOK_SOURCES[0])
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].post_id, "abc")
        self.assertEqual(posts[0].text, "New AI tooling post https://github.com/example/project")
        self.assertEqual(posts[0].metrics["like_count"], 12)
        self.assertIn("https://github.com/example/project", posts[0].links)
        self.assertIn("https://github.com/example/project", posts[0].github_repo_urls)
        self.assertFalse(posts[0].serves_truth)

    def test_social_search_returns_social_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "primitive_search.sqlite"
            registry.build_db(db)
            con = registry.connect(db)
            try:
                result = hybrid.search(
                    con,
                    "facebook page scraper rapidapi posts primitive drafts",
                    {"candidate_only": True},
                )
            finally:
                con.close()
            self.assertEqual(result["results"][0]["primitive_id"], "candidate.social.facebook_rapidapi_fetch_posts.v0")
            self.assertEqual(result["candidate_bundle"]["template_role"], "ingest_social_posts")

    def test_openwebui_plan_is_redacted(self) -> None:
        config = openwebui.OpenWebUIConfig()
        plan = openwebui.redacted_plan(config, mode="direct")
        self.assertFalse(plan["serves_truth"])
        self.assertTrue(plan["candidate_only"])
        self.assertEqual(plan["headers"]["Authorization"], "<redacted>")
        self.assertEqual(plan["endpoint"], "/api/chat/completions")
        cdp_plan = openwebui.redacted_plan(config, mode="cdp")
        self.assertEqual(cdp_plan["headers"]["Authorization"], "<browser-context>")

    def test_openwebui_payload_and_response_normalization(self) -> None:
        payload = openwebui.chat_payload("hello", "gemma-4-coding", system="be terse")
        self.assertEqual(payload["model"], "gemma-4-coding")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["content"], "hello")
        normalized = openwebui.normalize_chat_response(
            {
                "id": "chatcmpl-test",
                "model": "gemma-4-coding",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 1,
                    "total_tokens": 4,
                },
            }
        )
        self.assertEqual(normalized["assistant_content"], "ok")
        self.assertEqual(normalized["model"], "gemma-4-coding")
        self.assertFalse(normalized["serves_truth"])

    def test_primitive_factory_snapshot_is_candidate_only(self) -> None:
        snapshot = primitive_factory.factory_snapshot()
        self.assertFalse(snapshot["serves_truth"])
        self.assertTrue(snapshot["candidate_only"])
        self.assertGreaterEqual(snapshot["counts"]["genomes"], 13)
        self.assertGreater(snapshot["counts"]["mutations"], snapshot["counts"]["genomes"])
        self.assertGreater(snapshot["counts"]["crossovers"], 0)

    def test_primitive_factory_social_genome_exposes_runtime_mutators(self) -> None:
        snapshot = primitive_factory.factory_snapshot()
        genome = next(
            row
            for row in snapshot["genomes"]
            if row["primitive_id"] == "candidate.social.facebook_rapidapi_fetch_posts.v0"
        )
        self.assertEqual(genome["determinism"], "external_nondeterministic")
        self.assertIn("provider_fallback", genome["mutators"])
        self.assertIn("retry_wrapper", genome["mutators"])
        self.assertIn("ttl_cache", genome["mutators"])

    def test_primitive_factory_lineage_tracks_candidate_children(self) -> None:
        snapshot = primitive_factory.factory_snapshot()
        lineage = primitive_factory.lineage_for("candidate.social.facebook_rapidapi_fetch_posts.v0", snapshot)
        self.assertFalse(lineage["serves_truth"])
        self.assertTrue(lineage["children"])
        self.assertTrue(all(not child["serves_truth"] for child in lineage["children"]))
        tools = {child["tool"] for child in lineage["children"]}
        self.assertIn("provider_fallback", tools)


if __name__ == "__main__":
    unittest.main()
