# GapEngine

TinyFish scraping capability checker script for testing target sites like Indeed and Glassdoor.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## API Key

```bash
export TINYFISH_API_KEY="your_api_key_here"
```

## Run

```bash
python scripts/tinyfish_scrape_check.py
```

Optional flags:

```bash
python scripts/tinyfish_scrape_check.py --use-proxy --proxy-country US --raw-events
```

## Notes

- The script prints JSON per URL and returns exit code `0` only if all checks succeed.
- Respect each website's Terms of Service and robots/access policies before automating collection.

## Deep Debug (Recommended for null results)

Use this when you need full event-level visibility:

```bash
python scripts/tinyfish_stream_debug.py \
  --url "https://www.glassdoor.com/Reviews/index.htm" \
  --goal "Find what employees are saying about Stripe. Return strict JSON with keys: overall_sentiment, pros, cons, common_themes, sample_quotes, source_urls, notes." \
  --use-proxy --proxy-country US \
  --events-out glassdoor_events.ndjson
```

The script prints live event progress and writes raw event records to an `.ndjson` file so you can inspect exactly where `result` is missing.
