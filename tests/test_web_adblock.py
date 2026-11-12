from pathlib import Path

import pytest

from backend.infrastructure.web_adblock import FILTERS, QtAdblock
from backend.infrastructure.web_filter_rules import NetworkRules

PLAYER = "https://player.example/embed"
INTERNAL = "http://127.0.0.1:8000/"


@pytest.fixture
def setup(tmp_path):
    prefs = {}

    def fetch(url):
        name = next(name for name, address in FILTERS.items() if url == address)
        return f"! Title: {name}\n" + "! comment\n" * 100 + "||cdn.example^\n"

    blocker = QtAdblock(tmp_path, prefs.copy, prefs.update, fetch)
    return blocker, prefs, fetch


def test_network_rules():
    rules = NetworkRules(["""
        ||ads.example^$script,third-party,domain=player.example|~safe.player.example
        @@||ads.example/keep.js$script
        |https://img.example/ad^$image
        ||metrics.example^$~image
        ||badfilter.example^
        ||badfilter.example^$badfilter
        ||transform.example^$removeparam=tracking
        player.example##.sponsor
        @@||trusted.example^$document
        ||cdn.example^
        ||cdn.example/hard$important
        @@||cdn.example/hard
    """])
    assert rules.blocks("https://sub.ads.example/a", PLAYER, "script")
    assert not rules.blocks("https://ads.example.evil/a", PLAYER, "script")
    assert not rules.blocks("https://ads.example@evil.example/a", PLAYER, "script")
    assert not rules.blocks("https://ads.example/a", PLAYER, "image")
    assert not rules.blocks("https://ads.example/a", "https://safe.player.example", "script")
    assert not rules.blocks("https://ads.example/a", "https://ads.example/", "script")
    assert not rules.blocks("https://ads.example/keep.js", PLAYER, "script")
    assert rules.blocks("https://img.example/ad?x=1", PLAYER, "image")
    assert not rules.blocks("https://img.example/advert", PLAYER, "image")
    assert rules.blocks("https://metrics.example/track", PLAYER, "xmlhttprequest")
    assert not rules.blocks("https://metrics.example/track", PLAYER, "image")
    for host in ("badfilter.example", "transform.example"):
        assert not rules.blocks(f"https://{host}/track", PLAYER, "script")
    assert not rules.blocks("https://cdn.example/ad", "https://trusted.example/video", "script")
    assert rules.blocks("https://cdn.example/hard", "https://trusted.example/video", "script")


def test_toggle_exceptions_and_persistence(tmp_path, setup):
    blocker, prefs, fetch = setup
    ad = "https://cdn.example/ad.js"
    assert not blocker.should_block(ad, INTERNAL, PLAYER, "script")
    blocker.set_enabled(True)
    blocker.refresh()
    assert blocker.should_block(ad, INTERNAL, PLAYER, "script")
    assert blocker.status()["blocked"] == 1
    assert blocker.set_exception("https://PLAYER.example/embed", True)["exceptions"] == ["player.example"]
    assert blocker.set_exception("*.example", True)["exceptionError"]
    assert not blocker.should_block(ad, INTERNAL, PLAYER, "script")
    assert blocker.should_block(ad, INTERNAL, "https://other.example", "script")
    reopened = QtAdblock(tmp_path, prefs.copy, prefs.update, fetch)
    reopened.load_cache()
    assert reopened.status()["active"]
    assert reopened.status()["exceptions"] == ["player.example"]
    reopened.set_exception("player.example", False)
    assert reopened.should_block(ad, INTERNAL, PLAYER, "script")
    reopened.set_enabled(False)
    assert not reopened.should_block(ad, INTERNAL, PLAYER, "script")
    assert not prefs["web_player_linux_adblock"]


def test_media_and_internal_urls_remain_available(setup):
    blocker, _, _ = setup
    blocker.set_enabled(True)
    blocker.refresh()
    for path in ("video.m3u8", "manifest.mpd", "seg.m4s", "seg.ts", "text.vtt", "captions/eng"):
        assert not blocker.should_block(f"https://cdn.example/{path}?token=abc", INTERNAL, PLAYER, "xmlhttprequest")
    assert not blocker.should_block("https://cdn.example/token", INTERNAL, PLAYER, "media")
    assert not blocker.should_block("https://cdn.example/token", INTERNAL, PLAYER, "xmlhttprequest",
                                    lambda: {"range": "bytes=0-"})
    assert not blocker.should_block("https://cdn.example/token", INTERNAL, PLAYER, "xmlhttprequest",
                                    lambda: {"accept": "application/dash+xml"})
    assert not blocker.should_block("https://cdn.example/token", INTERNAL, INTERNAL, "script")
    assert not blocker.should_block(f"{INTERNAL}api/settings", INTERNAL, PLAYER, "xmlhttprequest")
    assert blocker.should_block("https://cdn.example/ads/vast.xml", INTERNAL, PLAYER, "xmlhttprequest")


