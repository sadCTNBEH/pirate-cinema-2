import re
from abc import ABC, abstractmethod

from backend.models.search import SearchResult

QUALITY_PATTERNS: list[tuple[str, str]] = [
    (r"\b(2160p|4k|uhd)\b", "2160p"),
    (r"\b(1080p|1080i|fhd)\b", "1080p"),
    (r"\b(720p|hd)\b", "720p"),
    (r"\b(480p|576p|sd)\b", "480p"),
    (r"\b(bdrip|bluray|blu-ray|remux)\b", "BDRip"),
    (r"\b(web-?dl|web-?rip)\b", "WEB-DL"),
    (r"\b(dvdrip|dvd)\b", "DVDRip"),
    (r"\b(camrip|telesync|ts|tc)\b", "CAMRip"),
]

QUALITY_SCORES: dict[str, float] = {
    "2160p": 35.0,
    "1080p": 30.0,
    "720p": 20.0,
    "BDRip": 18.0,
    "WEB-DL": 15.0,
    "DVDRip": 10.0,
    "480p": 8.0,
    "CAMRip": -40.0,
}


def extract_quality(title: str) -> str | None:
    """Extract standard video quality identifier from torrent title."""
    if not title:
        return None
    title_lower = title.lower()
    for pattern, quality in QUALITY_PATTERNS:
        if re.search(pattern, title_lower):
            return quality
    return None


def matches_release_filters(
    item: SearchResult,
    *,
    hdr: str | None = None,
    voiceover: str | None = None,
    language: str | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    source: str | None = None,
) -> bool:
    """Match optional release-level filters against normalized tracker results."""
    title = (item.title or "").lower()

    if hdr and hdr != "all":
        if hdr == "dolby_vision":
            if not re.search(r"dolby\s*vision|dovi|\bdv\b", title):
                return False
        elif hdr == "hdr" and not re.search(r"hdr10?\+?|\bhdr\b", title):
            return False

    if voiceover and voiceover.strip() and voiceover.strip().lower() not in title:
        return False

    if language and language != "all":
        language_patterns = {
            "russian": r"\b(?:ru|rus|russian)\b|рус(?:ский|ская|ская дорожка)?",
            "english": r"\b(?:en|eng|english)\b|англ(?:ийский)?",
            "original": r"\b(?:original|orig)\b|оригинал",
        }
        pattern = language_patterns.get(language)
        if pattern and not re.search(pattern, title):
            return False

    if min_size is not None and (item.size is None or item.size < min_size):
        return False
    if max_size is not None and (item.size is None or item.size > max_size):
        return False

    return not (
        source and source.strip() and item.source.lower() != source.strip().lower()
    )


def calculate_score(item: SearchResult) -> float:
    """Calculate ranking score based on seeders, detected quality, and file size."""
    # 1. Seeders score (diminishing returns beyond 50)
    seeders = item.seeders if item.seeders is not None else 0
    if seeders <= 0:
        seeders_score = 0.0
    elif seeders <= 50:
        seeders_score = float(seeders) * 2.0  # 0 to 100
    else:
        seeders_score = 100.0 + min(float(seeders - 50) * 0.1, 20.0)  # up to 120

    # 2. Quality score
    quality = item.quality or extract_quality(item.title)
    if quality and quality in QUALITY_SCORES:
        quality_score = QUALITY_SCORES[quality]
    elif quality:
        quality_score = 10.0
    else:
        quality_score = 5.0

    # 3. Size score (optimal streaming range: 1.5GB to 25GB)
    size_score = 0.0
    size = item.size
    if size is not None and size > 0:
        gb = size / (1024**3)
        if 1.5 <= gb <= 25.0:
            size_score = 15.0
        elif 0.5 <= gb < 1.5:
            size_score = 12.0
        elif 25.0 < gb <= 60.0:
            size_score = 10.0
        elif gb > 60.0:
            size_score = 5.0
        else:  # < 500MB
            size_score = 3.0

    total_score = max(0.0, seeders_score + quality_score + size_score)
    return round(total_score, 2)


def deduplicate_results(results: list[SearchResult]) -> list[SearchResult]:
    """Deduplicate results prioritizing infohash, falling back to normalized title.

    When duplicates are encountered, retains the entry with the highest score
    and merges complementary attributes like seeders and size.
    """
    seen_hashes: dict[str, SearchResult] = {}
    no_hash_items: list[SearchResult] = []

    for item in results:
        h = (item.infohash or "").strip().lower()
        if h:
            if h in seen_hashes:
                existing = seen_hashes[h]
                if item.score > existing.score:
                    # Keep item, merge missing attributes from existing
                    if item.size is None and existing.size is not None:
                        item.size = existing.size
                    if item.seeders is None and existing.seeders is not None:
                        item.seeders = existing.seeders
                    if not item.magnet and existing.magnet:
                        item.magnet = existing.magnet
                    seen_hashes[h] = item
                else:
                    # Keep existing, merge missing attributes from item
                    if existing.size is None and item.size is not None:
                        existing.size = item.size
                    if existing.seeders is None and item.seeders is not None:
                        existing.seeders = item.seeders
                    if not existing.magnet and item.magnet:
                        existing.magnet = item.magnet
            else:
                seen_hashes[h] = item
        else:
            no_hash_items.append(item)

    # Deduplicate non-hash items by normalized title
    deduped_no_hash: dict[str, SearchResult] = {}
    for item in no_hash_items:
        norm_title = re.sub(r"[^\w\s]", "", item.title.lower()).strip()
        if norm_title in deduped_no_hash:
            if item.score > deduped_no_hash[norm_title].score:
                deduped_no_hash[norm_title] = item
        else:
            deduped_no_hash[norm_title] = item

    combined = list(seen_hashes.values()) + list(deduped_no_hash.values())
    combined.sort(key=lambda r: r.score, reverse=True)
    return combined


def rank_results(results: list[SearchResult]) -> list[SearchResult]:
    """Calculate scores for all items and sort descending by score."""
    for item in results:
        if item.quality is None:
            item.quality = extract_quality(item.title)
        item.score = calculate_score(item)
    return deduplicate_results(results)


class SearchProvider(ABC):
    """Abstract interface for torrent search providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g. 'RuTor', 'Torznab')."""
        ...

    @abstractmethod
    async def search(self, query: str) -> list[SearchResult]:
        """Search query and return normalized SearchResult list."""
        ...
