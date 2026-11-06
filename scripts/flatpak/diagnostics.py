"""Check the installed Flatpak's graphics, playback and loopback services."""

import argparse
import ctypes
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from backend.core.settings import config, get_data_dir, resolve_mpv_binary
from backend.infrastructure.ffmpeg import get_ffmpeg, get_ffprobe
from backend.infrastructure.mpv.controller import MPVController
from backend.infrastructure.torrserver import process as torrserver



def check_gl_extensions() -> None:
    info = Path("/.flatpak-info").read_text()
    extensions = [line for line in info.splitlines() if "extensions=" in line]
    print("\n".join(extensions), flush=True)
    if not any("org.freedesktop.Platform.GL." in line for line in extensions):
        print("WARN: no Freedesktop GL extension is mounted", flush=True)
    nvidia = Path("/sys/module/nvidia/version")
    if nvidia.is_file():
        driver = nvidia.read_text().strip().replace(".", "-")
        if not any(f"org.freedesktop.Platform.GL.nvidia-{driver}=" in line for line in extensions):
            print(f"WARN: no Flatpak GL extension for loaded NVIDIA driver {driver}", flush=True)
    print("Host comparison: flatpak --gl-drivers; flatpak list --runtime", flush=True)


def check_xcb_dependencies(plugin: Path) -> None:
    if not plugin.is_file():
        raise RuntimeError(f"Qt xcb platform plugin is missing: {plugin}")
    if shutil.which("ldd"):
        result = subprocess.run(["ldd", str(plugin)], capture_output=True, text=True, timeout=10)
        if result.returncode or "not found" in result.stdout:
            raise RuntimeError(f"Qt xcb dependencies could not be loaded:\n{result.stdout}{result.stderr}")
        print("PASS: Qt xcb shared libraries resolve", flush=True)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_video(path: Path) -> None:
    subprocess.run(
        [
            str(get_ffmpeg()), "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=320x240:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", "3", "-c:v", "libx264", "-c:a", "aac", str(path),
        ],
        check=True,
        timeout=20,
    )
    codec = subprocess.check_output(
        [str(get_ffprobe()), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
        timeout=10,
    ).strip()
    if codec != "h264":
        raise RuntimeError(f"FFprobe did not identify the H.264 test video: {codec}")
    print("PASS: FFmpeg encoded H.264 and FFprobe read the stream", flush=True)


def check_glx() -> None:
    # Report the two common GLX failures separately. MPV uses EGL for --wid.
    x11 = ctypes.CDLL("libX11.so.6")
    gl = ctypes.CDLL("libGL.so.1")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
    x11.XFree.argtypes = [ctypes.c_void_p]
    gl.glXQueryExtension.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    gl.glXChooseFBConfig.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
    ]
    gl.glXChooseFBConfig.restype = ctypes.c_void_p
    display = x11.XOpenDisplay(None)
    try:
        if not display or not gl.glXQueryExtension(display, None, None):
            print("WARN: Could not initialize GLX", flush=True)
            return
        count = ctypes.c_int()
        configs = gl.glXChooseFBConfig(display, x11.XDefaultScreen(display), None, ctypes.byref(count))
        if configs:
            x11.XFree(configs)
        if count.value:
            print(f"PASS: GLX exposed {count.value} FBConfigs", flush=True)
        else:
            print("WARN: Failed to find matching FBConfig", flush=True)
    finally:
        if display:
            x11.XCloseDisplay(display)


