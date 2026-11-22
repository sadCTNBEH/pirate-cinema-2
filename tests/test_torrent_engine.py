from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import deps
from backend.infrastructure.torrserver.client import (
    AwaitableStr,
    FakeTorrentEngine,
    ITorrentEngine,
    TorrentEngine,
    TorrServerAdapter,
)
from backend.infrastructure.torrserver.process import (
    TorrServerHealthChecker,
    TorrServerProcessManager,
    torrserver_health_checker,
    torrserver_process_manager,
)
from backend.models.playback import PlayCommand
from backend.repositories.db import Database
from backend.repositories.playback import PlaybackRepository
from backend.services.magnet import MagnetService
from backend.services.playback import PlaybackService
from backend.services.torrent_selection import (
    select_file_from_engine,
    select_largest_file,
    select_torrent_file,
)


class TestTorrentEngineInterface:
    def test_abstract_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            TorrentEngine()  # type: ignore

    def test_interface_alias(self):
        assert ITorrentEngine is TorrentEngine

    def test_subclass_must_implement_all_methods(self):
        class IncompleteEngine(TorrentEngine):
            async def add_torrent(self, torrent: str, title: str = "", **kwargs):
                return {}

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteEngine()  # type: ignore


class TestAwaitableStr:
    def test_sync_string_operations(self):
        s = AwaitableStr("http://localhost:8090/stream/video.mp4")
        assert isinstance(s, str)
        assert s == "http://localhost:8090/stream/video.mp4"
        assert s.startswith("http://")
        assert len(s) > 10

    @pytest.mark.anyio
    async def test_await_returns_string(self):
        s = AwaitableStr("http://localhost:8090/stream/video.mp4")
        res = await s
        assert isinstance(res, str)
        assert res == "http://localhost:8090/stream/video.mp4"


class TestFakeTorrentEngine:
    @pytest.fixture
    def engine(self):
        return FakeTorrentEngine(base_url="http://fake-engine:8090")

    @pytest.mark.anyio
    async def test_add_and_get_files(self, engine: FakeTorrentEngine):
        magnet = "magnet:?xt=urn:btih:1111222233334444555566667777888899990000&dn=Test+Movie"
        res = await engine.add_torrent(magnet, title="Test Movie")
        assert res["hash"] == "1111222233334444555566667777888899990000"
        assert res["already_exists"] is False

        # Adding same magnet again indicates already_exists
        res2 = await engine.add_torrent(magnet, title="Test Movie")
        assert res2["already_exists"] is True

        files = await engine.get_files("1111222233334444555566667777888899990000")
        assert len(files) == 1
        assert files[0]["name"] == "Test Movie.mp4"
        assert files[0]["length"] == 104857600

    @pytest.mark.anyio
    async def test_custom_fake_files(self, engine: FakeTorrentEngine):
        h = "abcdef1234567890abcdef1234567890abcdef12"
        engine.add_fake_file(h, file_id=1, name="Episode 1.mkv", length=50000000)
        engine.add_fake_file(h, file_id=2, name="Episode 2.mkv", length=55000000)

        files = await engine.get_files(h)
        assert len(files) == 2
        assert files[0]["id"] == 1
        assert files[1]["name"] == "Episode 2.mkv"

    def test_get_stream_url(self, engine: FakeTorrentEngine):
        h = "1111222233334444555566667777888899990000"
        url = engine.get_stream_url(h, file_id=1, file_name="movie.mp4")
        assert isinstance(url, str)
        assert "http://fake-engine:8090/stream/movie.mp4" in url
        assert f"link={h}" in url
        assert "index=1" in url

    @pytest.mark.anyio
    async def test_get_stream_url_awaitable(self, engine: FakeTorrentEngine):
        h = "1111222233334444555566667777888899990000"
        url = await engine.get_stream_url(h, file_id=0, file_name="video.mp4")
        assert isinstance(url, str)
        assert f"link={h}" in url

    @pytest.mark.anyio
    async def test_get_stats(self, engine: FakeTorrentEngine):
        engine_stats = await engine.get_stats()
        assert engine_stats["status"] == "online"
        assert engine_stats["version"] == "FakeTorrentEngine/1.0"
        assert engine_stats["torrents_count"] == 0

        h = "1111222233334444555566667777888899990000"
        await engine.add_torrent(f"magnet:?xt=urn:btih:{h}")
        torrent_stats = await engine.get_stats(h)
        assert torrent_stats["hash"] == h
        assert torrent_stats["stat"] == 1
        assert torrent_stats["download_speed"] > 0

    @pytest.mark.anyio
    async def test_remove_torrent_and_reset(self, engine: FakeTorrentEngine):
        h = "1111222233334444555566667777888899990000"
        await engine.add_torrent(f"magnet:?xt=urn:btih:{h}")
        del_res = await engine.remove_torrent(h)
        assert del_res == {"status": "removed"}

        stats = await engine.get_stats()
        assert stats["torrents_count"] == 0

        # Reset clears all
        engine.add_fake_file("test", 1, "test.mp4")
        engine.reset()
        assert len(engine.files) == 0


