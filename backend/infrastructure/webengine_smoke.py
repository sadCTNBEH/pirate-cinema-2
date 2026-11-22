"""Play generated fixtures in Pirate Cinema's normal Qt window (Linux smoke mode)."""

import logging
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.infrastructure.chromium_security import apply_chromium_security_policy

logger = logging.getLogger(__name__)
ARGUMENT = "--smoke-test-webengine"
ROUTE = "/__webengine_smoke"
status = 1

PLAYBACK_SCRIPT = r"""
(() => {
  window.__pcSmokeResult = null;
  const result = {};
  const mp4 = 'video/mp4; codecs="avc1.42C01E, mp4a.40.2"';
  const webm = 'video/webm; codecs="vp9, opus"';
  const wait = (predicate, description) => new Promise((resolve, reject) => {
    const until = performance.now() + 5500;
    const tick = () => {
      if (predicate()) resolve();
      else if (performance.now() > until) reject(new Error(description));
      else setTimeout(tick, 50);
    };
    tick();
  });
  async function play(audio, name, mime, prepare) {
    const video = document.createElement('video');
    video.style.cssText = 'position:fixed;top:0;left:0;width:320px;height:180px;z-index:2147483647';
    document.body.appendChild(video);
    const info = result[name] = {
      canPlay: video.canPlayType(mime),
      mse: MediaSource.isTypeSupported(mime)
    };
    if (!info.canPlay || !info.mse) throw new Error(name + ': unsupported ' + mime);
    let frames = 0;
    function countFrame() {
      frames++;
      video.requestVideoFrameCallback(countFrame);
    }
    video.requestVideoFrameCallback(countFrame);
    const analyser = audio.createAnalyser();
    audio.createMediaElementSource(video).connect(analyser);
    analyser.connect(audio.destination);
    const samples = new Float32Array(analyser.fftSize);
    try {
      await prepare(video);
      await Promise.race([
        Promise.all([video.play(), audio.resume()]),
        wait(() => video.error, name + ': play/audio context did not start')
      ]);
      await wait(() => video.error || (frames >= 3 && video.currentTime >= 0.25),
                 name + ': no displayed frames or playback progress');
      if (video.error) throw new Error(video.error.code + ': ' + video.error.message);
      if (video.paused || video.readyState < 2) throw new Error(name + ': playback paused/stalled');
      info.frames = frames;
      info.currentTime = video.currentTime;
      analyser.getFloatTimeDomainData(samples);
      info.audioPeak = samples.reduce((peak, sample) => Math.max(peak, Math.abs(sample)), 0);
      if (info.audioPeak < 0.01 || video.muted) throw new Error(name + ': no decoded audio signal');
      video.currentTime = 2;
      await wait(() => !video.seeking && video.currentTime >= 2.15 && frames > info.frames,
                 name + ': seek did not resume playback');
      info.afterSeek = video.currentTime;
    } finally {
      video.pause();
      video.remove();
      analyser.disconnect();
    }
  }
  const path = name => '/__webengine_smoke/' + name;
  const start = document.createElement('button');
  start.textContent = 'Run embedded media smoke test';
  start.style.cssText = 'position:fixed;inset:0;z-index:2147483647';
  document.body.appendChild(start);
  start.addEventListener('click', () => {
    start.remove();
    const audio = new AudioContext();
    const resumed = audio.resume();
    (async () => {
    await resumed;
    await play(audio, 'H264/AAC', mp4, video => { video.src = path('test.mp4'); });
    await play(audio, 'VP9/Opus', webm, video => { video.src = path('test.webm'); });
    await play(audio, 'MP4 MSE', mp4, async video => {
      const source = new MediaSource();
      const opened = new Promise(resolve => source.addEventListener('sourceopen', resolve, {once:true}));
      video.src = URL.createObjectURL(source);
      const response = await fetch(path('fragmented.mp4'));
      if (!response.ok) throw new Error('MSE fixture HTTP ' + response.status);
      const data = await response.arrayBuffer();
      await opened;
      const buffer = source.addSourceBuffer(mp4);
      await new Promise((resolve, reject) => {
        buffer.addEventListener('updateend', resolve, {once:true});
        buffer.addEventListener('error', () => reject(new Error('SourceBuffer error')), {once:true});
        buffer.appendBuffer(data);
      });
      source.endOfStream();
    });
    window.__pcSmokeResult = {ok:true, result};
    })().catch(error => { window.__pcSmokeResult = {ok:false, error:String(error), result}; })
       .finally(() => audio.close());
  }, {once:true});
})();
"""


