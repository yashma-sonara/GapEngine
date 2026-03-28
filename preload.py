from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib import error, request


PRELOAD_MODE = True

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"

PRELOAD_SUBJECTS = [
    (
        "Tech",
        "Apple iPhone 16",
        "Apple claims the iPhone 16 camera system is the biggest leap in mobile photography ever",
    ),
    (
        "Food & Beverage",
        "Chick-fil-A Singapore",
        "Chick-fil-A claims its Singapore outlet serves the same quality and recipe as the US original",
    ),
    (
        "Transport",
        "Grab",
        "Grab claims it offers the most affordable and transparent pricing for rides in Southeast Asia",
    ),
    (
        "Government",
        "Singapore",
        "Singapore claims to be the least corrupt country in Asia",
    ),
    (
        "Government",
        "Singapore Healthcare",
        "Singapore claims to have one of the best healthcare systems in the world",
    ),
    (
        "Education",
        "NUS",
        "NUS claims a 97% graduate employment rate within 6 months of graduation",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preload GapEngine cache entries through the FastAPI analyze endpoint."
    )
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:8000/api/analyze",
        help="Full analyze endpoint URL.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore existing cache files and refresh every preload subject.",
    )
    return parser.parse_args()


def build_payload(category: str, subject: str, claim_or_question: str) -> Dict[str, str]:
    return {
        "category": category,
        "subject": subject,
        "claim_or_question": claim_or_question,
    }


def stream_analyze(
    endpoint: str,
    payload: Dict[str, str],
    force_refresh: bool,
) -> Dict[str, Any]:
    query = "?preload_mode=true"
    if force_refresh:
        query += "&force_refresh=true"

    req = request.Request(
        f"{endpoint}{query}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        open_kwargs: Dict[str, Any] = {}
        if not PRELOAD_MODE:
            open_kwargs["timeout"] = 60

        with request.urlopen(req, **open_kwargs) as response:
            buffer = ""
            for raw_chunk in response:
                buffer += raw_chunk.decode("utf-8", errors="replace")
                chunks = buffer.split("\n\n")
                buffer = chunks.pop() or ""
                for chunk in chunks:
                    parsed = parse_sse_chunk(chunk)
                    if not parsed:
                        continue
                    if parsed["event"] == "error":
                        raise RuntimeError(parsed["data"].get("message") or "Unknown preload error")
                    if parsed["event"] == "final_report":
                        return parsed["data"]
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Connection error: {exc}") from exc

    raise RuntimeError("Analyze stream ended without a final_report event.")


def parse_sse_chunk(chunk: str) -> Dict[str, Any] | None:
    event_name = "message"
    data_lines: List[str] = []
    for line in chunk.splitlines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())

    if not data_lines:
        return None

    try:
        return {"event": event_name, "data": json.loads("\n".join(data_lines))}
    except json.JSONDecodeError:
        return None


def preload_subjects(
    subjects: Iterable[tuple[str, str, str]],
    endpoint: str,
    force_refresh: bool,
) -> None:
    subject_list = list(subjects)
    total = len(subject_list)

    for index, (category, subject, claim_or_question) in enumerate(subject_list, start=1):
        cache_path = _cache_path(subject)
        cache_label = cache_path.relative_to(BASE_DIR).as_posix()

        if cache_path.exists() and not force_refresh:
            print(f"[{index}/{total}] Skipping: {subject} (already cached)")
            continue

        payload = build_payload(category, subject, claim_or_question)
        print(f"Starting: {subject}")

        try:
            report = stream_analyze(endpoint, payload, force_refresh)
            gap_score = report.get("result", {}).get("gap_score", "unknown")
            print(
                f"Done: {subject} - gap_score: {gap_score} - cached to {cache_label}"
            )
        except Exception as exc:
            print(f"FAILED: {subject} - error: {exc}")


def _cache_path(subject: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{_subject_slug(subject)}.json"


def _subject_slug(subject: str) -> str:
    return "_".join(
        chunk for chunk in "".join(
            character.lower() if character.isalnum() else "_"
            for character in subject.strip()
        ).split("_") if chunk
    ) or "subject"


def main() -> None:
    args = parse_args()
    preload_subjects(PRELOAD_SUBJECTS, args.endpoint, args.force)


if __name__ == "__main__":
    main()