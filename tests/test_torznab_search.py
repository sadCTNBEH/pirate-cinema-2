from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.infrastructure.search.base import (
    calculate_score,
    deduplicate_results,
    extract_quality,
)
from backend.infrastructure.search.torznab import TorznabProvider, parse_torznab_xml
from backend.models.search import SearchResult, TorznabConfig
from backend.services.search import SearchService
from backend.services.settings import SettingsService

SAMPLE_TORZNAB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <title>Jackett - rutracker</title>
    <description>All results</description>
    <item>
      <title>Inception / Начало (2010) 1080p BDRip</title>
      <link>magnet:?xt=urn:btih:1111111111111111111111111111111111111111&amp;dn=Inception</link>
      <size>8589934592</size>
      <torznab:attr name="category" value="2040" />
      <torznab:attr name="seeders" value="85" />
      <torznab:attr name="peers" value="12" />
      <torznab:attr name="infohash" value="1111111111111111111111111111111111111111" />
      <torznab:attr name="size" value="8589934592" />
      <torznab:attr name="magneturl" value="magnet:?xt=urn:btih:1111111111111111111111111111111111111111&amp;dn=Inception" />
      <torznab:attr name="tracker" value="Rutracker" />
    </item>
    <item>
      <title>Inception / Начало (2010) 2160p UHD HDR</title>
      <enclosure url="magnet:?xt=urn:btih:2222222222222222222222222222222222222222&amp;dn=Inception+4K" length="25000000000" type="application/x-bittorrent" />
      <torznab:attr name="seeders" value="15" />
      <torznab:attr name="tracker" value="NNMClub" />
    </item>
    <item>
      <title>Inception / Начало (2010) CAMRip</title>
      <link>magnet:?xt=urn:btih:3333333333333333333333333333333333333333</link>
      <torznab:attr name="seeders" value="50" />
      <torznab:attr name="size" value="1400000000" />
    </item>
  </channel>
