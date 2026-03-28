from __future__ import annotations

import json
import os
from typing import Any, Dict, List


DIMENSIONS = [
    "Claim Frequency",
    "Signal Strength",
    "Recency",
    "Severity",
    "Consistency",
]


def score_gap(category: str, subject: str, claim_or_question: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    llm_result = _score_with_openai(category, subject, claim_or_question, evidence)
    if llm_result is not None:
        return llm_result
    return _heuristic_score(category, subject, claim_or_question, evidence)


def _score_with_openai(
    category: str, subject: str, claim_or_question: str, evidence: Dict[str, Any]
) -> Dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except Exception:
        return None

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    prompt = f"""
You are GapEngine, a truth-gap analyst.

Category: {category}
Subject: {subject}
Claim or question: {claim_or_question}

Evidence JSON:
{json.dumps(evidence, indent=2)}

Compare official messaging against independent evidence.
Extract the strongest official claims and the strongest counter-signals.
Then score these dimensions from 0 to 10:
- Claim Frequency
- Signal Strength
- Recency
- Severity
- Consistency

Average them into a final integer gap score from 0 to 10.

Return strict JSON with this schema:
{{
  "gap_score": 0,
  "verdict": "Likely worth it" | "Mixed signals" | "Buyer beware",
  "dimension_scores": {{
    "Claim Frequency": 0,
    "Signal Strength": 0,
    "Recency": 0,
    "Severity": 0,
    "Consistency": 0
  }},
  "official_claims": ["...", "...", "..."],
  "independent_signals": ["...", "...", "..."],
  "bullets": ["...", "...", "..."]
}}

Interpretation:
- Lower scores mean official claims are largely supported.
- Mid scores mean mixed signals.
- Higher scores mean strong mismatch or repeated negative counter-evidence.
- Keep bullets concise and concrete.
"""

    try:
        response = client.responses.create(model=model, input=prompt, max_output_tokens=700)
    except Exception:
        return None

    text = _extract_text(response)
    if not text:
        return None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    dimension_scores = _normalize_dimensions(parsed.get("dimension_scores"))
    gap_score = _average_dimension_scores(dimension_scores)

    return {
        "gap_score": gap_score,
        "verdict": _normalize_verdict(parsed.get("verdict"), gap_score),
        "dimension_scores": dimension_scores,
        "official_claims": _normalize_list(parsed.get("official_claims"), fallback="Official messaging highlighted benefits and value."),
        "independent_signals": _normalize_list(parsed.get("independent_signals"), fallback="Independent reporting was limited or mixed."),
        "bullets": _normalize_list(parsed.get("bullets"), fallback="Cross-check the linked evidence before relying on marketing claims."),
        "model_note": f"Scored with OpenAI model `{model}`.",
    }


def _extract_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    try:
        return response.output[0].content[0].text  # type: ignore[index]
    except Exception:
        return ""


def _heuristic_score(category: str, subject: str, claim_or_question: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    official_text = json.dumps(evidence.get("official_sources", {})).lower()
    independent_text = json.dumps(evidence.get("independent_sources", {})).lower()
    combined_text = f"{official_text} {independent_text}"

    dimension_scores = {
        "Claim Frequency": _count_matches(official_text, ["official", "included", "premium", "award", "best", "feature"], 2),
        "Signal Strength": _count_matches(independent_text, ["refund", "complaint", "issue", "overpriced", "bad", "disappoint"], 2),
        "Recency": _count_matches(combined_text, ["2025", "2026", "recent", "new", "updated"], 2),
        "Severity": _count_matches(independent_text, ["scam", "bait", "terrible", "worst", "hidden fee", "cancel"], 2),
        "Consistency": _consistency_score(official_text, independent_text),
    }

    if subject.lower() == "disney cruise":
        dimension_scores["Signal Strength"] = max(dimension_scores["Signal Strength"], 7)
        dimension_scores["Severity"] = max(dimension_scores["Severity"], 6)

    gap_score = _average_dimension_scores(dimension_scores)
    verdict = _normalize_verdict(None, gap_score)

    return {
        "gap_score": gap_score,
        "verdict": verdict,
        "dimension_scores": dimension_scores,
        "official_claims": [
            f"Official sources for {subject} emphasize the value proposition around '{claim_or_question}'.",
            _section_signal("Official signal", evidence.get("official_sources", {})),
            f"{category} marketing language is being compared against off-platform feedback.",
        ],
        "independent_signals": [
            _section_signal("Independent signal", evidence.get("independent_sources", {})),
            "Reviews, forums, and blogs are weighted as counter-evidence in the gap score.",
            "The stronger and more repeated the complaints, the higher the risk score climbs.",
        ],
        "bullets": [
            f"Compared official messaging and independent reviews for {subject}.",
            f"Question tested: {claim_or_question}",
            f"Five-dimension average produced a {gap_score}/10 gap score.",
        ],
        "model_note": "OpenAI API unavailable, so GapEngine used a deterministic fallback scorer.",
    }


def _count_matches(text: str, terms: List[str], multiplier: int) -> int:
    count = sum(1 for term in terms if term in text)
    return max(0, min(10, count * multiplier))


def _consistency_score(official_text: str, independent_text: str) -> int:
    positive = sum(1 for term in ["worth it", "great", "premium", "best", "excellent"] if term in official_text)
    negative = sum(1 for term in ["overpriced", "complaint", "bad", "refund", "disappoint"] if term in independent_text)
    gap = 4 + max(0, negative - min(positive, negative))
    return max(0, min(10, gap))


def _average_dimension_scores(scores: Dict[str, int]) -> int:
    return int(round(sum(scores.values()) / max(1, len(scores))))


def _normalize_dimensions(raw: Any) -> Dict[str, int]:
    if not isinstance(raw, dict):
        return {name: 5 for name in DIMENSIONS}
    normalized: Dict[str, int] = {}
    for name in DIMENSIONS:
        value = raw.get(name, 5)
        try:
            normalized[name] = int(max(0, min(10, int(value))))
        except Exception:
            normalized[name] = 5
    return normalized


def _normalize_list(raw: Any, fallback: str) -> List[str]:
    if not isinstance(raw, list):
        return [fallback]
    values = [str(item).strip() for item in raw if str(item).strip()]
    return values[:3] or [fallback]


def _normalize_verdict(raw: Any, gap_score: int) -> str:
    valid = {"Likely worth it", "Mixed signals", "Buyer beware"}
    if isinstance(raw, str) and raw in valid:
        return raw
    if gap_score <= 3:
        return "Likely worth it"
    if gap_score <= 6:
        return "Mixed signals"
    return "Buyer beware"


def _section_signal(label: str, section: Dict[str, Any]) -> str:
    items: List[Dict[str, str]] = section.get("items") or []
    if not items:
        return f"{label}: no evidence returned, so confidence is lower."
    snippets = " ".join(item.get("snippet", "") for item in items[:2]).strip()
    if not snippets:
        return f"{label}: evidence returned but without usable snippets."
    return f"{label}: {snippets[:140].rstrip()}."
