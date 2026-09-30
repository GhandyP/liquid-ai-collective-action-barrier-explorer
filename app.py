"""Local Streamlit interface for synthetic and curated real D1 evidence."""

from __future__ import annotations

from copy import deepcopy

import streamlit as st

from src.app_state import (
    AppStateError,
    HumanReviewValidationError,
    load_curated_case,
    load_synthetic_case,
    record_human_review,
    run_case,
)


HYPOTHESIS_LABELS = {
    "perception_gap": "Perception gap",
    "values_conflict": "Values conflict",
    "response_efficacy_gap": "Response-efficacy gap",
    "collective_efficacy_gap": "Collective-efficacy gap",
    "structural_barrier": "Structural/capability barrier",
    "insufficient_evidence": "Insufficient evidence",
}

TRIAGE_MESSAGES = {
    "leading": "One hypothesis is above the illustrative high threshold; it is not established as a cause.",
    "mixed": "Several hypotheses are plausible and may coexist. Review the evidence before choosing a next step.",
    "possible": "One or more hypotheses are possible, but none crosses the illustrative high threshold.",
    "insufficient": "The available evidence is insufficient for a responsible distinction. Gather more evidence.",
    "unsupported": "No hypothesis crosses the illustrative low threshold; this does not show that no barrier exists.",
    "unavailable": "Triage is unavailable because a valid result was not produced.",
}

CASE_LOADERS = {
    "Synthetic demonstration": load_synthetic_case,
    "Curated real evidence": load_curated_case,
}


def main() -> None:
    st.set_page_config(page_title="D1 Evidence Hypothesis Review", layout="wide")
    st.title("D1 — Evidence-Informed Hypothesis Review")
    st.warning(
        "Outputs are hypotheses, not causal findings, population claims, or judgments "
        "about individuals. Do not use them for profiling, targeting, or persuasion."
    )

    selected_case_name = st.sidebar.radio(
        "Case",
        options=tuple(CASE_LOADERS),
        index=0,
        key="case_selection",
    )
    selected_mode = st.sidebar.radio("Run mode", options=("mock", "live"), index=0)
    st.sidebar.caption("Mock is the offline default. Selecting live is an explicit opt-in and requires LIQUID_API_KEY; D1_MODEL is optional.")
    st.sidebar.caption("The SDK setup follows Liquid's Decision Models documentation; a live API/model call has not been smoke-tested. Failures remain errors and never fall back to mock.")
    st.caption("Use anonymized summaries only. Do not enter personal, confidential, transcript, or respondent-row data.")

    previous_case_name = st.session_state.get("_active_case_selection")
    if previous_case_name != selected_case_name:
        _clear_case_bound_state()
        st.session_state["_active_case_selection"] = selected_case_name
    if st.session_state.get("run_case_selection") != selected_case_name and (
        "run_state" in st.session_state or "human_review" in st.session_state
    ):
        _clear_case_bound_state()

    try:
        case_fixture = CASE_LOADERS[selected_case_name]()
    except AppStateError as error:
        st.error(str(error))
        st.stop()
        return

    evidence_by_type = _evidence_by_type(case_fixture)
    focus_evidence = evidence_by_type["focus_group_summary"]
    survey_evidence = evidence_by_type["survey_aggregate"]
    is_synthetic = selected_case_name == "Synthetic demonstration"

    with st.form("case_run_form"):
        st.subheader("Case")
        if is_synthetic:
            action_values, observation_values = _render_editable_case(case_fixture)
        else:
            _render_curated_case(case_fixture, focus_evidence, survey_evidence)
            action_values = observation_values = None

        st.subheader("Separate evidence summaries")
        focus_column, survey_column = st.columns(2)
        with focus_column:
            focus_values = _render_focus_evidence(focus_evidence, editable=is_synthetic)
        with survey_column:
            survey_question = _render_survey_evidence(
                survey_evidence, editable=is_synthetic
            )

        run_submitted = st.form_submit_button(f"Run selected mode: {selected_mode}")

    if run_submitted:
        case = deepcopy(case_fixture)
        if is_synthetic:
            case["desired_action"].update(action_values)
            case["observed_non_action"].update(observation_values)
            case_evidence = _evidence_by_type(case)
            case_focus = case_evidence["focus_group_summary"]
            case_survey = case_evidence["survey_aggregate"]
            focus_theme, dissent_text = focus_values
            case_focus["theme"] = focus_theme
            dissenting_views = [
                line.strip() for line in dissent_text.splitlines() if line.strip()
            ]
            if dissenting_views:
                case_focus["dissenting_views"] = dissenting_views
            else:
                case_focus.pop("dissenting_views", None)
            case_survey["question"] = survey_question

        st.session_state["run_state"] = run_case(case, selected_mode)
        st.session_state["run_case_selection"] = selected_case_name
        st.session_state["human_review"] = {"status": "pending", "override_reason": None}
        st.session_state["review_decision"] = "pending"
        st.session_state["review_reason"] = ""

    run_state = None
    if st.session_state.get("run_case_selection") == selected_case_name:
        run_state = st.session_state.get("run_state")
    if run_state is None:
        st.info(f"Run status: not run. Selected mode: {selected_mode}.")
        return

    st.metric("Run status", run_state["run_status"])
    if run_state["run_status"] == "error":
        st.error(run_state["error"]["message"])
        return

    _render_interpretation_guide()

    if run_state["run_status"] == "mock":
        st.warning(
            "Illustrative mock result — this profile is a fixed demo fixture. It was NOT "
            "calculated from the evidence shown above and does not change when the case "
            "changes. Select live mode to evaluate the selected case with the model."
        )

    result = run_state["result"]
    triage = run_state["triage"]
    st.subheader("Independent hypothesis profile")
    st.caption("Probabilities are independent, do not sum to one, and are illustrative rather than validated accuracy estimates.")
    for name in HYPOTHESIS_LABELS:
        probability = result["hypotheses"][name]["probability"]
        left, right = st.columns([3, 1])
        with left:
            st.write(HYPOTHESIS_LABELS[name])
            st.progress(probability)
        with right:
            st.metric("Probability", f"{probability:.1%}")

    triage_status = triage["status"]
    st.subheader(f"Triage status: {triage_status}")
    st.info(TRIAGE_MESSAGES.get(triage_status, TRIAGE_MESSAGES["unavailable"]))
    if triage_status in {"mixed", "insufficient", "possible"}:
        st.warning("Review the evidence and uncertainty; this display does not select an intervention.")

    score = result.get("response_efficacy_level")
    if score is not None:
        st.metric("Illustrative response-efficacy Score (0–3)", f"{score['score']:.2f}")
    choice = result.get("next_diagnostic_probe")
    if choice is not None:
        suggested_probe = choice["choice"].replace("_", " ")
        st.info(f"Suggested next probe (suggestion only; no action is taken): {suggested_probe}.")

    st.subheader("Human review")
    current_review = st.session_state.get("human_review", result["human_review"])
    st.caption(f"Recorded decision: {current_review['status']}")
    with st.form("human_review_form"):
        decision = st.selectbox(
            "Decision",
            options=("pending", "confirmed", "corrected", "rejected"),
            key="review_decision",
        )
        reason = st.text_area(
            "Short reason (required for a completed decision)",
            max_chars=240,
            key="review_reason",
        )
        review_submitted = st.form_submit_button("Record human review")

    if review_submitted:
        try:
            review = record_human_review(decision, reason)
        except HumanReviewValidationError as error:
            st.error(str(error))
        else:
            st.session_state["human_review"] = review
            run_state["result"]["human_review"] = review
            st.session_state["run_state"] = run_state
            st.success(f"Human review recorded: {review['status']}.")

    recorded_review = st.session_state.get("human_review", {"status": "pending"})
    if recorded_review["status"] != "pending" and recorded_review.get("override_reason"):
        st.caption(f"Review reason: {recorded_review['override_reason']}")