</rss>
"""


def test_quality_extraction():
    assert extract_quality("Avatar.Way.of.Water.2022.2160p.HDR.WEBRip") == "2160p"
    assert extract_quality("Oppenheimer.2023.4K.UltraHD") == "2160p"
    assert extract_quality("Dune.Part.Two.2024.1080p.BluRay.x264") == "1080p"
    assert extract_quality("Interstellar.1080i.Remux") == "1080p"
    assert extract_quality("Breaking.Bad.S01E01.720p.HDTV") == "720p"
    assert extract_quality("Classic.Movie.480p.DVDRip") == "480p"
    assert extract_quality("Matrix.1999.BDRip") == "BDRip"
    assert extract_quality("The.Bear.S02.WEB-DL.1080p") == "1080p"
    assert extract_quality("Furiosa.2024.CAMRip.Line") == "CAMRip"
    assert extract_quality("Unlabeled.Video.File.mkv") is None


def test_calculate_score():
    # High seeders, 1080p, 8GB
    r1 = SearchResult(
        title="High Quality Release 1080p",
        seeders=60,
        quality="1080p",
        size=8 * 1024 * 1024 * 1024,
        source="Tracker",
    )
    score1 = calculate_score(r1)
    # seeders > 50 gives ~101 + 30 (quality) + 15 (size) = ~146
    assert score1 > 140

    # Low seeders, 480p, small size
    r2 = SearchResult(
        title="Low Quality Release 480p",
        seeders=2,
        quality="480p",
        size=300 * 1024 * 1024,
        source="Tracker",
    )
    score2 = calculate_score(r2)
    assert score2 < score1

    # CAMRip penalty
    cam = SearchResult(
        title="Bad Cam CAMRip",
        seeders=50,
        quality="CAMRip",
        size=1024 * 1024 * 1024,
        source="Tracker",
    )
    cam_score = calculate_score(cam)
    # Quality penalty (-40) keeps score significantly lower than clean 1080p with same seeders
    assert cam_score < score1


def test_parse_torznab_xml():
    results = parse_torznab_xml(SAMPLE_TORZNAB_XML)
    assert len(results) == 3

    # First item
    item1 = results[0]
    assert item1.title == "Inception / Начало (2010) 1080p BDRip"
    assert item1.infohash == "1111111111111111111111111111111111111111"
    assert item1.hash == "1111111111111111111111111111111111111111"
    assert item1.seeders == 85
    assert item1.size == 8589934592
    assert item1.source == "Rutracker"
    assert item1.quality == "1080p"
    assert item1.score > 0

    # Second item (enclosure)
    item2 = results[1]
    assert item2.title == "Inception / Начало (2010) 2160p UHD HDR"
    assert item2.infohash == "2222222222222222222222222222222222222222"
    assert item2.seeders == 15
    assert item2.size == 25000000000
    assert item2.source == "NNMClub"
    assert item2.quality == "2160p"

    # Third item (CAMRip)
    item3 = results[2]
    assert item3.quality == "CAMRip"
    assert item3.seeders == 50


def test_parse_torznab_xml_error():
    err_xml = '<error code="100" description="Incorrect user credentials" />'
    results = parse_torznab_xml(err_xml)
    assert results == []

    malformed_xml = "<invalid>xml not closed"
    results = parse_torznab_xml(malformed_xml)
    assert results == []


def test_deduplicate_by_infohash():
    # Two results with the exact same infohash, one has higher seeders and score
    h = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    r_rutor = SearchResult(
        title="Inception 1080p RuTor",
        infohash=h,
        magnet=f"magnet:?xt=urn:btih:{h}",
        seeders=10,
        quality="1080p",
        size=None,
        source="RuTor",
    )
    r_rutor.score = calculate_score(r_rutor)

    r_jackett = SearchResult(
        title="Inception 1080p Jackett",
        infohash=h,
        magnet=f"magnet:?xt=urn:btih:{h}",
        seeders=90,
        quality="1080p",
        size=8000000000,
        source="Rutracker",
    )
    r_jackett.score = calculate_score(r_jackett)

    assert r_jackett.score > r_rutor.score

    # Another distinct torrent
    r_other = SearchResult(
        title="Inception 2160p",
        infohash="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        seeders=30,
        quality="2160p",
        source="NNMClub",
    )
    r_other.score = calculate_score(r_other)

    deduped = deduplicate_results([r_rutor, r_jackett, r_other])
    assert len(deduped) == 2

    hashes = [r.infohash for r in deduped]
    assert h in hashes
    assert "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" in hashes

    # The winner for hash `h` is the one with higher score
    winner = next(r for r in deduped if r.infohash == h)
    assert winner.seeders == 90
    assert winner.size == 8000000000


@pytest.mark.anyio
async def test_search_service_parallel_aggregation_and_fallback():
    # Provider 1: RuTor (Success)
    mock_rutor = MagicMock()
    mock_rutor.name = "RuTor"
    rutor_item = SearchResult(
        title="RuTor Matrix 1080p",
        infohash="1234567890123456789012345678901234567890",
        seeders=25,
        quality="1080p",
        source="RuTor",
        score=80.0,
    )
    mock_rutor.search = AsyncMock(return_value=[rutor_item])

    # Provider 2: Torznab (Raises Exception -> Should NOT crash or block RuTor!)
    mock_torznab = MagicMock()
    mock_torznab.name = "Torznab"
    mock_torznab.search = AsyncMock(
        side_effect=httpx.ConnectTimeout("Connection timed out")
    )

    service = SearchService(providers=[mock_rutor, mock_torznab])
    results = await service.search_torrents("Matrix")

    # RuTor result should still be returned safely
    assert len(results) == 1
    assert results[0].title == "RuTor Matrix 1080p"
    assert results[0].infohash == "1234567890123456789012345678901234567890"


@pytest.mark.anyio
async def test_torznab_provider_fetch_with_retries():
    cfg = TorznabConfig(
        enabled=True,
        url="http://mock-torznab:9117/api",
        api_key="test-api-key",
        categories=[2000, 2040],
    )

    mock_client = MagicMock()
    # First attempt: 500 server error, Second attempt: 200 OK
    resp_err = MagicMock(status_code=500, text="Internal Error")
    resp_ok = MagicMock(status_code=200, text=SAMPLE_TORZNAB_XML)
    mock_client.get = AsyncMock(side_effect=[resp_err, resp_ok])
    mock_client.is_closed = False

    provider = TorznabProvider(config=cfg, http_client=mock_client, max_retries=2)
    results = await provider.search("Inception")

    assert len(results) == 3
    assert mock_client.get.call_count == 2
    # Verify call parameters
    args, kwargs = mock_client.get.call_args
    assert args[0] == "http://mock-torznab:9117/api"
    assert kwargs["params"]["q"] == "Inception"
    assert kwargs["params"]["apikey"] == "test-api-key"
    assert kwargs["params"]["cat"] == "2000,2040"


def test_settings_save_and_retrieve_torznab(tmp_path, monkeypatch):
    test_file = tmp_path / "settings.json"
    monkeypatch.setattr("backend.core.settings.user.settings_path", lambda: test_file)
    monkeypatch.setattr("backend.core.settings.settings_path", lambda: test_file)

    settings_svc = SettingsService(
        torrserver_client=MagicMock(),
        settings_provider=lambda: "http://localhost:8090",
    )

    # Update with TorznabConfig
    update_data = {
        "torznab": {
            "enabled": True,
            "url": "http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab",
            "api_key": "my-secret-key-123",
            "categories": [2000, 2040, 5000],
        }
    }
    settings_svc.update_settings(update_data)

    current = settings_svc.get_settings()
    assert "torznab" in current
    assert current["torznab"]["enabled"] is True
    assert (
        current["torznab"]["url"]
        == "http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab"
    )
    assert current["torznab"]["api_key"] == "my-secret-key-123"
    assert current["torznab"]["categories"] == [2000, 2040, 5000]

    # Verify synchronization with Jackett alias
    assert (
        current["jackett_url"]
        == "http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab"
    )
    assert current["jackett_api_key"] == "my-secret-key-123"


def test_api_endpoints_search_and_settings(tmp_path, monkeypatch):
    test_file = tmp_path / "settings.json"
    monkeypatch.setattr("backend.core.settings.user.settings_path", lambda: test_file)
    monkeypatch.setattr("backend.core.settings.settings_path", lambda: test_file)

    client = TestClient(app)

    # 1. Update settings via API (including torrserver_url)
    resp = client.post(
        "/api/settings",
        json={
            "torrserver_url": "http://127.0.0.1:8090",
            "torznab": {
                "enabled": True,
                "url": "http://localhost:9117/torznab",
                "api_key": "abc-key",
                "categories": [2000, 2010],
            },
        },
    )
    assert resp.status_code == 200

    # 2. Get settings via API
    resp_get = client.get("/api/settings")
    assert resp_get.status_code == 200
    data = resp_get.json()
    assert data["torrserver_url"] == "http://127.0.0.1:8090"
    assert "torznab" in data
    assert data["torznab"]["url"] == "http://localhost:9117/torznab"
    assert data["torznab"]["enabled"] is True
    assert data["torznab"]["api_key"] == "abc-key"


@pytest.mark.anyio
async def test_search_service_quality_and_seeders_filtering():
    p1 = MagicMock()
    p1.name = "Provider1"
    items = [
        SearchResult(
            title="Dune 2024 2160p UHD HDR",
            infohash="dune_4k",
            quality="2160p",
            seeders=50,
            source="P1",
            score=100.0,
        ),
        SearchResult(
            title="Dune 2024 1080p BDRip",
            infohash="dune_1080p",
            quality="1080p",
            seeders=25,
            source="P1",
            score=80.0,
        ),
        SearchResult(
            title="Dune 2024 720p HDTV",
            infohash="dune_720p",
            quality="720p",
            seeders=5,
            source="P1",
            score=40.0,
        ),
    ]
    p1.search = AsyncMock(return_value=items)

    service = SearchService(providers=[p1])

    # 1. Quality filter: 1080p
    res_1080 = await service.search_torrents("Dune", quality="1080p")
    assert len(res_1080) == 1
    assert res_1080[0].quality == "1080p"

    # 2. Quality filter: 4K alias matches 2160p
    res_4k = await service.search_torrents("Dune", quality="4k")
    assert len(res_4k) == 1
    assert res_4k[0].quality == "2160p"

    # 3. Min seeders filter
    res_seeders = await service.search_torrents("Dune", min_seeders=20)
    assert len(res_seeders) == 2
    assert all(r.seeders >= 20 for r in res_seeders)

    # 4. Combined quality + min seeders
    res_comb = await service.search_torrents("Dune", quality="2160p", min_seeders=60)
    assert len(res_comb) == 0


@pytest.mark.anyio
async def test_search_service_timeout_guard():
    import asyncio

    p_slow = MagicMock()
    p_slow.name = "SlowProvider"

    async def slow_search(q):
        await asyncio.sleep(5.0)
        return []

    p_slow.search = slow_search

    # Timeout set to 0.1s
    service = SearchService(providers=[p_slow], search_timeout=0.1)
    results = await service.search_torrents("Matrix")
    assert results == []


def test_api_search_with_quality_and_seeders_params(monkeypatch):
    from backend.api import deps

    mock_svc = MagicMock()
    mock_svc.search_torrents = AsyncMock(
        return_value=[
            SearchResult(
                title="Inception 1080p",
                infohash="inc_1080",
                seeders=30,
                quality="1080p",
                source="RuTor",
                score=90.0,
            )
        ]
    )

    app.dependency_overrides[deps.get_search_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.get("/api/search?q=Inception&quality=1080p&min_seeders=15")
        assert resp.status_code == 200
        mock_svc.search_torrents.assert_called_once_with(
            "Inception", quality="1080p", min_seeders=15
        )
        data = resp.json()
        assert len(data) == 1
        assert data[0]["quality"] == "1080p"
    finally:
        app.dependency_overrides.clear()
