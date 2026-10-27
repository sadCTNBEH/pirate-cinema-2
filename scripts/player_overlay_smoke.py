"""Windows HWND/OSD smoke host, independent of TorrServer and user history.

Run: python scripts/player_overlay_smoke.py path/to/local/video.mkv
Add --fullscreen to check native fullscreen composition directly.
Add --cursor-info to log the real Windows cursor over the video while playing/paused.
Set CINEMA_MPV_OSC=legacy to compare the original OSC. Close the window to stop MPV.
"""
import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clr

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
from unittest.mock import MagicMock

from System.Drawing import Size
from System.Windows.Forms import Application, Form, FormBorderStyle, Timer

from backend import gui
from backend.infrastructure.mpv.controller import MPVController
from backend.models.playback import PlaybackState
from backend.services.playback import PlaybackService

form = Form()
form.Text = 'Pirate Cinema Overlay Smoke'
form.FormBorderStyle = getattr(FormBorderStyle, 'None')  # Match the real frameless pywebview host.
form.ClientSize = Size(960, 540)
gui._window = SimpleNamespace(native=form, evaluate_js=lambda code: None)
api = gui.window_api
controller = MPVController()
service = PlaybackService(MagicMock(), MagicMock(), MagicMock(), lambda: controller,
                          MagicMock(), lambda: '')
service.controllers['smoke'] = controller
service.active_states['smoke'] = PlaybackState(hash='smoke', file_id=1)
service.loop = asyncio.new_event_loop()
threading.Thread(target=service.loop.run_forever, daemon=True).start()
paused = False
def progress(name, value):
    global paused
    if name == 'pause':
        paused = bool(value)
    if name in ('cinema-action', 'fullscreen'):
        service._handle_progress('smoke', name, value)
    if name in ('cinema-action', 'pause', 'volume', 'aid', 'sid'):
        print(name, value, flush=True)
controller.on_progress = progress

def start(sender, event):
    wid = api.ensure_player_hwnd()
    api.set_player_bounds(0, 0, 960, 540, 960, 540, clip_top=0)
    def launch():
        controller.launch(Path('mpv/mpv.exe').resolve(), str(Path(sys.argv[1]).resolve()), 'Overlay smoke', wid=wid)
        controller.send_command(['set_property', 'mute', True])
        if '--fullscreen' in sys.argv:
            service.set_fullscreen(True)
    threading.Thread(target=launch, daemon=True).start()

def resized(sender, event):
    api.set_player_bounds(0, 0, form.ClientSize.Width, form.ClientSize.Height,
                          form.ClientSize.Width, form.ClientSize.Height, clip_top=0)

form.Shown += start
form.Resize += resized

# Read-only native diagnostics: verify the system cursor, not a cursor baked into video.
cursor_timer = None
if '--cursor-info' in sys.argv:
    import ctypes
    from ctypes import wintypes

    class CursorInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                    ('hCursor', wintypes.HANDLE), ('ptScreenPos', wintypes.POINT)]

    user32 = ctypes.windll.user32
    user32.GetCursorInfo.argtypes = [ctypes.POINTER(CursorInfo)]
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
    last_cursor_info = None

    def report_cursor(sender, event):
        global last_cursor_info
        info = CursorInfo()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetCursorInfo(ctypes.byref(info)) and api._player_hwnd:
            under_mouse = user32.WindowFromPoint(info.ptScreenPos)
            if under_mouse == api._player_hwnd or user32.IsChild(api._player_hwnd, under_mouse):
                from System.Windows.Forms import Cursors

                status = (bool(info.flags & 1), info.hCursor == Cursors.Default.Handle.ToInt64(), api.is_fullscreen(), paused)
                if status != last_cursor_info:
                    print('native cursor: visible={} system_arrow={} fullscreen={} paused={}'.format(*status), flush=True)
                    last_cursor_info = status

    cursor_timer = Timer()
    cursor_timer.Interval = 100
    cursor_timer.Tick += report_cursor
    cursor_timer.Start()
def closed(sender, event):
    if cursor_timer:
        cursor_timer.Stop()
        cursor_timer.Dispose()
    api._hotkey_running = False
    controller.stop()
    service.loop.call_soon_threadsafe(service.loop.stop)
form.FormClosed += closed
Application.Run(form)
