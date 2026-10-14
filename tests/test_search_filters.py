from backend.infrastructure.search.base import matches_release_filters
from backend.models.search import SearchResult


def test_matches_release_filters_for_normalized_result() -> None:
    item = SearchResult(
        title="Example 2160p HDR10 Dolby Vision RUS Dubbing",
        source="RuTor",
        size=20 * 1024**3,
        seeders=50,
    )

    assert matches_release_filters(
        item,
        hdr="dolby_vision",
        voiceover="dubbing",
        language="russian",
        min_size=10 * 1024**3,
        max_size=30 * 1024**3,
        source="rutor",
    )
    assert not matches_release_filters(item, hdr="hdr", source="other")
    assert not matches_release_filters(item, min_size=30 * 1024**3)
