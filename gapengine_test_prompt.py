from __future__ import annotations

import argparse
import json
import time
from urllib.parse import quote_plus

from backend import build_source_plan
from tinyfish_web_agent import TinyFishWebAgentClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run GapEngine-style TinyFish prompts from the terminal.")
    parser.add_argument("--category", required=True, help="Category like Tech or Travel.")
    parser.add_argument("--subject", required=True, help="Company, product, or destination name.")
    parser.add_argument("--claim", required=True, help="Claim or question to test.")
    parser.add_argument("--mode", choices=["async", "sse"], default="async", help="Execution mode.")
    parser.add_argument("--poll-seconds", type=int, default=5, help="Polling interval in async mode.")
    parser.add_argument("--timeout-seconds", type=int, default=180, help="Timeout in async mode.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    client = TinyFishWebAgentClient(api_integration="gapengine-cli")
    source_plan = build_source_plan(args.category, args.subject, args.claim)

    print(f"Category: {args.category}")
    print(f"Subject: {args.subject}")
    print(f"Claim: {args.claim}")
    print("=" * 80)

    for source in source_plan:
        print(f"[{source['label']}]")
        print(f"Query: {source['query']}")
        print(f"Goal: {source['goal']}")
        print("-" * 80)

        url = f"https://www.google.com/search?q={quote_plus(source['query'])}"
        if args.mode == "sse":
            for event in client.run_sse(url=url, goal=source["goal"]):
                print(json.dumps(event, indent=2))
                print("-" * 80)
            continue

        run_id = client.start_automation(url=url, goal=source["goal"])
        print(f"Run ID: {run_id}")
        deadline = time.time() + args.timeout_seconds
        last_status = None
        while time.time() < deadline:
            run = (client.get_runs_batch([run_id]) or [{}])[0]
            status = str(run.get("status") or "UNKNOWN")
            if status != last_status:
                print(f"Status: {status}")
                last_status = status
            if status.upper() in {"COMPLETED", "FAILED", "CANCELLED"}:
                print(json.dumps(run, indent=2))
                print("=" * 80)
                break
            time.sleep(args.poll_seconds)
        else:
            print(f"Timed out waiting for run {run_id}")
            print("=" * 80)


if __name__ == "__main__":
    main()
