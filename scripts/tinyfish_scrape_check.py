#!/usr/bin/env python3
"""
TinyFish scraping capability check for target websites.

Usage:
  export TINYFISH_API_KEY="..."
  python scripts/tinyfish_scrape_check.py --urls https://www.indeed.com https://www.glassdoor.com
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from tinyfish import BrowserProfile, TinyFish

try:
    from tinyfish import EventType, ProxyConfig, ProxyCountryCode, RunStatus
except ImportError:
    EventType = None  # type: ignore[assignment]
    RunStatus = None  # type: ignore[assignment]
    ProxyConfig = None  # type: ignore[assignment]
    ProxyCountryCode = None  # type: ignore[assignment]


DEFAULT_URLS = [
    "https://www.indeed.com/",
    "https://www.glassdoor.com/",
]

DEFAULT_GOAL = (
    "Extract the top 5 visible job listings (if present). "
    "Return strict JSON with keys: "
    "site_accessible (boolean), "
    "jobs (array of {title, company, location, salary}), "
    "notes (string). "
    "If blocked or no listings found, explain in notes."
)


@dataclass
class CheckResult:
    url: str
    success: bool
    elapsed_seconds: float
    status: str | None
    result: Any
    error: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check TinyFish scraping capability on target URLs.")
    parser.add_argument("--urls", nargs="+", default=DEFAULT_URLS, help="One or more target URLs.")
    parser.add_argument("--goal", default=DEFAULT_GOAL, help="Goal prompt for TinyFish agent.")
    parser.add_argument(
        "--stealth",
        action="store_true",
        default=True,
        help="Use TinyFish stealth browser profile (default: enabled).",
    )
    parser.add_argument(
        "--no-stealth",
        action="store_false",
        dest="stealth",
        help="Disable stealth browser profile.",
    )
    parser.add_argument(
        "--proxy-country",
        default="US",
        help="Proxy country code when proxy is enabled (default: US).",
    )
    parser.add_argument(
        "--use-proxy",
        action="store_true",
        help="Enable TinyFish proxy config (optional).",
    )
    parser.add_argument(
        "--raw-events",
        action="store_true",
        help="Print every stream event for debugging.",
    )
    parser.add_argument(
        "--quiet-events",
        action="store_true",
        help="Hide live event progress logs.",
    )
    return parser.parse_args()


def require_api_key() -> None:
    if os.getenv("TINYFISH_API_KEY"):
        return
    print("ERROR: TINYFISH_API_KEY is not set.", file=sys.stderr)
    print('Set it with: export TINYFISH_API_KEY="your_key_here"', file=sys.stderr)
    sys.exit(2)


def build_proxy_config(use_proxy: bool, proxy_country: str):
    if not use_proxy:
        return None
    if ProxyConfig is None or ProxyCountryCode is None:
        raise RuntimeError("Installed tinyfish version does not expose ProxyConfig/ProxyCountryCode.")
    country_code = getattr(ProxyCountryCode, proxy_country.upper(), None)
    if country_code is None:
        raise ValueError(f"Unsupported proxy country code: {proxy_country}")
    return ProxyConfig(enabled=True, country_code=country_code)


def event_to_status(event: Any) -> str | None:
    status = getattr(event, "status", None)
    if status is None:
        return None
    return getattr(status, "value", str(status))


def should_mark_complete(event: Any) -> bool:
    if EventType is None:
        return str(getattr(event, "type", "")).upper().endswith("COMPLETE")
    return getattr(event, "type", None) == EventType.COMPLETE


def is_completed_status(event: Any) -> bool:
    if RunStatus is None:
        return "COMPLETED" in str(getattr(event, "status", "")).upper()
    return getattr(event, "status", None) == RunStatus.COMPLETED


def event_to_type(event: Any) -> str:
    event_type = getattr(event, "type", None)
    if event_type is None:
        return "UNKNOWN"
    return getattr(event_type, "value", str(event_type))


def run_check(
    client: TinyFish,
    url: str,
    goal: str,
    stealth: bool,
    proxy_config: Any,
    raw_events: bool,
    quiet_events: bool,
) -> CheckResult:
    start = time.time()
    last_status = None
    final_result = None
    error = None
    success = False
    last_printed_progress = None

    kwargs: dict[str, Any] = {
        "url": url,
        "goal": goal,
    }
    if stealth:
        kwargs["browser_profile"] = BrowserProfile.STEALTH
    if proxy_config is not None:
        kwargs["proxy_config"] = proxy_config

    try:
        with client.agent.stream(**kwargs) as stream:
            for event in stream:
                last_status = event_to_status(event)
                if raw_events:
                    print(f"[event] {url} -> {event}")
                elif not quiet_events:
                    event_type = event_to_type(event)
                    progress = f"{event_type} | status={last_status or 'N/A'}"
                    if progress != last_printed_progress:
                        print(f"[progress] {url} -> {progress}", flush=True)
                        last_printed_progress = progress
                if should_mark_complete(event):
                    final_result = getattr(event, "result_json", None)
                    success = is_completed_status(event)
    except Exception as exc:
        error = str(exc)

    elapsed = round(time.time() - start, 2)
    return CheckResult(
        url=url,
        success=success,
        elapsed_seconds=elapsed,
        status=last_status,
        result=final_result,
        error=error,
    )


def main() -> int:
    args = parse_args()
    require_api_key()

    try:
        proxy_config = build_proxy_config(args.use_proxy, args.proxy_country)
    except Exception as exc:
        print(f"ERROR: invalid proxy config: {exc}", file=sys.stderr)
        return 2

    client = TinyFish()
    results: list[CheckResult] = []

    print("Starting TinyFish scraping checks...")
    for url in args.urls:
        print(f"\nChecking: {url}")
        check = run_check(
            client=client,
            url=url,
            goal=args.goal,
            stealth=args.stealth,
            proxy_config=proxy_config,
            raw_events=args.raw_events,
            quiet_events=args.quiet_events,
        )
        results.append(check)
        print(
            json.dumps(
                {
                    "url": check.url,
                    "success": check.success,
                    "status": check.status,
                    "elapsed_seconds": check.elapsed_seconds,
                    "error": check.error,
                    "result": check.result,
                },
                indent=2,
                default=str,
            )
        )

    passed = sum(1 for item in results if item.success)
    print(f"\nSummary: {passed}/{len(results)} checks completed successfully.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
