import json
from datetime import datetime
from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_MAX_TOKENS
from models.claim import CanonicalClaim, RecencyDistribution


class OpenAIClient:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)

    def merge_fragments(
        self, all_fragments: list, subject: str, claim: str
    ) -> list[CanonicalClaim]:
        today = datetime.now().strftime("%Y-%m")

        system = (
            "You merge raw review fragments into canonical claim objects. "
            "Return ONLY a valid JSON array, no markdown, no explanation."
        )

        user = f"""
        Subject: {subject}
        Claim being investigated: {claim}
        Today's date: {today}

        Raw fragments from multiple sources:
        {json.dumps(all_fragments)}

        Group fragments that express the same underlying opinion into unique
        canonical claims using semantic meaning, not exact wording.
        Exclude irrelevant or empty fragments.

        Engagement weighting rules:
        - reddit upvotes: use as-is
        - tripadvisor helpful_votes: multiply by 3
        - tripadvisor rating <= 2 on a relevant topic: add 50 base engagement
        - no engagement data: use 0

        Convert relative dates to YYYY-MM using today's date: {today}
        If date is truly unknown mark as "unknown".

        Recency buckets:
        - last_6_months: posted within 6 months of today
        - 6_to_18_months: posted 6-18 months ago
        - older: posted more than 18 months ago
        - unknown: date could not be determined

        Return JSON array:
        [
          {{
            "claim_text": "neutral one sentence description of the claim",
            "sentiment": "positive | negative | neutral",
            "count": <number of fragments expressing this>,
            "sources": ["reddit", "tripadvisor"],
            "total_engagement": <weighted sum>,
            "most_recent": "YYYY-MM or unknown",
            "oldest": "YYYY-MM or unknown",
            "recency_distribution": {{
              "last_6_months": int,
              "6_to_18_months": int,
              "older": int,
              "unknown": int
            }},
            "representative_quote": "best direct quote capturing this claim"
          }}
        ]
        """

        raw = self._post(system, user)
        return self._parse_canonical_claims(raw)

    def score_gap(
        self,
        official_claims: list,
        independent_claims: list,
        python_scores: dict,
        subject: str,
        claim: str,
    ) -> dict:
        official_dicts = [c.to_dict() for c in official_claims]
        independent_dicts = [c.to_dict() for c in independent_claims]

        system = (
            "You score the gap between marketing claims and independent evidence. "
            "Return ONLY valid JSON, no markdown, no explanation."
        )

        user = f"""
        Subject: {subject}
        User question: {claim}

        Official claims:
        {json.dumps(official_dicts)}

        Independent canonical claims:
        {json.dumps(independent_dicts)}

        Pre-computed quantitative scores (0-10 scale):
        - claim_frequency: {python_scores['claim_frequency']}
        - consistency: {python_scores['consistency']}
        - recency: {python_scores['recency']}

        Your job is to score the two remaining qualitative dimensions:

        signal_strength (0-10): how substantiated and specific is the
        independent evidence? High = specific, firsthand, cited examples.
        Low = vague sentiment, unverifiable.

        severity (0-10): how materially does this gap affect a consumer
        making a decision about "{claim}"? High = financial, safety, or
        health impact. Low = cosmetic or minor inconvenience.

        Also match official claims against independent claims.

        Return JSON:
        {{
          "signal_strength": float,
          "severity": float,
          "dimension_notes": {{
            "claim_frequency": "one line",
            "signal_strength": "one line",
            "recency": "one line",
            "severity": "one line",
            "consistency": "one line"
          }},
          "matched_claims": [
            {{
              "official": "official claim text",
              "independent": "contradicting independent claim text",
              "gap_type": "exaggerated | false | unaddressed | confirmed"
            }}
          ],
          "verdict": "2-3 sentence plain English answer to the user question",
          "confidence": "high | medium | low"
        }}
        """

        return self._post(system, user)

    def _post(self, system: str, user: str) -> dict | list:
        response = self.client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=OPENAI_MAX_TOKENS,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0
        )

        text = response.choices[0].message.content
        return self._parse(text)

    def _parse(self, text: str) -> dict | list:
        clean = text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)

    def _parse_canonical_claims(self, raw: list) -> list[CanonicalClaim]:
        claims = []
        for item in raw:
            dist = item.get("recency_distribution", {})
            claims.append(
                CanonicalClaim(
                    claim_text=item["claim_text"],
                    sentiment=item["sentiment"],
                    count=item["count"],
                    sources=item["sources"],
                    total_engagement=item["total_engagement"],
                    most_recent=item["most_recent"],
                    oldest=item["oldest"],
                    recency_distribution=RecencyDistribution(
                        last_6_months=dist.get("last_6_months", 0),
                        months_6_to_18=dist.get("6_to_18_months", 0),
                        older=dist.get("older", 0),
                        unknown=dist.get("unknown", 0),
                    ),
                    representative_quote=item["representative_quote"],
                )
            )
        return claims
