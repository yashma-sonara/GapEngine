import requests
from urllib.parse import quote
from config import (
    TINYFISH_API_KEY,
    TINYFISH_BASE_URL,
    TINYFISH_DISCOVERY_TIMEOUT,
    TINYFISH_OFFICIAL_TIMEOUT,
    TINYFISH_SOURCE_TIMEOUT,
    MAX_FRAGMENTS_PER_SOURCE,
)


class TinyFishClient:
    def __init__(self):
        self.api_key = TINYFISH_API_KEY
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def discover_sources(self, subject: str, claim: str, category: str) -> list:
        goal = f"""
        Search for independent reviews and discussions about "{subject}"
        related to: "{claim}"

        From the search results find the top 6-8 URLs that contain
        real user reviews or discussions. Exclude the brand's own site.

        For each URL return:
        - url
        - platform (reddit, tripadvisor, trustpilot, blog etc)
        - platform_type (forum, structured_review, long_form)
        - estimated_reviews (guess from snippet how many reviews/comments exist)
        - requires_login (true/false)

        Return as JSON array only. No markdown.
        """

        search_url = f"https://www.google.com/search?q={quote(subject + ' honest review ' + category)}"
        return self._post(
            search_url,
            goal,
            timeout=TINYFISH_DISCOVERY_TIMEOUT,
            operation="discover_sources",
        )

    def scrape_official(self, subject: str, claim: str, category: str) -> dict:
        goal = f"""
        You are finding the official website for "{subject}" and extracting
        their marketing claims related to: "{claim}"

        1. Find and navigate to the official brand site from these search results
        2. Dismiss any popups or cookie banners
        3. Extract all marketing claims, value propositions, and promises
        4. Note any statistics, awards, or endorsements cited
        5. Extract pricing or value messaging if visible

        For each claim extract:
        - claim_text
        - location (hero, pricing, FAQ, about etc)
        - has_supporting_stat (true/false)

        Return as JSON:
        {{
          "claims": [{{"claim_text": str, "location": str, "has_supporting_stat": bool}}],
          "metadata": {{
            "source_url": str,
            "platform": "official_site",
            "platform_type": "official",
            "fragments_extracted": int,
            "blocked": false
          }}
        }}

        Return JSON only. No markdown.
        """

        search_url = f"https://www.google.com/search?q={quote(subject + ' official site ' + category)}"
        return self._post(
            search_url,
            goal,
            timeout=TINYFISH_OFFICIAL_TIMEOUT,
            operation="scrape_official",
        )

    def scrape_source(
        self, url: str, platform_type: str, subject: str, claim: str
    ) -> dict:
        goal = self._build_goal(platform_type, subject, claim)
        return self._post(
            url,
            goal,
            timeout=TINYFISH_SOURCE_TIMEOUT,
            operation=f"scrape_source:{platform_type}",
        )

    def _build_goal(self, platform_type: str, subject: str, claim: str) -> str:
        base = f"""
        Extract user opinions about "{subject}" relevant to: "{claim}"

        1. Dismiss any popups, cookie banners, or login prompts if possible
        2. If a login wall blocks content that cannot be dismissed return {{"blocked": true}}
        3. Only extract fragments relevant to the claim being investigated
        """

        metadata_block = """
        At the end include a metadata object:
        {{
          "source_url": str,
          "platform": str,
          "platform_type": str,
          "total_visible_content": int,
          "fragments_extracted": int,
          "blocked": bool,
          "login_wall_hit": bool,
          "pagination_available": bool,
          "oldest_date_seen": str,
          "newest_date_seen": str
        }}

        Return JSON only with keys "fragments" and "metadata". No markdown.
        """

        if platform_type == "forum":
            specific = f"""
        4. Scroll down to load all visible comments
        5. For each relevant comment extract:
           - text (truncate to 300 chars)
           - upvotes (number shown, 0 if not visible)
           - date (exact or relative string)
           - is_reply (true/false)
        6. Stop after {MAX_FRAGMENTS_PER_SOURCE} relevant comments

        Fragments schema:
        [{{"text": str, "upvotes": int, "date": str, "is_reply": bool}}]
            """

        elif platform_type == "structured_review":
            specific = f"""
        4. Sort by Most Recent if the option is available
        5. For each review extract:
           - text (truncate to 300 chars)
           - rating (number out of 5, null if not shown)
           - date (exact or relative string)
           - helpful_votes (0 if not shown)
           - reviewer_type (family, couple, solo, business etc if shown)
        6. Click Read more on truncated reviews if visible
        7. Stop after {MAX_FRAGMENTS_PER_SOURCE} reviews

        Fragments schema:
        [{{"text": str, "rating": int, "date": str, "helpful_votes": int, "reviewer_type": str}}]
            """

        elif platform_type == "long_form":
            specific = """
        4. Read the full article or post
        5. Extract distinct claims or opinions made about the subject
        6. For each extract:
           - text (the claim or opinion, truncated to 300 chars)
           - date (article publish date if visible)
           - author_type (journalist, blogger, expert, unknown)

        Fragments schema:
        [{"text": str, "date": str, "author_type": str}]
            """

        else:
            specific = f"""
        4. Extract all visible user opinions or reviews
        5. For each extract:
           - text (truncate to 300 chars)
           - date (if visible)
           - engagement (any numeric signal — likes, votes, helpful)
        6. Stop after {MAX_FRAGMENTS_PER_SOURCE} items

        Fragments schema:
        [{{"text": str, "date": str, "engagement": int}}]
            """

        return base + specific + metadata_block

    def _post(self, url: str, goal: str, timeout: int, operation: str) -> dict:
        try:
            print(f"[TinyFish] {operation}: starting request")
            print(f"[TinyFish] {operation}: timeout={timeout}s url={url}")
            response = requests.post(
                TINYFISH_BASE_URL,
                headers=self.headers,
                json={
                    "url": url,
                    "goal": goal,
                    "browser_profile": "stealth",
                    "proxy_config": {"enabled": True, "country_code": "US"},
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            normalized = self._unwrap_result(payload)
            print(
                f"[TinyFish] {operation}: success status={response.status_code} "
                f"payload_type={type(normalized).__name__}"
            )
            if isinstance(normalized, dict):
                print(
                    f"[TinyFish] {operation}: keys={sorted(normalized.keys())}"
                )
                if "fragments" in normalized:
                    print(
                        f"[TinyFish] {operation}: fragments="
                        f"{len(normalized.get('fragments') or [])}"
                    )
            elif isinstance(normalized, list):
                print(f"[TinyFish] {operation}: items={len(normalized)}")
            return normalized

        except requests.exceptions.Timeout:
            print(f"[TinyFish] {operation}: timeout after {timeout}s")
            return {"blocked": True, "error": "timeout", "operation": operation}
        except requests.exceptions.RequestException as e:
            print(f"[TinyFish] {operation}: request failed: {e}")
            return {"blocked": True, "error": str(e), "operation": operation}

    def _unwrap_result(self, payload):
        """
        TinyFish responses can come back wrapped in one or more "result" keys.
        Normalize them so downstream callers always see the actual object/list.
        """
        current = payload
        while isinstance(current, dict) and "result" in current and len(current) == 1:
            current = current["result"]
        return current
