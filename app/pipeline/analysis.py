from clients.tinyfish import TinyFishClient
from clients.claude import OpenAIClient
from pipeline.collector import SourceCollector
from pipeline.scorer import GapScorer
from models.claim import OfficialClaim
from models.result import GapResult, DimensionScores, MatchedClaim
from config import DEFAULT_SOURCES


class GapAnalysis:
    def __init__(self):
        self.tf = TinyFishClient()
        self.llm = OpenAIClient()
        self.scorer = GapScorer()

    def run(self, subject: str, claim: str, category: str) -> GapResult:
        print(f"\nStarting gap analysis: {subject} — {claim}\n")

        # discover sources
        print("Discovering sources...")
        discovered = self.tf.discover_sources(subject, claim, category)
        print(f"Discovery raw response: {discovered}") 

        # merge with category defaults as fallback
        candidate_sources = self._merge_sources(discovered, subject, category)
        print(f"Candidate sources after merge: {len(candidate_sources)}")
        for idx, source in enumerate(candidate_sources, start=1):
            print(
                f"  [{idx}] platform={source.get('platform')} "
                f"type={source.get('platform_type')} url={source.get('url')}"
            )

        # scrape official
        print("Scraping official sources...")
        official_raw = self.tf.scrape_official(subject, claim, category)
        print(f"Official raw response: {official_raw}")
        official_claims = self._parse_official_claims(official_raw)
        print(f"Official claims parsed: {len(official_claims)}")

        # collect independent sources
        print("Collecting independent sources...")
        collector = SourceCollector(self.tf)
        collector.collect(subject, claim, candidate_sources)
        metadata_summary = collector.get_metadata_summary()

        print(f"Collection complete: {metadata_summary['total_fragments']} fragments "
              f"from {metadata_summary['sources_scraped']} sources")

        # merge into canonical claims
        print("Merging fragments into canonical claims...")
        independent_claims = self.llm.merge_fragments(
            collector.get_all_fragments(), subject, claim
        )

        # compute quantitative scores in Python
        print("Computing scores...")
        python_scores = self.scorer.compute_all(
            independent_claims, metadata_summary["total_fragments"]
        )

        # get qualitative scores + verdict from OpenAI
        print("Running gap scoring with OpenAI...")
        llm_scores = self.llm.score_gap(
            official_claims, independent_claims, python_scores, subject, claim
        )

        # build final result
        confidence = self.scorer.compute_confidence(metadata_summary)

        scores = DimensionScores(
            claim_frequency=python_scores["claim_frequency"],
            signal_strength=float(llm_scores["signal_strength"]),
            recency=python_scores["recency"],
            severity=float(llm_scores["severity"]),
            consistency=python_scores["consistency"],
        )

        matched = [
            MatchedClaim(
                official=m["official"],
                independent=m["independent"],
                gap_type=m["gap_type"],
            )
            for m in llm_scores.get("matched_claims", [])
        ]

        return GapResult(
            subject=subject,
            claim_investigated=claim,
            category=category,
            official_claims=official_claims,
            independent_claims=independent_claims,
            scores=scores,
            matched_claims=matched,
            verdict=llm_scores["verdict"],
            confidence=confidence,
            sources_scraped=metadata_summary["sources"],
            dimension_notes=llm_scores.get("dimension_notes", {}),
        )

    def _merge_sources(self, discovered, subject: str, category: str) -> list:
        defaults = DEFAULT_SOURCES.get(category, [])
        default_formatted = [
            {
                "url": url_template.replace("{subject}", subject),
                "platform": platform,
                "platform_type": platform_type,
                "requires_login": False,
            }
            for url_template, platform, platform_type in defaults
        ]

        # normalize discovered — TinyFish may return strings, dicts, or a wrapped object
        normalized = []
        if isinstance(discovered, dict):
            # e.g. {"sources": [...]} or {"result": [...]}
            discovered = discovered.get("sources") or discovered.get("result") or []

        for item in discovered:
            if isinstance(item, str):
                # bare URL string — wrap it
                normalized.append({
                    "url": item,
                    "platform": self._guess_platform(item),
                    "platform_type": self._guess_platform_type(item),
                    "requires_login": False,
                })
            elif isinstance(item, dict):
                normalized.append(item)

        # deduplicate by platform — prefer discovered over defaults
        seen_platforms = {s["platform"] for s in normalized}
        extras = [d for d in default_formatted if d["platform"] not in seen_platforms]

        # if nothing came back from discovery just use defaults
        if not normalized:
            print("Discovery returned no usable sources — falling back to defaults")
            return default_formatted

        print(
            f"Discovery produced {len(normalized)} usable sources; "
            f"adding {len(extras)} defaults for missing platforms"
        )
        return normalized + extras

    def _guess_platform(self, url: str) -> str:
        for name in ["reddit", "tripadvisor", "trustpilot", "yelp", "g2", 
                    "glassdoor", "sitejabber", "cruisecritic", "metacritic"]:
            if name in url.lower():
                return name
        return "web"

    def _guess_platform_type(self, url: str) -> str:
        forums = ["reddit", "cruisecritic", "hackernews", "forum"]
        reviews = ["tripadvisor", "trustpilot", "yelp", "g2", "glassdoor", "sitejabber"]
        for f in forums:
            if f in url.lower():
                return "forum"
        for r in reviews:
            if r in url.lower():
                return "structured_review"
        return "long_form"

    def _parse_official_claims(self, raw: dict) -> list[OfficialClaim]:
        claims = []
        for item in raw.get("claims", []):
            claims.append(
                OfficialClaim(
                    claim_text=item.get("claim_text", ""),
                    location=item.get("location", "unknown"),
                    has_supporting_stat=item.get("has_supporting_stat", False),
                )
            )
        return claims
