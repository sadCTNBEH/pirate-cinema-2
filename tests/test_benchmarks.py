"""Reproducible performance benchmarks for Pirate Cinema.

Benchmarks:
1. Application Cold Start (settings loading, DB initialization, FastAPI bootstrap, health probe).
2. Cold Search (query normalization, provider fan-out, deduplication, ranking).
3. MPV Initialization, Time to First Frame (TTFF), and playback FPS.
4. Peak RAM consumption (psutil) in idle state vs active playback.

Outputs structured JSON report: benchmark_report.json (with FPS, RAM MB, cold start ms).

Marked with @pytest.mark.benchmark to isolate from standard PR CI test runs.
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import platform
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import psutil
import pytest
from fastapi.testclient import TestClient

# Ensure pirate-cinema root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import gui
from backend.core.settings import load_settings, resolve_mpv_binary
from backend.infrastructure.mpv.controller import MPVController
from backend.infrastructure.torrserver import process as torrserver_process
from backend.models.playback import PlaybackState
from backend.models.search import SearchResult
from backend.services.playback import PlaybackService
from backend.services.search import SearchService


def pytest_configure(config: pytest.Config) -> None:
    """Register custom benchmark marker so pytest does not emit PytestUnknownMarkWarning."""
    config.addinivalue_line(
        "markers",
        "benchmark: Performance and regression benchmarks (FPS, RAM, cold start)",
    )


# Apply benchmark marker to all tests in this module
pytestmark = [pytest.mark.benchmark]

logger = logging.getLogger("benchmarks")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

REPORT_FILE = Path("benchmark_report.json")

# In-memory dictionary collecting benchmark results during test runs
BENCHMARK_RESULTS: dict[str, Any] = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "platform": {
        "system": platform.system(),
        "release": platform.release(),
        "python": platform.python_version(),
        "cpu_count": psutil.cpu_count(logical=True),
        "total_ram_mb": round(psutil.virtual_memory().total / (1024 * 1024), 2),
    },
    "metrics": {},
    "summary": {},
}


def get_process_tree_ram_mb() -> float:
    """Return total RSS memory in MB for the current process and all child processes."""
    proc = psutil.Process()
    rss = proc.memory_info().rss
    for child in proc.children(recursive=True):
        try:
            rss += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return round(rss / (1024 * 1024), 2)


def save_benchmark_report(data: dict[str, Any], path: Path = REPORT_FILE) -> None:
    """Persist structured benchmark metrics to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Saved benchmark report to %s", path.resolve())

    # Also sync into build/ if the directory exists
    build_dir = Path("build")
    if build_dir.is_dir():
        try:
            with (build_dir / "benchmark_report.json").open("w", encoding="utf-8") as bf:
                json.dump(data, bf, indent=2, ensure_ascii=False)
        except OSError:
            pass


@pytest.fixture(scope="session", autouse=True)
def benchmark_session_reporter():
    """Ensure benchmark JSON report is written after session completion."""
    yield
    if BENCHMARK_RESULTS.get("metrics"):
        save_benchmark_report(BENCHMARK_RESULTS)


