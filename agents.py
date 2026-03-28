from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib import error, parse, request


EvidenceItem = Dict[str, str]
EvidenceSection = Dict[str, Any]
EvidenceBundle = Dict[str, EvidenceSection]


@dataclass
class SearchTask:
    key: str
    label: str
    query: str
    fallback_summary: str


class TinyFishClient:
    """TinyFish/OpenFish adapter with SDK-first and HTTP fallback search."""

    def __init__(self) -> None:
        self.api_key = os.getenv("TINYFISH_API_KEY", "")
        self.base_url = os.getenv("TINYFISH_BASE_URL", "").rstrip("/")
        self.search_path = os.getenv("TINYFISH_SEARCH_PATH", "/search")

    def search(self, query: str, limit: int = 4) -> List[EvidenceItem]:
        sdk_results = self._search_with_sdk(query, limit)
        if sdk_results is not None:
            return sdk_results

        http_results = self._search_with_http(query, limit)
        if http_results is not None:
            return http_results

        return []

    def _search_with_sdk(self, query: str, limit: int) -> Optional[List[EvidenceItem]]:
        try:
            import tinyfish  # type: ignore
        except Exception:
            return None

        candidates = []
        if hasattr(tinyfish, "Client"):
            try:
                client = tinyfish.Client(api_key=self.api_key) if self.api_key else tinyfish.Client()
                candidates.append(client)
            except Exception:
                pass

        candidates.append(tinyfish)

        for candidate in candidates:
            for method_name in ("search", "browse", "query", "extract"):
                method = getattr(candidate, method_name, None)
                if not callable(method):
                    continue

                payloads = (
                    {"query": query, "limit": limit},
                    {"q": query, "limit": limit},
                    {"query": query},
                )

                for kwargs in payloads:
                    try:
                        raw = method(**kwargs)
                        items = self._normalize_results(raw, limit)
                        if items:
                            return items
                    except Exception:
                        continue
        return None

    def _search_with_http(self, query: str, limit: int) -> Optional[List[EvidenceItem]]:
        if not self.base_url:
            return None

        endpoint = f"{self.base_url}{self.search_path}"
        payload = json.dumps({"query": query, "limit": limit}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=20) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError):
            return None

        return self._normalize_results(raw, limit)

    def _normalize_results(self, raw: Any, limit: int) -> List[EvidenceItem]:
        if raw is None:
            return []

        if isinstance(raw, dict):
            for key in ("results", "items", "data", "documents"):
                if key in raw and isinstance(raw[key], list):
                    raw = raw[key]
                    break

        if not isinstance(raw, list):
            return []

        normalized: List[EvidenceItem] = []
        for item in raw[:limit]:
            if isinstance(item, str):
                normalized.append(
                    {
                        "title": item[:80],
                        "url": "",
                        "snippet": item,
                        "source": "TinyFish",
                    }
                )
                continue

            if not isinstance(item, dict):
                continue

            normalized.append(
                {
                    "title": str(item.get("title") or item.get("name") or item.get("headline") or "Result"),
                    "url": str(item.get("url") or item.get("link") or ""),
                    "snippet": str(
                        item.get("snippet")
                        or item.get("summary")
                        or item.get("text")
                        or item.get("content")
                        or "No snippet returned."
                    ),
                    "source": str(item.get("source") or item.get("domain") or "TinyFish"),
                }
            )
        return normalized


def gather_gap_evidence(category: str, subject: str, claim_or_question: str) -> EvidenceBundle:
    client = TinyFishClient()

    tasks = [
        SearchTask(
            key="official_sources",
            label="Official sources",
            query=_official_query(category, subject, claim_or_question),
            fallback_summary="Official sources unavailable from TinyFish, preserving a direct search backup.",
        ),
        SearchTask(
            key="independent_sources",
            label="Independent sources",
            query=_independent_query(category, subject, claim_or_question),
            fallback_summary="Independent sources unavailable from TinyFish, preserving a direct search backup.",
        ),
    ]

    bundle: EvidenceBundle = {}
    for task in tasks:
        items = client.search(task.query, limit=4)
        bundle[task.key] = {
            "label": task.label,
            "query": task.query,
            "summary": _build_summary(task.label, items, task.fallback_summary),
            "items": items or [_fallback_item(task, subject)],
        }

    bundle["meta"] = {
        "category": category,
        "subject": subject,
        "claim_or_question": claim_or_question,
        "tinyfish_configured": bool(client.api_key or client.base_url),
    }
    return bundle


def _official_query(category: str, subject: str, claim_or_question: str) -> str:
    domain_hint = _domain_hint(subject)
    return (
        f'"{subject}" {category} ({claim_or_question}) '
        f'(site:{domain_hint} OR "press release" OR "official site" OR "newsroom" OR marketing)'
    )


def _independent_query(category: str, subject: str, claim_or_question: str) -> str:
    return (
        f'"{subject}" {category} ({claim_or_question}) '
        '("reddit" OR "tripadvisor" OR "review" OR "blog" OR "forum" OR "complaint")'
    )


def _domain_hint(subject: str) -> str:
    normalized = subject.lower().replace(" ", "")
    safe = "".join(ch for ch in normalized if ch.isalnum())
    return f"{safe}.com"


def _build_summary(label: str, items: List[EvidenceItem], fallback_summary: str) -> str:
    if not items:
        return fallback_summary
    return f"{label}: found {len(items)} public results for this side of the comparison."


def _fallback_item(task: SearchTask, subject: str) -> EvidenceItem:
    query = parse.quote_plus(task.query)
    return {
        "title": f"Search for {subject} evidence",
        "url": f"https://www.google.com/search?q={query}",
        "snippet": (
            "TinyFish results were not available in this runtime. "
            "This fallback link preserves the exact public query for demo backup."
        ),
        "source": "Search fallback",
    }
