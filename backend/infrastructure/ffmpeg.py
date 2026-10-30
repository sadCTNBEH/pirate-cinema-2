"""FFmpeg and FFprobe binary locator, media analyzer and HLS command builder."""

import asyncio
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend.core.settings import BASE_DIR, get_data_dir


def find_binary(name: str) -> Path | None:
    """Find CLI binary (ffmpeg, ffprobe) across bundled vendor dirs, user data, mpv dir, and PATH."""
    binary_name = f"{name}.exe" if sys.platform == "win32" else name
    appdir = os.environ.get('APPDIR')
    if appdir:
        candidate = Path(appdir) / 'vendor' / 'ffmpeg' / binary_name
        if candidate.is_file():
            return candidate

    # 1. PyInstaller _MEIPASS (onefile bundle)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / "vendor" / "ffmpeg" / binary_name
        if p.is_file():
            return p

    # 2. Bundled vendor directory in project root
    bundled = BASE_DIR / "vendor" / "ffmpeg" / binary_name
    if bundled.is_file():
        return bundled

    # 3. PyInstaller onedir internal directory
    internal_bundled = BASE_DIR / "_internal" / "vendor" / "ffmpeg" / binary_name
    if internal_bundled.is_file():
        return internal_bundled

    # 4. AppData / user data vendor directory
    user_vendor = get_data_dir() / "vendor" / "ffmpeg" / binary_name
    if user_vendor.is_file():
        return user_vendor

    # 5. Alongside mpv if bundled
    from backend.core.settings.user import find_mpv_binary
    mpv_bin = find_mpv_binary()
    if mpv_bin and (mpv_bin.parent / binary_name).is_file():
        return mpv_bin.parent / binary_name

    # 6. System PATH
    found = shutil.which(binary_name) or shutil.which(name)
    if found:
        return Path(found)

    # 7. Common Windows paths if on win32
    if sys.platform == "win32":
        for cand in [
            Path(r"C:\ffmpeg\bin") / binary_name,
            Path(r"D:\ffmpeg\bin") / binary_name,
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ffmpeg" / "bin" / binary_name,
            Path(os.environ.get("ProgramFiles", "")) / "ffmpeg" / "bin" / binary_name,
        ]:
            if cand.is_file():
                return cand

    return None


def get_ffprobe() -> Path | None:
    return find_binary("ffprobe")


def get_ffmpeg() -> Path | None:
    return find_binary("ffmpeg")


def probe_media_sync(source: str, timeout: float = 18.0) -> dict[str, Any]:
    """Execute ffprobe synchronously with bounded timeout and memory alloc."""
    ffprobe_bin = get_ffprobe()
    if not ffprobe_bin:
        raise FileNotFoundError("ffprobe executable not found")

    cmd = [
        str(ffprobe_bin),
        "-v", "quiet",
        "-max_alloc", "16777216",
        "-protocol_whitelist", "http,https,tcp,tls,file,pipe",
        "-rw_timeout", "8000000",
        "-probesize", "4194304",
        "-analyzeduration", "5000000",
        "-max_streams", "32",
        "-threads", "1",
        "-show_entries", "format=format_name,duration:stream=index,codec_type,codec_name,pix_fmt,profile,level,channels,sample_rate,start_time,duration:stream_tags=DURATION",
        "-of", "json",
        source,
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
        creationflags=creationflags,
    )
    if res.returncode != 0 or not res.stdout:
        raise ValueError(f"ffprobe failed with return code {res.returncode}")
    return json.loads(res.stdout)


async def probe_media(source: str, timeout: float = 18.0) -> dict[str, Any]:
    """Execute ffprobe in a thread to keep async event loop non-blocking."""
    return await asyncio.to_thread(probe_media_sync, source, timeout)