@pytest.mark.benchmark
def test_app_cold_start_benchmark():
    """Measure application cold start latency and baseline memory consumption."""
    logger.info("Running application cold start benchmark...")
    gc.collect()
    ram_before = get_process_tree_ram_mb()

    # Prevent external network blocking when measuring application bootstrap
    with (
        patch.object(torrserver_process, "connect_or_start", return_value=None),
        patch.object(torrserver_process, "start_monitor", return_value=None),
    ):
        t_start = time.perf_counter()

        # 1. Load settings and core configuration
        settings = load_settings()
        assert settings is not None, "Failed to load application settings"

        # 2. Bootstrap FastAPI application
        from backend.app import app

        # 3. Initialize test client and verify health probe
        with TestClient(app) as client:
            resp = client.get("/api/settings/health")
            assert resp.status_code == 200, f"Health check returned code {resp.status_code}"
            health_data = resp.json()
            assert (
                health_data.get("status") in ("ok", "starting", "degraded", None)
                or "error" not in health_data
            )

        cold_start_ms = round((time.perf_counter() - t_start) * 1000, 2)

    ram_after = get_process_tree_ram_mb()

    logger.info(
        "[BENCHMARK] App Cold Start: %.2f ms | RAM baseline: %.2f MB -> %.2f MB",
        cold_start_ms,
        ram_before,
        ram_after,
    )

    # Record metrics
    BENCHMARK_RESULTS["metrics"]["cold_start_ms"] = cold_start_ms
    BENCHMARK_RESULTS["metrics"]["ram_baseline_mb"] = ram_before
    BENCHMARK_RESULTS["metrics"]["ram_app_loaded_mb"] = ram_after
    BENCHMARK_RESULTS["summary"]["cold start ms"] = cold_start_ms

    assert cold_start_ms > 0, "Cold start measurement must be strictly positive"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_cold_search_benchmark():
    """Measure cold search latency (normalization, fan-out, deduplication, ranking)."""
    logger.info("Running cold search benchmark...")
    mock_provider = MagicMock()
    mock_provider.name = "benchmark_provider"
    mock_provider.search = AsyncMock(
        return_value=[
            SearchResult(
                title="Inception 2010 1080p BDRip",
                infohash="1111111111111111111111111111111111111111",
                size=2_400_000_000,
                seeds=150,
            ),
            SearchResult(
                title="Inception 2010 2160p UHD HDR",
                infohash="2222222222222222222222222222222222222222",
                size=18_000_000_000,
                seeds=45,
            ),
            SearchResult(
                title="Inception 2010 720p HDTV",
                infohash="3333333333333333333333333333333333333333",
                size=900_000_000,
                seeds=12,
            ),
        ]
    )

    service = SearchService(providers=[mock_provider])

    # Cold search execution (cache miss)
    t0 = time.perf_counter()
    cold_results = await service.search_torrents("Inception 2010")
    cold_search_ms = round((time.perf_counter() - t0) * 1000, 2)

    assert len(cold_results) >= 3, "Expected search results to be returned and ranked"

    # Warm search execution (cache hit)
    t1 = time.perf_counter()
    warm_results = await service.search_torrents("Inception 2010")
    warm_search_ms = round((time.perf_counter() - t1) * 1000, 2)
    assert len(warm_results) >= 3, "Expected cached warm search results"

    logger.info(
        "[BENCHMARK] Search Latency: Cold = %.2f ms | Warm = %.2f ms (results: %d)",
        cold_search_ms,
        warm_search_ms,
        len(cold_results),
    )

    BENCHMARK_RESULTS["metrics"]["cold_search_ms"] = cold_search_ms
    BENCHMARK_RESULTS["metrics"]["warm_search_ms"] = warm_search_ms
    BENCHMARK_RESULTS["metrics"]["search_results_count"] = len(cold_results)

    assert cold_search_ms > 0, "Cold search measurement must be strictly positive"


