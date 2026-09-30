"""Offline tests for Streamlit-independent app orchestration."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.app_state import (
    AppStateError,
    HumanReviewValidationError,
    load_curated_case,
    load_synthetic_case,
    mock_result,
    record_human_review,
    run_case,
)
from src.response_normalizer import NOUL_ANSWERS


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "synthetic_cases.json"
CURATED_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "curated_cases.json"


class FakeQuestion:
    def __init__(self, **kwargs):
        self.options = kwargs


class FakeClient:
    def __init__(self, response=None, failure=None):
        self.response = response or {"answers": {}}
        self.failure = failure
        self.calls = 0

    def system_one(self, **kwargs):
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.response


def fake_sdk():
    return SimpleNamespace(Noul=FakeQuestion, Score=FakeQuestion, Choice=FakeQuestion)


def live_response():
    probabilities = {
        "perception_gap": 0.1,
        "values_conflict": 0.2,
        "response_efficacy_gap": 0.75,
        "collective_efficacy_gap": 0.3,
        "structural_barrier": 0.68,
        "insufficient_evidence": 0.1,
    }
    answers = {
        name: {"probability": probability}
        for name, probability in probabilities.items()
    }
    answers["response_efficacy_level"] = {"score": 2.0, "probabilities": {"2": 1.0}}
    answers["next_diagnostic_probe"] = {
        "choice": "audit_practical_constraints",
        "confidence": 0.7,
    }
    return {"answers": answers}


class AppStateTests(unittest.TestCase):
    def test_fixture_loading_returns_detached_case_without_mutating_fixture(self) -> None:
        fixture_before = FIXTURE_PATH.read_text(encoding="utf-8")
        first = load_synthetic_case()
        original_action = first["desired_action"]["description"]
        first["desired_action"]["description"] = "edited only in this returned object"
        first["evidence"][0]["limitations"].append("local test change")

        second = load_synthetic_case()

        self.assertEqual(second["desired_action"]["description"], original_action)
        self.assertNotIn("local test change", second["evidence"][0]["limitations"])
        self.assertEqual(FIXTURE_PATH.read_text(encoding="utf-8"), fixture_before)

    def test_curated_fixture_loading_returns_detached_case_without_mutating_fixture(self) -> None:
        fixture_before = CURATED_FIXTURE_PATH.read_text(encoding="utf-8")
        first = load_curated_case()
        self.assertTrue(first["curated"])
        self.assertFalse(first["synthetic"])
        original_theme = first["evidence"][0]["theme"]
        first["evidence"][0]["limitations"].append("local test change")
        first["evidence"][1]["response_percentages"]["Other"] = 99

        second = load_curated_case()

        self.assertEqual(second["evidence"][0]["theme"], original_theme)
        self.assertNotIn("local test change", second["evidence"][0]["limitations"])
        self.assertEqual(second["evidence"][1]["response_percentages"]["Other"], 6)
        self.assertEqual(CURATED_FIXTURE_PATH.read_text(encoding="utf-8"), fixture_before)

    def test_curated_fixture_loader_requires_one_curated_non_synthetic_valid_case(self) -> None:
        invalid_fixtures = (
            ([], "exactly one case"),
            ([{"curated": True, "synthetic": True}], "explicitly curated, non-synthetic"),
            ([{"curated": False, "synthetic": False}], "explicitly curated, non-synthetic"),
            (
                [
                    {"curated": True, "synthetic": False},
                    {"curated": True, "synthetic": False},
                ],
                "exactly one case",
            ),
            ([{"curated": True, "synthetic": False}], "did not pass validation"),
        )
        for cases, message in invalid_fixtures:
            with self.subTest(message=message, case_count=len(cases)):
                with patch("src.app_state._CURATED_FIXTURE_PATH") as fixture_path:
                    fixture_path.open.return_value = StringIO(json.dumps(cases))
                    with self.assertRaisesRegex(AppStateError, message):
                        load_curated_case()

    def test_mock_execution_works_without_live_credentials_or_adapter_call(self) -> None:
        case = load_synthetic_case()
        with patch("src.app_state.run_live", side_effect=AssertionError("live called")) as live:
            state = run_case(case, "mock")

        live.assert_not_called()
        self.assertEqual(state["run_status"], "mock")
        self.assertEqual(state["run_mode"], "mock")
        self.assertIsNone(state["error"])
        self.assertEqual(set(state["result"]["hypotheses"]), set(NOUL_ANSWERS))
        self.assertEqual(state["result"]["run_status"], "mock")
        self.assertIn("response_efficacy_level", state["result"])
        self.assertIn("next_diagnostic_probe", state["result"])
        self.assertEqual(json.loads(json.dumps(state)), state)

    def test_curated_case_runs_in_mock_mode_without_live_credentials_or_adapter_call(self) -> None:
        case = load_curated_case()
        with patch("src.app_state.run_live", side_effect=AssertionError("live called")) as live:
            state = run_case(case, "mock")

        live.assert_not_called()
        self.assertEqual(state["run_status"], "mock")
        self.assertEqual(state["run_mode"], "mock")
        self.assertIsNone(state["error"])
        self.assertEqual(state["result"]["run_status"], "mock")
        self.assertEqual(set(state["result"]["hypotheses"]), set(NOUL_ANSWERS))

    def test_mock_result_is_fresh_and_probabilities_remain_independent(self) -> None:
        first = mock_result()
        first["hypotheses"]["perception_gap"]["probability"] = 0.99
        second = mock_result()

        self.assertEqual(second["hypotheses"]["perception_gap"]["probability"], 0.18)
        self.assertGreater(
            sum(answer["probability"] for answer in second["hypotheses"].values()),
            1.0,
        )

    def test_mock_run_passes_evidence_to_triage_and_displays_mixed_result(self) -> None:
        state = run_case(load_synthetic_case(), "mock")

        self.assertEqual(state["triage"]["status"], "mixed")
        self.assertEqual(
            state["triage"]["hypotheses"],
            ["response_efficacy_gap", "structural_barrier"],
        )
        self.assertTrue(state["triage"]["human_review_required"])

    def test_live_mode_uses_injected_client_and_normalizes_live_response(self) -> None:
        client = FakeClient(response=live_response())

        state = run_case(
            load_synthetic_case(),
            "live",
            live_client=client,
            live_sdk_module=fake_sdk(),
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(state["run_status"], "live")
        self.assertEqual(state["result"]["run_status"], "live")
        self.assertEqual(state["triage"]["status"], "mixed")
        self.assertEqual(
            state["result"]["next_diagnostic_probe"]["choice"],
            "audit_practical_constraints",
        )

    def test_curated_case_uses_injected_live_client_without_mock_fallback(self) -> None:
        client = FakeClient(response=live_response())

        state = run_case(
            load_curated_case(),
            "live",
            live_client=client,
            live_sdk_module=fake_sdk(),
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(state["run_status"], "live")
        self.assertEqual(state["run_mode"], "live")
        self.assertEqual(state["result"]["run_status"], "live")
        self.assertEqual(state["triage"]["status"], "mixed")
        self.assertNotEqual(state.get("result"), mock_result())

    def test_live_failure_remains_error_without_echo_or_mock_fallback(self) -> None:
        secret_marker = "sk-test-very-secret-value-123456"
        client = FakeClient(failure=RuntimeError(secret_marker))

        state = run_case(
            load_synthetic_case(),
            "live",
            live_client=client,
            live_sdk_module=fake_sdk(),
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(state["run_status"], "error")
        self.assertEqual(state["error"]["code"], "provider_error")
        self.assertIsNone(state["result"])
        self.assertEqual(state["triage"]["status"], "unavailable")
        self.assertNotIn(secret_marker, json.dumps(state))
        self.assertNotEqual(state.get("result"), mock_result())

    def test_mock_mode_never_uses_an_injected_live_client(self) -> None:
        client = FakeClient(response=live_response())

        state = run_case(
            load_synthetic_case(),
            "mock",
            live_client=client,
            live_sdk_module=fake_sdk(),
        )

        self.assertEqual(client.calls, 0)
        self.assertEqual(state["run_status"], "mock")

    def test_invalid_case_returns_bounded_error_state(self) -> None:
        case = load_synthetic_case()
        case["desired_action"]["description"] = ""
        case["private_marker"] = "should not appear in error state"

        state = run_case(case, "mock")

        self.assertEqual(state["run_status"], "error")
        self.assertEqual(state["error"]["code"], "invalid_case")
        self.assertNotIn("should not appear", json.dumps(state))
        self.assertIsNone(state["result"])

    def test_human_review_records_valid_decisions_with_trimmed_reason(self) -> None:
        review = record_human_review("confirmed", "  Reviewed the mixed profile with the facilitator.  ")

        self.assertEqual(
            review,
            {
                "status": "confirmed",
                "override_reason": "Reviewed the mixed profile with the facilitator.",
            },
        )
        self.assertEqual(
            record_human_review("pending"),
            {"status": "pending", "override_reason": None},
        )

    def test_human_review_rejects_invalid_decision_missing_reason_and_long_reason(self) -> None:
        for decision, reason in (
            ("approve", "Reason provided"),
            ("confirmed", "   "),
            ("rejected", "x" * 241),
        ):
            with self.subTest(decision=decision, reason_length=len(reason)):
                with self.assertRaises(HumanReviewValidationError):
                    record_human_review(decision, reason)

    def test_human_review_rejects_credential_like_reason_without_echoing_it(self) -> None:
        secret_reason = "The live key was LIQUID_API_KEY=secret-marker-123"

        with self.assertRaises(HumanReviewValidationError) as raised:
            record_human_review("corrected", secret_reason)

        self.assertNotIn("secret-marker-123", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
