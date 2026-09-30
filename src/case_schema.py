"""Validation for the local prototype's structured case payloads.

This module rejects a small set of obvious identifying/raw-record fields by
key name. It is not a substitute for the fuller text scanning and redaction
boundary planned for the privacy layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re
from typing import Any


SUPPORTED_EVIDENCE_TYPES = frozenset({"focus_group_summary", "survey_aggregate"})


class CaseValidationError(ValueError):
    """A case payload failed one or more actionable validation checks."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("Case validation failed: " + "; ".join(self.errors))


def validate_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a case and return a detached copy without changing its fields.

    Expected evidence records use ``focus_group_summary`` or
    ``survey_aggregate``. Evidence provenance and limitations are retained as
    provided. Validation errors identify field paths but never echo field
    values or dump the payload.
    """
    if not isinstance(case, Mapping):
        raise CaseValidationError(["case: must be an object"])

    errors: list[str] = []
    _reject_obvious_identifier_fields(case, "", errors, set())

    if "case_id" in case:
        _require_text(case, "case_id", "case", errors)
    if "exploratory" in case and not isinstance(case["exploratory"], bool):
        errors.append("exploratory: must be a boolean when supplied")

    action = case.get("desired_action")
    if not isinstance(action, Mapping):
        errors.append("desired_action: must be an object")
    else:
        for field in ("description", "actor_group", "time_horizon", "observable_success"):
            _require_text(action, field, "desired_action", errors)

    observed = case.get("observed_non_action")
    if not isinstance(observed, Mapping):
        errors.append("observed_non_action: must be an object")
    else:
        for field in ("description", "period"):
            _require_text(observed, field, "observed_non_action", errors)

    raw_evidence = case.get("evidence", [])
    if not isinstance(raw_evidence, list):
        errors.append("evidence: must be an array")
        evidence: list[Any] = []
    else:
        evidence = raw_evidence

    exploratory = case.get("exploratory") is True
    if not evidence and not exploratory:
        errors.append("evidence: add at least one item or explicitly set exploratory to true")

    seen_ids: set[str] = set()
    for index, item in enumerate(evidence):
        path = f"evidence[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{path}: must be an object")
            continue

        evidence_id = _require_text(item, "id", path, errors)
        if evidence_id is not None:
            if evidence_id in seen_ids:
                errors.append(f"{path}.id: must be unique within this case")
            seen_ids.add(evidence_id)

        evidence_type = item.get("type")
        if not isinstance(evidence_type, str) or evidence_type not in SUPPORTED_EVIDENCE_TYPES:
            errors.append(
                f"{path}.type: must be 'focus_group_summary' or 'survey_aggregate'"
            )
            continue

        if evidence_type == "focus_group_summary":
            _validate_focus_group(item, path, errors)
        else:
            _validate_survey(item, path, errors)

    if errors:
        raise CaseValidationError(errors)
    return deepcopy(dict(case))


def _require_text(
    record: Mapping[str, Any], field: str, path: str, errors: list[str]
) -> str | None:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}.{field}: must be a non-empty string")
        return None
    return value


def _require_text_list(
    record: Mapping[str, Any], field: str, path: str, errors: list[str]
) -> list[str] | None:
    value = record.get(field)
    if not isinstance(value, list) or not value:
        errors.append(f"{path}.{field}: must be a non-empty array of strings")
        return None
    if any(not isinstance(option, str) or not option.strip() for option in value):
        errors.append(f"{path}.{field}: every entry must be a non-empty string")
        return None
    if len(set(value)) != len(value):
        errors.append(f"{path}.{field}: entries must be unique")
        return None
    return value


def _require_count(
    record: Mapping[str, Any], field: str, path: str, errors: list[str]
) -> int | None:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        errors.append(f"{path}.{field}: must be a non-negative integer")
        return None
    return value


def _validate_limitations(item: Mapping[str, Any], path: str, errors: list[str]) -> None:
    fields = [field for field in ("limitations", "limitation") if field in item]
    if not fields:
        errors.append(f"{path}.limitations: provide at least one limitation")
        return
    for field in fields:
        value = item[field]
        field_path = f"{path}.{field}"
        if isinstance(value, str):
            if not value.strip():
                errors.append(f"{field_path}: must be non-empty")
        elif isinstance(value, list):
            if not value or any(not isinstance(entry, str) or not entry.strip() for entry in value):
                errors.append(f"{field_path}: must contain non-empty limitation text")
        else:
            errors.append(f"{field_path}: must be a non-empty string or array of strings")


def _validate_optional_text_or_list(
    item: Mapping[str, Any], field: str, path: str, errors: list[str]
) -> None:
    if field not in item:
        return
    value = item[field]
    if isinstance(value, str):
        if not value.strip():
            errors.append(f"{path}.{field}: must be non-empty when supplied")
    elif isinstance(value, list):
        if not value or any(not isinstance(entry, str) or not entry.strip() for entry in value):
            errors.append(f"{path}.{field}: must contain non-empty strings when supplied")
    else:
        errors.append(f"{path}.{field}: must be a string or array of strings when supplied")


def _validate_focus_group(item: Mapping[str, Any], path: str, errors: list[str]) -> None:
    for field in (
        "study_id",
        "collection_date",
        "population",
        "sampling_method",
        "moderator_prompt",
        "theme",
    ):
        _require_text(item, field, path, errors)
    _require_count(item, "participants_n", path, errors)
    _validate_limitations(item, path, errors)
    for field in ("dissenting_views", "dissent", "anonymized_quote", "anonymized_quotes"):
        _validate_optional_text_or_list(item, field, path, errors)


def _validate_survey(item: Mapping[str, Any], path: str, errors: list[str]) -> None:
    for field in ("study_id", "collection_date", "population", "sampling_method", "question"):
        _require_text(item, field, path, errors)

    response_scale = _require_text_list(item, "response_scale", path, errors)
    invited_n = _require_count(item, "respondents_invited_n", path, errors)
    received_n = _require_count(item, "responses_received_n", path, errors)
    valid_n = _require_count(item, "valid_n", path, errors)
    missing_n = _require_count(item, "item_missing_n", path, errors)
    _validate_limitations(item, path, errors)

    if invited_n is not None and received_n is not None and received_n > invited_n:
        errors.append(f"{path}.responses_received_n: cannot exceed respondents_invited_n")
    if received_n is not None and valid_n is not None and valid_n > received_n:
        errors.append(f"{path}.valid_n: cannot exceed responses_received_n")
    if received_n is not None and valid_n is not None and missing_n is not None:
        if missing_n != received_n - valid_n:
            errors.append(
                f"{path}.item_missing_n: must equal responses_received_n minus valid_n"
            )

    counts = item.get("response_counts")
    if not isinstance(counts, Mapping) or not counts:
        errors.append(f"{path}.response_counts: must be a non-empty object of response counts")
        return

    count_values: list[int] = []
    valid_count_values = True
    for option, value in counts.items():
        if not isinstance(option, str) or not option.strip():
            errors.append(f"{path}.response_counts: option names must be non-empty strings")
            valid_count_values = False
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(f"{path}.response_counts.{option}: must be a non-negative integer")
            valid_count_values = False
            continue
        count_values.append(value)

    if response_scale is not None and set(counts) != set(response_scale):
        errors.append(f"{path}.response_counts: keys must match the response_scale options exactly")
    if valid_count_values and valid_n is not None and sum(count_values) != valid_n:
        errors.append(f"{path}.response_counts: counts must sum exactly to valid_n")


def _reject_obvious_identifier_fields(
    value: Any, path: str, errors: list[str], seen_containers: set[int]
) -> None:
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen_containers:
            return
        seen_containers.add(identity)
        for key, child in value.items():
            if not isinstance(key, str):
                errors.append(f"{path or 'case'}: object keys must be strings")
                continue
            child_path = f"{path}.{key}" if path else key
            if _is_obvious_identifier_field(key):
                errors.append(
                    f"{child_path}: identifying, raw-transcript, or respondent-level fields are not accepted"
                )
            _reject_obvious_identifier_fields(child, child_path, errors, seen_containers)
    elif isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in seen_containers:
            return
        seen_containers.add(identity)
        for index, child in enumerate(value):
            _reject_obvious_identifier_fields(child, f"{path}[{index}]", errors, seen_containers)


def _is_obvious_identifier_field(field: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", field.casefold())
    normalized = "".join(tokens)
    exact_names = {
        "name",
        "names",
        "fullname",
        "firstname",
        "lastname",
        "givenname",
        "familyname",
        "personname",
        "participantname",
        "respondentname",
        "employeename",
    }
    identifier_subjects = {"employee", "staff", "worker", "respondent", "participant", "person", "user"}
    row_terms = {"row", "rows", "record", "records", "entry", "entries", "data"}

    if normalized in exact_names or "email" in normalized:
        return True
    if "transcript" in tokens and ("raw" in tokens or normalized in {"transcript", "transcripts"}):
        return True
    if "id" in tokens and identifier_subjects.intersection(tokens):
        return True
    if "name" in tokens and identifier_subjects.intersection(tokens):
        return True
    if "respondent" in tokens and row_terms.intersection(tokens):
        return True
    if "individual" in tokens and "response" in tokens:
        return True
    if normalized in {"responses", "surveyresponses", "respondentresponses", "surveyrows"}:
        return True
    return False
