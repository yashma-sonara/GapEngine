from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Optional
from urllib import error, request


BASE_URL = "https://agent.tinyfish.ai/v1"
DEFAULT_DB_PATH = "tinyfish_results.db"


try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


class TinyFishAPIError(RuntimeError):
    pass


@dataclass
class CompetitorTarget:
    name: str
    url: str
    category: str = "competitor"


class TinyFishWebAgentClient:
    """Reusable TinyFish Web Agent client for async automations."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = BASE_URL,
        api_integration: str = "gapengine",
        browser_profile: str = "lite",
    ) -> None:
        _load_local_env()
        self.api_key = api_key or os.getenv("TINYFISH_API_KEY")
        if not self.api_key:
            raise TinyFishAPIError("Set TINYFISH_API_KEY before calling the TinyFish Web Agent API.")

        self.base_url = base_url.rstrip("/")
        self.api_integration = api_integration
        self.browser_profile = browser_profile

    def start_automation(
        self,
        *,
        url: str,
        goal: str,
        proxy_config: Optional[Dict[str, Any]] = None,
        feature_flags: Optional[Dict[str, Any]] = None,
    ) -> str:
        payload = self._build_payload(
            url=url,
            goal=goal,
            proxy_config=proxy_config,
            feature_flags=feature_flags,
        )
        response = self._request("POST", "/automation/run-async", payload)
        run_id = response.get("run_id")
        if not run_id:
            raise TinyFishAPIError(f"Unexpected TinyFish response: {response}")
        return str(run_id)

    def run_sse(
        self,
        *,
        url: str,
        goal: str,
        proxy_config: Optional[Dict[str, Any]] = None,
        feature_flags: Optional[Dict[str, Any]] = None,
        use_vault: bool = False,
        credential_item_ids: Optional[List[str]] = None,
    ) -> Iterator[Dict[str, Any]]:
        payload = self._build_payload(
            url=url,
            goal=goal,
            proxy_config=proxy_config,
            feature_flags=feature_flags,
        )
        if use_vault:
            payload["use_vault"] = True
        if credential_item_ids:
            payload["credential_item_ids"] = credential_item_ids

        req = request.Request(
            f"{self.base_url}/automation/run-sse",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-API-Key": self.api_key,
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=300) as response:
                buffer: List[str] = []
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line.startswith("data:"):
                        buffer.append(line[5:].strip())
                    elif line == "" and buffer:
                        event_text = "\n".join(buffer)
                        buffer = []
                        try:
                            yield json.loads(event_text)
                        except json.JSONDecodeError:
                            yield {"type": "MESSAGE", "raw": event_text}
                if buffer:
                    event_text = "\n".join(buffer)
                    try:
                        yield json.loads(event_text)
                    except json.JSONDecodeError:
                        yield {"type": "MESSAGE", "raw": event_text}
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise TinyFishAPIError(f"TinyFish HTTP {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise TinyFishAPIError(f"TinyFish connection error: {exc}") from exc

    def get_runs_batch(self, run_ids: List[str]) -> List[Dict[str, Any]]:
        if not run_ids:
            return []
        response = self._request("POST", "/runs/batch", {"run_ids": run_ids})
        return list(response.get("data") or [])

    def wait_for_runs(
        self,
        run_ids: List[str],
        *,
        poll_interval_seconds: int = 10,
        timeout_seconds: int = 300,
    ) -> List[Dict[str, Any]]:
        pending = set(run_ids)
        results: Dict[str, Dict[str, Any]] = {}
        deadline = time.time() + timeout_seconds

        while pending:
            if time.time() > deadline:
                raise TimeoutError(f"Timed out waiting for TinyFish runs: {sorted(pending)}")

            for run in self.get_runs_batch(sorted(pending)):
                run_id = str(run.get("run_id"))
                results[run_id] = run
                status = str(run.get("status") or "").upper()
                if status in {"COMPLETED", "FAILED", "CANCELLED"}:
                    pending.discard(run_id)

            if pending:
                time.sleep(poll_interval_seconds)

        return [results[run_id] for run_id in run_ids if run_id in results]

    def extract_competitor_data(
        self,
        competitors: Iterable[CompetitorTarget],
        *,
        proxy_config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        run_map: Dict[str, CompetitorTarget] = {}
        for competitor in competitors:
            goal = (
                "Extract structured data from this competitor website. "
                "Capture products or services, pricing, plan names, positioning, promotions, "
                "target customer, differentiators, and any visible FAQs or claims. "
                "Return clean structured JSON."
            )
            run_id = self.start_automation(url=competitor.url, goal=goal, proxy_config=proxy_config)
            run_map[run_id] = competitor

        completed_runs = self.wait_for_runs(list(run_map.keys()))
        rows: List[Dict[str, Any]] = []
        for run in completed_runs:
            competitor = run_map[str(run["run_id"])]
            rows.append(
                {
                    "run_id": run.get("run_id"),
                    "job_type": "competitor_extract",
                    "subject": competitor.name,
                    "category": competitor.category,
                    "source_url": competitor.url,
                    "status": run.get("status"),
                    "goal": run.get("goal"),
                    "result": run.get("result"),
                    "error": run.get("error"),
                    "captured_at": _utc_now(),
                }
            )
        return rows

    def monitor_pricing(
        self,
        pricing_pages: Iterable[CompetitorTarget],
        *,
        proxy_config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        run_map: Dict[str, CompetitorTarget] = {}
        for page in pricing_pages:
            goal = (
                "Find all visible pricing information on this page or linked pricing pages. "
                "Extract plan names, currencies, list prices, discounts, trial details, "
                "billing cadence, usage caps, and any new promotions. Return structured JSON."
            )
            run_id = self.start_automation(url=page.url, goal=goal, proxy_config=proxy_config)
            run_map[run_id] = page

        completed_runs = self.wait_for_runs(list(run_map.keys()))
        snapshots: List[Dict[str, Any]] = []
        for run in completed_runs:
            page = run_map[str(run["run_id"])]
            snapshots.append(
                {
                    "run_id": run.get("run_id"),
                    "job_type": "pricing_monitor",
                    "subject": page.name,
                    "category": page.category,
                    "source_url": page.url,
                    "status": run.get("status"),
                    "goal": run.get("goal"),
                    "result": run.get("result"),
                    "error": run.get("error"),
                    "captured_at": _utc_now(),
                }
            )
        return snapshots

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
        }
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, headers=headers, method=method)

        try:
            with request.urlopen(req, timeout=60) as response:
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise TinyFishAPIError(f"TinyFish HTTP {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise TinyFishAPIError(f"TinyFish connection error: {exc}") from exc

        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            raise TinyFishAPIError(f"TinyFish returned non-JSON response: {body}") from exc

    def _build_payload(
        self,
        *,
        url: str,
        goal: str,
        proxy_config: Optional[Dict[str, Any]] = None,
        feature_flags: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "url": url,
            "goal": goal,
            "browser_profile": self.browser_profile,
            "api_integration": self.api_integration,
        }
        if proxy_config:
            payload["proxy_config"] = proxy_config
        if feature_flags:
            payload["feature_flags"] = feature_flags
        return payload


class ResultStore:
    """SQLite-backed store; replace with your own DB adapter if needed."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tinyfish_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    category TEXT,
                    source_url TEXT NOT NULL,
                    status TEXT,
                    goal TEXT,
                    result_json TEXT,
                    error_json TEXT,
                    captured_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tinyfish_runs_subject_job_time
                ON tinyfish_runs(subject, job_type, captured_at DESC)
                """
            )

    def save_rows(self, rows: Iterable[Dict[str, Any]]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO tinyfish_runs (
                    run_id, job_type, subject, category, source_url, status, goal,
                    result_json, error_json, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.get("run_id"),
                        row.get("job_type"),
                        row.get("subject"),
                        row.get("category"),
                        row.get("source_url"),
                        row.get("status"),
                        row.get("goal"),
                        json.dumps(row.get("result")),
                        json.dumps(row.get("error")),
                        row.get("captured_at"),
                    )
                    for row in rows
                ],
            )

    def latest_snapshot(self, subject: str, job_type: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM tinyfish_runs
                WHERE subject = ? AND job_type = ?
                ORDER BY captured_at DESC
                LIMIT 1
                """,
                (subject, job_type),
            ).fetchone()

        if row is None:
            return None

        return {
            "run_id": row["run_id"],
            "job_type": row["job_type"],
            "subject": row["subject"],
            "category": row["category"],
            "source_url": row["source_url"],
            "status": row["status"],
            "goal": row["goal"],
            "result": _safe_json_loads(row["result_json"]),
            "error": _safe_json_loads(row["error_json"]),
            "captured_at": row["captured_at"],
        }


