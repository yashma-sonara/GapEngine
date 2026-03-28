from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List
from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from scorer import score_gap
from tinyfish_web_agent import TinyFishAPIError, TinyFishWebAgentClient


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
CACHE_DIR = BASE_DIR / "cache"

SOURCE_BUCKETS = {
    "official_sources": "Official sources",
    "independent_sources": "Independent sources",
}

TRUSTED_INDEPENDENT_DOMAINS = (
    "old.reddit.com",
    "trustpilot.com",
    "tripadvisor.com",
    "glassdoor.com",
    "g2.com",
    "wirecutter.com",
    "consumerreports.org",
)

OFFICIAL_ITEM_LIMIT = 3
INDEPENDENT_ITEM_LIMIT = 3
PRELOAD_OFFICIAL_ITEM_LIMIT = 5
PRELOAD_INDEPENDENT_ITEM_LIMIT = 6
CACHE_ONLY_MODE = "cache_only"
CLAIM_KEY_PHRASE_FALLBACK_WORDS = {
    "claims",
    "claim",
    "offers",
    "offer",
    "offering",
    "with",
    "within",
    "that",
    "this",
    "from",
    "their",
    "there",
    "about",
    "into",
    "onto",
    "have",
    "has",
    "had",
    "more",
    "most",
    "very",
    "same",
    "than",
    "ever",
    "best",
    "one",
    "world",
    "months",
}

CATEGORY_EXTRA_DOMAINS = {
    "Government": (
        "gov.sg",
        "nus.edu.sg",
        "channelnewsasia.com",
        "straitstimes.com",
    ),
    "Education": (
        "gov.sg",
        "nus.edu.sg",
        "channelnewsasia.com",
        "straitstimes.com",
    ),
}

CATEGORIES = {
    "Entertainment": [
        "Disney Cruise",
        "Netflix",
        "Peloton",
        "Spotify Premium",
    ],
    "Tech": [
        "Tesla Model 3",
        "Dyson V15",
        "Apple Vision Pro",
        "Notion",
    ],
    "Travel": [
        "Airbnb",
        "Singapore Airlines Business Class",
        "Grab Premium",
        "Klook",
    ],
    "Food & Beverage": [
        "Nespresso",
        "HelloFresh",
        "Hawker Chan",
        "Toast Box",
    ],
    "Finance": [
        "Revolut",
        "Wise",
        "Grab PayLater",
        "StashAway",
    ],
}

logger = logging.getLogger(__name__)

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


@app.get("/cache")
@app.get("/api/cache")
def list_cache() -> List[str]:
    return _list_cached_subjects()


@app.get("/categories")
@app.get("/api/categories")
def list_categories() -> Dict[str, List[str]]:
    return CATEGORIES


