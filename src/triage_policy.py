"""Deterministic local triage for normalized, independent Noul probabilities.

The default cutoffs are illustrative and have not been validated against a
representative labeled evaluation set. They can be overridden per call.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any


# Illustrative defaults only; they are not provider-validated or empirically tuned.
DEFAULT_LOW_THRESHOLD = 0.35
DEFAULT_HIGH_THRESHOLD = 0.65

BARRIER_HYPOTHESES = (
    "perception_gap",
    "values_conflict",
    "response_efficacy_gap",
    "collective_efficacy_gap",
    "structural_barrier",
)
INSUFFICIENT_EVIDENCE = "insufficient_evidence"
ALL_HYPOTHESES = (*BARRIER_HYPOTHESES, INSUFFICIENT_EVIDENCE)


def triage_result(
    normalized_result: Any,
    usable_evidence: bool,
    *,
    low_threshold: float = DEFAULT_LOW_THRESHOLD,
    high_threshold: float = DEFAULT_HIGH_THRESHOLD,
) -> dict[str, Any]:
    """Return a JSON-friendly local policy result without changing probabilities.

    A valid normalized result must have ``run_status`` of ``live`` or ``mock``
    and all six Noul probabilities in ``hypotheses``. Errors and malformed
    results fail closed as ``unavailable`` with no displayed hypotheses.
    """
    low = _validate_threshold("low_threshold", low_threshold)
    high = _validate_threshold("high_threshold", high_threshold)
    if low >= high:
        raise ValueError("low_threshold must be less than high_threshold")

    profile = _extract_profile(normalized_result)
    if profile is None or not isinstance(usable_evidence, bool):
        return _triage_payload(
            status="unavailable",
            low=low,
            high=high,
            profile={},
            hypotheses=[],
            request_more_evidence=False,
        )

    if not usable_evidence or profile[INSUFFICIENT_EVIDENCE] >= high:
        return _triage_payload(
            status="insufficient",
            low=low,
            high=high,
            profile=profile,
            hypotheses=[],
            request_more_evidence=True,
        )

    high_hypotheses = [
        name for name in BARRIER_HYPOTHESES if profile[name] >= high
    ]
    if len(high_hypotheses) >= 2:
        status = "mixed"
        hypotheses = high_hypotheses
    elif len(high_hypotheses) == 1:
        status = "leading"
        hypotheses = high_hypotheses
    else:
        possible_hypotheses = [
            name for name in BARRIER_HYPOTHESES if profile[name] >= low
        ]
        if possible_hypotheses:
            status = "possible"
            hypotheses = possible_hypotheses
        else:
            status = "unsupported"
            hypotheses = []

    return _triage_payload(
        status=status,
        low=low,
        high=high,
        profile=profile,
        hypotheses=hypotheses,
        request_more_evidence=False,
    )


def _validate_threshold(name: str, value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number in [0, 1]")
    try:
        threshold = float(value)
    except (OverflowError, TypeError, ValueError):
        raise ValueError(f"{name} must be a finite number in [0, 1]") from None
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError(f"{name} must be a finite number in [0, 1]")
    return threshold


def _extract_profile(result: Any) -> dict[str, float] | None:
    if not isinstance(result, Mapping):
        return None
    try:
        run_status = result.get("run_status")
        if run_status not in {"live", "mock"}:
            return None
        hypotheses = result.get("hypotheses")
        if not isinstance(hypotheses, Mapping):
            return None

        profile: dict[str, float] = {}
        for name in ALL_HYPOTHESES:
            answer = hypotheses.get(name)
            if not isinstance(answer, Mapping):
                return None
            probability = answer.get("probability")
            if (
                not isinstance(probability, (int, float))
                or isinstance(probability, bool)
            ):
                return None
            probability = float(probability)
            if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                return None
            profile[name] = probability
        return profile
    except Exception:
        # A malformed mapping or value must not leak a partial prediction.
        return None


def _triage_payload(
    *,
    status: str,
    low: float,
    high: float,
    profile: dict[str, float],
    hypotheses: list[str],
    request_more_evidence: bool,
) -> dict[str, Any]:
    return {
        "status": status,
        "thresholds": {"low": low, "high": high},
        "thresholds_illustrative": True,
        "hypothesis_profile": profile,
        "hypotheses": hypotheses,
        "request_more_evidence": request_more_evidence,
        "human_review_required": True,
    }
