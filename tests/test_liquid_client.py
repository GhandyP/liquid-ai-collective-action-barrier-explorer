"""Offline tests for the lazy Liquid client boundary."""

from __future__ import annotations
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.liquid_client import run_live
from src.response_normalizer import NOUL_ANSWERS


RESPONSE_PATH = Path(__file__).resolve().parent / "fixtures" / "system_one_response.json"


def load_response() -> dict:
    with RESPONSE_PATH.open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


class FakeQuestion:
    def __init__(self, kind: str, arguments: dict) -> None:
        self.kind = kind
        self.arguments = arguments


def _question_constructor(kind: str):
    return lambda **arguments: FakeQuestion(kind, arguments)


FAKE_SDK = SimpleNamespace(
    Noul=_question_constructor("Noul"),
    Score=_question_constructor("Score"),
    Choice=_question_constructor("Choice"),
)


class FakeClient:
    def __init__(self, response: object = None, failure: Exception | None = None) -> None:
        self.response = response
        self.failure = failure
        self.calls: list[dict] = []

    def system_one(self, **arguments):
        self.calls.append(arguments)
        if self.failure is not None:
            raise self.failure
        return self.response


class LiquidClientTests(unittest.TestCase):
    def test_injected_client_receives_serialized_state_and_all_question_types(self) -> None:
        case = {
            "case_id": "FICTIONAL-CASE-01",
            "summary": "Síntesis ficticia — 東京",
        }
        client = FakeClient(response=load_response())

        normalized = run_live(
            case,
            client=client,
            sdk_module=FAKE_SDK,
            environ={"D1_MODEL": "offline-test-model"},
        )

        self.assertEqual(normalized["run_status"], "live")
        self.assertEqual(normalized["model"], "offline-test-model")
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["model"], "offline-test-model")
        self.assertEqual(call["state"], json.dumps(case, ensure_ascii=False))
        self.assertIn("東京", call["state"])
        questions = call["questions"]
        self.assertEqual(
            set(questions),
            set(NOUL_ANSWERS) | {"response_efficacy_level", "next_diagnostic_probe"},
        )
        self.assertTrue(all(questions[name].kind == "Noul" for name in NOUL_ANSWERS))
        self.assertEqual(questions["response_efficacy_level"].kind, "Score")
        self.assertEqual(questions["next_diagnostic_probe"].kind, "Choice")
        self.assertIn("values or trade-offs", questions["perception_gap"].arguments["instructions"])
        self.assertIn("coordinate", questions["collective_efficacy_gap"].arguments["instructions"])
        self.assertEqual(
            set(questions["next_diagnostic_probe"].arguments["criteria"]),
            {
                "check_factual_understanding",
                "map_values_and_tradeoffs",
                "test_response_efficacy",
                "check_collective_coordination",
                "audit_practical_constraints",
                "collect_more_evidence",
                "human_review_mixed_case",
            },
        )

    def test_missing_api_key_returns_error_without_loading_sdk(self) -> None:
        with patch("src.liquid_client.importlib.import_module") as import_module:
            result = run_live(
                {"summary": "Fictional aggregate summary"},
                environ={},
            )

        self.assertEqual(result["run_status"], "error")
        self.assertEqual(result["error"]["code"], "missing_configuration")
        self.assertIn("LIQUID_API_KEY", result["error"]["message"])
        self.assertNotIn("mock", result)
        import_module.assert_not_called()

    def test_provider_exception_returns_safe_error_not_mock_data(self) -> None:
        private_marker = "provider-private-detail-marker"
        client = FakeClient(failure=RuntimeError("provider details: " + private_marker))

        result = run_live(
            {"summary": "Fictional aggregate summary"},
            client=client,
            sdk_module=FAKE_SDK,
            environ={},
        )

        self.assertEqual(result["run_status"], "error")
        self.assertEqual(result["error"]["code"], "provider_error")
        self.assertNotIn(private_marker, json.dumps(result))
        self.assertNotIn("mock", result)

    def test_missing_sdk_is_reported_without_importing_it_at_module_load(self) -> None:
        client = FakeClient(response=load_response())
        with patch("src.liquid_client.importlib.import_module", side_effect=ModuleNotFoundError):
            result = run_live(
                {"summary": "Fictional aggregate summary"},
                client=client,
                environ={},
            )

        self.assertEqual(result["run_status"], "error")
        self.assertEqual(result["error"]["code"], "sdk_unavailable")
        self.assertEqual(client.calls, [])

    def test_privacy_rejection_prevents_provider_call_and_does_not_echo_value(self) -> None:
        private_value = "synthetic.contact" + chr(64) + "example.invalid"
        client = FakeClient(response=load_response())

        result = run_live(
            {"notes": "Fictional note for " + private_value},
            client=client,
            sdk_module=FAKE_SDK,
            environ={},
        )

        self.assertEqual(result["run_status"], "error")
        self.assertEqual(result["error"]["code"], "privacy_rejected")
        self.assertNotIn(private_value, json.dumps(result))
        self.assertEqual(client.calls, [])

    def test_malformed_provider_response_is_error_not_mock(self) -> None:
        client = FakeClient(response={"answers": {}})

        result = run_live(
            {"summary": "Fictional aggregate summary"},
            client=client,
            sdk_module=FAKE_SDK,
            environ={},
        )

        self.assertEqual(result["run_status"], "error")
        self.assertEqual(result["error"]["code"], "malformed_response")
        self.assertNotIn("mock", result)


if __name__ == "__main__":
    unittest.main()
