"""Guardrails for obvious personal or respondent-level data in live requests.

This boundary catches common identifiers and raw-record fields. It is a
best-effort guardrail, not a complete PII detector or a redaction system.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re
from typing import Any


_MAX_REPORTED_FINDINGS = 12
_SAFE_FIELD = re.compile(r"[a-z_][a-z0-9_]{0,63}\Z")
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)
_PHONE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]\d{3,4}[\s.-]\d{3,4}(?!\w)"
)
_LOCAL_PHONE = re.compile(r"(?<!\w)\d{3}[\s.-]\d{4}(?!\w)")
_UNFORMATTED_PHONE = re.compile(r"(?<!\w)\+?\d{10,15}(?!\w)")
_ADDRESS = re.compile(
    r"(?i)\b\d{1,6}\s+(?:[A-Z0-9.'-]+\s+){0,5}"
    r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|boulevard|blvd\.?|"
    r"lane|ln\.?|drive|dr\.?|way|court|ct\.?|place|pl\.?|terrace|ter\.?|"
    r"rue|straße|strasse)\b"
)
_LABELED_NAME = re.compile(
    r"(?i)\b(?:name|participant|respondent|employee|contact)\s*(?:is|:|=)\s*"
    r"[A-Z][A-Za-z'-]*(?:\s+[A-Z][A-Za-z'-]*){0,2}\b"
)
_STANDALONE_NAME = re.compile(
    r"\A\s*[A-Z][A-Za-z'-]{1,30}(?:\s+[A-Z][A-Za-z'-]{1,30}){1,2}\s*\Z"
)
_TEXT_IDENTIFIER = re.compile(
    r"(?i)\b(?:employee|respondent|participant|staff|worker|subject|person|user)"
    r"\s*(?:id|identifier|number|no\.?|code)\s*[:#=]\s*[A-Z0-9_-]+\b"
)
_RAW_CONTENT_LABEL = re.compile(
    r"(?i)\b(?:raw\s+)?(?:transcript|recording|audio recording)\s*[:=]"
)

_NAME_EXACT = {
    "name",
    "names",
    "fullname",
    "firstname",
    "lastname",
    "givenname",
    "familyname",
    "personname",
    "contactname",
}
_SUBJECT_TOKENS = {
    "employee",
    "respondent",
    "participant",
    "staff",
    "worker",
    "subject",
    "person",
    "user",
}
_IDENTIFIER_TOKENS = {"id", "ids", "identifier", "identifiers", "number", "no", "code"}
_RECORD_TOKENS = {"record", "records", "row", "rows", "entry", "entries", "data", "response", "responses"}


class PrivacyError(ValueError):
    """A live-request payload contains fields rejected by the privacy guardrail."""

    def __init__(self, findings: list[tuple[str, str]]) -> None:
        self.findings = tuple(findings[:_MAX_REPORTED_FINDINGS])
        details = "; ".join(f"{path} ({category})" for path, category in self.findings)
        if len(findings) > _MAX_REPORTED_FINDINGS:
            details += "; additional findings omitted"
        super().__init__(f"Privacy check rejected fields: {details}")


def prepare_case_for_request(case: Mapping[str, Any]) -> dict[str, Any]:
    """Reject obvious identifying/raw-record content and return a detached copy.

    Errors include only sanitized field paths and finding categories. The
    supplied object is never modified. Passing this check does not guarantee
    that all personal or confidential information has been detected.
    """
    if not isinstance(case, Mapping):
        raise PrivacyError([("case", "structured_payload")])

    findings: list[tuple[str, str]] = []
    try:
        _inspect(case, "case", findings, set())
    except RecursionError:
        raise PrivacyError([("case", "structure_too_deep")]) from None

    if findings:
        raise PrivacyError(findings)

    try:
        return deepcopy(dict(case))
    except Exception:
        raise PrivacyError([("case", "unsupported_structure")]) from None


def _inspect(value: Any, path: str, findings: list[tuple[str, str]], seen: set[int]) -> None:
    if len(findings) > _MAX_REPORTED_FINDINGS:
        return

    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        for key, child in value.items():
            if not isinstance(key, str):
                _add_finding(findings, path, "unsupported_key")
                continue
            child_path = _join_path(path, key)
            for category in _key_categories(key, child):
                _add_finding(findings, child_path, category)
            if isinstance(child, str):
                for category in _text_categories(child):
                    _add_finding(findings, child_path, category)
            _inspect(child, child_path, findings, seen)
    elif isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            if isinstance(child, str):
                for category in _text_categories(child):
                    _add_finding(findings, child_path, category)
            _inspect(child, child_path, findings, seen)
    elif isinstance(value, str):
        for category in _text_categories(value):
            _add_finding(findings, path, category)


def _key_categories(key: str, value: Any) -> tuple[str, ...]:
    tokens = re.findall(r"[a-z0-9]+", key.casefold())
    token_set = set(tokens)
    normalized = "".join(tokens)
    categories: list[str] = list(_text_categories(key))

    if "email" in normalized:
        categories.append("email")
    if token_set.intersection({"phone", "telephone", "mobile", "cellphone", "fax"}):
        categories.append("phone")
    if token_set.intersection({"address", "street", "postcode", "postal", "zipcode", "zip", "housenumber"}):
        categories.append("address")
    if (
        normalized in _NAME_EXACT
        or ("name" in token_set and token_set.intersection(_SUBJECT_TOKENS | {"first", "last", "given", "family", "full", "contact"}))
    ):
        categories.append("name")
    if "transcript" in token_set or token_set.intersection({"recording", "audio", "video"}):
        categories.append("raw_content")
    if token_set.intersection(_SUBJECT_TOKENS) and token_set.intersection(_IDENTIFIER_TOKENS):
        categories.append("personal_identifier")

    respondent_level = (
        ("respondent" in token_set and token_set.intersection(_RECORD_TOKENS))
        or ("individual" in token_set and token_set.intersection({"response", "responses"}))
        or ("respondents" in token_set and isinstance(value, (Mapping, list, tuple)))
        or (
            "responses" in token_set
            and key.casefold() != "response_counts"
            and isinstance(value, (list, tuple))
            and any(isinstance(item, Mapping) for item in value)
        )
    )
    if respondent_level:
        categories.append("respondent_level_records")

    return tuple(dict.fromkeys(categories))


def _text_categories(text: str) -> tuple[str, ...]:
    categories: list[str] = []
    if _EMAIL.search(text):
        categories.append("email")
    if _PHONE.search(text) or _LOCAL_PHONE.search(text) or _UNFORMATTED_PHONE.search(text):
        categories.append("phone")
    if _ADDRESS.search(text):
        categories.append("address")
    if _LABELED_NAME.search(text) or _STANDALONE_NAME.fullmatch(text):
        categories.append("name")
    if _TEXT_IDENTIFIER.search(text):
        categories.append("personal_identifier")
    if _RAW_CONTENT_LABEL.search(text):
        categories.append("raw_content")
    return tuple(categories)


def _join_path(parent: str, key: str) -> str:
    safe_key = key if _SAFE_FIELD.fullmatch(key) else "<field>"
    joined = f"{parent}.{safe_key}"
    return joined if len(joined) <= 180 else f"{joined[:177]}..."


def _add_finding(findings: list[tuple[str, str]], path: str, category: str) -> None:
    finding = (path, category)
    if finding not in findings and len(findings) <= _MAX_REPORTED_FINDINGS:
        findings.append(finding)