class TestTorrServerAdapter:
    @pytest.mark.anyio
    async def test_adapter_implements_torrent_engine(self):
        adapter = TorrServerAdapter(base_url="http://localhost:8090")
        assert isinstance(adapter, TorrentEngine)

    @pytest.mark.anyio
    async def test_adapter_add_and_remove_delegates_to_client(self):
        mock_client = MagicMock()
        mock_client.add_magnet = AsyncMock(return_value={"hash": "deadbeef", "already_exists": False})
        mock_client.remove_torrent = AsyncMock()

        adapter = TorrServerAdapter(
            base_url="http://localhost:8090",
            client=mock_client,
        )

        res = await adapter.add_torrent("magnet:?xt=urn:btih:deadbeef", title="Dead Beef")
        assert res["hash"] == "deadbeef"
        mock_client.add_magnet.assert_awaited_once_with(
            "http://localhost:8090", "magnet:?xt=urn:btih:deadbeef", "Dead Beef"
        )

        del_res = await adapter.remove_torrent("deadbeef")
        assert del_res == {"status": "removed"}
        mock_client.remove_torrent.assert_awaited_once_with("http://localhost:8090", "deadbeef")

    @pytest.mark.anyio
    async def test_adapter_get_files_delegates(self):
        mock_client = MagicMock()
        mock_client.torrent_video_files = AsyncMock(
            return_value=[{"id": 0, "name": "sample.mp4", "length": 123456}]
        )

        adapter = TorrServerAdapter(
            base_url="http://localhost:8090",
            client=mock_client,
        )

        files = await adapter.get_files("somehash")
        assert len(files) == 1
        assert files[0]["name"] == "sample.mp4"
        mock_client.torrent_video_files.assert_awaited_once_with("http://localhost:8090", "somehash")

    def test_adapter_get_stream_url(self):
        adapter = TorrServerAdapter(base_url="http://localhost:8090")
        h = "1111222233334444555566667777888899990000"
        url = adapter.get_stream_url(h, file_id=2, file_name="ep 02.mkv")
        assert isinstance(url, str)
        assert url.startswith("http://localhost:8090/stream/")
        assert f"link={h}" in url
        assert "index=2" in url

    @pytest.mark.anyio
    async def test_adapter_get_stats_mock_transport(self, monkeypatch):
        h = "1111222233334444555566667777888899990000"

        async def handler(request: httpx.Request):
            if request.url.path == "/torrents":
                return httpx.Response(
                    200,
                    json={
                        "hash": h,
                        "title": "My Movie",
                        "stat": 2,
                        "stat_string": "Downloading",
                        "download_speed": 5000000.0,
                        "upload_speed": 100000.0,
                        "connected_seeders": 15,
                        "active_peers": 8,
                        "total_peers": 30,
                    },
                )
            if request.url.path == "/echo":
                return httpx.Response(200, text="MatriX.133")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        mock_http_client = httpx.AsyncClient(transport=transport)
        from backend.infrastructure.torrserver import client as ts_mod

        monkeypatch.setattr(ts_mod, "get_client", lambda: mock_http_client)

        adapter = TorrServerAdapter(base_url="http://localhost:8090")
        stats = await adapter.get_stats(h)
        assert stats["hash"] == h
        assert stats["stat_string"] == "Downloading"
        assert stats["connected_seeders"] == 15

        engine_stats = await adapter.get_stats()
        assert engine_stats["status"] == "online"
        assert engine_stats["version"] == "MatriX.133"


