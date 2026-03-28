from config import (
    MIN_FRAGMENTS,
    MIN_SOURCES,
    MAX_SOURCES,
    MIN_RECENT_FRAGMENTS,
    MIN_PLATFORM_TYPES,
    MIN_FRAGMENTS_PER_SOURCE,
    MIN_LONG_FORM_FRAGMENTS_PER_SOURCE,
)
from clients.tinyfish import TinyFishClient


class SourceCollector:
    def __init__(self, tf_client: TinyFishClient):
        self.tf = tf_client
        self.all_fragments = []
        self.scraped_sources = []
        self.platform_types_seen = set()

    def collect(self, subject: str, claim: str, candidate_sources: list):
        for source in candidate_sources:
            if len(self.scraped_sources) >= MAX_SOURCES:
                print("Reached MAX_SOURCES limit — stopping collection")
                break

            url = source["url"]
            platform = source["platform"]
            platform_type = source["platform_type"]
            print(
                f"Collecting source: platform={platform} "
                f"type={platform_type} url={url}"
            )

            result = self.tf.scrape_source(url, platform_type, subject, claim)
            if not isinstance(result, dict):
                print(f"Skipping {platform} — invalid scrape response")
                continue

            metadata = result.get("metadata", {})
            fragments = result.get("fragments", [])
            blocked = bool(result.get("blocked")) or bool(metadata.get("blocked"))
            login_wall_hit = bool(result.get("login_wall_hit")) or bool(
                metadata.get("login_wall_hit")
            )
            print(
                f"Collector response for {platform}: "
                f"blocked={blocked} login_wall_hit={login_wall_hit} "
                f"fragments={len(fragments)} metadata_keys={sorted(metadata.keys())}"
            )
            if result.get("error"):
                print(f"Collector error for {platform}: {result.get('error')}")

            if blocked or login_wall_hit:
                print(f"Skipping {platform} — blocked or login wall")
                continue

            min_fragments = self._min_fragments_for(platform_type)
            print(
                f"Minimum fragments required for {platform} ({platform_type}): "
                f"{min_fragments}"
            )
            if len(fragments) < min_fragments:
                print(f"Skipping {platform} — insufficient fragments ({len(fragments)})")
                continue

            self._tag_fragments(fragments, platform)
            self.all_fragments.extend(fragments)
            self.scraped_sources.append(metadata)
            self.platform_types_seen.add(platform_type)

            print(f"Scraped {platform}: {len(fragments)} fragments")
            print(
                f"Running totals: sources={len(self.scraped_sources)} "
                f"fragments={len(self.all_fragments)} "
                f"platform_types={sorted(self.platform_types_seen)}"
            )

            if len(self.scraped_sources) >= MIN_SOURCES and self.is_sufficient():
                print("Sufficiency threshold met — stopping collection")
                break

    def is_sufficient(self) -> bool:
        return (
            len(self.all_fragments) >= MIN_FRAGMENTS
            and len(self.scraped_sources) >= MIN_SOURCES
            and self.is_diverse()
            and self._recent_fragment_count() >= MIN_RECENT_FRAGMENTS
        )

    def is_diverse(self) -> bool:
        return len(self.platform_types_seen) >= MIN_PLATFORM_TYPES

    def get_all_fragments(self) -> list:
        return self.all_fragments

    def get_metadata_summary(self) -> dict:
        return {
            "sources_scraped": len(self.scraped_sources),
            "total_fragments": len(self.all_fragments),
            "platform_types": list(self.platform_types_seen),
            "sources": self.scraped_sources,
            "sufficient": self.is_sufficient(),
            "diverse": self.is_diverse(),
        }

    def _tag_fragments(self, fragments: list, source_name: str):
        for fragment in fragments:
            fragment["source"] = source_name

    def _recent_fragment_count(self) -> int:
        # rough check — fragments where date string suggests recency
        # Claude will do proper date parsing later
        recent_keywords = ["day", "week", "month", "2024", "2025"]
        return sum(
            1 for f in self.all_fragments
            if any(k in str(f.get("date", "")).lower() for k in recent_keywords)
        )

    def _min_fragments_for(self, platform_type: str) -> int:
        if platform_type == "long_form":
            return MIN_LONG_FORM_FRAGMENTS_PER_SOURCE
        return MIN_FRAGMENTS_PER_SOURCE
