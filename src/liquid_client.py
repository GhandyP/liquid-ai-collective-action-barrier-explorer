"""Optional, lazy OpenRouter adapter for the plan-defined live contract.

The official System One Adapter bridges typed Noul/Score/Choice questions to
OpenRouter's OpenAI-compatible Chat Completions API. Importing this module does
not load provider dependencies or read live configuration.
"""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from src.privacy import PrivacyError, prepare_case_for_request
from src.response_normalizer import (
    TAXONOMY_VERSION,
    ResponseNormalizationError,
    describe_response_shape,
    normalize_response,
)


API_BASE_URL = "https://openrouter.ai/api/v1"
_ADAPTER_MODULE = "system_one_adapter"
_QUESTION_MODULE = "typesafe_sdk"
_MAX_ERROR_LENGTH = 320


class _AdapterUnavailable(Exception):
    """A provider or question SDK dependency is unavailable."""


class _AdapterIncompatible(Exception):
    """The installed provider adapter lacks its required public classes."""


def run_live(
    case: Mapping[str, Any],
    *,
    client: Any = None,
    adapter_module: Any = None,
    environ: Mapping[str, str] | None = None,
    taxonomy_version: str = TAXONOMY_VERSION,
) -> dict[str, Any]:
    """Run one explicitly configured live call, returning an error on failure.

    ``client`` and ``adapter_module`` are injectable for offline tests. An
    injected client represents an already-configured provider client and does
    not require an API key, but an explicit OpenRouter model is always required.
    No failure path returns mock data, and exception details are never exposed.
    """
    try:
        safe_case = prepare_case_for_request(case)
    except PrivacyError as error:
        return _error_result("privacy_rejected", str(error))
    except Exception:
        return _error_result(
            "privacy_check_failed", "The privacy check could not inspect this request."
        )

    try:
        state = json.dumps(safe_case, ensure_ascii=False)
    except Exception:
        return _error_result("invalid_case", "The case could not be serialized for a live request.")

    environment = os.environ if environ is None else environ
    selected_model = environment.get("OPENROUTER_MODEL")
    if not isinstance(selected_model, str) or not selected_model.strip():
        return _error_result(
            "missing_configuration", "OPENROUTER_MODEL is required for live requests."
        )
    selected_model = selected_model.strip()

    api_key = environment.get("OPENROUTER_API_KEY")
    if client is None and (not isinstance(api_key, str) or not api_key.strip()):
        return _error_result(
            "missing_configuration", "OPENROUTER_API_KEY is required for live requests."
        )

    try:
        runtime = adapter_module if adapter_module is not None else _load_adapter_runtime()
    except _AdapterUnavailable:
        return _error_result(
            "adapter_unavailable", "The System One OpenAI adapter is unavailable for live requests."
        )
    except _AdapterIncompatible:
        return _error_result(
            "adapter_incompatible", "The System One OpenAI adapter lacks required classes."
        )
    except Exception:
        return _error_result(
            "adapter_unavailable", "The System One OpenAI adapter could not be loaded."
        )

    try:
        questions = build_questions(runtime)
    except _AdapterIncompatible:
        return _error_result(
            "adapter_incompatible", "The typed decision questions could not be constructed."
        )
    except Exception:
        return _error_result(
            "adapter_incompatible", "The typed decision questions could not be constructed."
        )

    provider_client = client
    if provider_client is None:
        try:
            provider_type = getattr(runtime, "OpenAIProvider")
            provider = provider_type(
                model_name=selected_model,
                base_url=API_BASE_URL,
                api_key=api_key,
                api="chat_completions",
            )
            client_type = getattr(runtime, "SystemOneAdapterClient")
            provider_client = client_type(provider)
        except Exception:
            return _error_result(
                "client_unavailable", "The OpenRouter System One adapter could not be constructed."
            )

    try:
        result = provider_client.system_one(state=state, questions=questions)
    except Exception as error:
        # Adapter exceptions can contain traces and request/response bodies.
        # Expose only the exception class, never its message or attached data.
        return _error_result(
            "provider_error",
            "The live provider request failed.",
            diagnostic=type(error).__name__,
        )

    try:
        return normalize_response(
            result, model=selected_model, taxonomy_version=taxonomy_version
        )
    except ResponseNormalizationError as error:
        return _error_result(
            "malformed_response",
            str(error),
            diagnostic=_response_shape_diagnostic(result),
        )
    except Exception:
        return _error_result(
            "malformed_response",
            "The live response could not be normalized.",
            diagnostic=_response_shape_diagnostic(result),
        )


def build_questions(adapter_module: Any = None) -> dict[str, Any]:
    """Construct the six Noul questions and optional Score and Choice."""
    runtime = adapter_module if adapter_module is not None else _load_adapter_runtime()
    try:
        noul_type = getattr(runtime, "Noul")
        score_type = getattr(runtime, "Score")
        choice_type = getattr(runtime, "Choice")
    except Exception:
        raise _AdapterIncompatible from None

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


def _load_adapter_runtime() -> Any:
    try:
        adapter = importlib.import_module(_ADAPTER_MODULE)
    except Exception:
        raise _AdapterUnavailable from None
    try:
        question_sdk = importlib.import_module(_QUESTION_MODULE)
    except Exception:
        raise _AdapterUnavailable from None

    provider_type = getattr(adapter, "OpenAIProvider", None)
    if provider_type is None:
        try:
            providers = importlib.import_module(f"{_ADAPTER_MODULE}.providers")
            provider_type = getattr(providers, "OpenAIProvider")
        except Exception:
            try:
                openai = importlib.import_module(f"{_ADAPTER_MODULE}.providers.openai")
                provider_type = getattr(openai, "OpenAIProvider")
            except Exception:
                raise _AdapterIncompatible from None

    try:
        return SimpleNamespace(
            SystemOneAdapterClient=getattr(adapter, "SystemOneAdapterClient"),
            OpenAIProvider=provider_type,
            Noul=getattr(question_sdk, "Noul"),
            Score=getattr(question_sdk, "Score"),
            Choice=getattr(question_sdk, "Choice"),
        )
    except Exception:
        raise _AdapterIncompatible from None


def _error_result(
    code: str,
    message: str,
    *,
    diagnostic: str | None = None,
) -> dict[str, Any]:
    error: dict[str, str] = {
        "code": code,
        "message": message[:_MAX_ERROR_LENGTH],
    }
    if diagnostic is not None:
        error["diagnostic"] = diagnostic[:120]
    return {"run_status": "error", "error": error}


def _response_shape_diagnostic(result: Any) -> str:
    try:
        return json.dumps(
            describe_response_shape(result), ensure_ascii=True, separators=(",", ":")
        )
    except Exception:
        return f"uninspectable ({type(result).__name__})"
