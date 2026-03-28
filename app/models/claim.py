from dataclasses import dataclass, field
from typing import List


@dataclass
class RecencyDistribution:
    last_6_months: int = 0
    months_6_to_18: int = 0
    older: int = 0
    unknown: int = 0


@dataclass
class CanonicalClaim:
    claim_text: str
    sentiment: str                          # positive | negative | neutral
    count: int
    sources: List[str]
    total_engagement: int
    most_recent: str                        # YYYY-MM or unknown
    oldest: str                             # YYYY-MM or unknown
    recency_distribution: RecencyDistribution
    representative_quote: str

    def to_dict(self):
        return {
            "claim_text": self.claim_text,
            "sentiment": self.sentiment,
            "count": self.count,
            "sources": self.sources,
            "total_engagement": self.total_engagement,
            "most_recent": self.most_recent,
            "oldest": self.oldest,
            "recency_distribution": {
                "last_6_months": self.recency_distribution.last_6_months,
                "6_to_18_months": self.recency_distribution.months_6_to_18,
                "older": self.recency_distribution.older,
                "unknown": self.recency_distribution.unknown,
            },
            "representative_quote": self.representative_quote,
        }


@dataclass
class OfficialClaim:
    claim_text: str
    location: str                           # hero, pricing, FAQ etc
    has_supporting_stat: bool

    def to_dict(self):
        return {
            "claim_text": self.claim_text,
            "location": self.location,
            "has_supporting_stat": self.has_supporting_stat,
        }