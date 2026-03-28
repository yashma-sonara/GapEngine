# GapEngine

## Live React UI + TinyFish SSE

The project now includes:

- [backend.py](C:/Users/yashm/GapEngine/backend.py) for the API server and TinyFish SSE proxy
- [frontend/index.html](C:/Users/yashm/GapEngine/frontend/index.html) for the app shell
- [frontend/app.js](C:/Users/yashm/GapEngine/frontend/app.js) for the React UI
- [frontend/styles.css](C:/Users/yashm/GapEngine/frontend/styles.css) for the visual design
- [tinyfish_web_agent.py](C:/Users/yashm/GapEngine/tinyfish_web_agent.py) for reusable TinyFish API calls

### Run the app

Install dependencies:

```powershell
pip install -r requirements.txt
```

Start the server:

```powershell
uvicorn backend:app --reload
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The backend serves the frontend and streams TinyFish events live over SSE.

### Category-aware source plans

- `Tech`, `Consumer`, `Finance`, `Health`, `Other`: Company Careers Page, LinkedIn Company Page, Google News / Search, Reddit
- `Travel`: Official Site, Booking.com, Google Reviews / Search, Reddit
- fallback categories: Official Site, Google Reviews / Search, Reddit

### Test TinyFish directly from the terminal

Use [tinyfish_cli_test.py](C:/Users/yashm/GapEngine/tinyfish_cli_test.py) to send a project-style prompt straight to TinyFish and print streamed events in the console:

```powershell
.\.venv\Scripts\python.exe tinyfish_cli_test.py --url "https://www.google.com/search?q=Scale+AI+careers+jobs" --goal "Check the careers page signals, open roles, and whether hiring looks active. Return structured JSON."
```

You can swap the URL and goal for any similar test prompt.

### Test the same GapEngine prompt flow from the terminal

Use [gapengine_test_prompt.py](C:/Users/yashm/GapEngine/gapengine_test_prompt.py) to generate the same category-aware TinyFish prompts as the app:

```powershell
.\.venv\Scripts\python.exe gapengine_test_prompt.py --category "Tech" --subject "Scale AI" --claim "Hiring aggressively"
```

Travel example:

```powershell
.\.venv\Scripts\python.exe gapengine_test_prompt.py --category "Travel" --subject "Disney Cruise" --claim "Is it worth the price?"
```

## TinyFish Web Agent integration

Reusable TinyFish automation client: [tinyfish_web_agent.py](C:/Users/yashm/GapEngine/tinyfish_web_agent.py)

### What it does

- Extracts structured data from multiple competitor websites
- Monitors pricing pages and flags daily changes
- Stores run results in a local SQLite database by default

### TinyFish API endpoints used

- `POST https://agent.tinyfish.ai/v1/automation/run-async`
- `POST https://agent.tinyfish.ai/v1/automation/run-sse`
- `POST https://agent.tinyfish.ai/v1/runs/batch`

### Setup

Set your API key as an environment variable:

```powershell
$env:TINYFISH_API_KEY="your_real_api_key"
```

Or copy `.env.example` to `.env` and fill in your real keys:

```powershell
Copy-Item .env.example .env
```

If you want the script to load `.env` automatically, install `python-dotenv`:

```powershell
pip install python-dotenv
```

### Example

```python
from tinyfish_web_agent import CompetitorTarget, competitor_extract_job, daily_pricing_monitor_job

targets = [
    CompetitorTarget(name="Competitor A", url="https://example.com"),
    CompetitorTarget(name="Competitor B", url="https://example.org/pricing"),
]

extract_rows = competitor_extract_job(targets, db_path="tinyfish_results.db")
pricing_rows = daily_pricing_monitor_job(targets, db_path="tinyfish_results.db")
```

### Database

The default store is SQLite in `tinyfish_results.db`. Replace `ResultStore` with your own adapter if you want PostgreSQL, MySQL, or another database.

### Scheduling daily monitoring

Run `daily_pricing_monitor_job(...)` from:

- Windows Task Scheduler
- cron
- GitHub Actions
- your existing worker or queue