def check_graphics(video: Path, require_audio: bool) -> None:
    print("Checking Qt xcb platform plugin", flush=True)
    from PyQt6.QtCore import QLibraryInfo
    from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication, QWidget
    from Xlib import display

    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    check_xcb_dependencies(plugins / "platforms" / "libqxcb.so")
    app = QApplication(["pirate-cinema-diagnostics"])
    if app.platformName() != "xcb":
        raise RuntimeError(f"Qt platform plugin xcb could not be initialized: {app.platformName()}")
    print("PASS: Qt xcb initialized", flush=True)
    check_glx()

    surface = QOffscreenSurface()
    surface.create()
    context = QOpenGLContext()
    if not context.create() or not context.makeCurrent(surface):
        raise RuntimeError("Could not create an OpenGL context; check the Flatpak GL extension")
    gl = ctypes.CDLL("libGL.so.1")
    gl.glGetString.restype = ctypes.c_char_p
    for name, key in (("vendor", 0x1F00), ("renderer", 0x1F01), ("version", 0x1F02)):
        print(f"OpenGL {name}: {gl.glGetString(key)}", flush=True)
    context.doneCurrent()

    view = QWebEngineView()
    result = []
    crash = []
    view.renderProcessTerminated.connect(lambda status, code: crash.append((status, code)))
    view.loadFinished.connect(
        lambda ok: view.page().runJavaScript("document.body.textContent", result.append)
        if ok else result.append(None)
    )
    view.setHtml("<html><body>WebEngine renderer OK</body></html>")
    view.show()
    deadline = time.monotonic() + 20
    while not result and not crash and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    if crash or result != ["WebEngine renderer OK"]:
        raise RuntimeError(f"Qt WebEngine process crashed or page failed: {crash or result}")
    print("PASS: Qt WebEngine renderer executed JavaScript", flush=True)
    view.close()

    media_view = QWebEngineView()
    media_result = []
    media_view.loadFinished.connect(
        lambda ok: media_view.page().runJavaScript(
            """(() => {
              const v=document.querySelector('video');
              const a=document.querySelector('audio');
              const mp4='video/mp4; codecs=\"avc1.42E01E, mp4a.40.2\"';
              const aac='audio/mp4; codecs=\"mp4a.40.2\"';
              const mse=window.MediaSource && MediaSource.isTypeSupported(mp4);
              return {canPlay:v.canPlayType(mp4), audioCanPlay:a.canPlayType(aac), mse:!!mse, state:v.readyState,
                error:v.error && {code:v.error.code,message:v.error.message},
                currentTime:v.currentTime, audioTime:a.currentTime, duration:v.duration};
            })()""", media_result.append,
        ) if ok else media_result.append(None)
    )
    from PyQt6.QtCore import QUrl
    media_view.setHtml(
        f'<video autoplay muted playsinline src="{video.as_uri()}"></video>'
        f'<audio autoplay muted src="{video.as_uri()}"></audio>',
        QUrl.fromLocalFile(str(video.parent) + "/"),
    )
    media_view.show()
    deadline = time.monotonic() + 12
    while not media_result and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    if not media_result or not isinstance(media_result[0], dict):
        raise RuntimeError("Qt WebEngine did not report H.264/AAC playback capabilities")
    result = media_result[0]
    print(f"Qt WebEngine H.264/AAC: {result}", flush=True)
    if not result["canPlay"] or not result["audioCanPlay"]:
        print("WARN: Qt WebEngine lacks H.264/AAC support; FFmpeg/MPV availability does not supply browser codecs", flush=True)
    if not result["mse"]:
        print("WARN: Qt WebEngine does not advertise MP4 MSE support", flush=True)
    if result["canPlay"] and result["audioCanPlay"]:
        media_deadline = time.monotonic() + 8
        while time.monotonic() < media_deadline:
            app.processEvents()
            media_result.clear()
            media_view.page().runJavaScript(
                "({time:document.querySelector('video').currentTime,audioTime:document.querySelector('audio').currentTime,error:document.querySelector('video').error?.code})",
                media_result.append,
            )
            if (media_result and isinstance(media_result[0], dict) and
                    media_result[0].get("time", 0) > 0 and media_result[0].get("audioTime", 0) > 0):
                print("PASS: Qt WebEngine played the local H.264 video and AAC audio", flush=True)
                break
            time.sleep(0.05)
        else:
            raise RuntimeError(f"Qt WebEngine advertises H.264/AAC but did not play the test media: {result}")
    media_view.close()

    parent = QWidget()
    parent.resize(480, 270)
    parent.show()
    app.processEvents()
    wid = int(parent.winId())
    x11 = display.Display()
    window = x11.create_resource_object("window", wid)
    # A second IPC connection can query MPV while the controller owns its event socket.
    player = MPVController()
    played = False

    def on_progress(name, value):
        nonlocal played
        if name == "time-pos" and isinstance(value, (int, float)) and value > 0:
            played = True

    player.on_progress = on_progress
    config.MPV_ARGS = [*config.MPV_ARGS, "--hwdec=auto", "--ao=pulse"]
    try:
        player.launch(resolve_mpv_binary(), str(video), "Flatpak diagnostics", wid=wid)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            app.processEvents()
            if not player.is_running:
                break
            if played and window.query_tree().children and player._osd_ready:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("MPV --wid failed to attach, decode video or initialize cinema.lua")
        if not player.is_running:
            raise RuntimeError(f"MPV --wid failed to attach: {player.last_error}")

        properties = mpv_properties(player.pipe_name, ("hwdec-current", "current-ao"))
        if require_audio and properties["current-ao"] != "pulse":
            raise RuntimeError(f"MPV failed to connect to PulseAudio: {properties}")
        print(f"PASS: MPV --wid, video decoding and cinema.lua; {properties}", flush=True)
    except (OSError, RuntimeError):
        log = get_data_dir() / "mpv_debug.log"
        if log.is_file():
            print(log.read_text(errors="replace")[-4000:], flush=True)
        raise
    finally:
        player.stop()
        x11.close()
        parent.close()


def mpv_properties(pipe_name: str, names: tuple[str, ...]) -> dict:
    result = {}
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(3)
        sock.connect(pipe_name)
        with sock.makefile("rb") as responses:
            for request_id, name in enumerate(names, 1):
                request = {"command": ["get_property", name], "request_id": request_id}
                sock.sendall((json.dumps(request) + "\n").encode())
                while line := responses.readline():
                    response = json.loads(line)
                    if response.get("request_id") == request_id:
                        break
                else:
                    raise RuntimeError(f"MPV IPC closed while reading {name}")
                result[name] = response.get("data")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-audio", action="store_true", help="fail without a Pulse server")
    args = parser.parse_args()

    if not os.environ.get("DISPLAY"):
        parser.exit(1, "X11 DISPLAY is missing; enable XWayland for this Wayland session.\n")
    check_gl_extensions()
    with tempfile.TemporaryDirectory(prefix="pirate-cinema-diagnostics-") as tmp:
        folder = Path(tmp)
        os.environ["XDG_DATA_HOME"] = str(folder / "data")
        try:
            torrserver.connect_or_start(f"http://127.0.0.1:{free_port()}", data_dir=folder / "ts")
            print("PASS: bundled TorrServer bound localhost and answered /echo", flush=True)
        except (OSError, RuntimeError) as error:
            raise RuntimeError(f"TorrServer cannot bind localhost or answer /echo: {error}") from error
        finally:
            torrserver.stop()
        video = folder / "test.mp4"
        make_video(video)
        from backend.services import tray
        print(f"System tray available: {tray.is_available()}", flush=True)
        check_graphics(video, args.require_audio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