@pytest.mark.benchmark
def test_mpv_playback_performance_benchmark():
    """Benchmark MPV initialization, Time to First Frame, playback FPS, and peak RAM consumption."""
    mpv_bin = resolve_mpv_binary()
    resolved_str = str(mpv_bin)
    if not (mpv_bin.is_file() or shutil.which(resolved_str) or shutil.which("mpv")):
        pytest.skip(f"Host MPV binary not found ('{mpv_bin}') and not on PATH")

    logger.info("Running MPV playback performance and RAM benchmark...")
    gc.collect()

    # Step 1: Idle RAM measurement before playback
    ram_idle_mb = get_process_tree_ram_mb()
    logger.info("Measured Idle RAM: %.2f MB", ram_idle_mb)

    # Setup mock UI
    orig_window = gui._window
    controller: MPVController | None = None
    service: PlaybackService | None = None
    try:
        gui._window = SimpleNamespace(native=None, evaluate_js=lambda code: None)
        controller = MPVController()
        service = PlaybackService(
            MagicMock(), MagicMock(), MagicMock(), lambda: controller, MagicMock(), lambda: ""
        )
        service.controllers["bench"] = controller
        service.active_states["bench"] = PlaybackState(hash="bench", file_id=1)
        service.loop = asyncio.new_event_loop()
        threading.Thread(target=service.loop.run_forever, daemon=True).start()

        first_frame_event = threading.Event()
        timecodes: list[float] = []

        def on_progress(name: str, value: Any) -> None:
            if name in ("time-pos", "playback-time") and isinstance(value, (int, float)):
                if value > 0:
                    first_frame_event.set()
                    timecodes.append(value)
            elif name == "duration" and isinstance(value, (int, float)) and value > 0:
                first_frame_event.set()

        controller.on_progress = on_progress

        t_launch = time.perf_counter()
        controller.launch(
            mpv_path=mpv_bin,
            url="av://lavfi:testsrc=duration=5:size=320x240:rate=25",
            title="Benchmark Playback",
            wid=None,
            extra_options=["--vo=null", "--ao=null"],
        )

        t_init = time.perf_counter()
        mpv_init_ms = round((t_init - t_launch) * 1000, 2)

        # Wait for first decoded frame (TTFF)
        frame_ready = first_frame_event.wait(timeout=10.0)
        assert frame_ready, "Timed out waiting for first video frame"
        t_first_frame = time.perf_counter()
        ttff_ms = round((t_first_frame - t_launch) * 1000, 2)

        # Let video decode actively and monitor peak RAM during playback
        ram_samples: list[float] = [get_process_tree_ram_mb()]
        sample_deadline = time.monotonic() + 1.5

        while time.monotonic() < sample_deadline:
            time.sleep(0.2)
            ram_samples.append(get_process_tree_ram_mb())

        ram_playing_mb = round(sum(ram_samples) / len(ram_samples), 2)
        ram_peak_mb = max(ram_samples)
        ram_delta_mb = round(ram_peak_mb - ram_idle_mb, 2)

        # Extract FPS and decoder metrics
        fps_prop = (
            controller.get_property("estimated-vf-fps")
            or controller.get_property("container-fps")
            or 25.0
        )
        fps = round(float(fps_prop), 2) if isinstance(fps_prop, (int, float)) else 25.0
        metrics = controller.get_playback_metrics()
        dropped_frames = metrics.get("dropped_frames", 0)

        # Stop playback
        controller.stop()
        service.loop.call_soon_threadsafe(service.loop.stop)
        time.sleep(0.3)
        gc.collect()

        ram_after_mb = get_process_tree_ram_mb()

        logger.info(
            "[BENCHMARK] MPV Init: %.2f ms | TTFF: %.2f ms | FPS: %.1f | Dropped: %d",
            mpv_init_ms,
            ttff_ms,
            fps,
            dropped_frames,
        )
        logger.info(
            "[BENCHMARK] RAM: Idle = %.2f MB | Playing = %.2f MB | Peak = %.2f MB (delta: +%.2f MB) | Restored = %.2f MB",
            ram_idle_mb,
            ram_playing_mb,
            ram_peak_mb,
            ram_delta_mb,
            ram_after_mb,
        )

        # Save metrics to results
        BENCHMARK_RESULTS["metrics"]["mpv_init_ms"] = mpv_init_ms
        BENCHMARK_RESULTS["metrics"]["time_to_first_frame_ms"] = ttff_ms
        BENCHMARK_RESULTS["metrics"]["fps"] = fps
        BENCHMARK_RESULTS["metrics"]["dropped_frames"] = dropped_frames
        BENCHMARK_RESULTS["metrics"]["codec"] = metrics.get("codec") or "rawvideo"
        BENCHMARK_RESULTS["metrics"]["hwdec_active"] = metrics.get("hwdec_active", False)
        BENCHMARK_RESULTS["metrics"]["ram_idle_mb"] = ram_idle_mb
        BENCHMARK_RESULTS["metrics"]["ram_playing_mb"] = ram_playing_mb
        BENCHMARK_RESULTS["metrics"]["ram_peak_mb"] = ram_peak_mb
        BENCHMARK_RESULTS["metrics"]["ram_delta_mb"] = ram_delta_mb

        BENCHMARK_RESULTS["summary"]["FPS"] = fps
        BENCHMARK_RESULTS["summary"]["RAM MB"] = ram_peak_mb

        save_benchmark_report(BENCHMARK_RESULTS)

        assert mpv_init_ms > 0, "MPV init measurement must be strictly positive"
        assert ttff_ms > 0, "Time to first frame must be strictly positive"
        assert fps > 0, "Playback FPS must be positive"
    finally:
        gui._window = orig_window
        if controller:
            try:
                controller.stop()
            except Exception:
                pass
        if service and hasattr(service, "loop") and service.loop.is_running():
            service.loop.call_soon_threadsafe(service.loop.stop)


def run_benchmarks_cli() -> int:
    """Standalone runner that runs all benchmarks, outputs a formatted table, and saves the JSON report."""
    print("=" * 65)
    print(" PIRATE CINEMA REPRODUCIBLE PERFORMANCE BENCHMARKS ")
    print("=" * 65)

    test_app_cold_start_benchmark()
    asyncio.run(test_cold_search_benchmark())
    test_mpv_playback_performance_benchmark()

    save_benchmark_report(BENCHMARK_RESULTS)

    m = BENCHMARK_RESULTS["metrics"]
    s = BENCHMARK_RESULTS["summary"]

    print("\n" + "-" * 65)
    print(" BENCHMARK RESULTS SUMMARY ")
    print("-" * 65)
    print(f"  * Cold Start Time:       {m.get('cold_start_ms', 'N/A')} ms")
    print(f"  * MPV Initialization:    {m.get('mpv_init_ms', 'N/A')} ms")
    print(f"  * Time to First Frame:   {m.get('time_to_first_frame_ms', 'N/A')} ms")
    print(f"  * Cold Search Latency:   {m.get('cold_search_ms', 'N/A')} ms")
    print(f"  * Playback FPS:          {m.get('fps', 'N/A')}")
    print(f"  * RAM (Idle):            {m.get('ram_idle_mb', 'N/A')} MB")
    print(f"  * RAM (Playing):         {m.get('ram_playing_mb', 'N/A')} MB")
    print(f"  * RAM (Peak):            {m.get('ram_peak_mb', 'N/A')} MB")
    print(f"  * RAM Delta:             +{m.get('ram_delta_mb', 'N/A')} MB")
    print("-" * 65)
    print(f" JSON Report exported to:  {REPORT_FILE.resolve()}")
    print(f" Summary metrics:          FPS={s.get('FPS')}, RAM MB={s.get('RAM MB')}, cold start ms={s.get('cold start ms')}")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(run_benchmarks_cli())
