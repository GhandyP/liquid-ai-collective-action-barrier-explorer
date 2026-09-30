"""Offline tests for the live-request privacy boundary."""

from __future__ import annotations

from copy import deepcopy
import unittest

from src.privacy import PrivacyError, prepare_case_for_request


class PrivacyBoundaryTests(unittest.TestCase):
    def test_safe_input_returns_detached_copy_without_mutating_source(self) -> None:
        case = {
            "case_id": "FICTIONAL-CASE-01",
            "evidence": [{"type": "survey_aggregate", "theme": "Fictional aggregate summary"}],
        }
        before = deepcopy(case)

        prepared = prepare_case_for_request(case)

        self.assertEqual(case, before)
        self.assertEqual(prepared, before)
        self.assertIsNot(prepared, case)
        self.assertIsNot(prepared["evidence"], case["evidence"])

    def test_rejects_identifying_keys_and_respondent_level_records(self) -> None:
        case = {
            "evidence": [
                {
                    "participant_name": "Fictional Person",
                    "employee_id": "synthetic-id-marker",
                }
            ],
            "respondent_records": [{"answer": "fictional response"}],
        }

        with self.assertRaises(PrivacyError) as raised:
            prepare_case_for_request(case)

        message = str(raised.exception)
        self.assertIn("case.evidence[0].participant_name (name)", message)
        self.assertIn("case.evidence[0].employee_id (personal_identifier)", message)
        self.assertIn("case.respondent_records (respondent_level_records)", message)
        self.assertNotIn("Fictional Person", message)
        self.assertNotIn("synthetic-id-marker", message)
        self.assertNotIn("fictional response", message)

    def test_detects_email_in_text_without_echoing_it(self) -> None:
        generated_email = "fictional.contact" + chr(64) + "example.invalid"
        case = {"notes": "For a synthetic case, contact " + generated_email}

        with self.assertRaises(PrivacyError) as raised:
            prepare_case_for_request(case)

        self.assertIn("case.notes (email)", str(raised.exception))
        self.assertNotIn(generated_email, str(raised.exception))

    def test_detects_email_used_as_a_structured_key_without_echoing_it(self) -> None:
        generated_email = "fictional.key" + chr(64) + "example.invalid"
        case = {generated_email: "synthetic value"}

        with self.assertRaises(PrivacyError) as raised:
            prepare_case_for_request(case)

        self.assertIn("case.<field> (email)", str(raised.exception))
        self.assertNotIn(generated_email, str(raised.exception))

    def test_detects_raw_transcript_fields_without_echoing_content(self) -> None:
        transcript_marker = "synthetic-transcript-content-marker"
        case = {"evidence": [{"raw_transcript": transcript_marker}]}

        with self.assertRaises(PrivacyError) as raised:
            prepare_case_for_request(case)

        self.assertIn("case.evidence[0].raw_transcript (raw_content)", str(raised.exception))
        self.assertNotIn(transcript_marker, str(raised.exception))

    def test_detects_phone_address_and_labeled_name_in_text(self) -> None:
        case = {
            "note": "participant: Example Person may be reached via +1 202 555 0144 at 42 Example Street"
        }

        with self.assertRaises(PrivacyError) as raised:
            prepare_case_for_request(case)

        categories = {category for _, category in raised.exception.findings}
        self.assertTrue({"name", "phone", "address"}.issubset(categories))
        self.assertNotIn("Example Person", str(raised.exception))
        self.assertNotIn("202 555 0144", str(raised.exception))

    def test_rejects_respondent_identifier_text_without_echoing_identifier(self) -> None:
        identifier_marker = "synthetic-respondent-77"
        case = {"notes": "respondent ID: " + identifier_marker}

        with self.assertRaises(PrivacyError) as raised:
            prepare_case_for_request(case)

        self.assertIn("personal_identifier", str(raised.exception))
        self.assertNotIn(identifier_marker, str(raised.exception))

    def test_name_like_mapping_key_is_not_echoed_in_error_path(self) -> None:
        generated_email = "fictional.nested" + chr(64) + "example.invalid"
        case = {"Fictional Person": {"email_address": generated_email}}

        with self.assertRaises(PrivacyError) as raised:
            prepare_case_for_request(case)

        self.assertIn("case.<field>.email_address (email)", str(raised.exception))
        self.assertNotIn("Fictional Person", str(raised.exception))
        self.assertNotIn(generated_email, str(raised.exception))

    def test_unusual_field_names_are_sanitized_in_error_paths(self) -> None:
        case = {"fictional person key": "name: Example Person"}

        with self.assertRaises(PrivacyError) as raised:
            prepare_case_for_request(case)

        self.assertIn("case.<field> (name)", str(raised.exception))
        self.assertNotIn("fictional person key", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
