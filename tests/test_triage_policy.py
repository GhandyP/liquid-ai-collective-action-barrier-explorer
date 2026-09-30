"""Offline tests for the deterministic local triage policy."""

from __future__ import annotations

import json
import math
import unittest

from src.triage_policy import (
    ALL_HYPOTHESES,
    BARRIER_HYPOTHESES,
    DEFAULT_HIGH_THRESHOLD,
    DEFAULT_LOW_THRESHOLD,
    triage_result,
)


def normalized_result(
    overrides: dict[str, float] | None = None,
    *,
    run_status: str = "live",
) -> dict:
    probabilities = {name: 0.1 for name in BARRIER_HYPOTHESES}
    probabilities["insufficient_evidence"] = 0.1
    probabilities.update(overrides or {})
    return {
        "run_status": run_status,
        "hypotheses": {
            name: {"probability": probabilities[name]} for name in ALL_HYPOTHESES
        },
    }


class TriagePolicyTests(unittest.TestCase):
    def test_one_high_barrier_is_a_leading_hypothesis(self) -> None:
        result = triage_result(
            normalized_result({"perception_gap": 0.65}), usable_evidence=True
        )

        self.assertEqual(result["status"], "leading")
        self.assertEqual(result["hypotheses"], ["perception_gap"])
        self.assertTrue(result["human_review_required"])
        self.assertEqual(result["thresholds"], {"low": 0.35, "high": 0.65})

    def test_two_or_more_high_barriers_are_mixed(self) -> None:
        result = triage_result(
            normalized_result(
                {"perception_gap": 0.8, "structural_barrier": 0.65}
            ),
            usable_evidence=True,
        )

        self.assertEqual(result["status"], "mixed")
        self.assertEqual(
            result["hypotheses"], ["perception_gap", "structural_barrier"]
        )
        self.assertTrue(result["human_review_required"])

    def test_low_and_high_boundaries_are_inclusive(self) -> None:
        at_low = triage_result(
            normalized_result({"values_conflict": 0.35}), usable_evidence=True
        )
        just_below_high = triage_result(
            normalized_result({"values_conflict": 0.649999}), usable_evidence=True
        )
        at_high = triage_result(
            normalized_result({"values_conflict": 0.65}), usable_evidence=True
        )

        self.assertEqual(at_low["status"], "possible")
        self.assertEqual(at_low["hypotheses"], ["values_conflict"])
        self.assertEqual(just_below_high["status"], "possible")
        self.assertEqual(at_high["status"], "leading")

    def test_possible_lists_each_barrier_between_low_and_high(self) -> None:
        result = triage_result(
            normalized_result(
                {"values_conflict": 0.35, "structural_barrier": 0.649999}
            ),
            usable_evidence=True,
        )

        self.assertEqual(result["status"], "possible")
        self.assertEqual(
            result["hypotheses"], ["values_conflict", "structural_barrier"]
        )
        self.assertTrue(result["human_review_required"])

    def test_high_insufficient_evidence_overrides_barrier_hypotheses(self) -> None:
        result = triage_result(
            normalized_result(
                {
                    "perception_gap": 0.9,
                    "structural_barrier": 0.9,
                    "insufficient_evidence": 0.65,
                }
            ),
            usable_evidence=True,
        )

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["hypotheses"], [])
        self.assertEqual(
            result["hypothesis_profile"]["insufficient_evidence"], 0.65
        )
        self.assertTrue(result["request_more_evidence"])
        self.assertTrue(result["human_review_required"])

    def test_missing_usable_evidence_requests_more_information(self) -> None:
        result = triage_result(
            normalized_result({"perception_gap": 0.9}), usable_evidence=False
        )

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["hypotheses"], [])
        self.assertTrue(result["request_more_evidence"])
        self.assertTrue(result["human_review_required"])

    def test_no_candidate_at_low_cutoff_is_unsupported(self) -> None:
        result = triage_result(
            normalized_result(
                {
                    "perception_gap": 0.349999,
                    "values_conflict": 0.2,
                    "insufficient_evidence": 0.64,
                }
            ),
            usable_evidence=True,
        )

        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["hypotheses"], [])
        self.assertFalse(result["request_more_evidence"])
        self.assertTrue(result["human_review_required"])

    def test_error_and_malformed_results_fail_closed_without_hypotheses(self) -> None:
        valid = normalized_result()
        cases = [
            {**valid, "run_status": "error"},
            {**valid, "run_status": "unavailable"},
            {"run_status": "live", "hypotheses": {}},
            {
                **valid,
                "hypotheses": {
                    **valid["hypotheses"],
                    "values_conflict": {"probability": math.nan},
                },
            },
            {
                **valid,
                "hypotheses": {
                    **valid["hypotheses"],
                    "values_conflict": {"probability": True},
                },
            },
        ]
        for malformed in cases:
            with self.subTest(run_status=malformed.get("run_status")):
                result = triage_result(malformed, usable_evidence=True)
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["hypothesis_profile"], {})
                self.assertEqual(result["hypotheses"], [])
                self.assertTrue(result["human_review_required"])

    def test_missing_run_status_and_non_boolean_evidence_fail_closed(self) -> None:
        result = triage_result(
            {"hypotheses": normalized_result()["hypotheses"]},
            usable_evidence=True,
        )
        invalid_evidence = triage_result(normalized_result(), usable_evidence=None)

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(invalid_evidence["status"], "unavailable")
        self.assertEqual(invalid_evidence["hypotheses"], [])

    def test_mock_results_are_accepted_and_output_is_json_serializable(self) -> None:
        result = triage_result(
            normalized_result({"response_efficacy_gap": 0.7}, run_status="mock"),
            usable_evidence=True,
        )

        self.assertEqual(result["status"], "leading")
        self.assertEqual(json.loads(json.dumps(result)), result)
        self.assertTrue(result["thresholds_illustrative"])

    def test_independent_probabilities_are_preserved(self) -> None:
        probabilities = {
            "perception_gap": 0.8,
            "values_conflict": 0.75,
            "response_efficacy_gap": 0.2,
            "collective_efficacy_gap": 0.1,
            "structural_barrier": 0.15,
            "insufficient_evidence": 0.1,
        }
        result = triage_result(normalized_result(probabilities), usable_evidence=True)

        self.assertEqual(result["hypothesis_profile"], probabilities)
        self.assertGreater(sum(result["hypothesis_profile"].values()), 1.0)

    def test_threshold_validation_rejects_invalid_order_and_values(self) -> None:
        for low, high in (
            (0.65, 0.65),
            (0.7, 0.65),
            (-0.1, 0.65),
            (0.35, 1.1),
            (math.nan, 0.65),
            (True, 0.65),
        ):
            with self.subTest(low=low, high=high):
                with self.assertRaises(ValueError):
                    triage_result(
                        normalized_result(),
                        usable_evidence=True,
                        low_threshold=low,
                        high_threshold=high,
                    )

    def test_default_cutoffs_are_explicitly_illustrative(self) -> None:
        self.assertEqual(DEFAULT_LOW_THRESHOLD, 0.35)
        self.assertEqual(DEFAULT_HIGH_THRESHOLD, 0.65)


if __name__ == "__main__":
    unittest.main()
