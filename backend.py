from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List
from urllib.parse import quote_plus

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from scorer import score_gap
from tinyfish_web_agent import TinyFishAPIError, TinyFishWebAgentClient


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"


app = FastAPI(title="GapEngine Live")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")


class AnalyzeRequest(BaseModel):
    category: str
    subject: str
    claim_or_question: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.post("/api/analyze")
def analyze(payload: AnalyzeRequest) -> StreamingResponse:
    def event_stream() -> Iterable[str]:
        try:
            client = TinyFishWebAgentClient(api_integration="gapengine-live")
            source_plan = build_source_plan(payload.category, payload.subject, payload.claim_or_question)
            source_sections: Dict[str, Dict[str, Any]] = {}

            for source in source_plan:
                section = yield from _run_source_scan(client=client, source=source)
                source_sections[source["key"]] = section

            evidence = _build_evidence(payload=payload, source_plan=source_plan, source_sections=source_sections)
            result = score_gap(
                category=payload.category,
                subject=payload.subject,
                claim_or_question=payload.claim_or_question,
                evidence=evidence,
            )

            yield _sse_event(
                "final_report",
                {
                    "result": result,
                    "evidence": evidence,
                    "source_sections": source_sections,
                    "source_plan": source_plan,
                },
            )
        except TinyFishAPIError as exc:
            yield _sse_event("error", {"message": str(exc)})
        except Exception as exc:
            yield _sse_event("error", {"message": f"Unexpected server error: {exc}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def build_source_plan(category: str, subject: str, claim_or_question: str) -> List[Dict[str, str]]:
    normalized = category.strip().lower()

    if normalized == "travel":
        return [
            _source(
                "official_site",
                "Official Site",
                "official",
                f'"{subject}" official site "{claim_or_question}"',
                (
                    f"Research the official site for {subject}. Extract the strongest official claims, pricing or value messaging, "
                    f"inclusions, exclusions, guarantees, and promises relevant to: {claim_or_question}. "
                    "Return structured JSON with claims, snippets, links, and pricing references."
                ),
                "Checking the official site for direct pricing and marketing claims.",
            ),
            _source(
                "booking_reviews",
                "Booking.com",
                "independent",
                f'site:booking.com "{subject}" review rating "{claim_or_question}"',
                (
                    f"Research Booking.com pages and snippets about {subject}. Extract ratings, complaints, praise, price-value comments, "
                    f"and recent traveler signals relevant to: {claim_or_question}. Return structured JSON with snippets and links."
                ),
                "Checking Booking.com for rating and traveler review signals.",
            ),
            _source(
                "google_reviews_search",
                "Google Reviews / Search",
                "independent",
                f'"{subject}" "{claim_or_question}" reviews complaints value worth it',
                (
                    f"Research public Google-indexed reviews and search results for {subject}. Focus on price-value concerns, repeated complaints, "
                    f"and recent customer sentiment relevant to: {claim_or_question}. Return structured JSON with titles, snippets, and links."
                ),
                "Checking public reviews and search results for price-value signals.",
            ),
            _source(
                "reddit",
                "Reddit",
                "independent",
                f'site:reddit.com "{subject}" ("worth it" OR overpriced OR review OR complaint)',
                (
                    f"Research Reddit discussions about {subject}. Focus on honest traveler or customer sentiment, price complaints, hidden fees, "
                    f"and whether people think it is worth it relative to: {claim_or_question}. Return structured JSON with snippets and links."
                ),
                "Checking Reddit for unfiltered user sentiment.",
            ),
        ]

    company_like = normalized in {"tech", "consumer", "finance", "health", "other"}
    if company_like:
        return [
            _source(
                "careers_page",
                "Company Careers Page",
                "official",
                f'"{subject}" careers jobs "{claim_or_question}"',
                (
                    f"Research the careers page for {subject}. Check open roles, role freshness, number of openings, and whether the site supports "
                    f"the claim: {claim_or_question}. Return structured JSON with job titles, snippets, counts, and links."
                ),
                "Checking the careers page for open roles and posting age.",
            ),
            _source(
                "linkedin_company",
                "LinkedIn Company Page",
                "official",
                f'site:linkedin.com/company "{subject}" headcount hiring jobs "{claim_or_question}"',
                (
                    f"Research the public LinkedIn company page for {subject}. Extract headcount trend clues, hiring posture, recent activity, "
                    f"and public jobs-tab signals relevant to: {claim_or_question}. Return structured JSON with snippets and links."
                ),
                "Checking LinkedIn company signals for public hiring posture.",
            ),
            _source(
                "google_news_search",
                "Google News / Search",
                "independent",
                f'"{subject}" "{claim_or_question}" layoffs hiring expansion freeze news',
                (
                    f"Research public Google-indexed news and search results about {subject}. Focus on layoffs, hiring announcements, funding, "
                    f"expansion, or freeze signals relevant to: {claim_or_question}. Return structured JSON with titles, snippets, dates, and links."
                ),
                "Checking Google News and public search results for layoffs or expansion signals.",
            ),
            _source(
                "reddit",
                "Reddit",
                "independent",
                f'site:reddit.com "{subject}" ("ghost interview" OR "hiring freeze" OR layoffs OR recruiter OR interview)',
                (
                    f"Research Reddit discussions about {subject}. Focus on ghost interviews, hiring freezes, recruiter behavior, layoffs, "
                    f"and recent candidate chatter relevant to: {claim_or_question}. Return structured JSON with snippets and links."
                ),
                "Checking Reddit for ghost interview, freeze, and recruiter chatter.",
            ),
        ]

    return [
        _source(
            "official_site",
            "Official Site",
            "official",
            f'"{subject}" official site "{claim_or_question}"',
            (
                f"Research the official site for {subject}. Extract the strongest official claims and value messaging relevant to: "
                f"{claim_or_question}. Return structured JSON with claims, snippets, and links."
            ),
            "Checking the official site for direct marketing claims.",
        ),
        _source(
            "google_reviews_search",
            "Google Reviews / Search",
            "independent",
            f'"{subject}" "{claim_or_question}" reviews complaints worth it',
            (
                f"Research public Google-indexed reviews and search results for {subject}. Focus on repeated complaints, praise, and price-value "
                f"signals relevant to: {claim_or_question}. Return structured JSON with snippets and links."
            ),
            "Checking public reviews and search results for trust signals.",
        ),
        _source(
            "reddit",
            "Reddit",
            "independent",
            f'site:reddit.com "{subject}" (review OR complaint OR "worth it")',
            (
                f"Research Reddit discussions about {subject}. Focus on honest user experience, repeat complaints, and whether users think it supports "
                f"the claim: {claim_or_question}. Return structured JSON with snippets and links."
            ),
            "Checking Reddit for unfiltered user sentiment.",
        ),
    ]


def _source(key: str, label: str, group: str, query: str, goal: str, stage_message: str) -> Dict[str, str]:
    return {
        "key": key,
        "label": label,
        "group": group,
        "query": query,
        "goal": goal,
        "stage_message": stage_message,
    }


def _run_source_scan(
    *,
    client: TinyFishWebAgentClient,
    source: Dict[str, str],
) -> Generator[str, None, Dict[str, Any]]:
    url = f"https://www.google.com/search?q={quote_plus(source['query'])}"
    complete_event: Dict[str, Any] | None = None

    yield _sse_event(
        "stage",
        {
            "stage": source["key"],
            "label": source["label"],
            "message": source["stage_message"],
        },
    )

    for event in client.run_sse(url=url, goal=source["goal"]):
        yield _sse_event(
            "tinyfish_event",
            {
                "stage": source["key"],
                "label": source["label"],
                "tinyfish_event": event,
            },
        )
        if str(event.get("type", "")).upper() == "COMPLETE":
            complete_event = event

    result = complete_event.get("result") if complete_event else None
    return {
        "key": source["key"],
        "label": source["label"],
        "group": source["group"],
        "query": source["query"],
        "summary": _section_summary(source["label"], result),
        "items": _result_to_items(source["label"], result, url),
        "raw_result": result,
    }


def _build_evidence(
    *,
    payload: AnalyzeRequest,
    source_plan: List[Dict[str, str]],
    source_sections: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    official_keys = {source["key"] for source in source_plan if source["group"] == "official"}
    independent_keys = {source["key"] for source in source_plan if source["group"] == "independent"}

    return {
        "official_sources": {
            "label": "Official sources",
            "summary": "Combined evidence from official or company-controlled sources.",
            "items": _combine_items(source_sections, official_keys),
        },
        "independent_sources": {
            "label": "Independent sources",
            "summary": "Combined evidence from public third-party sources.",
            "items": _combine_items(source_sections, independent_keys),
        },
        "source_sections": source_sections,
        "meta": {
            "category": payload.category,
            "subject": payload.subject,
            "claim_or_question": payload.claim_or_question,
            "source": "tinyfish-sse",
        },
    }


def _combine_items(source_sections: Dict[str, Dict[str, Any]], bucket_keys: set[str]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for key in bucket_keys:
        for item in source_sections.get(key, {}).get("items", []):
            if isinstance(item, dict):
                items.append(item)
    return items[:10]


def _result_to_items(source_label: str, result: Any, fallback_url: str) -> List[Dict[str, str]]:
    if result is None:
        return [
            {
                "title": "No structured result returned",
                "url": fallback_url,
                "snippet": "TinyFish completed without a parseable result payload.",
                "source": source_label,
            }
        ]

    if isinstance(result, list):
        iterable: List[Any] = result
    elif isinstance(result, dict):
        iterable = (
            result.get("items")
            or result.get("results")
            or result.get("claims")
            or result.get("signals")
            or result.get("jobs")
            or [result]
        )
    else:
        iterable = [result]

    if not isinstance(iterable, list):
        iterable = [iterable]

    items: List[Dict[str, str]] = []
    for entry in iterable[:6]:
        if isinstance(entry, str):
            items.append(
                {
                    "title": source_label,
                    "url": fallback_url,
                    "snippet": entry,
                    "source": source_label,
                }
            )
            continue

        if not isinstance(entry, dict):
            continue

        title = str(
            entry.get("title")
            or entry.get("claim")
            or entry.get("signal")
            or entry.get("job_title")
            or entry.get("source_name")
            or source_label
        )
        snippet = (
            json.dumps(entry, ensure_ascii=True)
            if any(isinstance(v, (dict, list)) for v in entry.values())
            else str(
                entry.get("snippet")
                or entry.get("summary")
                or entry.get("text")
                or entry.get("description")
                or entry
            )
        )
        items.append(
            {
                "title": title[:140],
                "url": str(entry.get("url") or entry.get("link") or fallback_url),
                "snippet": snippet[:500],
                "source": source_label,
            }
        )

    return items or [
        {
            "title": source_label,
            "url": fallback_url,
            "snippet": json.dumps(result, ensure_ascii=True)[:500],
            "source": source_label,
        }
    ]


def _section_summary(source_label: str, result: Any) -> str:
    if result is None:
        return f"{source_label} scan completed, but no structured evidence was returned."
    return f"TinyFish finished scanning {source_label} and returned structured evidence."


def _sse_event(event_name: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
