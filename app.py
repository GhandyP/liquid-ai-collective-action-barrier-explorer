"""Local Streamlit interface for the fictional D1 case demonstration."""

from __future__ import annotations

from copy import deepcopy

import streamlit as st

from src.app_state import (
    AppStateError,
    HumanReviewValidationError,
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


def main() -> None:
    st.set_page_config(page_title="D1 Hypothesis Review", layout="wide")
    st.title("D1 — Fictional Case Hypothesis Review")
    st.warning(
        "Results are hypotheses based on supplied evidence, not causal findings, "
        "facts about a population, or judgments about individuals. This demo is "
        "not for profiling, targeting, or persuading people."
    )

    selected_mode = st.sidebar.radio("Run mode", options=("mock", "live"), index=0)
    st.sidebar.caption("Mock is the offline default. Live is opt-in and requires LIQUID_API_KEY; D1_MODEL is optional.")
    st.sidebar.caption("The Liquid SDK, API, and model contract are unverified. Live failures remain errors.")
    st.caption("Use synthetic or anonymized summaries only. Do not enter personal, confidential, transcript, or respondent-row data.")

    try:
        fixture_case = load_synthetic_case()
    except AppStateError as error:
        st.error(str(error))
        st.stop()
        return

    focus_evidence = next(
        item for item in fixture_case["evidence"] if item["type"] == "focus_group_summary"
    )
    survey_evidence = next(
        item for item in fixture_case["evidence"] if item["type"] == "survey_aggregate"
    )

    with st.form("case_run_form"):
        st.subheader("Case")
        action_column, observation_column = st.columns(2)
        with action_column:
            action_description = st.text_input(
                "Desired action", value=fixture_case["desired_action"]["description"]
            )
            actor_group = st.text_input(
                "Actor group", value=fixture_case["desired_action"]["actor_group"]
            )
            time_horizon = st.text_input(
                "Time horizon", value=fixture_case["desired_action"]["time_horizon"]
            )
            observable_success = st.text_input(
                "Observable success", value=fixture_case["desired_action"]["observable_success"]
            )
        with observation_column:
            observed_non_action = st.text_input(
                "Observed non-action", value=fixture_case["observed_non_action"]["description"]
            )
            observation_period = st.text_input(
                "Period", value=fixture_case["observed_non_action"]["period"]
            )

        st.subheader("Separate evidence summaries")
        focus_column, survey_column = st.columns(2)
        with focus_column:
            st.markdown("#### Focus-group summary")
            st.caption(
                f"{focus_evidence['study_id']} · {focus_evidence['collection_date']} · "
                f"{focus_evidence['participants_n']} fictional participants"
            )
            focus_theme = st.text_area(
                "Anonymized theme summary — not raw transcript",
                value=focus_evidence["theme"],
                height=110,
            )
            dissent_text = st.text_area(
                "Dissenting summary points — one per line",
                value="\n".join(focus_evidence.get("dissenting_views", [])),
                height=90,
            )
            st.caption("Focus-group themes do not estimate how common a view is.")
            for limitation in focus_evidence["limitations"]:
                st.caption(f"Limitation: {limitation}")

        with survey_column:
            st.markdown("#### Aggregate survey")
            st.caption(
                f"{survey_evidence['study_id']} · {survey_evidence['collection_date']} · "
                f"{survey_evidence['sampling_method']}"
            )
            survey_question = st.text_area(
                "Aggregate item wording",
                value=survey_evidence["question"],
                height=110,
            )
            st.caption(
                f"Invited: {survey_evidence['respondents_invited_n']} · "
                f"responses received: {survey_evidence['responses_received_n']} · "
                f"valid denominator: {survey_evidence['valid_n']} · "
                f"item missing: {survey_evidence['item_missing_n']}"
            )
            count_columns = st.columns(len(survey_evidence["response_scale"]))
            for column, option in zip(count_columns, survey_evidence["response_scale"]):
                with column:
                    st.metric(
                        option.replace("_", " "),
                        f"{survey_evidence['response_counts'][option]}/{survey_evidence['valid_n']}",
                    )
            st.caption("Each count is shown over the valid-response denominator; the synthetic distribution is not causal or representative.")
            for limitation in survey_evidence["limitations"]:
                st.caption(f"Limitation: {limitation}")

        run_submitted = st.form_submit_button(f"Run selected mode: {selected_mode}")

    if run_submitted:
        case = deepcopy(fixture_case)
        case["desired_action"].update(
            {
                "description": action_description,
                "actor_group": actor_group,
                "time_horizon": time_horizon,
                "observable_success": observable_success,
            }
        )
        case["observed_non_action"].update(
            {"description": observed_non_action, "period": observation_period}
        )
        case["evidence"][0]["theme"] = focus_theme
        dissenting_views = [line.strip() for line in dissent_text.splitlines() if line.strip()]
        if dissenting_views:
            case["evidence"][0]["dissenting_views"] = dissenting_views
        else:
            case["evidence"][0].pop("dissenting_views", None)
        case["evidence"][1]["question"] = survey_question

        st.session_state["run_state"] = run_case(case, selected_mode)
        st.session_state["human_review"] = {"status": "pending", "override_reason": None}
        st.session_state["review_decision"] = "pending"
        st.session_state["review_reason"] = ""

    run_state = st.session_state.get("run_state")
    if run_state is None:
        st.info(f"Run status: not run. Selected mode: {selected_mode}.")
        return

    st.metric("Run status", run_state["run_status"])
    if run_state["run_status"] == "error":
        st.error(run_state["error"]["message"])
        return

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


def _run_app() -> None:
    main()


if __name__ == "__main__":
    _run_app()