class TestMagnetServiceWithEngine:
    @pytest.mark.anyio
    async def test_magnet_service_with_fake_engine(self):
        fake_engine = FakeTorrentEngine()
        service = MagnetService(engine=fake_engine)

        assert service.engine is fake_engine

        magnet = "magnet:?xt=urn:btih:2222333344445555666677778888999900001111&dn=Fake+Title"
        add_res = await service.add_magnet(magnet, "Custom Title")
        assert add_res["hash"] == "2222333344445555666677778888999900001111"
        assert add_res["already_exists"] is False

        # add_torrent alias works identically
        add_torrent_res = await service.add_torrent(magnet, "Custom Title")
        assert add_torrent_res["already_exists"] is True

        del_res = await service.delete_torrent("2222333344445555666677778888999900001111")
        assert del_res == {"status": "removed"}

    @pytest.mark.anyio
    async def test_magnet_service_backwards_compatible_init(self):
        mock_ts = MagicMock()
        mock_ts.add_magnet = AsyncMock(return_value={"hash": "abcd1234abcd1234abcd1234abcd1234abcd1234"})
        mock_ts.remove_torrent = AsyncMock()

        service = MagnetService(
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=None,
        )

        assert isinstance(service.engine, TorrentEngine)

        res = await service.add_magnet("magnet:?xt=urn:btih:abcd1234abcd1234abcd1234abcd1234abcd1234", "Title")
        assert res["hash"] == "abcd1234abcd1234abcd1234abcd1234abcd1234"

        del_res = await service.delete_torrent("abcd1234abcd1234abcd1234abcd1234abcd1234")
        assert del_res == {"status": "removed"}


class TestFastAPIDependencyInjection:
    def test_get_torrent_engine_default(self):
        engine = deps.get_torrent_engine()
        assert isinstance(engine, TorrentEngine)
        assert isinstance(engine, TorrServerAdapter)

    def test_app_dependency_override_with_fake_engine(self):
        app = FastAPI()

        @app.get("/test/stream")
        async def stream_endpoint(
            engine: deps.Annotated[TorrentEngine, deps.Depends(deps.get_torrent_engine)],
        ):
            return {"stream_url": engine.get_stream_url("test_hash", 0, "test.mp4")}

        @app.post("/test/magnet")
        async def add_magnet_endpoint(
            magnet_svc: deps.Annotated[MagnetService, deps.Depends(deps.get_magnet_service)],
        ):
            res = await magnet_svc.add_torrent("magnet:?xt=urn:btih:3333444455556666777788889999000011112222", "Test")
            return res

        fake_engine = FakeTorrentEngine(base_url="http://test-server:9999")
        app.dependency_overrides[deps.get_torrent_engine] = lambda: fake_engine

        client = TestClient(app)

        resp = client.get("/test/stream")
        assert resp.status_code == 200
        assert "http://test-server:9999/stream/test.mp4" in resp.json()["stream_url"]

        resp2 = client.post("/test/magnet")
        assert resp2.status_code == 200
        assert resp2.json()["hash"] == "3333444455556666777788889999000011112222"


