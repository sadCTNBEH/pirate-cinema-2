"""Run with a real Qt/pywebview runtime: python -m tests.qt_adblock_smoke (or PYTHONPATH=. python tests/qt_adblock_smoke.py)."""

import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tempfile import TemporaryDirectory

import webview

from backend.infrastructure import web_adblock


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        port = self.server.server_port
        path = self.path.partition("?")[0]
        if path == "/":
            body = f"""<script>
            window.results = [];
            addEventListener('message', e => results.push(e.data));
            window.player = n => {{
              const frame = document.createElement('iframe');
              frame.allow = 'autoplay';
              frame.src = 'http://kodikplayer.com:{port}/embed?n=' + n;
              document.body.appendChild(frame);
            }};
            </script><body></body>"""
        elif path == "/embed":
            body = f"""<body><script>
            (async () => {{
              const ad = document.createElement('script');
              const result = new Promise(resolve => {{
                ad.onload = () => resolve(true);
                ad.onerror = () => resolve(false);
              }});
              ad.src = 'http://ads.test:{port}/ad.js' + location.search;
              document.head.appendChild(ad);
              const adVideo = document.createElement('video');
              const adVideoResult = new Promise(resolve => {{
                adVideo.onloadeddata = () => resolve(true);
                adVideo.onerror = () => resolve(false);
              }});
              adVideo.src = 'http://runtime.strm.yandex.ru/videos/ad-id/outputs/preroll.mp4'
                + location.search;
              document.body.appendChild(adVideo);
              const media = await Promise.all(['live.m3u8', 'stream.mpd', 'seg.m4s', 'sub.vtt']
                .map(path => fetch('http://ads.test:{port}/' + path + location.search)
                    .then(r => r.ok).catch(() => false)));
              const video = document.createElement('video');
              video.muted = true;
              video.src = 'http://ads.test:{port}/clip.webm' + location.search;
              document.body.appendChild(video);
              const playing = await new Promise(resolve => {{
                const timeout = setTimeout(() => resolve(false), 4000);
                video.ontimeupdate = () => {{
                  if (video.currentTime > 0.1) {{ clearTimeout(timeout); resolve(true); }}
                }};
                video.play().catch(() => {{ clearTimeout(timeout); resolve(false); }});
              }});
              video.pause();
              parent.postMessage([await result, await adVideoResult, ...media, playing], '*');
            }})();
            </script></body>"""
        else:
            body = "/* fixture */"
        if path in {"/clip.webm", "/videos/ad-id/outputs/preroll.mp4"}:
            data, mime = self.server.clip, "video/webm"
        else:
            data, mime = body.encode(), "application/javascript" if path.endswith(".js") else "text/html"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main():
    os.environ.setdefault("QT_API", "pyqt6")
    with TemporaryDirectory() as temp, ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        flags = ('--no-proxy-server --host-resolver-rules="MAP *.test 127.0.0.1, '
                 'MAP kodikplayer.com 127.0.0.1, '
                 f'MAP runtime.strm.yandex.ru 127.0.0.1:{server.server_port}"')
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
            os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "") + " " + flags
        )
        os.environ["XDG_DATA_HOME"] = temp
        server.clip = subprocess.check_output([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=20",
            "-t", "1", "-an", "-threads", "1", "-c:v", "libvpx-vp9", "-f", "webm", "pipe:1",
        ], timeout=15)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        from backend.core.settings import get_data_dir, save_settings
        from PyQt6.QtCore import QT_VERSION_STR, qVersion

        cache = get_data_dir() / "web-adblock" / "filters.json"
        cache.parent.mkdir()
        cache.write_text(json.dumps({
            "updated": int(time.time()),
            "sources": {name: f"! Title: {name}\n" + "! fixture\n" * 100 + "||ads.test^"
                        for name in web_adblock.FILTERS},
        }), encoding="utf-8")
        save_settings({"web_player_linux_adblock": True})
        web_adblock.install_qt_adblock()
        blocker = web_adblock.qt_adblock
        assert blocker is not None
        window = webview.create_window("Qt filter smoke", f"http://127.0.0.1:{server.server_port}/")
        errors = []

        def exercise():
            try:
                deadline = time.monotonic() + 5
                while not blocker.status()["active"] and time.monotonic() < deadline:
                    time.sleep(0.05)
                assert blocker.status()["active"]

                def play(index, expected_ad):
                    window.evaluate_js(f"player({index})")
                    deadline = time.monotonic() + 6
                    result = None
                    while time.monotonic() < deadline:
                        result = window.evaluate_js(f"results[{index}] || null")
                        if result is not None:
                            break
                        time.sleep(0.05)
                    assert result == [expected_ad, expected_ad, True, True, True, True, True], result

                play(0, False)
                assert blocker.status()["blocked"] == 2, blocker.status()
                blocker.set_exception("kodikplayer.com", True)
                play(1, True)
                blocker.set_exception("kodikplayer.com", False)
                blocker.set_enabled(False)
                play(2, True)
                blocker.set_enabled(True)
                play(3, False)
                assert blocker.status()["blocked"] == 4, blocker.status()
                print(f"PASS Qt {qVersion()} (bindings built with {QT_VERSION_STR}): "
                      "blocked ad script and video in Kodik iframe, allowed HLS/DASH/segment/subtitle, played WebM, "
                      "applied exception and live toggles", flush=True)
            except Exception as error:
                errors.append(error)
            finally:
                window.destroy()

        webview.start(exercise, gui="qt", private_mode=True)
        if errors:
            raise errors[0]


if __name__ == "__main__":
    main()