def _render_interpretation_guide() -> None:
    with st.expander("How to interpret these results"):
        st.markdown(
            """
- **A probability is not a population share.** "Response-efficacy gap: 74%" does not mean
  74% of people have that barrier. It is the model's estimated support for that hypothesis
  given the supplied evidence.
- **Probabilities are independent.** Several barriers can coexist; the six values do not sum
  to 100% and are not competing for one cause.
- **`mixed`** means several hypotheses are plausible at once. It does not select one cause.
- **`leading`** names the strongest hypothesis only; it is not proof of a cause.
- **`insufficient`** means the evidence cannot distinguish the hypotheses — it does not show
  that no barrier exists.
- **Score (0–3)** is a position on an ordered rubric, not a percentage. 2.10 sits between
  levels 2 and 3.
- **The suggested next probe** is a question worth investigating, not an action taken.
- Every output is a **hypothesis for human review** — never a causal finding, a fact about a
  population, or a judgment about an individual.
            """
        )


def _clear_case_bound_state() -> None:
    for key in (
        "run_state",
        "run_case_selection",
        "human_review",
        "review_decision",
        "review_reason",
    ):
        if key in st.session_state:
            del st.session_state[key]


def _evidence_by_type(case: dict) -> dict:
    return {item["type"]: item for item in case["evidence"]}


def _render_editable_case(case_fixture: dict) -> tuple[dict, dict]:
    action_column, observation_column = st.columns(2)
    with action_column:
        action = case_fixture["desired_action"]
        action_values = {
            "description": st.text_input("Desired action", value=action["description"]),
            "actor_group": st.text_input("Actor group", value=action["actor_group"]),
            "time_horizon": st.text_input("Time horizon", value=action["time_horizon"]),
            "observable_success": st.text_input(
                "Observable success", value=action["observable_success"]
            ),
        }
    with observation_column:
        observation = case_fixture["observed_non_action"]
        observation_values = {
            "description": st.text_input(
                "Observed non-action", value=observation["description"]
            ),
            "period": st.text_input("Period", value=observation["period"]),
        }
    return action_values, observation_values


