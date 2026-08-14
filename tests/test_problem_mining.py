from __future__ import annotations

import unittest

from aidevobserver_fabric.problem_mining import (
    FRICTION_ARCHETYPES,
    UNKNOWN_FRICTION,
    assess_opportunity,
    automatic_build_gate,
    classify_friction,
    cluster_problem_signals,
    extract_problem_signal,
    signal_similarity,
)


class ProblemMiningTests(unittest.TestCase):
    def _invoice_signal(
        self,
        signal_id: str,
        source_class: str | None,
        *,
        evidence_ref: str | None = None,
        oracle: str | None = "expected mapped fields equal the golden fixture",
        severity: float | None = None,
        momentum: float | None = None,
        solution_gap: float | None = None,
    ):
        return extract_problem_signal(
            signal_id=signal_id,
            text=(
                "Our accounting team manually copy invoice totals from vendor email "
                "into ERP during invoice intake, causing settlement delays."
            ),
            source_ref=f"https://example.test/{signal_id}",
            source_class=source_class,
            evidence_refs=(evidence_ref or f"evidence:{signal_id}",),
            actor="accounting team",
            workflow="invoice intake",
            oracle=oracle,
            severity=severity,
            momentum=momentum,
            solution_gap=solution_gap,
        )

    def test_vocabulary_covers_each_requested_friction_class(self) -> None:
        fixtures = {
            "manual_transfer": "Staff manually copy invoice fields into the ERP.",
            "reconciliation": "Analysts reconcile mismatches between records.",
            "validation_compliance": "We validate every claim for regulatory compliance.",
            "aggregation": "We consolidate fragmented feeds into a single view.",
            "monitoring": "Operators monitor status and alert when it changes.",
            "lookup": "Agents look up the customer record before every call.",
            "triage": "Support must triage and route tickets to a work queue.",
            "handoff": "Requests fall through the cracks between teams during handoff.",
            "extraction": "Clerks extract fields from unstructured PDF documents.",
            "decision_inconsistency": (
                "The same case gets different decisions because policy interpretation varies."
            ),
            "missing_integration": "The ERP has no integration with the payment service.",
            "scheduling_coordination": "Dispatchers schedule manually around shift coverage.",
            "exception_handling": "Staff perform exception handling for failed items.",
            "data_quality_cleanup": "Imported records have missing fields and bad data.",
            "status_chasing": "Coordinators chase status while waiting for update.",
            "manual_workflow": "The same manual process runs every morning.",
        }
        self.assertEqual(set(fixtures), set(FRICTION_ARCHETYPES))
        for expected, text in fixtures.items():
            with self.subTest(expected=expected):
                actual, confidence = classify_friction(text)
                self.assertEqual(actual, expected)
                self.assertIsNotNone(confidence)

    def test_redacts_sensitive_values_and_bounds_excerpt(self) -> None:
        signal = extract_problem_signal(
            text=(
                "Our support team manually copy records for jane@example.com, phone "
                "+1 (212) 555-0199. Authorization: Bearer abc.def.ghi; "
                "api_key=secret123; token ghp_abcdefghijklmnopqrstuvwxyz. "
                + "extra " * 100
            ),
            source_ref="https://example.test/ticket?token=url-secret&item=1",
            source_class="support",
            contradictions=("Contact owner@example.com before deciding.",),
            max_excerpt_chars=160,
        )
        self.assertLessEqual(len(signal.excerpt), 160)
        self.assertIn("<redacted-email>", signal.excerpt)
        self.assertIn("<redacted-phone>", signal.excerpt)
        self.assertIn("<redacted-token>", signal.excerpt)
        self.assertNotIn("secret123", signal.excerpt)
        self.assertIn("token=<redacted-token>", signal.source_ref)
        self.assertEqual(signal.contradictions, ("Contact <redacted-email> before deciding.",))

    def test_unknown_values_are_not_fabricated(self) -> None:
        signal = extract_problem_signal(
            text="The current process is frustrating and expensive.",
            source_ref="evidence:unknown",
            source_class=None,
        )
        self.assertEqual(signal.friction_type, UNKNOWN_FRICTION)
        self.assertIsNone(signal.classification_confidence)
        self.assertIsNone(signal.actor)
        self.assertIsNone(signal.workflow)
        self.assertIsNone(signal.archetype)
        self.assertIsNone(signal.input_contract)
        self.assertIsNone(signal.output_contract)
        self.assertIn("actor", signal.unknown_fields)
        self.assertIn("source_class", signal.unknown_fields)

    def test_extracts_actor_workflow_and_maps_contract_shape(self) -> None:
        signal = extract_problem_signal(
            text=(
                "Our accounting team manually copy invoice totals during invoice intake, "
                "causing late settlement."
            ),
            source_ref="issue:42",
            source_class="github",
            oracle="mapped totals match a reviewed invoice fixture",
        )
        self.assertEqual(signal.actor, "accounting team")
        self.assertEqual(signal.workflow, "invoice intake")
        self.assertEqual(signal.consequence, "late settlement")
        self.assertEqual(signal.archetype, "adapter")
        self.assertEqual(signal.input_contract, "SourceRecord")
        self.assertEqual(signal.output_contract, "DestinationRecord")

    def test_signal_identity_and_fingerprint_are_deterministic(self) -> None:
        kwargs = {
            "text": "Our accounting team manually copy invoices during intake.",
            "source_ref": "issue:7",
            "source_class": "github",
            "evidence_refs": ("comment:2", "issue:7"),
        }
        first = extract_problem_signal(**kwargs)
        second = extract_problem_signal(**kwargs)
        self.assertEqual(first.signal_id, second.signal_id)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.evidence_refs, ("comment:2", "issue:7"))

    def test_friction_override_does_not_fabricate_classifier_confidence(self) -> None:
        signal = extract_problem_signal(
            text="Operators monitor a status feed and alert on changes.",
            source_ref="issue:8",
            source_class="github",
            friction_type="lookup",
        )
        self.assertEqual(signal.friction_type, "lookup")
        self.assertIsNone(signal.classification_confidence)

    def test_metric_bounds_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            extract_problem_signal(
                text="We manually copy records.",
                source_ref="issue:1",
                source_class="github",
                severity=1.01,
            )
        with self.assertRaises(ValueError):
            extract_problem_signal(
                text="We manually copy records.",
                source_ref="issue:1",
                source_class="github",
                budget_amount=-1,
            )

    def test_clustering_is_order_invariant_and_domain_sensitive(self) -> None:
        first = self._invoice_signal("signal-a", "github")
        second = extract_problem_signal(
            signal_id="signal-b",
            text=(
                "Our accounting team copy and paste invoice totals from vendor email into "
                "ERP during invoice intake."
            ),
            source_ref="forum:2",
            source_class="discourse",
            actor="accounting team",
            workflow="invoice intake",
            oracle="expected mapped fields equal the golden fixture",
        )
        other = extract_problem_signal(
            signal_id="signal-c",
            text=(
                "Our HR team manually copy candidate profiles from a recruiting portal "
                "into payroll during employee onboarding."
            ),
            source_ref="issue:3",
            source_class="github",
            actor="HR team",
            workflow="employee onboarding",
            oracle="candidate fixture equals the payroll record",
        )
        forward = cluster_problem_signals((first, second, other))
        reverse = cluster_problem_signals((other, second, first))
        self.assertEqual(forward, reverse)
        self.assertEqual(sorted(len(cluster.member_signal_ids) for cluster in forward), [1, 2])
        pair = next(cluster for cluster in forward if len(cluster.member_signal_ids) == 2)
        self.assertEqual(pair.member_signal_ids, ("signal-a", "signal-b"))
        self.assertTrue(pair.semantic_fingerprint.startswith("sha256:"))
        self.assertTrue(pair.membership_fingerprint.startswith("sha256:"))

    def test_different_friction_types_never_cluster(self) -> None:
        manual = extract_problem_signal(
            signal_id="manual",
            text="Our team manually copy invoice records during intake.",
            source_ref="issue:1",
            source_class="github",
        )
        validate = extract_problem_signal(
            signal_id="validate",
            text="Our team validate invoice records during intake.",
            source_ref="issue:2",
            source_class="github",
        )
        self.assertEqual(signal_similarity(manual, validate), 0.0)
        clusters = cluster_problem_signals((manual, validate), minimum_similarity=0.0)
        self.assertEqual(len(clusters), 2)

    def test_member_fingerprints_support_split_lineage_comparison(self) -> None:
        first = self._invoice_signal("a", "github")
        second = self._invoice_signal("b", "discourse")
        parent = cluster_problem_signals((first, second))[0]
        child = cluster_problem_signals((first,))[0]
        self.assertIn(first.fingerprint, parent.member_fingerprints)
        self.assertEqual(child.member_fingerprints, (first.fingerprint,))
        self.assertNotEqual(parent.membership_fingerprint, child.membership_fingerprint)

    def test_duplicate_signal_ids_are_rejected(self) -> None:
        first = self._invoice_signal("duplicate", "github")
        second = self._invoice_signal("duplicate", "discourse")
        with self.assertRaises(ValueError):
            cluster_problem_signals((first, second))

    def test_regular_build_gate_requires_three_evidence_refs_and_two_sources(self) -> None:
        signals = (
            self._invoice_signal("a", "github", evidence_ref="github:1"),
            self._invoice_signal("b", "github", evidence_ref="github:2"),
            self._invoice_signal("c", "discourse", evidence_ref="discourse:3"),
        )
        cluster = cluster_problem_signals(signals)[0]
        allowed, reasons = automatic_build_gate(cluster)
        self.assertTrue(allowed)
        self.assertEqual(reasons, ())
        self.assertEqual(cluster.evidence_refs, ("discourse:3", "github:1", "github:2"))
        self.assertEqual(cluster.source_classes, ("discourse", "github"))

    def test_same_source_evidence_does_not_pass_regular_gate(self) -> None:
        signals = tuple(
            self._invoice_signal(str(index), "github", evidence_ref=f"github:{index}")
            for index in range(3)
        )
        allowed, reasons = automatic_build_gate(cluster_problem_signals(signals)[0])
        self.assertFalse(allowed)
        self.assertIn("insufficient_independent_evidence_or_budgeted_procurement", reasons)

    def test_one_explicit_budgeted_procurement_item_can_pass(self) -> None:
        signal = extract_problem_signal(
            signal_id="tender-1",
            text=(
                "The procurement team requires an automated compliance validation service "
                "during supplier onboarding."
            ),
            source_ref="ted:notice:1",
            source_class="procurement",
            actor="procurement team",
            workflow="supplier onboarding",
            oracle="known eligible and ineligible supplier fixtures",
            explicit_budgeted_procurement=True,
            budget_amount=125_000,
            budget_currency="EUR",
        )
        cluster = cluster_problem_signals((signal,))[0]
        allowed, reasons = automatic_build_gate(cluster)
        self.assertTrue(allowed)
        self.assertEqual(reasons, ())
        self.assertEqual(cluster.explicit_budgeted_procurement_signal_ids, ("tender-1",))

    def test_procurement_flag_without_positive_budget_is_not_enough(self) -> None:
        signal = extract_problem_signal(
            signal_id="tender-1",
            text="The procurement team requires compliance validation during onboarding.",
            source_ref="ted:notice:1",
            source_class="procurement",
            actor="procurement team",
            workflow="supplier onboarding",
            oracle="eligible supplier fixture",
            explicit_budgeted_procurement=True,
        )
        allowed, reasons = automatic_build_gate(cluster_problem_signals((signal,))[0])
        self.assertFalse(allowed)
        self.assertIn("insufficient_independent_evidence_or_budgeted_procurement", reasons)

    def test_build_gate_requires_actor_workflow_contract_and_oracle_clarity(self) -> None:
        signal = extract_problem_signal(
            text="Staff manually copy invoice data.",
            source_ref="issue:1",
            source_class="github",
            explicit_budgeted_procurement=True,
            budget_amount=10_000,
            budget_currency="USD",
        )
        allowed, reasons = automatic_build_gate(cluster_problem_signals((signal,))[0])
        self.assertFalse(allowed)
        self.assertIn("actor_unknown", reasons)
        self.assertIn("workflow_unknown", reasons)
        self.assertIn("testable_oracle_unknown", reasons)
        self.assertNotIn("contract_unknown", reasons)

    def test_contradictions_and_unknown_metrics_survive_assessment(self) -> None:
        signal = extract_problem_signal(
            signal_id="a",
            text=(
                "Our accounting team manually copy invoice totals during invoice intake."
            ),
            source_ref="issue:a",
            source_class="github",
            actor="accounting team",
            workflow="invoice intake",
            oracle="expected mapped fields equal the golden fixture",
            contradictions=("Maintainer says a supported import already exists.",),
        )
        cluster = cluster_problem_signals((signal,))[0]
        assessment = assess_opportunity(cluster)
        vector = dict(assessment.score_vector)
        self.assertEqual(
            cluster.contradictions,
            ("Maintainer says a supported import already exists.",),
        )
        self.assertEqual(vector["contradiction_count"], 1.0)
        self.assertEqual(vector["contradiction_pressure"], 1.0)
        self.assertIsNone(vector["severity"])
        self.assertIn("severity", assessment.unknown_dimensions)

    def test_score_vector_and_queue_components_are_transparent(self) -> None:
        signals = (
            self._invoice_signal("a", "github", severity=0.8),
            self._invoice_signal("b", "discourse", severity=0.6),
            self._invoice_signal("c", "stackexchange", severity=0.7),
        )
        cluster = cluster_problem_signals(signals)[0]
        first = assess_opportunity(cluster)
        second = assess_opportunity(cluster)
        vector = dict(first.score_vector)
        self.assertEqual(first, second)
        self.assertTrue(first.profile_digest.startswith("sha256:"))
        self.assertEqual(vector["severity"], 0.7)
        self.assertIsNone(vector["momentum"])
        self.assertIn("momentum", first.unknown_dimensions)
        momentum_component = next(row for row in first.queue_components if row[0] == "momentum")
        self.assertIsNone(momentum_component[1])
        self.assertEqual(momentum_component[3], 0.0)
        self.assertGreaterEqual(first.queue_score, 0.0)
        self.assertLessEqual(first.queue_score, 1.0)
        self.assertTrue(first.build_gate_passed)

    def test_profile_override_changes_digest_and_exposes_components(self) -> None:
        cluster = cluster_problem_signals((self._invoice_signal("a", "github", severity=1.0),))[0]
        default = assess_opportunity(cluster)
        changed = assess_opportunity(cluster, profile={"weights": {"severity": 0.5}})
        self.assertNotEqual(default.profile_digest, changed.profile_digest)
        component = next(row for row in changed.queue_components if row[0] == "severity")
        self.assertEqual(component, ("severity", 1.0, 0.5, 0.5))

    def test_mixed_currency_budget_total_remains_unknown(self) -> None:
        first = extract_problem_signal(
            signal_id="a",
            text="The finance team requires validation during invoice intake.",
            source_ref="rfp:a",
            source_class="procurement",
            actor="finance team",
            workflow="invoice intake",
            oracle="known valid and invalid invoice fixtures",
            explicit_budgeted_procurement=True,
            budget_amount=10_000,
            budget_currency="USD",
        )
        second = extract_problem_signal(
            signal_id="b",
            text="The finance team requires validation during invoice intake.",
            source_ref="rfp:b",
            source_class="procurement",
            actor="finance team",
            workflow="invoice intake",
            oracle="known valid and invalid invoice fixtures",
            explicit_budgeted_procurement=True,
            budget_amount=9_000,
            budget_currency="EUR",
        )
        assessment = assess_opportunity(cluster_problem_signals((first, second))[0])
        self.assertIsNone(dict(assessment.score_vector)["budget_total"])
        self.assertIn("budget_total", assessment.unknown_dimensions)

    def test_records_serialize_without_promoting_candidates(self) -> None:
        signal = self._invoice_signal("a", "github")
        cluster = cluster_problem_signals((signal,))[0]
        assessment = assess_opportunity(cluster)
        for record in (signal, cluster, assessment):
            payload = record.to_dict()
            self.assertTrue(payload["candidate_only"])
            self.assertFalse(payload["serves_truth"])


if __name__ == "__main__":
    unittest.main()
