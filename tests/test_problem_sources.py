from __future__ import annotations

import json
import os
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from aidevobserver_fabric.problem_sources import (
    AMBER,
    GREEN,
    RED,
    DEFAULT_GITHUB_OPERATIONAL_REPOS,
    DEFAULT_SOURCE_BY_ID,
    DEFAULT_SOURCE_SPECS,
    AccessClass,
    SourcePolicy,
    SourceSpec,
    collect_many,
    collect_source,
    load_source_specs,
    fetch_source,
    replay_fetch_result,
)


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        url: str,
        status: int = 200,
        content_type: str = "application/json",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.url = url
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))
        for key, value in (extra_headers or {}).items():
            self.headers[key] = value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self.url

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]


class FakeOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests = []
        self.timeouts = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        self.timeouts.append(timeout)
        return self.response


def source_with(
    adapter: str,
    *,
    source_id: str = "fixture.source",
    endpoint: str = "https://fixture.example/feed",
    policy: SourcePolicy | None = None,
    auth_env: str | None = None,
    auth_header: str | None = None,
    auth_prefix: str = "",
) -> SourceSpec:
    return SourceSpec(
        source_id=source_id,
        name="Fixture source",
        adapter=adapter,
        endpoint=endpoint,
        fixed_hosts=("fixture.example",),
        policy=policy or SourcePolicy(AMBER, max_bytes=10_000, excerpt_chars=120),
        cadence_seconds=300,
        auth_env=auth_env,
        auth_header=auth_header,
        auth_prefix=auth_prefix,
    )


class ProblemSourcePolicyTests(unittest.TestCase):
    def test_custom_source_portfolio_is_validated_and_secret_values_are_rejected(self) -> None:
        payload = {
            "sources": [
                {
                    "source_id": "discourse.example",
                    "name": "Example operator forum",
                    "adapter": "rss",
                    "endpoint": "https://forum.example.test/latest.rss",
                    "fixed_hosts": ["forum.example.test"],
                    "access_class": "AMBER",
                    "cadence_seconds": 900,
                }
            ]
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "sources.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            sources = load_source_specs(path)
        self.assertEqual(sources[0].source_id, "discourse.example")
        self.assertEqual(sources[0].adapter, "rss")
        payload["sources"][0]["default_headers"] = {"Authorization": "secret"}
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "sources.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_source_specs(path)

    def test_default_sources_are_fixed_https_candidate_sources(self) -> None:
        self.assertEqual(len(DEFAULT_SOURCE_SPECS), 8)
        self.assertEqual(len(DEFAULT_SOURCE_BY_ID), 8)
        required_adapters = {
            "github_issues",
            "hn_ask",
            "stackexchange_questions",
            "rss",
            "cfpb_complaints",
            "federal_register",
        }
        self.assertTrue(required_adapters.issubset({row.adapter for row in DEFAULT_SOURCE_SPECS}))
        self.assertTrue(all(row.endpoint.startswith("https://") for row in DEFAULT_SOURCE_SPECS))
        self.assertTrue(all(row.policy.candidate_only for row in DEFAULT_SOURCE_SPECS))
        self.assertTrue(all(row.policy.access_class in {GREEN, AMBER} for row in DEFAULT_SOURCE_SPECS))
        self.assertEqual(len(DEFAULT_GITHUB_OPERATIONAL_REPOS), 7)
        self.assertIn("frappe/erpnext", DEFAULT_GITHUB_OPERATIONAL_REPOS)
        self.assertIn("woocommerce/woocommerce", DEFAULT_GITHUB_OPERATIONAL_REPOS)

    def test_access_classes_and_red_network_boundary(self) -> None:
        self.assertEqual(AccessClass.GREEN.value, "GREEN")
        self.assertEqual(AccessClass.AMBER.value, "AMBER")
        self.assertEqual(AccessClass.RED.value, "RED")
        red_policy = SourcePolicy(RED, allow_network=False)
        red_source = source_with("rss", policy=red_policy)
        result = fetch_source(red_source)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "source_disabled")

    def test_source_spec_rejects_non_https_and_host_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use https"):
            source_with("rss", endpoint="http://fixture.example/feed")
        with self.assertRaisesRegex(ValueError, "outside fixed_hosts"):
            source_with("rss", endpoint="https://evil.example/feed")

    def test_auth_configuration_and_secret_values_are_not_serialized(self) -> None:
        source = source_with(
            "github_issues",
            auth_env="FIXTURE_API_TOKEN",
            auth_header="Authorization",
            auth_prefix="Bearer ",
        )
        secret = "never-serialize-this-secret"
        response = FakeResponse(
            json.dumps({"items": []}).encode(),
            url=source.endpoint,
            extra_headers={"ETag": '"abc"', "Last-Modified": "Tue, 01 Jan 2030 00:00:00 GMT"},
        )
        opener = FakeOpener(response)
        with patch.dict(os.environ, {"FIXTURE_API_TOKEN": secret}):
            result = fetch_source(
                source,
                etag='"old"',
                last_modified="Mon, 01 Jan 2029 00:00:00 GMT",
                opener=opener,
            )
        headers = {key.lower(): value for key, value in opener.requests[0].header_items()}
        self.assertEqual(headers["authorization"], f"Bearer {secret}")
        self.assertEqual(headers["if-none-match"], '"old"')
        self.assertEqual(headers["if-modified-since"], "Mon, 01 Jan 2029 00:00:00 GMT")
        self.assertEqual(opener.timeouts, [source.policy.timeout_seconds])
        serialized = json.dumps({"source": source.to_dict(), "result": result.to_dict()})
        self.assertNotIn(secret, serialized)
        self.assertNotIn("FIXTURE_API_TOKEN", serialized)
        self.assertEqual(result.etag, '"abc"')

        with self.assertRaisesRegex(ValueError, "credential-bearing default_headers"):
            SourceSpec(
                source_id="header.fixture",
                name="Header fixture",
                adapter="github_issues",
                endpoint="https://fixture.example/feed",
                fixed_hosts=("fixture.example",),
                policy=SourcePolicy(AMBER),
                cadence_seconds=300,
                default_headers={"X-Api-Key": secret, "Accept": "application/json"},
            )

    def test_fixed_host_policy_rejects_override_before_open(self) -> None:
        source = source_with("rss")
        opener = FakeOpener(FakeResponse(b"", url=source.endpoint))
        result = fetch_source(source, request_url="https://evil.example/rss", opener=opener)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "url_policy_error")
        self.assertEqual(opener.requests, [])

    def test_response_size_is_bounded_and_failure_is_a_receipt(self) -> None:
        policy = SourcePolicy(AMBER, max_bytes=80, excerpt_chars=80)
        source = source_with("rss", policy=policy)
        response = FakeResponse(b"x" * 81, url=source.endpoint)
        result = fetch_source(source, opener=FakeOpener(response))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "response_too_large")
        self.assertEqual(result.observations, ())
        self.assertFalse(result.to_dict()["serves_truth"])

    def test_fixture_path_replay_and_parse_errors_do_not_raise(self) -> None:
        source = source_with("github_issues")
        with TemporaryDirectory() as directory:
            fixture = Path(directory) / "bad.json"
            fixture.write_text("not-json", encoding="utf-8")
            fetched = replay_fetch_result(source, fixture)
            result = collect_source(source, fixture=fixture)
        self.assertTrue(fetched.ok)
        self.assertTrue(fetched.from_fixture)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "parse_error")