def _render_curated_case(case: dict, focus_evidence: dict, survey_evidence: dict) -> None:
    st.caption("Curated real-evidence fields are read-only and cannot be overwritten in this interface.")
    action_column, observation_column = st.columns(2)
    with action_column:
        st.markdown("#### Desired action")
        for label, field in (
            ("Description", "description"),
            ("Actor group", "actor_group"),
            ("Time horizon", "time_horizon"),
            ("Observable success", "observable_success"),
        ):
            st.write(f"**{label}:** {case['desired_action'][field]}")
    with observation_column:
        st.markdown("#### Observed non-action")
        st.write(f"**Description:** {case['observed_non_action']['description']}")
        st.write(f"**Period:** {case['observed_non_action']['period']}")

    st.markdown("#### Curated source details")
    st.write(f"**Case topic:** {case.get('topic', 'Not supplied')}")
    for evidence in (focus_evidence, survey_evidence):
        _render_source_details(evidence)


def _render_focus_evidence(
    evidence: dict, *, editable: bool
) -> tuple[str, str] | None:
    st.markdown("#### Focus-group summary")
    st.caption(
        f"{evidence['study_id']} · {evidence['collection_date']} · "
        f"{evidence.get('sampling_method', 'Sampling method not supplied')}"
    )
    if editable:
        st.caption(f"{evidence['participants_n']} fictional participants")
        focus_theme = st.text_area(
            "Anonymized theme summary — not raw transcript",
            value=evidence["theme"],
            height=110,
        )
        dissent_text = st.text_area(
            "Dissenting summary points — one per line",
            value="\n".join(evidence.get("dissenting_views", [])),
            height=90,
        )
        st.caption("Focus-group themes do not estimate how common a view is.")
    else:
        if "group_size_range" in evidence:
            st.write(f"**Participant range:** {evidence['group_size_range']}")
        if "participants_n" in evidence:
            st.write(
                "**Schema-required participant lower bound (not the study total):** "
                f"{evidence['participants_n']}"
            )
        if "participant_count_note" in evidence:
            st.write(f"**Participant-count note:** {evidence['participant_count_note']}")
        st.write(f"**Focus-group theme:** {evidence['theme']}")
        if evidence.get("dissenting_views"):
            st.write("**Dissenting summary points:**")
            for dissent in evidence["dissenting_views"]:
                st.write(f"- {dissent}")
        st.caption("Focus-group themes do not estimate how common a view is.")
    _render_limitations(evidence)
    if editable:
        return focus_theme, dissent_text
    return None


def _render_survey_evidence(evidence: dict, *, editable: bool) -> str | None:
    st.markdown("#### Aggregate survey")
    st.caption(
        f"{evidence['study_id']} · {evidence['collection_date']} · "
        f"{evidence['sampling_method']}"
    )
    if editable:
        survey_question = st.text_area(
            "Aggregate item wording",
            value=evidence["question"],
            height=110,
        )
        st.caption(
            f"Invited: {evidence['respondents_invited_n']} · "
            f"responses received: {evidence['responses_received_n']} · "
            f"valid denominator: {evidence['valid_n']} · "
            f"item missing: {evidence['item_missing_n']}"
        )
        count_columns = st.columns(len(evidence["response_scale"]))
        for column, option in zip(count_columns, evidence["response_scale"]):
            with column:
                st.metric(
                    option.replace("_", " "),
                    f"{evidence['response_counts'][option]}/{evidence['valid_n']}",
                )
        st.caption("Each count is shown over the valid-response denominator; the synthetic distribution is not causal or representative.")
    else:
        st.write(f"**Survey question:** {evidence['question']}")
        st.write(f"**Percentage base:** {evidence['percentage_base']}")
        if evidence.get("allows_multiple_answers"):
            max_answers = evidence.get("max_answers_per_respondent")
            if max_answers is not None:
                st.caption(
                    "Multiple answers were allowed; up to "
                    f"{max_answers} answers per respondent."
                )
            else:
                st.caption("Multiple answers were allowed.")
        else:
            st.caption("One answer per respondent was allowed.")

        st.caption(
            "Values are rounded source percentages. They are not normalized and are "
            "not expected to sum to 100%."
        )
        percentage_columns = st.columns(3)
        percentages = evidence["response_percentages"]
        for index, option in enumerate(evidence["response_scale"]):
            with percentage_columns[index % len(percentage_columns)]:
                st.write(option)
                st.metric("Reported percentage", f"{percentages[option]:g}%")
    _render_limitations(evidence)
    if editable:
        return survey_question
    return None


def _render_limitations(evidence: dict) -> None:
    limitations = evidence.get("limitations", evidence.get("limitation", []))
    if isinstance(limitations, str):
        limitations = [limitations]
    for limitation in limitations:
        st.caption(f"Limitation: {limitation}")


def _render_source_details(evidence: dict) -> None:
    st.markdown(f"**{evidence['type'].replace('_', ' ').title()} source**")
    for label, field in (
        ("Source filename", "source_filename"),
        ("Source title", "source_title"),
        ("Source reference", "source_reference"),
    ):
        if evidence.get(field):
            st.write(f"**{label}:** {evidence[field]}")
    if evidence.get("source_url"):
        st.write(f"**Source URL:** {evidence['source_url']}")


def _run_app() -> None:
    main()


if __name__ == "__main__":
    _run_app()