def test_custom_app_origin_is_exempt(tmp_path, setup):
    _, prefs, fetch = setup
    app = "https://cdn.example:8000"
    blocker = QtAdblock(tmp_path, prefs.copy, prefs.update, fetch, app_url=app)
    blocker.set_enabled(True)
    blocker.refresh()
    assert not blocker.should_block(app + "/assets/main.js", app, app, "script")
    assert blocker.should_block("https://cdn.example/ad.js", app, PLAYER, "script")


def test_kodik_ad_requests_are_blocked_without_blocking_the_player(setup):
    blocker, _, _ = setup
    kodik = "https://kodikplayer.com/serial/123"
    requests = (
        ("https://kodikplayer.com/adsbygoogle.js", "script"),
        ("https://bs.serving-sys.ru/Serving/adServer.bs", "xmlhttprequest"),
        ("https://ds.serving-sys.ru/ads/preroll.mp4", "media"),
    )
    assert not any(blocker.should_block(url, INTERNAL, kodik, kind) for url, kind in requests)
    blocker.set_enabled(True)
    for url, kind in requests:
        assert blocker.should_block(url, INTERNAL, kodik, kind)
    assert not blocker.should_block("https://bs.serving-sys.ru/Serving/adServer.bs", INTERNAL, PLAYER,
                                    "xmlhttprequest")
    for url, kind in (
        ("https://kodikplayer.com/ftor", "xmlhttprequest"),
        ("https://kodikplayer.com/assets/js/player.js", "script"),
        ("https://cloud2.solodcdn.com/video/720.mp4", "media"),
    ):
        assert not blocker.should_block(url, INTERNAL, kodik, kind)
    blocker.set_exception("kodikplayer.com", True)
    assert not any(blocker.should_block(url, INTERNAL, kodik, kind) for url, kind in requests)


def test_alloha_and_cvh_ad_requests_do_not_block_video(setup):
    blocker, _, _ = setup
    blocker.set_enabled(True)
    alloha = "https://alloha.yani.tv/"
    cvh = "https://player.cdnvideohub.com/s2/v2/frame/"
    assert blocker.should_block("https://vast2.ufouxbwn.com/vast.php?zone=1", INTERNAL, alloha, "xmlhttprequest")
    assert blocker.should_block("https://yandex.ru/ads/adfox/123/getCode", INTERNAL, alloha, "xmlhttprequest")
    assert blocker.should_block("https://bs.serving-sys.ru/Serving/adServer.bs", INTERNAL, cvh, "xmlhttprequest")
    assert blocker.should_block("https://yandex.ru/ads/adfox/123/getCode", INTERNAL, cvh, "xmlhttprequest")
    assert blocker.should_block("https://ya.ru/adfox/123/getCode", INTERNAL, cvh, "xmlhttprequest")
    assert not blocker.should_block("https://stream.userplay.live/master.m3u8", INTERNAL, alloha, "xmlhttprequest")
    assert not blocker.should_block("https://plapi.cdnvideohub.com/api/v1/player/sv/video/12", INTERNAL, cvh, "xmlhttprequest")
    assert not blocker.should_block("https://vd362.okcdn.ru/", INTERNAL, cvh, "media")


def test_update_replaces_cache_only_after_valid_pair(tmp_path: Path, setup):
    blocker, prefs, fetch = setup
    blocker.set_enabled(True)
    blocker.refresh()
    cache = blocker.cache.read_bytes()
    assert blocker.status()["updatedAt"] > 0

    def broken(url):
        return fetch(url) if url.endswith("/2.txt") else "<html>bad gateway</html>"

    reopened = QtAdblock(tmp_path, prefs.copy, prefs.update, broken)
    reopened.load_cache()
    reopened.refresh()
    assert reopened.status()["active"]
    assert reopened.status()["error"]
    assert reopened.cache.read_bytes() == cache
    assert reopened.should_block("https://cdn.example/ad", INTERNAL, PLAYER, "image")

    def updated(url):
        return fetch(url).replace("cdn.example", "other.example")

    updated_blocker = QtAdblock(tmp_path, prefs.copy, prefs.update, updated)
    updated_blocker.load_cache()
    updated_blocker.refresh()
    assert not updated_blocker.should_block("https://cdn.example/ad", INTERNAL, PLAYER, "image")
    assert updated_blocker.should_block("https://other.example/ad", INTERNAL, PLAYER, "image")