class ProblemSourceParserTests(unittest.TestCase):
    def test_github_issues_drop_pull_requests_and_minimize_pii(self) -> None:
        source = source_with("github_issues")
        payload = {
            "items": [
                {
                    "id": 11,
                    "node_id": "ISSUE_node",
                    "number": 22,
                    "repository_url": "https://api.github.com/repos/acme/erp",
                    "html_url": "https://github.com/acme/erp/issues/22",
                    "title": "Manual reconciliation blocks close",
                    "body": (
                        "Email jane@example.com or call (212) 555-0188. "
                        "The spreadsheet workaround takes four hours every Friday."
                    ),
                    "user": {"login": "jane-private"},
                    "labels": [{"name": "workflow"}],
                    "comments": 7,
                    "reactions": {"total_count": 13},
                    "state": "open",
                    "created_at": "2026-07-01T00:00:00Z",
                    "updated_at": "2026-07-02T00:00:00Z",
                },
                {"id": 12, "title": "PR", "pull_request": {"url": "https://example"}},
            ]
        }
        result = collect_source(source, fixture=payload)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.observations), 1)
        row = result.observations[0]
        self.assertEqual(row.metadata["repository"], "acme/erp")
        self.assertEqual(row.metadata["labels"], ["workflow"])
        self.assertIn("[email redacted]", row.excerpt)
        self.assertIn("[phone redacted]", row.excerpt)
        self.assertNotIn("jane-private", json.dumps(result.to_dict()))
        self.assertTrue(row.candidate_only)
        self.assertFalse(row.serves_truth)

    def test_hn_ask_index_and_item_shapes(self) -> None:
        source = source_with("hn_ask")
        index_result = collect_source(source, fixture=[101, 102])
        self.assertEqual(len(index_result.observations), 2)
        self.assertTrue(index_result.observations[0].metadata["needs_item_fetch"])

        item_result = collect_source(
            source,
            fixture={
                "id": 101,
                "type": "story",
                "title": "Ask HN: What do you still reconcile manually?",
                "text": "Contact @private_user; our team uses three spreadsheets.",
                "by": "private_user",
                "score": 42,
                "descendants": 18,
                "time": 1780000000,
            },
        )
        self.assertTrue(item_result.ok)
        row = item_result.observations[0]
        self.assertEqual(row.kind, "hn_ask")
        self.assertIn("[handle redacted]", row.excerpt)
        self.assertNotIn("private_user", json.dumps(item_result.to_dict()))

    def test_stackexchange_shape_omits_owner_and_preserves_validation_signals(self) -> None:
        source = source_with("stackexchange_questions")
        result = collect_source(
            source,
            fixture={
                "items": [
                    {
                        "question_id": 700,
                        "title": "How can I stop duplicate invoice imports?",
                        "body": "Our CSV import creates duplicate invoices every night.",
                        "link": "https://stackoverflow.com/questions/700/example",
                        "owner": {"display_name": "Private Name"},
                        "tags": ["csv", "accounting"],
                        "score": 8,
                        "view_count": 1200,
                        "answer_count": 0,
                        "is_answered": False,
                        "creation_date": 1780000000,
                        "last_activity_date": 1780000100,
                    }
                ],
                "quota_remaining": 999,
            },
        )
        self.assertTrue(result.ok)
        row = result.observations[0]
        self.assertEqual(row.metadata["tags"], ["csv", "accounting"])
        self.assertEqual(row.metadata["view_count"], 1200)
        self.assertFalse(row.metadata["is_answered"])
        self.assertNotIn("Private Name", json.dumps(result.to_dict()))

    def test_discourse_rss_and_atom_are_parsed_without_authors(self) -> None:
        source = source_with("rss")
        rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel><title>Forum</title><item>
          <title>Orders fail to sync</title>
          <link>https://fixture.example/t/orders-fail/44</link>
          <guid>topic-44</guid><pubDate>Fri, 10 Jul 2026 10:00:00 GMT</pubDate>
          <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">Private User</dc:creator>
          <category>integration</category>
          <description><![CDATA[Email ops@example.com. Orders are manually re-keyed.]]></description>
        </item></channel></rss>"""
        result = collect_source(source, fixture=rss)
        self.assertTrue(result.ok)
        row = result.observations[0]
        self.assertEqual(row.kind, "forum_topic")
        self.assertEqual(row.metadata["categories"], ["integration"])
        self.assertIn("[email redacted]", row.excerpt)
        self.assertNotIn("Private User", json.dumps(result.to_dict()))

    def test_cfpb_shape_omits_zip_and_retains_problem_taxonomy(self) -> None:
        source = source_with("cfpb_complaints")
        result = collect_source(
            source,
            fixture={
                "hits": {
                    "hits": [
                        {
                            "_id": "9001",
                            "_source": {
                                "complaint_id": 9001,
                                "product": "Money transfer",
                                "sub_product": "International transfer",
                                "issue": "Money was not available",
                                "sub_issue": "Recipient did not receive money",
                                "complaint_what_happened": "Support made us repeat verification five times.",
                                "company": "Example Payments",
                                "company_response": "Closed with explanation",
                                "timely": "Yes",
                                "submitted_via": "Web",
                                "state": "NY",
                                "zip_code": "10001",
                            },
                        }
                    ]
                }
            },
        )
        self.assertTrue(result.ok)
        row = result.observations[0]
        self.assertEqual(row.metadata["issue"], "Money was not available")
        self.assertEqual(row.metadata["company"], "Example Payments")
        self.assertNotIn("zip", json.dumps(row.to_dict()).lower())

    def test_federal_register_shape_preserves_dates_and_dockets(self) -> None:
        source = source_with("federal_register")
        result = collect_source(
            source,
            fixture={
                "results": [
                    {
                        "document_number": "2026-12345",
                        "type": "Proposed Rule",
                        "title": "Information collection for small entities",
                        "abstract": "The agency requests comment on manual reporting burden.",
                        "html_url": "https://www.federalregister.gov/d/2026-12345",
                        "pdf_url": "https://www.federalregister.gov/documents/2026.pdf",
                        "publication_date": "2026-07-10",
                        "comments_close_on": "2026-09-01",
                        "effective_on": None,
                        "agencies": [{"name": "Example Agency", "id": 4}],
                        "docket_ids": ["EXAMPLE-2026-001"],
                        "regulation_id_numbers": ["1234-AA00"],
                    }
                ]
            },
        )
        self.assertTrue(result.ok)
        row = result.observations[0]
        self.assertEqual(row.metadata["agencies"], ["Example Agency"])
        self.assertEqual(row.metadata["comment_end_date"], "2026-09-01")
        self.assertEqual(row.metadata["docket_ids"], ["EXAMPLE-2026-001"])

    def test_collect_many_preserves_successes_and_source_failures(self) -> None:
        github = source_with("github_issues", source_id="good")
        broken = source_with("github_issues", source_id="broken")
        results = collect_many(
            (github, broken),
            fixtures={"good": {"items": []}, "broken": "not-json"},
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].ok)
        self.assertFalse(results[1].ok)
        self.assertEqual(results[1].error_code, "parse_error")


if __name__ == "__main__":
    unittest.main()