class TestTorrentSelectionWithEngine:
    def test_select_largest_file(self):
        files = [
            {"id": 1, "name": "sample.mp4", "path": "sample.mp4", "length": 5_000_000},
            {"id": 2, "name": "Feature.Film.2024.1080p.mkv", "path": "Feature.Film.2024.1080p.mkv", "length": 4_500_000_000},
            {"id": 3, "name": "Featurette.Bonus.mkv", "path": "Featurette.Bonus.mkv", "length": 300_000_000},
        ]
        largest = select_largest_file(files)
        assert largest is not None
        assert largest["id"] == 2
        assert largest["name"] == "Feature.Film.2024.1080p.mkv"

    def test_select_torrent_file(self):
        files = [
            {"id": 1, "name": "sample.mp4", "path": "sample.mp4", "length": 5_000_000},
            {"id": 2, "name": "Feature.Film.2024.1080p.mkv", "path": "Feature.Film.2024.1080p.mkv", "length": 4_500_000_000},
        ]
        result = select_torrent_file(files)
        assert result["file"] is not None
        assert result["file"]["id"] == 2

    @pytest.mark.anyio
    async def test_select_file_from_fake_engine_movie(self):
        engine = FakeTorrentEngine()
        h = "aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111"
        engine.add_fake_file(h, file_id=10, name="Sample/sample.mp4", length=10_000_000)
        engine.add_fake_file(h, file_id=20, name="Avatar.2009.Extended.mkv", length=8_000_000_000)

        result = await select_file_from_engine(engine, h)
        assert result["file"] is not None
        assert result["file"]["id"] == 20

    @pytest.mark.anyio
    async def test_select_file_from_fake_engine_series(self):
        engine = FakeTorrentEngine()
        h = "bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222"
        engine.add_fake_file(h, file_id=1, name="Show.S01E01.mkv", length=800_000_000)
        engine.add_fake_file(h, file_id=2, name="Show.S01E02.mkv", length=820_000_000)
        engine.add_fake_file(h, file_id=3, name="Show.S01E03.mkv", length=810_000_000)

        result = await select_file_from_engine(engine, h, season=1, episode=2)
        assert result["file"] is not None
        assert result["file"]["id"] == 2
        assert result["file"]["name"] == "Show.S01E02.mkv"


class TestPlaybackWithFakeTorrentEngine:
    @pytest.mark.anyio
    async def test_playback_select_and_launch_stream_url_from_fake_engine(self, monkeypatch):
        from backend.services import playback

        monkeypatch.setattr(playback, "load_settings", lambda: {"embedded_player": False})
        monkeypatch.setattr(playback, "resolve_mpv_binary", lambda _: "mpv")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
            db.init_db()

            playback_repo = PlaybackRepository(db=db)
            mock_controller = MagicMock(is_running=False)
            fake_engine = FakeTorrentEngine(base_url="http://fake-engine:8090")

            h = "cccc3333cccc3333cccc3333cccc3333cccc3333"
            fake_engine.add_fake_file(h, file_id=101, name="Series.S01E01.mkv", length=500_000_000)
            fake_engine.add_fake_file(h, file_id=102, name="Series.S01E02.mkv", length=520_000_000)

            service = PlaybackService(
                playback_repo=playback_repo,
                history_repo=MagicMock(),
                metadata_repo=MagicMock(),
                mpv_controller_factory=lambda: mock_controller,
                torrserver_client=fake_engine,
                settings_provider=lambda: fake_engine.base_url,
                engine=fake_engine,
            )

            assert service.engine is fake_engine

            # 1. Selection through FakeTorrentEngine
            selection = await service.select_torrent_file(h, season=1, episode=2)
            assert selection["file"] is not None
            assert selection["file"]["id"] == 102

            # 2. Launch uses the universal stream URL from the engine
            cmd = PlayCommand(hash=h, file_id=102, file_name="Series.S01E02.mkv")
            res = await service.launch(cmd)
            assert res == "launched"

            # Check that controller received the engine's stream URL
            assert mock_controller.launch.called
            call_url = mock_controller.launch.call_args.kwargs["url"]
            assert call_url.startswith("http://fake-engine:8090/stream/Series.S01E02.mkv")
            assert f"link={h}" in call_url
            assert "index=102" in call_url


class TestTorrServerProcessManager:
    def test_health_checker_and_process_manager_instances(self):
        assert isinstance(torrserver_health_checker, TorrServerHealthChecker)
        assert isinstance(torrserver_process_manager, TorrServerProcessManager)
        assert torrserver_process_manager.health_checker is torrserver_health_checker

    def test_status_reporting(self):
        status = torrserver_process_manager.get_status()
        assert isinstance(status, dict)
        assert "state" in status
        assert "managed" in status