def analyze_compatibility(probe_data: dict[str, Any]) -> dict[str, Any]:
    """Determine playback strategy: direct play or HLS transcoding."""
    fmt = probe_data.get("format", {})
    streams = probe_data.get("streams", [])
    v_streams = [s for s in streams if s.get("codec_type") == "video"]
    a_streams = [s for s in streams if s.get("codec_type") == "audio"]

    duration = 0.0
    video = v_streams[0] if v_streams else {}
    raw_dur = video.get('duration')
    if not raw_dur:
        tagged_duration = video.get('tags', {}).get('DURATION', '')
        try:
            hours, minutes, seconds = tagged_duration.split(':')
            raw_dur = int(hours) * 3600 + int(minutes) * 60 + float(seconds) - float(video.get('start_time') or 0)
        except (ValueError, TypeError):
            raw_dur = fmt.get('duration', 0)
    try:
        if raw_dur is not None:
            duration = float(raw_dur)
    except (ValueError, TypeError):
        duration = 0.0
    if not math.isfinite(duration) or duration < 0:
        duration = 0.0

    fmt_name = fmt.get("format_name", "").lower()
    format_list = [f.strip() for f in fmt_name.split(",")]

    if not v_streams:
        return {
            "mode": "unsupported",
            "duration": duration,
            "reason": "Видеопоток не обнаружен в файле",
            "video_codec": "",
            "audio_codec": "",
        }

    v = v_streams[0]
    v_codec = (v.get("codec_name") or "").lower()
    v_pix = (v.get("pix_fmt") or "").lower()
    v_profile = v.get("profile") or ""
    v_level = v.get("level") or 999

    is_mp4_container = any(k in format_list for k in ("mov", "mp4", "m4a", "3gp", "3g2", "mj2", "m4v"))
    is_h264 = v_codec == "h264"
    is_8bit = v_pix in ("yuv420p", "yuvj420p")
    is_profile_ok = v_profile in ("Constrained Baseline", "Baseline", "Main", "High")
    is_level_ok = 0 < v_level <= 52

    # Audio checks
    a = a_streams[0] if a_streams else {}
    a_codec = (a.get("codec_name") or "").lower()
    is_all_aac_stereo = (
        len(a_streams) > 0
        and all(
            (s.get("codec_name") or "").lower() == "aac"
            and (s.get("channels") or 0) <= 2
            for s in a_streams
        )
    )

    # 1. Direct Play: compatible MP4 container, 8-bit H.264, AAC stereo
    if (
        is_mp4_container
        and len(v_streams) == 1
        and is_h264
        and is_8bit
        and is_profile_ok
        and is_level_ok
        and is_all_aac_stereo
    ):
        return {
            "mode": "direct",
            "duration": duration,
            "video_codec": v_codec,
            "audio_codec": a_codec,
            "reason": "Direct Play: MP4/H.264/AAC полностью совместим",
        }

    # On-demand VOD needs exact, independently decodable segment boundaries.
    # Copying arbitrary source GOPs cannot satisfy the advertised seek timeline.

    # Transcode: incompatible video codec (HEVC, VP9, AV1, 10-bit H.264, etc.)
    return {
        "mode": "transcode",
        "duration": duration,
        "video_codec": v_codec,
        "audio_codec": a_codec,
        "reason": f"Transcode: перекодирование {v_codec} ({v_pix}) в H.264/AAC для Safari",
    }


def build_hls_command(
    ffmpeg_bin: Path,
    source: str,
    start_time: float,
    start_number: int,
    segment_duration: float,
    sink_segment_url: str,
    sink_playlist_url: str,
    audio_track_idx: int = 0,
    segment_count: int = 7,
) -> list[str]:
    """Construct safe, resource-bounded FFmpeg command line writing segments via HTTP PUT to memory sink."""
    cmd = [
        str(ffmpeg_bin),
        "-v", "warning",
        "-nostdin",
        "-protocol_whitelist", "http,https,tcp,tls,file,pipe",
        "-rw_timeout", "10000000",
    ]

    # Fast input seeking
    if start_time > 0:
        cmd.extend(["-ss", f"{start_time:.3f}"])

    cmd.extend([
        "-i", source,
        "-map", "0:v:0",
        "-map", f"0:a:{max(0, audio_track_idx)}?",
        "-t", str(segment_duration * segment_count),
    ])

    # Transcode video to H.264 8-bit with reasonable CPU / RAM bounds
    threads = min(4, max(1, (os.cpu_count() or 2) - 1))
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-maxrate", "4000k",
        "-bufsize", "8000k",
        "-pix_fmt", "yuv420p",
        "-vf", "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
        "-force_key_frames", f"expr:gte(t,n_forced*{segment_duration})",
        "-sc_threshold", "0",
        "-threads", str(threads),
        "-c:a", "aac",
        "-b:a", "160k",
        "-ac", "2",
    ])

    # Offset TS timestamps so PTS matches absolute timeline in VOD
    if start_time > 0:
        cmd.extend(["-output_ts_offset", f"{start_time:.3f}"])

    # HLS muxer sending segments via HTTP PUT to memory sink
    cmd.extend([
        "-sn",  # ignore subtitles for segmenter stability
        "-f", "hls",
        "-hls_time", str(segment_duration),
        "-hls_list_size", "15",
        "-start_number", str(start_number),
        "-hls_flags", "independent_segments",
        "-hls_segment_filename", sink_segment_url,
        "-method", "PUT",
        sink_playlist_url,
    ])

    return cmd