def daily_pricing_monitor_job(
    pricing_pages: Iterable[CompetitorTarget],
    *,
    db_path: str = DEFAULT_DB_PATH,
    proxy_config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    client = TinyFishWebAgentClient()
    store = ResultStore(db_path)

    latest_by_subject = {
        target.name: store.latest_snapshot(target.name, "pricing_monitor")
        for target in pricing_pages
    }

    new_rows = client.monitor_pricing(pricing_pages, proxy_config=proxy_config)
    store.save_rows(new_rows)

    for row in new_rows:
        previous = latest_by_subject.get(str(row["subject"]))
        row["pricing_changed"] = _result_changed(previous["result"], row["result"]) if previous else True

    return new_rows


def competitor_extract_job(
    competitors: Iterable[CompetitorTarget],
    *,
    db_path: str = DEFAULT_DB_PATH,
    proxy_config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    client = TinyFishWebAgentClient()
    store = ResultStore(db_path)
    rows = client.extract_competitor_data(competitors, proxy_config=proxy_config)
    store.save_rows(rows)
    return rows


def example_usage() -> None:
    competitors = [
        CompetitorTarget(name="Acme", url="https://example.com"),
        CompetitorTarget(name="Bravo", url="https://example.org/pricing"),
    ]

    extracted = competitor_extract_job(competitors)
    print("Competitor extracts:")
    print(json.dumps(extracted, indent=2))

    pricing = daily_pricing_monitor_job(competitors)
    print("Pricing snapshots:")
    print(json.dumps(pricing, indent=2))


def _result_changed(previous: Any, current: Any) -> bool:
    return json.dumps(previous, sort_keys=True) != json.dumps(current, sort_keys=True)


def _safe_json_loads(value: Optional[str]) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_local_env() -> None:
    if load_dotenv is not None:
        load_dotenv()


if __name__ == "__main__":
    example_usage()
