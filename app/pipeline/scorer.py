from models.claim import CanonicalClaim
from config import MIN_FRAGMENTS


class GapScorer:

    def compute_all(
        self, independent_claims: list[CanonicalClaim], total_fragments: int
    ) -> dict:
        return {
            "claim_frequency": self.compute_frequency_score(
                independent_claims, total_fragments
            ),
            "consistency": self.compute_consistency_score(independent_claims),
            "recency": self.compute_recency_score(independent_claims),
        }

    def compute_frequency_score(
        self, claims: list[CanonicalClaim], total_fragments: int
    ) -> float:
        if not claims or total_fragments == 0:
            return 0.0

        negative_claims = [c for c in claims if c.sentiment == "negative"]
        negative_fragment_count = sum(c.count for c in negative_claims)

        ratio = negative_fragment_count / total_fragments
        # scale 0-1 ratio to 0-10
        return round(min(ratio * 10, 10.0), 1)

    def compute_consistency_score(self, claims: list[CanonicalClaim]) -> float:
        if not claims:
            return 0.0

        negative_claims = [c for c in claims if c.sentiment == "negative"]
        if not negative_claims:
            return 0.0

        # score based on how many sources each negative claim appears in
        source_weights = {1: 0.33, 2: 0.66, 3: 1.0}
        scores = []
        for claim in negative_claims:
            source_count = len(claim.sources)
            weight = source_weights.get(source_count, 1.0)
            scores.append(weight * 10)

        return round(sum(scores) / len(scores), 1)

    def compute_recency_score(self, claims: list[CanonicalClaim]) -> float:
        if not claims:
            return 0.0

        negative_claims = [c for c in claims if c.sentiment == "negative"]
        if not negative_claims:
            return 0.0

        total_recent = sum(c.recency_distribution.last_6_months for c in negative_claims)
        total_mid = sum(c.recency_distribution.months_6_to_18 for c in negative_claims)
        total_older = sum(c.recency_distribution.older for c in negative_claims)
        total_known = total_recent + total_mid + total_older

        if total_known == 0:
            return 5.0  # neutral if all unknown

        # weight recent more heavily
        weighted = (total_recent * 1.0) + (total_mid * 0.5) + (total_older * 0.1)
        max_possible = total_known * 1.0

        return round((weighted / max_possible) * 10, 1)

    def compute_confidence(self, metadata_summary: dict) -> str:
        total = metadata_summary.get("total_fragments", 0)
        sources = metadata_summary.get("sources_scraped", 0)
        diverse = metadata_summary.get("diverse", False)

        if total >= MIN_FRAGMENTS and sources >= 3 and diverse:
            return "high"
        elif total >= 10 and sources >= 2:
            return "medium"
        else:
            return "low"