"""Optional, lazy Liquid adapter for the plan-defined live contract.

Compatibility with ``typesafe-sdk`` and the documented API/model identifiers
is unverified until a configured live smoke test succeeds. Importing this
module does not import the provider SDK or read live configuration.
"""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Mapping
from typing import Any

from src.privacy import PrivacyError, prepare_case_for_request
from src.response_normalizer import (
    TAXONOMY_VERSION,
    ResponseNormalizationError,
    normalize_response,
)


API_BASE_URL = "https://api.liquid.ai"
DEFAULT_MODEL = "d1:free"
_SDK_MODULE = "typesafe_sdk"
_MAX_ERROR_LENGTH = 320


class _SdkUnavailable(Exception):
    """The provider module or one of its required typed classes is unavailable."""


def run_live(
    case: Mapping[str, Any],
    *,
    client: Any = None,
    sdk_module: Any = None,
    environ: Mapping[str, str] | None = None,
    model: str | None = None,
    taxonomy_version: str = TAXONOMY_VERSION,
) -> dict[str, Any]:
    """Run one explicitly requested live call, returning an error envelope on failure.

    ``client`` and ``sdk_module`` are injectable for offline tests. An injected
    client represents an already-configured provider client and therefore does
    not require an environment API key. No failure path returns mock data.
    """
    try:
        safe_case = prepare_case_for_request(case)
    except PrivacyError as error:
        return _error_result("privacy_rejected", str(error))
    except Exception:
        return _error_result("privacy_check_failed", "The privacy check could not inspect this request.")

    try:
        state = json.dumps(safe_case, ensure_ascii=False)
    except Exception:
        return _error_result("invalid_case", "The case could not be serialized for a live request.")

    environment = os.environ if environ is None else environ
    selected_model = model if model is not None else environment.get("D1_MODEL", DEFAULT_MODEL)
    if not isinstance(selected_model, str) or not selected_model.strip():
        selected_model = DEFAULT_MODEL

    api_key: str | None = None
    if client is None:
        api_key = environment.get("LIQUID_API_KEY")
        if not isinstance(api_key, str) or not api_key.strip():
            return _error_result(
                "missing_configuration",
                "LIQUID_API_KEY is required for live requests.",
            )

    try:
        sdk = sdk_module if sdk_module is not None else _load_sdk()
    except _SdkUnavailable:
        return _error_result("sdk_unavailable", "The Liquid SDK is unavailable for live requests.")
    except Exception:
        return _error_result("sdk_unavailable", "The Liquid SDK could not be loaded for live requests.")

    try:
        questions = build_questions(sdk)
    except _SdkUnavailable:
        return _error_result("sdk_unavailable", "The Liquid SDK lacks required typed question classes.")
    except Exception:
        return _error_result("sdk_incompatible", "The Liquid question definitions could not be constructed.")

    provider_client = client
    if provider_client is None:
        try:
            client_type = getattr(sdk, "TypeSafeClient")
            provider_client = client_type(api_key=api_key, base_url=API_BASE_URL)
        except Exception:
            return _error_result("client_unavailable", "The Liquid client could not be constructed.")

    try:
        result = provider_client.system_one(
            model=selected_model,
            state=state,
            questions=questions,
        )
    except Exception:
        return _error_result("provider_error", "The live provider request failed.")

    try:
        return normalize_response(result, model=selected_model, taxonomy_version=taxonomy_version)
    except ResponseNormalizationError as error:
        return _error_result("malformed_response", str(error))
    except Exception:
        return _error_result("malformed_response", "The live response could not be normalized.")


def build_questions(sdk_module: Any = None) -> dict[str, Any]:
    """Construct the six independent Noul questions and optional Score/Choice."""
    sdk = sdk_module if sdk_module is not None else _load_sdk()
    try:
        noul_type = getattr(sdk, "Noul")
        score_type = getattr(sdk, "Score")
        choice_type = getattr(sdk, "Choice")
    except Exception:
        raise _SdkUnavailable from None

    return {
        "perception_gap": noul_type(
            instructions=(
                "Using only the supplied evidence, is a material gap in factual understanding "
                "or visibility contributing to the inaction? Distinguish lack of knowledge "
                "from people who know the facts but disagree about values or trade-offs."
            )
        ),
        "values_conflict": noul_type(
            instructions=(
                "Using only the supplied evidence, could stakeholders understand the relevant "
                "facts yet disagree about priorities, principles, trade-offs, or who bears costs? "
                "Do not label missing information as a values conflict."
            )
        ),
        "response_efficacy_gap": noul_type(
            instructions=(
                "Using only the supplied evidence, is there evidence that stakeholders doubt "
                "the proposed action will produce a meaningful result? This concerns whether "
                "the action works, not whether the group can coordinate to carry it out."
            )
        ),
        "collective_efficacy_gap": noul_type(
            instructions=(
                "Using only the supplied evidence, is there evidence that stakeholders doubt "
                "the group can coordinate or influence the result together? Distinguish group "
                "coordination beliefs from doubts that the action itself is effective."
            )
        ),
        "structural_barrier": noul_type(
            instructions=(
                "Using only the supplied evidence, do objective constraints such as time, "
                "resources, authority, access, safety, or skills prevent action? Distinguish "
                "practical constraints from beliefs about whether action would work."
            )
        ),
        "insufficient_evidence": noul_type(
            instructions=(
                "Using only the supplied evidence, is it too thin or contradictory to "
                "distinguish among the candidate barriers? Do not infer a barrier merely "
                "because evidence is missing."
            )
        ),
        "response_efficacy_level": score_type(
            instructions=(
                "Using only the supplied evidence, how strongly do stakeholders doubt that "
                "the proposed action will work? Score the strength of response-efficacy doubt."
            ),
            criteria=[
                "No evident doubt: stakeholders expect the action to work",
                "Some doubt: they still expect a meaningful effect",
                "Strong doubt: they expect only a small or uncertain effect",
                "Futility: they expect no meaningful effect",
            ],
        ),
        "next_diagnostic_probe": choice_type(
            instructions=(
                "Using only the supplied evidence, choose one useful next diagnostic probe, "
                "including an uncertainty or mixed-case option. This is a probe suggestion, "
                "not a declaration of the true cause."
            ),
            criteria={
                "check_factual_understanding": "Verify beliefs about facts and causal relationships",
                "map_values_and_tradeoffs": "Clarify priorities and unacceptable trade-offs",
                "test_response_efficacy": "Run a small test of whether the action can change the outcome",
                "check_collective_coordination": "Clarify roles, timing, and expectations about others",
                "audit_practical_constraints": "Check resources, time, authority, access, safety, and skills",
                "collect_more_evidence": "Gather more evidence before choosing an intervention",
                "human_review_mixed_case": "Escalate a mixed or ambiguous case to a facilitator",
            },
        ),
    }


def _load_sdk() -> Any:
    try:
        return importlib.import_module(_SDK_MODULE)
    except Exception:
        raise _SdkUnavailable from None


def _error_result(code: str, message: str) -> dict[str, Any]:
    bounded_message = message[:_MAX_ERROR_LENGTH]
    return {
        "run_status": "error",
        "error": {
            "code": code,
            "message": bounded_message,
        },
    }
