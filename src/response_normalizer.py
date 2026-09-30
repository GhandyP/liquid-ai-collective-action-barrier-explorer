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


def describe_response_shape(result: Any) -> dict[str, Any]:
    """Describe response structure without exposing any field values.

    Names are sorted and bounded at each inspected level. The result contains
    only type names, field names, and truncation markers, so it is suitable for
    bounded diagnostics rather than logging provider payloads.
    """
    try:
        top_names, top_truncated = _shape_names(result, 24)
        descriptor: dict[str, Any] = {
            "type": _shape_type_name(result),
            "keys": _with_truncation_marker(top_names, top_truncated),
        }
        answers = _get(result, "answers")
        if answers is not _MISSING:
            descriptor["answers"] = _describe_answers_shape(answers)
        return descriptor
    except BaseException:
        return {"type": f"uninspectable ({_shape_type_name(result)})"[:200]}


def _describe_answers_shape(answers: Any) -> dict[str, Any]:
    answer_names, answers_truncated = _shape_names(answers, 24)
    items: list[dict[str, Any]] = []
    for name in answer_names:
        answer = _get(answers, name)
        if answer is _MISSING:
            items.append({"key": name, "type": "unavailable", "fields": []})
            continue
        field_names, fields_truncated = _shape_names(answer, 12)
        items.append(
            {
                "key": name,
                "type": _shape_type_name(answer),
                "fields": _with_truncation_marker(field_names, fields_truncated),
            }
        )
    return {
        "type": _shape_type_name(answers),
        "keys": _with_truncation_marker(answer_names, answers_truncated),
        "items": items,
    }


def _shape_names(value: Any, limit: int) -> tuple[list[str], bool]:
    if isinstance(value, Mapping):
        raw_names = value.keys()
    else:
        names: set[str] = set()
        try:
            instance_fields = object.__getattribute__(value, "__dict__")
        except AttributeError:
            instance_fields = None
        if instance_fields is not None and isinstance(instance_fields, Mapping):
            names.update(name for name in instance_fields.keys() if type(name) is str)

        value_type = type(value)
        try:
            hierarchy = type.__getattribute__(value_type, "__mro__")
        except BaseException:
            hierarchy = ()
        for owner in hierarchy:
            try:
                namespace = type.__getattribute__(owner, "__dict__")
            except BaseException:
                continue
            slots = namespace.get("__slots__", ())
            if type(slots) is str:
                slots = (slots,)
            if isinstance(slots, (tuple, list)):
                names.update(name for name in slots if type(name) is str and not name.startswith("__"))
            annotations = namespace.get("__annotations__", {})
            if isinstance(annotations, Mapping):
                names.update(
                    name
                    for name in annotations.keys()
                    if type(name) is str and not name.startswith("__")
                )
            names.update(
                name
                for name, member in namespace.items()
                if type(name) is str and isinstance(member, property)
            )
        raw_names = names

    sorted_names = sorted(
        (name[:120] for name in raw_names if type(name) is str)
    )
    return sorted_names[:limit], len(sorted_names) > limit


def _with_truncation_marker(names: list[str], truncated: bool) -> list[str]:
    return [*names, "..."] if truncated else names


def _shape_type_name(value: Any) -> str:
    try:
        name = type.__getattribute__(type(value), "__name__")
        if type(name) is str and name:
            return name[:120]
    except BaseException:
        pass
    return "unknown"


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
