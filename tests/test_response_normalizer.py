"""Offline tests for the bounded Liquid response normalizer."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from src.response_normalizer import (
    NOUL_ANSWERS,
    ResponseNormalizationError,
    describe_response_shape,
    normalize_response,
)


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "system_one_response.json"


def load_response() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


class ResponseNormalizerTests(unittest.TestCase):
    def test_normalizes_complete_noul_score_and_choice_response(self) -> None:
        normalized = normalize_response(load_response(), model="d1:free")

        self.assertEqual(normalized["run_status"], "live")
        self.assertEqual(normalized["taxonomy_version"], "0.1")
        self.assertEqual(set(normalized["hypotheses"]), set(NOUL_ANSWERS))
        self.assertEqual(normalized["hypotheses"]["perception_gap"]["probability"], 0.78)
        self.assertGreater(
            sum(item["probability"] for item in normalized["hypotheses"].values()),
            1.0,
        )
        self.assertEqual(normalized["response_efficacy_level"]["score"], 2.3)
        self.assertEqual(normalized["response_efficacy_level"]["probabilities"]["2"], 0.42)
        self.assertEqual(
            normalized["next_diagnostic_probe"]["choice"],
            "audit_practical_constraints",
        )
        self.assertEqual(normalized["next_diagnostic_probe"]["confidence"], 0.47)
        self.assertEqual(normalized["human_review"], {"status": "pending", "override_reason": None})
        self.assertNotIn("rationale", normalized)

    def test_supports_attribute_style_results_and_answers(self) -> None:
        fixture_answers = load_response()["answers"]
        answer_objects = {
            name: SimpleNamespace(probability=fixture_answers[name]["probability"])
            for name in NOUL_ANSWERS
        }
        answer_objects["response_efficacy_level"] = SimpleNamespace(
            score=1.5,
            probabilities={"low": 0.4, "high": 0.6},
        )
        answer_objects["next_diagnostic_probe"] = SimpleNamespace(
            choice="collect_more_evidence",
            probabilities={"collect_more_evidence": 0.7, "human_review_mixed_case": 0.3},
            confidence=0.7,
        )

        normalized = normalize_response(
            SimpleNamespace(answers=SimpleNamespace(**answer_objects)),
            model="injected-model",
            taxonomy_version="test-taxonomy",
        )

        self.assertEqual(normalized["model"], "injected-model")
        self.assertEqual(normalized["taxonomy_version"], "test-taxonomy")
        self.assertEqual(normalized["response_efficacy_level"]["score"], 1.5)
        self.assertEqual(normalized["next_diagnostic_probe"]["choice"], "collect_more_evidence")
        self.assertEqual(normalized["next_diagnostic_probe"]["probabilities"]["collect_more_evidence"], 0.7)

    def test_describes_mapping_shape_without_exposing_values(self) -> None:
        response = {
            "metadata": "private-marker-top-level",
            "answers": {
                "values_conflict": {
                    "probability": 0.45,
                    "rationale": "private-marker-answer-value",
                },
                "attribute_answer": SimpleNamespace(
                    field_name="private-marker-attribute-value"
                ),
            },
        }

        shape = describe_response_shape(response)
        rendered = json.dumps(shape)

        self.assertEqual(shape["type"], "dict")
        self.assertIn("metadata", shape["keys"])
        self.assertEqual(shape["answers"]["type"], "dict")
        self.assertIn("values_conflict", shape["answers"]["keys"])
        values_answer = next(
            item for item in shape["answers"]["items"] if item["key"] == "values_conflict"
        )
        self.assertEqual(values_answer["fields"], ["probability", "rationale"])
        self.assertIn("field_name", rendered)
        self.assertNotIn("private-marker", rendered)
        self.assertNotIn("0.45", rendered)

    def test_describes_attribute_style_shape_without_exposing_values(self) -> None:
        response = SimpleNamespace(
            request_id="private-marker-request",
            answers=SimpleNamespace(
                values_conflict=SimpleNamespace(
                    probability="private-marker-probability",
                    rationale="private-marker-rationale",
                )
            ),
        )

        shape = describe_response_shape(response)
        rendered = json.dumps(shape)

        self.assertEqual(shape["type"], "SimpleNamespace")
        self.assertIn("request_id", shape["keys"])
        self.assertIn("values_conflict", shape["answers"]["keys"])
        self.assertEqual(
            shape["answers"]["items"][0]["fields"], ["probability", "rationale"]
        )
        self.assertNotIn("private-marker", rendered)

    def test_shape_descriptor_bounds_names_and_each_string(self) -> None:
        response = {
            **{f"top_{index:02}": "private-marker" for index in range(30)},
            "answers": {
                f"answer_{index:02}": {
                    f"field_{field_index:02}": "private-marker"
                    for field_index in range(20)
                }
                for index in range(30)
            },
        }

        shape = describe_response_shape(response)

        self.assertEqual(len(shape["keys"]), 25)
        self.assertEqual(shape["keys"][-1], "...")
        self.assertEqual(len(shape["answers"]["keys"]), 25)
        self.assertEqual(shape["answers"]["keys"][-1], "...")
        self.assertEqual(len(shape["answers"]["items"]), 24)
        self.assertEqual(len(shape["answers"]["items"][0]["fields"]), 13)
        self.assertEqual(shape["answers"]["items"][0]["fields"][-1], "...")

        def assert_bounded_strings(value) -> None:
            if isinstance(value, str):
                self.assertLessEqual(len(value), 200)
            elif isinstance(value, dict):
                for key, item in value.items():
                    assert_bounded_strings(key)
                    assert_bounded_strings(item)
            elif isinstance(value, list):
                for item in value:
                    assert_bounded_strings(item)

        assert_bounded_strings(shape)
        self.assertNotIn("private-marker", json.dumps(shape))

    def test_shape_descriptor_never_raises_for_uninspectable_objects(self) -> None:
        class Uninspectable:
            @property
            def __dict__(self):
                raise RuntimeError("private-marker-property-error")

        shape = describe_response_shape(Uninspectable())

        self.assertIn("uninspectable (Uninspectable)", shape["type"])
        self.assertNotIn("private-marker", json.dumps(shape))

    def test_normalizes_attribute_style_noul_probabilities(self) -> None:
        probability_values = {
            name: (index + 1) / 10 for index, name in enumerate(NOUL_ANSWERS)
        }
        answer_objects = {
            name: SimpleNamespace(noul=probability)
            for name, probability in probability_values.items()
        }

        normalized = normalize_response(
            SimpleNamespace(answers=SimpleNamespace(**answer_objects))
        )

        self.assertEqual(
            {
                name: normalized["hypotheses"][name]["probability"]
                for name in NOUL_ANSWERS
            },
            probability_values,
        )
        self.assertEqual(
            set(normalized["hypotheses"]["perception_gap"]), {"probability"}
        )
        self.assertGreater(
            sum(item["probability"] for item in normalized["hypotheses"].values()),
            1.0,
        )

    def test_optional_score_and_choice_are_omitted_when_absent(self) -> None:
        fixture = load_response()
        del fixture["answers"]["response_efficacy_level"]
        del fixture["answers"]["next_diagnostic_probe"]

        normalized = normalize_response(fixture)

        self.assertNotIn("response_efficacy_level", normalized)
        self.assertNotIn("next_diagnostic_probe", normalized)

    def test_missing_required_answer_has_bounded_error(self) -> None:
        fixture = load_response()
        del fixture["answers"]["values_conflict"]

        with self.assertRaises(ResponseNormalizationError) as raised:
            normalize_response(fixture)

        self.assertIn("answers.values_conflict", str(raised.exception))
        self.assertNotIn("probability", str(raised.exception))

    def test_invalid_probability_is_rejected_without_echoing_raw_value(self) -> None:
        fixture = load_response()
        fixture["answers"]["perception_gap"]["probability"] = "private-marker-not-a-number"

        with self.assertRaises(ResponseNormalizationError) as raised:
            normalize_response(fixture)

        self.assertIn("answers.perception_gap.probability", str(raised.exception))
        self.assertNotIn("private-marker-not-a-number", str(raised.exception))

    def test_probability_bounds_and_boolean_values_are_enforced(self) -> None:
        for invalid_probability in (-0.01, 1.01, True, float("inf")):
            with self.subTest(invalid_probability=type(invalid_probability).__name__):
                fixture = load_response()
                fixture["answers"]["structural_barrier"]["probability"] = invalid_probability
                with self.assertRaisesRegex(ResponseNormalizationError, r"\[0, 1\]"):
                    normalize_response(fixture)

    def test_malformed_optional_score_is_rejected_without_echoing_value(self) -> None:
        fixture = load_response()
        fixture["answers"]["response_efficacy_level"]["score"] = "private-score-marker"

        with self.assertRaises(ResponseNormalizationError) as raised:
            normalize_response(fixture)

        self.assertIn("answers.response_efficacy_level.score", str(raised.exception))
        self.assertNotIn("private-score-marker", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