@contextmanager
def serve_fixtures():
    from fastapi.staticfiles import StaticFiles

    from backend.app import app
    from backend.infrastructure.ffmpeg import get_ffmpeg
    from backend.infrastructure.process_env import system_process_env

    with TemporaryDirectory(prefix="pirate-webengine-smoke-") as directory:
        common = [
            str(get_ffmpeg()), "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", "5", "-threads", "2",
        ]
        h264 = ["-c:v", "libx264", "-profile:v", "baseline", "-level:v", "3.0",
                "-g", "25", "-c:a", "aac"]
        vp9 = ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus"]
        for name, options in (
            ("test.mp4", [*h264, "-movflags", "+faststart"]),
            ("fragmented.mp4", [*h264, "-movflags", "+frag_keyframe+empty_moov+default_base_moof"]),
            ("test.webm", vp9),
        ):
            subprocess.run([*common, *options, str(Path(directory) / name)],
                           env=system_process_env(), check=True, timeout=25)
        app.mount(ROUTE, StaticFiles(directory=directory))
        try:
            yield
        finally:
            app.router.routes.pop()


def install(expected_url):
    """Attach only to the primary pywebview page used by the running app."""
    import webview.platforms.qt as qt
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    if not qt.is_webengine:
        raise RuntimeError("The main window did not select Qt WebEngine")
    page_class = qt.BrowserView.WebPage
    init = page_class.__init__

    def finish(payload):
        global status
        status = int(not payload.get("ok"))
        logger.log(logging.ERROR if status else logging.INFO, "[WEBENGINE-SMOKE] %s", payload)
        QApplication.quit()

    def initialize(self, parent, *args, **kwargs):
        init(self, parent, *args, **kwargs)
        timeout = QTimer(self)
        timeout.setSingleShot(True)
        timeout.timeout.connect(lambda: finish({"ok": False, "error": "main window playback timed out"}))
        timeout.start(35000)
        poll = QTimer(self)
        poll.setInterval(200)

        def collect(payload):
            if not isinstance(payload, dict) or not poll.isActive():
                return
            timeout.stop()
            poll.stop()
            if payload.get("ok") and "bundled" == os.getenv("PIRATE_CINEMA_QT_RUNTIME_SELECTED"):
                from backend.infrastructure.webengine_diagnostics import _loaded_qt_libraries

                prefix = Path(sys._MEIPASS).resolve()
                libraries = _loaded_qt_libraries()
                if not libraries or any(not Path(path).resolve().is_relative_to(prefix) for path in libraries):
                    payload.update(ok=False, error=f"Qt loaded outside the bundle: {libraries}")
            if payload.get("ok"):
                from PyQt6 import QtWebEngineCore

                minimum_security = os.getenv("PIRATE_CINEMA_MIN_CHROMIUM_SECURITY_VERSION")
                chromium = getattr(QtWebEngineCore, "qWebEngineChromiumVersion", lambda: "")()
                patch = getattr(QtWebEngineCore, "qWebEngineChromiumSecurityPatchVersion", lambda: "")()
                security = apply_chromium_security_policy(
                    payload,
                    chromium,
                    patch,
                    minimum_security,
                    strict=os.getenv("PIRATE_CINEMA_STRICT_CHROMIUM_SECURITY") == "1",
                )
                if security["status"] == "WARNING":
                    logger.warning("[WEBENGINE-SMOKE] %s", security["message"])
            finish(payload)

        poll.timeout.connect(lambda: self.runJavaScript("window.__pcSmokeResult", collect))

        def click():
            view = parent.webview
            target = view.focusProxy() or view
            QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.rect().center())

        def loaded(ok):
            if ok and self.url().toString().rstrip("/") == expected_url and not poll.isActive():
                self.runJavaScript(PLAYBACK_SCRIPT)
                poll.start()
                QTimer.singleShot(500, click)

        self.loadFinished.connect(loaded)

    page_class.__init__ = initialize
