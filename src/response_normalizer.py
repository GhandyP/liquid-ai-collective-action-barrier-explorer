"""Normalize the documented ``result.answers`` shape without fabricating text."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any


TAXONOMY_VERSION = "0.1"
NOUL_ANSWERS = (
    "perception_gap",
    "values_conflict",
    "response_efficacy_gap",
    "collective_efficacy_gap",
    "structural_barrier",
    "insufficient_evidence",
)
_MISSING = object()


class ResponseNormalizationError(ValueError):
    """An SDK response is missing a required answer or has an invalid shape."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Response normalization failed at {path}: {reason}")


def normalize_response(
    result: Any,
    model: str = "d1:free",
    taxonomy_version: str = TAXONOMY_VERSION,
) -> dict[str, Any]:
    """Normalize mapping- or attribute-style SDK results to the local contract.

    Noul probabilities remain independent; no sum-to-one normalization or
    rationale is added. Score and Choice outputs are included only when their
    corresponding optional answers are present.
    """
    answers = _get(result, "answers")
    if answers is _MISSING or answers is None:
        raise ResponseNormalizationError("answers", "required object is missing")

    hypotheses: dict[str, dict[str, float]] = {}
    for name in NOUL_ANSWERS:
        path = f"answers.{name}"
        answer = _get(answers, name)
        if answer is _MISSING or answer is None:
            raise ResponseNormalizationError(path, "required Noul answer is missing")
        probability_value = answer if _is_numeric(answer) else _get(answer, "probability")
        if probability_value is _MISSING:
            probability_value = _get(answer, "noul")
        if probability_value is _MISSING:
            raise ResponseNormalizationError(f"{path}.probability", "required probability is missing")
        hypotheses[name] = {
            "probability": _number_in_range(probability_value, f"{path}.probability", 0.0, 1.0)
        }

    normalized: dict[str, Any] = {
        "run_status": "live",
        "model": model,
        "taxonomy_version": taxonomy_version,
        "hypotheses": hypotheses,
    }

    score_answer = _get(answers, "response_efficacy_level")
    if score_answer is not _MISSING:
        normalized["response_efficacy_level"] = _normalize_score(
            score_answer, "answers.response_efficacy_level"
        )

    choice_answer = _get(answers, "next_diagnostic_probe")
    if choice_answer is not _MISSING:
        normalized["next_diagnostic_probe"] = _normalize_choice(
            choice_answer, "answers.next_diagnostic_probe"
        )

    normalized["human_review"] = {"status": "pending", "override_reason": None}
    return normalized


def _normalize_score(answer: Any, path: str) -> dict[str, Any]:
    score_value = answer if _is_numeric(answer) else _get(answer, "score")
    if score_value is _MISSING:
        raise ResponseNormalizationError(f"{path}.score", "required Score value is missing")

    probabilities_value = _get(answer, "probabilities")
    probabilities = (
        {} if probabilities_value is _MISSING else _normalize_probabilities(probabilities_value, f"{path}.probabilities")
    )
    return {
        "score": _number_in_range(score_value, f"{path}.score", 0.0, 3.0),
        "probabilities": probabilities,
    }


def _normalize_choice(answer: Any, path: str) -> dict[str, Any]:
    choice_value = answer if isinstance(answer, str) else _get(answer, "choice")
    normalized: dict[str, Any] = {}

    if choice_value is not _MISSING:
        if not isinstance(choice_value, str) or not choice_value.strip() or len(choice_value) > 160:
            raise ResponseNormalizationError(f"{path}.choice", "must be a non-empty bounded string")
        normalized["choice"] = choice_value

    probabilities_value = _get(answer, "probabilities")
    if probabilities_value is not _MISSING:
        normalized["probabilities"] = _normalize_probabilities(
            probabilities_value, f"{path}.probabilities"
        )

    confidence_value = _get(answer, "confidence")
    if confidence_value is not _MISSING:
        normalized["confidence"] = _number_in_range(
            confidence_value, f"{path}.confidence", 0.0, 1.0
        )

    if not normalized:
        raise ResponseNormalizationError(path, "Choice answer has no supported fields")
    return normalized


def _normalize_probabilities(value: Any, path: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ResponseNormalizationError(path, "must be an object of probabilities")

    normalized: dict[str, float] = {}
    for label, probability in value.items():
        if not isinstance(label, str) or not label:
            raise ResponseNormalizationError(path, "probability labels must be non-empty strings")
        normalized[label] = _number_in_range(probability, path, 0.0, 1.0)
    return normalized


def _number_in_range(value: Any, path: str, minimum: float, maximum: float) -> float:
    if not _is_numeric(value):
        raise ResponseNormalizationError(path, f"must be a finite number in [{minimum:g}, {maximum:g}]")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        raise ResponseNormalizationError(path, f"must be a finite number in [{minimum:g}, {maximum:g}]") from None
    if not math.isfinite(number) or number < minimum or number > maximum:
        raise ResponseNormalizationError(path, f"must be a finite number in [{minimum:g}, {maximum:g}]")
    return number


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _get(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        try:
            return value[key] if key in value else _MISSING
        except Exception:
            return _MISSING
    try:
        return getattr(value, key)
    except Exception:
        return _MISSING
