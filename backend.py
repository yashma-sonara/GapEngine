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

SOURCE_BUCKETS = {
    "careers_page": "Company Careers Page",
    "linkedin_company": "LinkedIn Company Page",
    "google_news_search": "Google News / Search",
    "reddit": "Reddit",
}

OFFICIAL_BUCKETS = {"careers_page", "linkedin_company"}
INDEPENDENT_BUCKETS = {"google_news_search", "reddit"}

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
            source_sections: Dict[str, Dict[str, Any]] = {}

            for stage in SOURCE_BUCKETS:
                section = yield from _run_source_scan(
                    client=client,
                    stage=stage,
                    category=payload.category,
                    subject=payload.subject,
                    claim_or_question=payload.claim_or_question,
                )
                source_sections[stage] = section

            evidence = _build_evidence(payload=payload, source_sections=source_sections)
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
                },
            )
        except TinyFishAPIError as exc:
            yield _sse_event("error", {"message": str(exc)})
        except Exception as exc:
            yield _sse_event("error", {"message": f"Unexpected server error: {exc}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _run_source_scan(
    *,
    client: TinyFishWebAgentClient,
    stage: str,
    category: str,
    subject: str,
    claim_or_question: str,
) -> Generator[str, None, Dict[str, Any]]:
    query = _search_query(stage=stage, category=category, subject=subject, claim_or_question=claim_or_question)
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    goal = _goal(stage=stage, category=category, subject=subject, claim_or_question=claim_or_question)

    complete_event: Dict[str, Any] | None = None

    yield _sse_event(
        "stage",
        {
            "stage": stage,
            "label": SOURCE_BUCKETS[stage],
            "message": _stage_message(stage),
        },
    )

    for event in client.run_sse(url=url, goal=goal):
        yield _sse_event(
            "tinyfish_event",
            {
                "stage": stage,
                "label": SOURCE_BUCKETS[stage],
                "tinyfish_event": event,
            },
        )
        if str(event.get("type", "")).upper() == "COMPLETE":
            complete_event = event

    result = complete_event.get("result") if complete_event else None
    return {
        "key": stage,
        "label": SOURCE_BUCKETS[stage],
        "query": query,
        "summary": _section_summary(stage, result),
        "items": _result_to_items(stage, result, url),
        "raw_result": result,
    }


def _build_evidence(payload: AnalyzeRequest, source_sections: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    official_items = _combine_items(source_sections, OFFICIAL_BUCKETS)
    independent_items = _combine_items(source_sections, INDEPENDENT_BUCKETS)

    return {
        "official_sources": {
            "label": "Official sources",
            "summary": "Combined official evidence from careers and LinkedIn.",
            "items": official_items,
        },
        "independent_sources": {
            "label": "Independent sources",
            "summary": "Combined public evidence from Google News/Search and Reddit.",
            "items": independent_items,
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
        section = source_sections.get(key, {})
        for item in section.get("items", []):
            if isinstance(item, dict):
                items.append(item)
    return items[:10]


def _search_query(*, stage: str, category: str, subject: str, claim_or_question: str) -> str:
    if stage == "careers_page":
        return f'"{subject}" careers jobs "{claim_or_question}"'
    if stage == "linkedin_company":
        return f'site:linkedin.com/company "{subject}" headcount hiring jobs "{claim_or_question}"'
    if stage == "google_news_search":
        return f'"{subject}" {category} "{claim_or_question}" layoffs hiring expansion news'
    return f'site:reddit.com "{subject}" ("ghost" OR "hiring freeze" OR layoffs OR recruiter OR interview)'


def _goal(*, stage: str, category: str, subject: str, claim_or_question: str) -> str:
    if stage == "careers_page":
        return (
            f"Research the careers page for {subject}. "
            f"Check open roles, job posting age, number of openings, and whether the site supports the claim: {claim_or_question}. "
            "Return structured JSON with titles, job ages, counts, snippets, and links."
        )
    if stage == "linkedin_company":
        return (
            f"Research the public LinkedIn company page for {subject}. "
            f"Extract public headcount trend clues, hiring posture, recent activity, and job-tab signals relevant to: {claim_or_question}. "
            "Return structured JSON with sources, signals, snippets, and links."
        )
    if stage == "google_news_search":
        return (
            f"Research public Google-indexed news and search results about {subject} in the {category} category. "
            f"Focus on recent layoffs, hiring announcements, funding, expansion, or freeze signals relevant to: {claim_or_question}. "
            "Return structured JSON with source titles, snippets, dates if visible, sentiment, and links."
        )
    return (
        f"Research Reddit discussions about {subject}. "
        f"Focus on ghost interviews, hiring freezes, layoffs, recruiter behavior, and recent candidate or customer chatter relevant to: {claim_or_question}. "
        "Return structured JSON with thread titles, snippets, sentiment, severity hints, and links."
    )


def _result_to_items(stage: str, result: Any, fallback_url: str) -> List[Dict[str, str]]:
    if result is None:
        return [
            {
                "title": "No structured result returned",
                "url": fallback_url,
                "snippet": "TinyFish completed without a parseable result payload.",
                "source": SOURCE_BUCKETS[stage],
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
                    "title": SOURCE_BUCKETS[stage],
                    "url": fallback_url,
                    "snippet": entry,
                    "source": SOURCE_BUCKETS[stage],
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
            or SOURCE_BUCKETS[stage]
        )
        snippet = json.dumps(entry, ensure_ascii=True) if any(isinstance(v, (dict, list)) for v in entry.values()) else str(
            entry.get("snippet")
            or entry.get("summary")
            or entry.get("text")
            or entry.get("description")
            or entry
        )
        items.append(
            {
                "title": title[:140],
                "url": str(entry.get("url") or entry.get("link") or fallback_url),
                "snippet": snippet[:500],
                "source": SOURCE_BUCKETS[stage],
            }
        )

    return items or [
        {
            "title": SOURCE_BUCKETS[stage],
            "url": fallback_url,
            "snippet": json.dumps(result, ensure_ascii=True)[:500],
            "source": SOURCE_BUCKETS[stage],
        }
    ]


def _section_summary(stage: str, result: Any) -> str:
    if result is None:
        return f"{SOURCE_BUCKETS[stage]} scan completed, but no structured evidence was returned."
    return f"TinyFish finished scanning {SOURCE_BUCKETS[stage]} and returned structured evidence."


def _stage_message(stage: str) -> str:
    if stage == "careers_page":
        return "Checking the company careers page for open roles and posting age."
    if stage == "linkedin_company":
        return "Checking LinkedIn company signals for public hiring posture."
    if stage == "google_news_search":
        return "Checking Google News and public search results for layoffs or expansion signals."
    return "Checking Reddit for ghost interview, freeze, and recruiter chatter."


def _sse_event(event_name: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
