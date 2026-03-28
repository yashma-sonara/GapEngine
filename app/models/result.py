from dataclasses import dataclass, field
from typing import List, Dict
from .claim import CanonicalClaim, OfficialClaim


@dataclass
class DimensionScores:
    claim_frequency: float
    signal_strength: float
    recency: float
    severity: float
    consistency: float

    def gap_score(self):
        scores = [
            self.claim_frequency,
            self.signal_strength,
            self.recency,
            self.severity,
            self.consistency,
        ]
        return round(sum(scores) / len(scores), 1)

    def to_dict(self):
        return {
            "claim_frequency": self.claim_frequency,
            "signal_strength": self.signal_strength,
            "recency": self.recency,
            "severity": self.severity,
            "consistency": self.consistency,
            "gap_score": self.gap_score(),
        }


@dataclass
class MatchedClaim:
    official: str
    independent: str
    gap_type: str                           # exaggerated | false | unaddressed | confirmed


@dataclass
class GapResult:
    subject: str
    claim_investigated: str
    category: str
    official_claims: List[OfficialClaim]
    independent_claims: List[CanonicalClaim]
    scores: DimensionScores
    matched_claims: List[MatchedClaim]
    verdict: str
    confidence: str                         # high | medium | low
    sources_scraped: List[Dict]
    dimension_notes: Dict[str, str]

    def to_dict(self):
        return {
            "subject": self.subject,
            "claim_investigated": self.claim_investigated,
            "category": self.category,
            "gap_score": self.scores.gap_score(),
            "confidence": self.confidence,
            "scores": self.scores.to_dict(),
            "dimension_notes": self.dimension_notes,
            "verdict": self.verdict,
            "official_claims": [c.to_dict() for c in self.official_claims],
            "independent_claims": [c.to_dict() for c in self.independent_claims],
            "matched_claims": [vars(m) for m in self.matched_claims],
            "sources_scraped": self.sources_scraped,
        }