@app.post("/analyze", include_in_schema=False)
@app.post("/api/analyze")
async def analyze(
    payload: AnalyzeRequest,
    mode: str | None = Query(default=None),
    preload_mode: bool = Query(default=False),
    force_refresh: bool = Query(default=False),
) -> StreamingResponse:
    cached_payload = None if force_refresh else _load_cached_result(payload.subject)

    if mode == CACHE_ONLY_MODE:
        if cached_payload is None:
            raise HTTPException(
                status_code=404,
                detail=f"No cached result for {payload.subject}.",
            )
        return StreamingResponse(
            _single_event_stream("final_report", cached_payload),
            media_type="text/event-stream",
        )

    async def event_stream() -> AsyncGenerator[str, None]:
        if cached_payload is not None:
            yield _sse_event("final_report", cached_payload)
            return

        try:
            client = TinyFishWebAgentClient(api_integration="gapengine-live")
            queue: asyncio.Queue[str] = asyncio.Queue()
            loop = asyncio.get_running_loop()
            stream_events: List[Dict[str, Any]] = []

            def enqueue_event(event_name: str, event_payload: Dict[str, Any]) -> None:
                stream_events.append({"kind": event_name, **event_payload})
                queue.put_nowait(_sse_event(event_name, event_payload))

            def emit(event_name: str, event_payload: Dict[str, Any]) -> None:
                loop.call_soon_threadsafe(enqueue_event, event_name, event_payload)

            official_task = asyncio.create_task(
                _run_source_scan_async(
                    client=client,
                    stage="official_sources",
                    category=payload.category,
                    subject=payload.subject,
                    claim_or_question=payload.claim_or_question,
                    preload_mode=preload_mode,
                    emit=emit,
                )
            )
            independent_task = asyncio.create_task(
                _run_source_scan_async(
                    client=client,
                    stage="independent_sources",
                    category=payload.category,
                    subject=payload.subject,
                    claim_or_question=payload.claim_or_question,
                    preload_mode=preload_mode,
                    emit=emit,
                )
            )

            pending = {official_task, independent_task}
            while pending:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    pass
                pending = {task for task in pending if not task.done()}

            while not queue.empty():
                yield await queue.get()

            source_sections = {
                "official_sources": _task_result_or_fallback(
                    official_task,
                    "official_sources",
                    payload,
                ),
                "independent_sources": _task_result_or_fallback(
                    independent_task,
                    "independent_sources",
                    payload,
                ),
            }
            evidence = _build_evidence(
                payload=payload,
                source_sections=source_sections,
                preload_mode=preload_mode,
            )
            low_signal = (
                len(evidence["independent_sources"].get("items", [])) < 2
            )

            result = await asyncio.to_thread(
                score_gap,
                payload.category,
                payload.subject,
                payload.claim_or_question,
                evidence,
            )
            result["official_claims"] = (
                result.get("official_claims") or []
            )[:_official_claim_limit(preload_mode)]
            result["independent_signals"] = (
                result.get("independent_signals") or []
            )[:_independent_signal_limit(preload_mode)]

            final_payload = {
                "result": result,
                "evidence": evidence,
                "source_sections": source_sections,
                "low_signal": low_signal,
                "stream_events": stream_events,
            }
            _save_cached_result(payload.subject, final_payload)

            yield _sse_event("final_report", final_payload)
        except TinyFishAPIError as exc:
            yield _sse_event("error", {"message": str(exc)})
        except Exception as exc:
            logger.exception("Unexpected server error during analysis")
            yield _sse_event(
                "error",
                {"message": f"Unexpected server error: {exc}"},
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _single_event_stream(
    event_name: str,
    payload: Dict[str, Any],
) -> AsyncGenerator[str, None]:
    yield _sse_event(event_name, payload)


async def _run_source_scan_async(
    *,
    client: TinyFishWebAgentClient,
    stage: str,
    category: str,
    subject: str,
    claim_or_question: str,
    preload_mode: bool,
    emit: Callable[[str, Dict[str, Any]], None],
) -> Dict[str, Any]:
    try:
        task = asyncio.to_thread(
            _run_source_scan_blocking,
            client,
            stage,
            category,
            subject,
            claim_or_question,
            preload_mode,
            emit,
        )
        return await task
    except TinyFishAPIError as exc:
        logger.warning("TinyFish failed for %s: %s", stage, exc)
        emit(
            "tinyfish_event",
            {
                "stage": stage,
                "label": SOURCE_BUCKETS[stage],
                "tinyfish_event": {
                    "type": "ERROR",
                    "purpose": str(exc),
                },
            },
        )
        query = _search_query(
            stage=stage,
            category=category,
            subject=subject,
            claim_or_question=claim_or_question,
        )
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        return _fallback_section(
            stage=stage,
            query=query,
            fallback_url=url,
            reason=str(exc),
        )


def _run_source_scan_blocking(
    client: TinyFishWebAgentClient,
    stage: str,
    category: str,
    subject: str,
    claim_or_question: str,
    preload_mode: bool,
    emit: Callable[[str, Dict[str, Any]], None],
) -> Dict[str, Any]:
    claim_key_phrase = (
        _claim_key_phrase(subject, claim_or_question)
        if stage == "official_sources"
        else None
    )
    query = _search_query(
        stage=stage,
        category=category,
        subject=subject,
        claim_or_question=claim_or_question,
        claim_key_phrase=claim_key_phrase,
    )
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    goal = _goal(
        stage=stage,
        category=category,
        subject=subject,
        claim_or_question=claim_or_question,
        preload_mode=preload_mode,
        claim_key_phrase=claim_key_phrase,
    )

    complete_event: Dict[str, Any] | None = None

    emit(
        "stage",
        {
            "stage": stage,
            "label": SOURCE_BUCKETS[stage],
            "message": _stage_message(stage),
        },
    )

    for event in client.run_sse(
        url=url,
        goal=goal,
    ):
        emit(
            "tinyfish_event",
            {
                "stage": stage,
                "label": SOURCE_BUCKETS[stage],
                "tinyfish_event": event,
            },
        )
        event_type = str(event.get("type", "")).upper()
        if event_type == "COMPLETE":
            complete_event = event
        elif complete_event is None and event.get("result"):
            complete_event = event

    result = complete_event.get("result") if complete_event else None
    if result is None:
        return _fallback_section(
            stage=stage,
            query=query,
            fallback_url=url,
            reason=(
                "TinyFish returned no structured result. "
                "Falling back to search snippets."
            ),
        )

    return {
        "key": stage,
        "label": SOURCE_BUCKETS[stage],
        "query": query,
        "summary": _section_summary(stage, result),
        "items": _result_to_items(stage, result, url, preload_mode),
        "raw_result": result,
    }


def _task_result_or_fallback(
    task: asyncio.Task[Dict[str, Any]],
    stage: str,
    payload: AnalyzeRequest,
) -> Dict[str, Any]:
    query = _search_query(
        stage=stage,
        category=payload.category,
        subject=payload.subject,
        claim_or_question=payload.claim_or_question,
    )
    fallback_url = f"https://www.google.com/search?q={quote_plus(query)}"

    if task.cancelled():
        return _fallback_section(
            stage=stage,
            query=query,
            fallback_url=fallback_url,
            reason="Scan was cancelled.",
        )

    exception = task.exception()
    if exception is not None:
        logger.warning(
            "Falling back after task failure for %s: %s",
            stage,
            exception,
        )
        return _fallback_section(
            stage=stage,
            query=query,
            fallback_url=fallback_url,
            reason=str(exception),
        )

    return task.result()


def _build_evidence(
    payload: AnalyzeRequest,
    source_sections: Dict[str, Dict[str, Any]],
    preload_mode: bool,
) -> Dict[str, Any]:
    official_section = source_sections.get("official_sources", {})
    independent_section = source_sections.get("independent_sources", {})

    return {
        "official_sources": {
            "label": "Official sources",
            "summary": str(
                official_section.get("summary")
                or "Official sources were checked."
            ),
            "items": list(official_section.get("items") or [])[
                :_official_claim_limit(preload_mode)
            ],
        },
        "independent_sources": {
            "label": "Independent sources",
            "summary": str(
                independent_section.get("summary")
                or "Independent sources were checked."
            ),
            "items": list(independent_section.get("items") or [])[
                :_independent_signal_limit(preload_mode)
            ],
        },
        "source_sections": source_sections,
        "meta": {
            "category": payload.category,
            "subject": payload.subject,
            "claim_or_question": payload.claim_or_question,
            "source": "tinyfish-sse",
        },
    }


def _search_query(
    *,
    stage: str,
    category: str,
    subject: str,
    claim_or_question: str,
    claim_key_phrase: str | None = None,
) -> str:
    extra_domains = CATEGORY_EXTRA_DOMAINS.get(category, ())

    if stage == "official_sources":
        key_phrase = claim_key_phrase or _claim_key_phrase(subject, claim_or_question)
        official_domain = _official_domain(subject, category, claim_or_question)
        return f'"{subject}" "{key_phrase}" site:{official_domain}'

    trusted_domains = list(TRUSTED_INDEPENDENT_DOMAINS)
    trusted_domains.extend(extra_domains)
    trusted_clause = " OR ".join(f"site:{domain}" for domain in trusted_domains)
    return f'"{subject}" {category} "{claim_or_question}" ({trusted_clause})'


def _goal(
    *,
    stage: str,
    category: str,
    subject: str,
    claim_or_question: str,
    preload_mode: bool,
    claim_key_phrase: str | None = None,
) -> str:
    if stage == "official_sources":
        key_phrase = claim_key_phrase or _claim_key_phrase(subject, claim_or_question)
        return (
            f"Research official public sources for {subject} in the {category} category. "
            f"Search for official pages, press releases, or statements from {subject} that are specifically about {key_phrase}. "
            "Ignore careers pages, job listings, investor relations pages, and unrelated product pages. "
            f"Focus on direct brand claims and support for the claim: {claim_or_question}. "
            f"Return at most {_official_claim_limit(preload_mode)} concise items with titles, snippets, and links. "
            "If a page is blocked, empty, or too slow, fall back to the Google search snippet text instead of retrying the page."
        )

    trusted_domains = list(TRUSTED_INDEPENDENT_DOMAINS)
    trusted_domains.extend(CATEGORY_EXTRA_DOMAINS.get(category, ()))
    trusted = ", ".join(trusted_domains)
    return (
        f"Research independent public sources about {subject} in the {category} category. "
        f"Only use these trusted domains: {trusted}. "
        f"Focus on public reviews, forum discussions, complaints, and product quality signals relevant to: {claim_or_question}. "
        f"Return at most {_independent_signal_limit(preload_mode)} concise items with titles, snippets, links, and negative or mixed signal hints. "
        "If a page is blocked, empty, or too slow, fall back to the Google search snippet text instead of retrying the page."
    )


def _result_to_items(
    stage: str,
    result: Any,
    fallback_url: str,
    preload_mode: bool,
) -> List[Dict[str, str]]:
    limit = (
        _official_claim_limit(preload_mode)
        if stage == "official_sources"
        else _independent_signal_limit(preload_mode)
    )

    if result is None:
        return [
            {
                "title": "No structured result returned",
                "url": fallback_url,
                "snippet": "TinyFish completed without a parseable result payload. Google search snippet fallback should be used for demo backup.",
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
    for entry in iterable[:limit]:
        if isinstance(entry, str):
            items.append(
                {
                    "title": SOURCE_BUCKETS[stage],
                    "url": fallback_url,
                    "snippet": entry[:500],
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
        snippet = json.dumps(entry, ensure_ascii=True) if any(isinstance(value, (dict, list)) for value in entry.values()) else str(
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
        return f"{SOURCE_BUCKETS[stage]} scan completed, but only fallback evidence was available."
    return f"TinyFish finished scanning {SOURCE_BUCKETS[stage]} and returned structured evidence."


def _stage_message(stage: str) -> str:
    if stage == "official_sources":
        return "Checking official sources for direct brand claims and hiring posture."
    return "Checking trusted review and forum domains for independent signals."


def _fallback_section(*, stage: str, query: str, fallback_url: str, reason: str) -> Dict[str, Any]:
    return {
        "key": stage,
        "label": SOURCE_BUCKETS[stage],
        "query": query,
        "summary": f"{SOURCE_BUCKETS[stage]} fallback used: {reason}",
        "items": [
            {
                "title": f"Fallback search for {SOURCE_BUCKETS[stage]}",
                "url": fallback_url,
                "snippet": reason,
                "source": SOURCE_BUCKETS[stage],
            }
        ],
        "raw_result": None,
    }


def _cache_path(subject: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{_subject_slug(subject)}.json"


def _load_cached_result(subject: str) -> Dict[str, Any] | None:
    cache_path = _cache_path(subject)
    if not cache_path.exists():
        return None

    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Ignoring unreadable cache file: %s", cache_path)
        return None


def _save_cached_result(subject: str, payload: Dict[str, Any]) -> None:
    cache_path = _cache_path(subject)
    cache_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _list_cached_subjects() -> List[str]:
    if not CACHE_DIR.exists():
        return []

    subjects: List[str] = []
    for cache_file in sorted(CACHE_DIR.glob("*.json")):
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            subject = str(payload.get("evidence", {}).get("meta", {}).get("subject") or "").strip()
        except (OSError, json.JSONDecodeError):
            subject = ""

        subjects.append(subject or _subject_from_slug(cache_file.stem))

    return subjects


def _subject_slug(subject: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", subject.strip().lower())
    return normalized.strip("_") or "subject"


def _subject_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("_") if part)


def _official_claim_limit(preload_mode: bool) -> int:
    if preload_mode:
        return PRELOAD_OFFICIAL_ITEM_LIMIT
    return OFFICIAL_ITEM_LIMIT


def _independent_signal_limit(preload_mode: bool) -> int:
    if preload_mode:
        return PRELOAD_INDEPENDENT_ITEM_LIMIT
    return INDEPENDENT_ITEM_LIMIT


def _domain_hint(subject: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", subject.lower())
    return f"{normalized}.com" if normalized else "example.com"


def _official_domain(subject: str, category: str, claim_or_question: str) -> str:
    subject_lower = subject.lower()
    claim_lower = claim_or_question.lower()

    if "nus" in subject_lower:
        return "nus.edu.sg"
    if "singapore healthcare" in subject_lower or "healthcare system" in claim_lower:
        return "gov.sg"

    category_domains = CATEGORY_EXTRA_DOMAINS.get(category, ())
    if category_domains:
        subject_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", subject_lower)
            if len(token) >= 3
        }
        for domain in category_domains:
            if any(token in domain for token in subject_tokens):
                return domain

    return _domain_hint(subject)


def _claim_key_phrase(subject: str, claim_or_question: str) -> str:
    llm_phrase = _claim_key_phrase_with_openai(subject, claim_or_question)
    if llm_phrase:
        return llm_phrase
    return _claim_key_phrase_fallback(subject, claim_or_question)


def _claim_key_phrase_with_openai(subject: str, claim_or_question: str) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except Exception:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    client = OpenAI(api_key=api_key)
    prompt = f"""
Extract a 3-5 word key phrase capturing what this claim is actually about.
Return strict JSON with one field:
{{"key_phrase":"..."}}

Subject: {subject}
Claim: {claim_or_question}

Examples:
- "NUS claims a 97% graduate employment rate within 6 months of graduation" -> "graduate employment rate"
- "Apple claims the iPhone 16 camera system is the biggest leap in mobile photography ever" -> "iPhone 16 camera system"
- "Grab claims it offers the most affordable and transparent pricing" -> "affordable transparent pricing"
"""

    try:
        response = client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=40,
        )
    except Exception:
        return None

    text = _extract_response_text(response)
    if not text:
        return None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    raw_phrase = parsed.get("key_phrase")
    if not isinstance(raw_phrase, str):
        return None

    return _normalize_key_phrase(raw_phrase)


def _claim_key_phrase_fallback(subject: str, claim_or_question: str) -> str:
    claim = re.sub(r"\s+", " ", claim_or_question.strip())
    patterns = (
        r"claims?\s+(?:that\s+)?(?:it|they|its|their|there is|there are)\s+(.*)",
        r"claims?\s+(.*)",
        r"is\s+(.*)",
        r"are\s+(.*)",
    )

    candidate = claim
    for pattern in patterns:
        match = re.search(pattern, claim, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(" .,:;!?")
            break

    subject_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", subject.lower())
        if token
    }
    words = re.findall(r"[A-Za-z0-9]+", candidate)
    kept_words: List[str] = []
    for word in words:
        lowered = word.lower()
        if lowered in CLAIM_KEY_PHRASE_FALLBACK_WORDS:
            continue
        if lowered in subject_tokens and kept_words:
            continue
        kept_words.append(word)
        if len(kept_words) == 5:
            break

    if len(kept_words) < 3:
        claim_words = [
            word
            for word in re.findall(r"[A-Za-z0-9]+", claim)
            if word.lower() not in CLAIM_KEY_PHRASE_FALLBACK_WORDS
        ]
        kept_words = claim_words[:5]

    return _normalize_key_phrase(" ".join(kept_words) or claim)


def _normalize_key_phrase(raw_phrase: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", raw_phrase)
    cleaned = " ".join(words[:5]).strip()
    return cleaned or "official claim"


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text).strip()

    try:
        return str(response.output[0].content[0].text).strip()  # type: ignore[index]
    except Exception:
        return ""


def _sse_event(event_name: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
