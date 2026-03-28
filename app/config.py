from dotenv import load_dotenv
import os

load_dotenv()

TINYFISH_API_KEY = os.getenv("TINYFISH_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "2000"))
TINYFISH_DISCOVERY_TIMEOUT = int(os.getenv("TINYFISH_DISCOVERY_TIMEOUT", "25"))
TINYFISH_OFFICIAL_TIMEOUT = int(os.getenv("TINYFISH_OFFICIAL_TIMEOUT", "90"))
TINYFISH_SOURCE_TIMEOUT = int(os.getenv("TINYFISH_SOURCE_TIMEOUT", "90"))
TINYFISH_BASE_URL = "https://agent.tinyfish.ai/v1/automation/run"

# sufficiency thresholds
MIN_FRAGMENTS = 15
MIN_SOURCES = 3
MAX_SOURCES = 5
MIN_RECENT_FRAGMENTS = 5
MIN_PLATFORM_TYPES = 2
MIN_FRAGMENTS_PER_SOURCE = 5
MIN_LONG_FORM_FRAGMENTS_PER_SOURCE = 2
MAX_FRAGMENTS_PER_SOURCE = 30
NEW_CLAIMS_DIMINISHING_THRESHOLD = 2

# engagement weighting
TRIPADVISOR_HELPFUL_MULTIPLIER = 3
TRIPADVISOR_LOW_RATING_BASE = 50
TRIPADVISOR_LOW_RATING_THRESHOLD = 2

# recency buckets in months
RECENT_MONTHS = 6
MID_MONTHS = 18

# default sources per category — (url_template, platform, platform_type)
DEFAULT_SOURCES = {
    "Travel": [
        ("https://www.reddit.com/search/?q={subject}+review&sort=top", "reddit", "forum"),
        ("https://www.tripadvisor.com/Search?q={subject}", "tripadvisor", "structured_review"),
        ("https://www.cruisecritic.com/search/#?query={subject}", "cruisecritic", "forum"),
    ],
    "Tech": [
        ("https://www.reddit.com/search/?q={subject}+review&sort=top", "reddit", "forum"),
        ("https://www.g2.com/search?query={subject}", "g2", "structured_review"),
        ("https://news.ycombinator.com/search?q={subject}", "hackernews", "forum"),
        ("https://www.trustpilot.com/search?query={subject}", "trustpilot", "structured_review"),
    ],
    "Finance": [
        ("https://www.reddit.com/search/?q={subject}+review&sort=top", "reddit", "forum"),
        ("https://www.trustpilot.com/search?query={subject}", "trustpilot", "structured_review"),
        ("https://www.consumerfinance.gov/search/?q={subject}", "cfpb", "structured_review"),
    ],
    "Entertainment": [
        ("https://www.reddit.com/search/?q={subject}+review&sort=top", "reddit", "forum"),
        ("https://www.metacritic.com/search/{subject}/", "metacritic", "structured_review"),
        ("https://letterboxd.com/search/{subject}/", "letterboxd", "structured_review"),
    ],
    "Health & Wellness": [
        ("https://www.reddit.com/search/?q={subject}+review&sort=top", "reddit", "forum"),
        ("https://www.trustpilot.com/search?query={subject}", "trustpilot", "structured_review"),
        ("https://examine.com/search/?q={subject}", "examine", "long_form"),
    ],
    "Food & Beverage": [
        ("https://www.reddit.com/search/?q={subject}+review&sort=top", "reddit", "forum"),
        ("https://www.yelp.com/search?find_desc={subject}", "yelp", "structured_review"),
        ("https://www.tripadvisor.com/Search?q={subject}", "tripadvisor", "structured_review"),
    ],
    "Education": [
        ("https://www.reddit.com/search/?q={subject}+review&sort=top", "reddit", "forum"),
        ("https://www.coursereport.com/search?q={subject}", "coursereport", "structured_review"),
        ("https://www.trustpilot.com/search?query={subject}", "trustpilot", "structured_review"),
    ],
    "Retail": [
        ("https://www.reddit.com/search/?q={subject}+review&sort=top", "reddit", "forum"),
        ("https://www.trustpilot.com/search?query={subject}", "trustpilot", "structured_review"),
        ("https://www.sitejabber.com/search?q={subject}", "sitejabber", "structured_review"),
    ],
}
