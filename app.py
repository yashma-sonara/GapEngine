from __future__ import annotations

from typing import Dict, List

import streamlit as st

from agents import gather_gap_evidence
from scorer import score_gap


CATEGORY_OPTIONS: List[str] = [
    "Travel",
    "Entertainment",
    "Tech",
    "Education",
    "Government",
    "Food and Beverage",
    "Transport",
]

DEMO_SUBJECTS: Dict[str, Dict[str, str]] = {
    "Disney Cruise": {
        "category": "Travel",
        "question": "Is it worth the price?",
    },
    "Notion AI": {
        "category": "Tech",
        "question": "Does it actually save teams time?",
    },
    "MasterClass": {
        "category": "Entertainment",
        "question": "Is it worth paying annually?",
    },
}


def load_demo(subject: str, category: str, question: str) -> None:
    st.session_state["subject_name"] = subject
    st.session_state["category_name"] = category
    st.session_state["question_text"] = question


def render_section(section: Dict[str, object]) -> None:
    st.caption(str(section.get("summary") or ""))
    for item in section.get("items", []):
        if not isinstance(item, dict):
            continue
        title = item.get("title") or "Untitled result"
        url = item.get("url") or ""
        snippet = item.get("snippet") or "No snippet returned."
        source = item.get("source") or "public web"
        st.markdown(f"**{title}**")
        st.write(snippet)
        if url:
            st.markdown(f"[{source}]({url})")
        else:
            st.caption(str(source))
        st.divider()


st.set_page_config(page_title="GapEngine", page_icon="G", layout="centered")

st.title("GapEngine")
st.caption("Claim-vs-reality detector for the TinyFish SG Hackathon")
st.write(
    "Pick a category, type a subject, and test a claim or question against official messaging and independent evidence."
)

with st.sidebar:
    st.subheader("Demo presets")
    for subject, demo in DEMO_SUBJECTS.items():
        if st.button(subject, use_container_width=True):
            load_demo(subject, demo["category"], demo["question"])
    st.markdown(
        """
        **Runtime keys**
        - `OPENAI_API_KEY`
        - `TINYFISH_API_KEY` or custom TinyFish env vars
        """
    )

default_subject = st.session_state.get("subject_name", "Disney Cruise")
default_category = st.session_state.get("category_name", "Travel")
default_question = st.session_state.get("question_text", "Is it worth the price?")

with st.form("gap_form"):
    category = st.selectbox(
        "Category",
        CATEGORY_OPTIONS,
        index=CATEGORY_OPTIONS.index(default_category) if default_category in CATEGORY_OPTIONS else 0,
    )
    subject = st.text_input("Subject", value=default_subject, placeholder="Disney Cruise")
    claim_or_question = st.text_area(
        "Claim or question",
        value=default_question,
        height=90,
        placeholder="Is it worth the price?",
    )
    submitted = st.form_submit_button("Analyze gap", use_container_width=True)

if submitted:
    if not subject.strip() or not claim_or_question.strip():
        st.error("Enter both a subject and a claim or question.")
    else:
        with st.spinner("Scraping official and independent sources..."):
            evidence = gather_gap_evidence(
                category=category.strip(),
                subject=subject.strip(),
                claim_or_question=claim_or_question.strip(),
            )
        with st.spinner("Scoring the credibility gap..."):
            result = score_gap(
                category=category.strip(),
                subject=subject.strip(),
                claim_or_question=claim_or_question.strip(),
                evidence=evidence,
            )

        top_left, top_right = st.columns([1, 2])
        with top_left:
            st.metric("Gap Score", f"{result['gap_score']}/10")
        with top_right:
            verdict = result["verdict"]
            if verdict == "Likely worth it":
                st.success(f"Verdict: {verdict}")
            elif verdict == "Mixed signals":
                st.warning(f"Verdict: {verdict}")
            else:
                st.error(f"Verdict: {verdict}")

        st.subheader("Dimension breakdown")
        breakdown = result["dimension_scores"]
        cols = st.columns(len(breakdown))
        for col, (name, value) in zip(cols, breakdown.items()):
            with col:
                st.metric(name, f"{value}/10")

        st.subheader("Official claim vs. independent evidence")
        compare_left, compare_right = st.columns(2)
        with compare_left:
            st.markdown("**Official claims**")
            for bullet in result["official_claims"]:
                st.write(f"- {bullet}")
        with compare_right:
            st.markdown("**Independent counter-signals**")
            for bullet in result["independent_signals"]:
                st.write(f"- {bullet}")

        st.subheader("Why")
        for bullet in result["bullets"]:
            st.write(f"- {bullet}")

        st.subheader("Evidence")
        tabs = st.tabs(["Official sources", "Independent sources"])
        with tabs[0]:
            render_section(evidence["official_sources"])
        with tabs[1]:
            render_section(evidence["independent_sources"])

        if result.get("model_note"):
            st.caption(result["model_note"])
