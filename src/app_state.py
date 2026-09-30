"""Streamlit-independent orchestration for the local D1 prototype."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
import math
from pathlib import Path
import re
from typing import Any

from src.case_schema import CaseValidationError, validate_case
from src.liquid_client import run_live
from src.response_normalizer import NOUL_ANSWERS, TAXONOMY_VERSION
from src.triage_policy import triage_result


_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "synthetic_cases.json"
_MOCK_RESULT: dict[str, Any] = {
    "run_status": "mock",
    "model": "local-illustrative-mock",
    "taxonomy_version": TAXONOMY_VERSION,
    "hypotheses": {
        "perception_gap": {"probability": 0.18},
        "values_conflict": {"probability": 0.22},
        "response_efficacy_gap": {"probability": 0.74},
        "collective_efficacy_gap": {"probability": 0.51},
        "structural_barrier": {"probability": 0.68},
        "insufficient_evidence": {"probability": 0.14},
    },
    "response_efficacy_level": {
        "score": 2.1,
        "probabilities": {"0": 0.04, "1": 0.16, "2": 0.48, "3": 0.32},
    },
    "next_diagnostic_probe": {
        "choice": "human_review_mixed_case",
        "confidence": 0.58,
    },
    "human_review": {"status": "pending", "override_reason": None},
}

_REQUIRED_PROBES = frozenset(
    {
        "check_factual_understanding",
        "map_values_and_tradeoffs",
        "test_response_efficacy",
        "check_collective_coordination",
        "audit_practical_constraints",
        "collect_more_evidence",
        "human_review_mixed_case",
    }
)
_SAFE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,79}\Z")
_SECRET_LIKE = re.compile(
    r"(?i)(?:\b(?:liquid[_ -]?api[_ -]?key|api[_ -]?key|access[_ -]?token|client[_ -]?secret|password|authorization)\b\s*[:=]\s*\S+"
    r"|\bbearer\s+\S+|\bsk-[A-Za-z0-9_-]{12,}\b|\b(?:ghp|github_pat|hf|glpat)-[A-Za-z0-9_-]{16,}\b)"
)
_REVIEW_DECISIONS = frozenset({"pending", "confirmed", "corrected", "rejected"})
_MAX_REASON_LENGTH = 240


class AppStateError(RuntimeError):
    """The local synthetic fixture could not be safely loaded."""


class HumanReviewValidationError(ValueError):
    """A human review decision or reason did not meet the bounded contract."""


def load_synthetic_case() -> dict[str, Any]:
    """Load and validate the sole fictional fixture as a detached case object."""
    try:
        with _FIXTURE_PATH.open(encoding="utf-8") as fixture_file:
            cases = json.load(fixture_file)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise AppStateError("The synthetic case fixture could not be loaded.") from None

    if not isinstance(cases, list) or len(cases) != 1:
        raise AppStateError("The synthetic fixture must contain exactly one case.")
    case = cases[0]
    if not isinstance(case, Mapping) or case.get("synthetic") is not True:
        raise AppStateError("The fixture must contain one explicitly fictional case.")
    try:
        return validate_case(case)
    except CaseValidationError:
        raise AppStateError("The synthetic case fixture did not pass validation.") from None


def mock_result() -> dict[str, Any]:
    """Return a fresh deterministic normalized mock with six independent scores."""
    return deepcopy(_MOCK_RESULT)


def run_case(
    case: Mapping[str, Any],
    run_mode: str,
    *,
    live_client: Any = None,
    live_sdk_module: Any = None,
) -> dict[str, Any]:
    """Validate and execute exactly the explicitly selected mock or live mode.

    Live adapter failures remain bounded errors and are never replaced with a
    mock result. The optional client and SDK module are for offline injection.
    The returned object contains no submitted case text or raw exception.
    """
    if not isinstance(run_mode, str) or run_mode not in {"mock", "live"}:
        return _error_state("error", "invalid_mode", "Choose mock or live mode.", False)

    try:
        validated_case = validate_case(case)
    except CaseValidationError:
        return _error_state(run_mode, "invalid_case", "The case did not pass validation.", False)
    except Exception:
        return _error_state(run_mode, "invalid_case", "The case did not pass validation.", False)

    usable_evidence = bool(validated_case.get("evidence"))
    if run_mode == "mock":
        normalized = mock_result()
    else:
        live_kwargs: dict[str, Any] = {}
        if live_client is not None:
            live_kwargs["client"] = live_client
        if live_sdk_module is not None:
            live_kwargs["sdk_module"] = live_sdk_module
        try:
            live_response = run_live(validated_case, **live_kwargs)
        except Exception:
            return _error_state(
                run_mode,
                "provider_error",
                _LIVE_ERROR_MESSAGES["provider_error"],
                usable_evidence,
            )
        if not isinstance(live_response, Mapping) or live_response.get("run_status") != "live":
            code = _known_live_error_code(live_response)
            return _error_state(run_mode, code, _LIVE_ERROR_MESSAGES[code], usable_evidence)
        normalized = live_response

    try:
        bounded_result = _bound_normalized_result(normalized, run_mode)
        triage = triage_result(bounded_result, usable_evidence=usable_evidence)
    except Exception:
        code = "malformed_response" if run_mode == "live" else "mock_result_invalid"
        message = _LIVE_ERROR_MESSAGES.get(code, "The local mock result was unavailable.")
        return _error_state(run_mode, code, message, usable_evidence)

    return {
        "run_status": run_mode,
        "run_mode": run_mode,
        "result": bounded_result,
        "triage": triage,
        "error": None,
    }


def record_human_review(decision: str, reason: str = "") -> dict[str, str | None]:
    """Validate and return a bounded in-memory human review record.

    Invalid input messages never include the supplied reason. Credential-like
    text is rejected so it cannot be echoed by the result display.
    """
    if not isinstance(decision, str) or decision not in _REVIEW_DECISIONS:
        raise HumanReviewValidationError(
            "Decision must be pending, confirmed, corrected, or rejected."
        )
    if not isinstance(reason, str):
        raise HumanReviewValidationError("Enter a short text reason for the review.")

    trimmed_reason = reason.strip()
    if len(trimmed_reason) > _MAX_REASON_LENGTH:
        raise HumanReviewValidationError("Review reason must be 240 characters or fewer.")
    if _SECRET_LIKE.search(trimmed_reason):
        raise HumanReviewValidationError("Review reason appears to contain credential-like text.")
    if decision != "pending" and not trimmed_reason:
        raise HumanReviewValidationError("A short reason is required for a completed review.")
    if any(ord(character) < 32 and character not in "\t\n" for character in trimmed_reason):
        raise HumanReviewValidationError("Review reason contains unsupported control characters.")

    return {
        "status": decision,
        "override_reason": trimmed_reason or None,
    }


_LIVE_ERROR_MESSAGES = {
    "invalid_case": "The case did not pass validation.",
    "invalid_mode": "Choose mock or live mode.",
    "missing_configuration": "LIQUID_API_KEY is required for live mode.",
    "privacy_rejected": "The live request was rejected by the privacy checks.",
    "privacy_check_failed": "The live privacy check could not complete.",
    "sdk_unavailable": "The Liquid SDK is unavailable for live mode.",
    "sdk_incompatible": "The Liquid SDK could not prepare the live request.",
    "client_unavailable": "The Liquid client could not be constructed.",
    "provider_error": "The live request failed; no mock result was substituted.",
    "malformed_response": "The live response could not be safely normalized.",
    "mock_result_invalid": "The local mock result was unavailable.",
}


def _known_live_error_code(response: Any) -> str:
    if isinstance(response, Mapping):
        error = response.get("error")
        if isinstance(error, Mapping):
            code = error.get("code")
            if isinstance(code, str) and code in _LIVE_ERROR_MESSAGES:
                return code
    return "provider_error"


def _error_state(
    run_mode: str,
    code: str,
    message: str,
    usable_evidence: bool,
) -> dict[str, Any]:
    error_code = code if code in _LIVE_ERROR_MESSAGES else "provider_error"
    bounded_message = _LIVE_ERROR_MESSAGES.get(error_code, message)[:160]
    return {
        "run_status": "error",
        "run_mode": run_mode,
        "result": None,
        "triage": triage_result({"run_status": "error"}, usable_evidence=usable_evidence),
        "error": {"code": error_code, "message": bounded_message},
    }


def _bound_normalized_result(value: Any, expected_mode: str) -> dict[str, Any]:
    """Keep only known, finite decision fields in the public app-state shape."""
    if not isinstance(value, Mapping) or value.get("run_status") != expected_mode:
        raise ValueError("normalized result has an unexpected status")
    raw_hypotheses = value.get("hypotheses")
    if not isinstance(raw_hypotheses, Mapping):
        raise ValueError("normalized hypotheses are missing")

    hypotheses: dict[str, dict[str, float]] = {}
    for name in NOUL_ANSWERS:
        answer = raw_hypotheses.get(name)
        if not isinstance(answer, Mapping):
            raise ValueError("normalized hypothesis is missing")
        hypotheses[name] = {"probability": _bounded_number(answer.get("probability"), 0.0, 1.0)}

    model = value.get("model")
    safe_model = (
        model
        if isinstance(model, str) and len(model) <= 80 and _SAFE_MODEL.fullmatch(model)
        else "configured-live-model"
    )
    if expected_mode == "mock":
        safe_model = "local-illustrative-mock"

    normalized: dict[str, Any] = {
        "run_status": expected_mode,
        "model": safe_model,
        "taxonomy_version": TAXONOMY_VERSION,
        "hypotheses": hypotheses,
    }

    raw_score = value.get("response_efficacy_level")
    if raw_score is not None:
        if not isinstance(raw_score, Mapping):
            raise ValueError("normalized Score is malformed")
        normalized["response_efficacy_level"] = {
            "score": _bounded_number(raw_score.get("score"), 0.0, 3.0)
        }

    raw_choice = value.get("next_diagnostic_probe")
    if raw_choice is not None:
        if not isinstance(raw_choice, Mapping):
            raise ValueError("normalized Choice is malformed")
        choice = raw_choice.get("choice")
        if not isinstance(choice, str) or choice not in _REQUIRED_PROBES:
            raise ValueError("normalized Choice is not in the bounded probe set")
        normalized["next_diagnostic_probe"] = {"choice": choice}
        confidence = raw_choice.get("confidence")
        if confidence is not None:
            normalized["next_diagnostic_probe"]["confidence"] = _bounded_number(
                confidence, 0.0, 1.0
            )

    normalized["human_review"] = {"status": "pending", "override_reason": None}
    # All returned fields are bounded primitives, and this rejects non-JSON numbers.
    json.dumps(normalized, allow_nan=False)
    return normalized


def _bounded_number(value: Any, minimum: float, maximum: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("normalized numeric answer is malformed")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError("normalized numeric answer is outside its range")
    return number
