"""Check the installed Flatpak's graphics, playback and loopback services."""

import argparse
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
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


def make_vp9_video(path: Path) -> None:
    subprocess.run(
        [
            str(get_ffmpeg()), "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=320x240:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", "3", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
            "-c:a", "libopus", str(path),
        ],
        check=True,
        timeout=30,
    )
    codecs = subprocess.check_output(
        [str(get_ffprobe()), "-v", "error", "-show_entries", "stream=codec_name",
         "-of", "default=nw=1:nk=1", str(path)],
        text=True,
        timeout=10,
    ).splitlines()
    if codecs != ["vp9", "opus"]:
        raise RuntimeError(f"FFprobe did not identify VP9/Opus test media: {codecs}")
    print("PASS: FFmpeg encoded VP9/Opus and FFprobe read both streams", flush=True)


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


def check_graphics(video: Path, vp9_video: Path, require_audio: bool, webengine_only: bool = False) -> None:
    print("Checking Qt xcb platform plugin", flush=True)
    from PyQt6.QtCore import QLibraryInfo
    from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication, QWidget
    from Xlib import display

    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    check_xcb_dependencies(plugins / "platforms" / "libqxcb.so")

    def play_test_media(path: Path, label: str, codec: str) -> dict | None:
        mime = ('video/mp4; codecs="avc1.42E01E, mp4a.40.2"' if codec == "h264"
                else 'video/webm; codecs="vp9, opus"')
        code = r'''import json,sys,time
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
path,label,mime=sys.argv[1:]
app=QApplication(["pirate-cinema-media-test"])
view=QWebEngineView(); results=[]
view.settings().setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture,False)
html="""<!doctype html><video id='v' controls autoplay muted playsinline src=MEDIA_URL></video>
<script>const v=document.getElementById('v'),events=[];
for(const e of ['loadedmetadata','canplay','playing','timeupdate','error','ended'])v.addEventListener(e,()=>events.push({event:e,time:v.currentTime,readyState:v.readyState,networkState:v.networkState,error:v.error?{code:v.error.code,message:v.error.message}:null}));
window.snapshot=()=>({events,canPlay:v.canPlayType(MIME),mse:MediaSource.isTypeSupported(MIME),currentTime:v.currentTime,duration:v.duration,readyState:v.readyState,networkState:v.networkState,error:v.error?{code:v.error.code,message:v.error.message}:null});</script>""".replace('MEDIA_URL',json.dumps(QUrl.fromLocalFile(path).toString())).replace('MIME',json.dumps(mime))
view.loadFinished.connect(lambda ok:view.page().runJavaScript('window.snapshot()',results.append) if ok else results.append(None))
view.setHtml(html,QUrl.fromLocalFile(__import__('pathlib').Path(path).parent.as_uri()+'/'));view.show()
deadline=time.monotonic()+15
while not results and time.monotonic()<deadline:app.processEvents();time.sleep(.02)
result=results[0] if results and isinstance(results[0],dict) else None
deadline=time.monotonic()+8
while result and time.monotonic()<deadline and not result.get('error') and result.get('currentTime',0)<=.005:
 app.processEvents();results.clear();view.page().runJavaScript('window.snapshot()',results.append)
 if results and isinstance(results[0],dict):result=results[0]
 time.sleep(.05)
print(json.dumps(result),flush=True)
view.close();view.deleteLater();app.processEvents()
'''
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code, str(path), label, mime],
                capture_output=True, text=True, timeout=25, check=False,
            )
            payload = next((line for line in reversed(proc.stdout.splitlines()) if line.startswith("{")), None)
            result = json.loads(payload) if payload else None
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            print(f"WARN: isolated Qt WebEngine test failed for {label}: {error}", flush=True)
            return None
        if proc.returncode or not isinstance(result, dict):
            print(f"WARN: isolated Qt WebEngine test failed for {label}: {proc.stderr[-1200:]}", flush=True)
            return None
        print(f"Qt WebEngine {label} playback/events: {result}", flush=True)
        if result.get("error"):
            print(f"WARN: {label} media error {result['error']}", flush=True)
        elif result.get("currentTime", 0) > 0.005:
            print(f"PASS: Qt WebEngine decoded and played local {label}", flush=True)
        else:
            print(f"WARN: Qt WebEngine did not advance local {label}", flush=True)
        return result

    h264_result = play_test_media(video, "H.264/AAC", "h264")
    if not h264_result or not h264_result.get("canPlay") or not h264_result.get("mse"):
        print("WARN: embedded player sources using H.264/AAC MP4 MSE need a system browser", flush=True)
    play_test_media(vp9_video, "VP9/Opus", "vp9")
    if webengine_only:
        return

    app = QApplication(["pirate-cinema-diagnostics"])
    if app.platformName() != "xcb":
        raise RuntimeError(f"Qt platform plugin xcb could not be initialized: {app.platformName()}")
    print("PASS: Qt xcb initialized", flush=True)
    if not webengine_only:
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

    if not webengine_only:
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
        view.deleteLater()
        app.processEvents()

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
    parser.add_argument(
        "--webengine-media-only",
        action="store_true",
        help="test local H.264/AAC and VP9/Opus playback without running MPV diagnostics",
    )
    args = parser.parse_args()

    if not os.environ.get("DISPLAY"):
        parser.exit(1, "X11 DISPLAY is missing; enable XWayland for this Wayland session.\n")
    if not args.webengine_media_only:
        check_gl_extensions()
    with tempfile.TemporaryDirectory(prefix="pirate-cinema-diagnostics-") as tmp:
        folder = Path(tmp)
        os.environ["XDG_DATA_HOME"] = str(folder / "data")
        if not args.webengine_media_only:
            try:
                torrserver.connect_or_start(f"http://127.0.0.1:{free_port()}", data_dir=folder / "ts")
                print("PASS: bundled TorrServer bound localhost and answered /echo", flush=True)
            except (OSError, RuntimeError) as error:
                raise RuntimeError(f"TorrServer cannot bind localhost or answer /echo: {error}") from error
            finally:
                torrserver.stop()
        video = folder / "test.mp4"
        make_video(video)
        vp9_video = folder / "test.webm"
        make_vp9_video(vp9_video)
        if not args.webengine_media_only:
            from backend.services import tray
            print(f"System tray available: {tray.is_available()}", flush=True)
        check_graphics(video, vp9_video, args.require_audio, args.webengine_media_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
