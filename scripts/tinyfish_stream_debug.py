#!/usr/bin/env python3
"""
Minimal TinyFish stream debugger.

Purpose:
- Show live event flow with useful fields.
- Persist raw event payloads for post-run inspection.
- Explain why final result may be null.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from tinyfish import BrowserProfile, TinyFish

try:
    from tinyfish import ProxyConfig, ProxyCountryCode
except ImportError:
    ProxyConfig = None  # type: ignore[assignment]
    ProxyCountryCode = None  # type: ignore[assignment]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TinyFish stream debugger")
    parser.add_argument("--url", required=True, help="Target URL")
    parser.add_argument("--goal", required=True, help="TinyFish goal prompt")
    parser.add_argument("--stealth", action="store_true", default=True, help="Use stealth profile (default: on)")
    parser.add_argument("--no-stealth", action="store_false", dest="stealth", help="Disable stealth profile")
    parser.add_argument("--use-proxy", action="store_true", help="Enable proxy")
    parser.add_argument("--proxy-country", default="US", help="Proxy country code (default: US)")
    parser.add_argument(
        "--events-out",
        default="tinyfish_events.ndjson",
        help="Output file for raw event records (default: tinyfish_events.ndjson)",
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


def safe_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return dict(value.__dict__)
        except Exception:
            pass
    return str(value)


def event_type(event: Any) -> str:
    value = getattr(event, "type", None)
    return getattr(value, "value", str(value)) if value is not None else "UNKNOWN"


def event_status(event: Any) -> str | None:
    value = getattr(event, "status", None)
    return getattr(value, "value", str(value)) if value is not None else None


def likely_complete(event: Any) -> bool:
    return "COMPLETE" in event_type(event).upper()


def extract_result(event: Any) -> Any:
    for key in ("result_json", "result", "output", "data"):
        if hasattr(event, key):
            value = getattr(event, key)
            if value is not None:
                return safe_jsonable(value)
    return None


def to_record(event: Any, elapsed_seconds: float) -> dict[str, Any]:
    payload = safe_jsonable(event)
    if not isinstance(payload, dict):
        payload = {"raw": payload}
    return {
        "elapsed_seconds": round(elapsed_seconds, 2),
        "type": event_type(event),
        "status": event_status(event),
        "result_candidate": extract_result(event),
        "payload": payload,
    }


def main() -> int:
    args = parse_args()
    require_api_key()

    try:
        proxy_config = build_proxy_config(args.use_proxy, args.proxy_country)
    except Exception as exc:
        print(f"ERROR: invalid proxy config: {exc}", file=sys.stderr)
        return 2

    client = TinyFish()
    start = time.time()
    event_count = 0
    final_result = None
    final_status = None
    last_event_type = None
    last_error = None

    kwargs: dict[str, Any] = {"url": args.url, "goal": args.goal}
    if args.stealth:
        kwargs["browser_profile"] = BrowserProfile.STEALTH
    if proxy_config is not None:
        kwargs["proxy_config"] = proxy_config

    print(f"Starting TinyFish run for {args.url}")
    print(f"Events file: {args.events_out}")

    try:
        with open(args.events_out, "w", encoding="utf-8") as out:
            with client.agent.stream(**kwargs) as stream:
                for event in stream:
                    event_count += 1
                    elapsed = time.time() - start
                    record = to_record(event, elapsed)
                    out.write(json.dumps(record, default=str) + "\n")
                    out.flush()

                    e_type = record["type"]
                    e_status = record["status"]
                    result_candidate = record["result_candidate"]
                    print(
                        f"[{record['elapsed_seconds']:>6}s] "
                        f"event#{event_count:<3} type={e_type} status={e_status or 'N/A'} "
                        f"has_result={'yes' if result_candidate is not None else 'no'}",
                        flush=True,
                    )

                    last_event_type = e_type
                    final_status = e_status
                    if result_candidate is not None:
                        final_result = result_candidate
                    if likely_complete(event):
                        # Keep streaming until server closes, but note completion event.
                        print(f"Completion event observed at {record['elapsed_seconds']}s", flush=True)
    except Exception as exc:
        last_error = str(exc)

    total = round(time.time() - start, 2)
    summary = {
        "url": args.url,
        "elapsed_seconds": total,
        "events_seen": event_count,
        "last_event_type": last_event_type,
        "final_status": final_status,
        "error": last_error,
        "final_result": final_result,
        "events_file": args.events_out,
    }
    print("\nRun summary:")
    print(json.dumps(summary, indent=2, default=str))

    if final_result is None:
        print(
            "\nNo final result payload was found in known fields "
            "(`result_json`, `result`, `output`, `data`). "
            f"Inspect {args.events_out} for raw payload details.",
            file=sys.stderr,
        )
        return 1
    if last_error:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
