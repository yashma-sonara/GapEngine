from __future__ import annotations

import argparse
import json
import time

from tinyfish_web_agent import TinyFishWebAgentClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a TinyFish SSE automation from the command line.")
    parser.add_argument("--url", required=True, help="Target URL for TinyFish to open.")
    parser.add_argument("--goal", required=True, help="Natural-language goal for the TinyFish web agent.")
    parser.add_argument(
        "--integration",
        default="gapengine-cli-test",
        help="api_integration label sent to TinyFish.",
    )
    parser.add_argument(
        "--browser-profile",
        default="lite",
        choices=["lite", "stealth"],
        help="TinyFish browser profile.",
    )
    parser.add_argument(
        "--mode",
        default="async",
        choices=["async", "sse"],
        help="Use async polling or raw SSE streaming.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=5,
        help="Polling interval for async mode.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    client = TinyFishWebAgentClient(
        api_integration=args.integration,
        browser_profile=args.browser_profile,
    )

    print("Starting TinyFish SSE run...")
    print(f"URL: {args.url}")
    print(f"Goal: {args.goal}")
    print("-" * 80)

    if args.mode == "sse":
        print("Mode: SSE streaming")
        print("Tip: first events can take a bit to arrive; Ctrl+C interrupts the stream.")
        print("-" * 80)
        for event in client.run_sse(url=args.url, goal=args.goal):
            print(json.dumps(event, indent=2))
            print("-" * 80)
        return

    print("Mode: async polling")
    run_id = client.start_automation(url=args.url, goal=args.goal)
    print(f"Run ID: {run_id}")
    print("-" * 80)

    last_status = None

    while True:
        runs = client.get_runs_batch([run_id])
        run = runs[0] if runs else {}
        status = str(run.get("status") or "UNKNOWN")

        if status != last_status:
            print(f"Status: {status}")
            last_status = status

        if status.upper() in {"COMPLETED", "FAILED", "CANCELLED"}:
            print(json.dumps(run, indent=2))
            print("-" * 80)
            return

        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
