"""Offline contract tests for the case validation API."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from src.case_schema import CaseValidationError, validate_case


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "synthetic_cases.json"


def load_synthetic_case() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as fixture_file:
        cases = json.load(fixture_file)
    if not isinstance(cases, list) or len(cases) != 1:
        raise AssertionError("synthetic fixture must contain exactly one case")
    return cases[0]


class CaseSchemaTests(unittest.TestCase):
    def test_synthetic_case_validates_and_keeps_evidence_types_separate(self) -> None:
        case = load_synthetic_case()

        validated = validate_case(case)

        self.assertTrue(validated["synthetic"])
        self.assertIsNot(validated, case)
        self.assertEqual(
            [item["type"] for item in validated["evidence"]],
            ["focus_group_summary", "survey_aggregate"],
        )
        self.assertEqual(validated["evidence"][0]["study_id"], "RB-FICTIONAL-STUDY-01")
        self.assertEqual(validated["evidence"][1]["valid_n"], 68)
        self.assertEqual(validated["evidence"][1]["item_missing_n"], 4)

    def test_missing_required_action_fields_are_reported(self) -> None:
        case = load_synthetic_case()
        case["desired_action"] = {}

        with self.assertRaises(CaseValidationError) as raised:
            validate_case(case)

        for field in ("description", "actor_group", "time_horizon", "observable_success"):
            self.assertIn(f"desired_action.{field}", str(raised.exception))

    def test_empty_evidence_requires_explicit_exploratory_marker(self) -> None:
        case = load_synthetic_case()
        case["evidence"] = []

        with self.assertRaisesRegex(CaseValidationError, "exploratory to true"):
            validate_case(case)

        case["exploratory"] = True
        self.assertEqual(validate_case(case)["evidence"], [])

    def test_duplicate_evidence_ids_are_rejected(self) -> None:
        case = load_synthetic_case()
        case["evidence"][1]["id"] = case["evidence"][0]["id"]

        with self.assertRaisesRegex(CaseValidationError, "must be unique"):
            validate_case(case)

    def test_empty_evidence_id_is_rejected(self) -> None:
        case = load_synthetic_case()
        case["evidence"][0]["id"] = "   "

        with self.assertRaisesRegex(CaseValidationError, r"evidence\[0\]\.id: must be a non-empty string"):
            validate_case(case)

    def test_malformed_focus_group_metadata_and_optional_quote_are_rejected(self) -> None:
        case = load_synthetic_case()
        focus_group = case["evidence"][0]
        del focus_group["moderator_prompt"]
        focus_group["anonymized_quote"] = "  "

        with self.assertRaises(CaseValidationError) as raised:
            validate_case(case)

        self.assertIn("evidence[0].moderator_prompt", str(raised.exception))
        self.assertIn("evidence[0].anonymized_quote", str(raised.exception))

    def test_survey_response_counts_must_sum_to_valid_denominator(self) -> None:
        case = load_synthetic_case()
        case["evidence"][1]["response_counts"]["a_lot"] += 1

        with self.assertRaisesRegex(CaseValidationError, "counts must sum exactly to valid_n"):
            validate_case(case)

    def test_survey_denominator_order_is_enforced(self) -> None:
        case = load_synthetic_case()
        case["evidence"][1]["respondents_invited_n"] = 70

        with self.assertRaisesRegex(CaseValidationError, "cannot exceed respondents_invited_n"):
            validate_case(case)

    def test_survey_item_missingness_must_match_received_minus_valid(self) -> None:
        case = load_synthetic_case()
        case["evidence"][1]["item_missing_n"] = 3

        with self.assertRaisesRegex(CaseValidationError, "must equal responses_received_n minus valid_n"):
            validate_case(case)

    def test_survey_counts_must_be_non_negative_integers_not_booleans(self) -> None:
        for invalid_count in (-1, 1.5, True):
            with self.subTest(invalid_count=invalid_count):
                case = load_synthetic_case()
                case["evidence"][1]["valid_n"] = invalid_count
                with self.assertRaisesRegex(CaseValidationError, "valid_n: must be a non-negative integer"):
                    validate_case(case)

    def test_survey_exact_question_wording_is_required(self) -> None:
        case = load_synthetic_case()
        del case["evidence"][1]["question"]

        with self.assertRaisesRegex(CaseValidationError, r"evidence\[1\]\.question"):
            validate_case(case)

    def test_unsupported_evidence_type_is_rejected(self) -> None:
        case = load_synthetic_case()
        case["evidence"][0]["type"] = "interview_transcript"

        with self.assertRaisesRegex(CaseValidationError, "focus_group_summary.*survey_aggregate"):
            validate_case(case)

    def test_obvious_identifier_and_raw_record_fields_are_rejected_without_echoing_values(self) -> None:
        unsafe_fields = ("name", "email_address", "employee_id", "raw_transcript", "respondent_rows")
        for field in unsafe_fields:
            with self.subTest(field=field):
                case = load_synthetic_case()
                private_value = "private-person@example.invalid"
                case["extra_metadata"] = {field: private_value}

                with self.assertRaises(CaseValidationError) as raised:
                    validate_case(case)

                self.assertIn("not accepted", str(raised.exception))
                self.assertNotIn(private_value, str(raised.exception))

    def test_unicode_text_is_validated_and_preserved(self) -> None:
        case = load_synthetic_case()
        case["desired_action"]["description"] = "Votar en una elección ficticia — 東京の投票所 🗳️"
        case["evidence"][0]["theme"] = "Some fictional vecinos question whether their vote matters; café hours also conflict."

        validated = validate_case(case)

        self.assertEqual(validated["desired_action"]["description"], case["desired_action"]["description"])
        self.assertEqual(validated["evidence"][0]["theme"], case["evidence"][0]["theme"])


if __name__ == "__main__":
    unittest.main()
