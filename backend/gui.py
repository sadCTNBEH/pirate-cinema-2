"""Desktop UI & Tray Manager."""

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

import uvicorn

try:
    import webview
except (ImportError, OSError):
    webview = None

from backend.core.settings import BASE_DIR, config, get_data_dir
from backend.core.settings import load_settings as _load_settings
from backend.core.settings import save_settings as _save_settings
from backend.infrastructure.process_env import system_process_env
from backend.infrastructure.torrserver import process as torrserver_process
from backend.infrastructure.window_geometry import WindowGeometry, native_displays
from backend.services import tray
from backend.services.i18n import DEFAULT_LANG, t
from backend.services.settings import SettingsService

logger = logging.getLogger(__name__)

_window: Any = None


class WindowApi:
    """JS API exposed to pywebview and frontend for window chrome and embedded player management."""

    def __init__(self):
        self._is_maximized = False
        self._is_fullscreen = False
        self._is_pip = False
        self._pre_pip_window_state = None
        self._pre_pip_bounds = None
        self._player_visible = False
        self._player_occluded = False
        self._viewport_panel = None
        self._mpv_panel = None
        self._player_hwnd: int | None = None
        self._last_bounds: dict[str, float] | None = None
        self._inline_bounds: dict[str, float] | None = None
        self._pre_fs_window_state = None
        self._pre_fs_bounds = None
        self._hotkey_running = False
        self._hotkey_thread: threading.Thread | None = None
        self._last_fs_exit_time: float = 0.0
        self._last_fs_toggle_time: float = 0.0
        self._input_focused: bool = False
        self._form_hwnd: int | None = None
        self._on_frontend_ready: Callable[[], None] | None = None
        self._browser_proc: Any = None
        self._server: Any = None
        self._geometry: WindowGeometry | None = None
        self._geometry_suspended = False

    def _capture_geometry(self, *args) -> None:
        if not self._geometry or self._geometry_suspended or self._is_fullscreen or not _window:
            return
        try:
            displays = native_displays(webview)
            if os.name == 'nt' and getattr(_window, 'native', None):
                form = _window.native
                state = int(form.WindowState)
                if state == 1:
                    return
                rect = form.RestoreBounds if state == 2 else form.Bounds
                bounds = [rect.X, rect.Y, rect.Width, rect.Height]
                name = str(__import__('System.Windows.Forms', fromlist=['Screen']).Screen.FromControl(form).DeviceName)
                display = next((d for d in displays if d.name == name), displays[0])
                maximized = state == 2
            else:
                bounds = [_window.x, _window.y, _window.width, _window.height]
                display = next((d for d in displays if d.x <= bounds[0] < d.x+d.width
                                and d.y <= bounds[1] < d.y+d.height), displays[0])
                maximized = self._is_maximized
                if maximized and self._geometry.state.get('normal'):
                    bounds = self._geometry.state['normal']['bounds']
            self._geometry.remember(bounds, display, pip=self._is_pip, maximized=maximized)
        except (OSError, AttributeError, RuntimeError, IndexError, TypeError):
            logger.debug('Window geometry capture unavailable', exc_info=True)

    def _normal_geometry_bounds(self, fallback):
        if self._geometry:
            try:
                restored = self._geometry.restore(native_displays(webview), default_size=(config.WINDOW_WIDTH, config.WINDOW_HEIGHT))
                if restored:
                    return restored['bounds']
            except (OSError, AttributeError, RuntimeError):
                pass
        return fallback

    def set_input_focused(self, focused: bool) -> bool:
        self._input_focused = bool(focused)
        return self._input_focused

    def set_browser_process(self, proc: Any, server: Any = None) -> None:
        self._browser_proc = proc
        self._server = server

    def set_frontend_ready_callback(self, callback: Callable[[], None] | None) -> None:
        self._on_frontend_ready = callback

    def dismiss_startup_splash(self) -> bool:
        """Close the native splash once React has confirmed its health endpoint."""
        callback = self._on_frontend_ready
        self._on_frontend_ready = None
        if callback is not None:
            callback()
        return True

    def _invoke_ui(self, fn, sync: bool = False):
        if not _window or not getattr(_window, "native", None):
            return False
        form = _window.native

        def guarded_action():
            try:
                if not form.IsDisposed:
                    fn()
            except Exception:
                logger.exception("Failed to execute action on WinForms UI thread")

        try:
            import clr

            clr.AddReference("System")
            import System

            if getattr(form, "InvokeRequired", False):
                if sync:
                    form.Invoke(System.Action(guarded_action))
                else:
                    form.BeginInvoke(System.Action(guarded_action))
            else:
                guarded_action()
            return True
        except Exception:
            logger.exception("Failed to invoke action on WinForms UI thread")
            return False

    def ensure_player_hwnd(self) -> int | None:
        if self._player_hwnd:
            self._start_hotkey_listener()
            return self._player_hwnd
        if not _window or not getattr(_window, "native", None):
            return None

        def _init_panels():
            if self._player_hwnd and self._viewport_panel and self._mpv_panel:
                return
            import clr

            clr.AddReference("System.Drawing")
            clr.AddReference("System.Windows.Forms")
            import System.Windows.Forms as WinForms
            from System import Drawing

            form = _window.native

            viewport = WinForms.Panel()
            viewport.BackColor = Drawing.Color.Black
            viewport.TabStop = False
            viewport.Cursor = WinForms.Cursors.Default
            viewport.Visible = False
            viewport.SetBounds(0, 0, 800, 450)

            mpv_host = WinForms.Panel()
            mpv_host.BackColor = Drawing.Color.Black
            mpv_host.TabStop = False
            mpv_host.Cursor = WinForms.Cursors.Default
            mpv_host.Visible = True
            mpv_host.SetBounds(0, 0, 800, 450)



            viewport.Controls.Add(mpv_host)
            form.Controls.Add(viewport)
            viewport.BringToFront()

            self._viewport_panel = viewport
            self._mpv_panel = mpv_host
            self._player_hwnd = int(mpv_host.Handle.ToInt64())
            self._form_hwnd = int(form.Handle.ToInt64())
            logger.info(
                "[GUI] Created embedded MPV player HWND: %s, Form HWND: %s",
                self._player_hwnd,
                self._form_hwnd,
            )

        self._invoke_ui(_init_panels, sync=True)
        self._start_hotkey_listener()
        return self._player_hwnd

    def _start_hotkey_listener(self) -> None:
        """Bridge native MPV keyboard focus to the frontend action manager.

        WebView-owned input is handled only in React. Embedded MPV keyboard
        bindings are disabled; its OSC/mouse controls remain enabled.
        """
        if self._hotkey_running:
            return
        self._hotkey_running = True

        def _hotkey_loop():
            import ctypes
            from ctypes import wintypes

            from backend.infrastructure.input_bridge import KEY_CODES, key_payload

            class GUIThreadInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                            ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                            ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                            ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                            ("rcCaret", wintypes.RECT)]

            try:
                user32 = ctypes.windll.user32
                user32.GetForegroundWindow.restype = ctypes.c_void_p
                user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
            except (AttributeError, OSError):
                return
            held: dict[int, float] = {}
            previous_active = None
            while self._hotkey_running:
                time.sleep(0.03 if self._player_visible else 0.15)
                try:
                    foreground = user32.GetForegroundWindow()
                    active = bool(foreground and self._form_hwnd and (
                        foreground == self._form_hwnd or user32.IsChild(self._form_hwnd, foreground)))
                    if active != previous_active:
                        self._emit_input_event("cinema-native-focus", active)
                        previous_active = active
                    info = GUIThreadInfo()
                    info.cbSize = ctypes.sizeof(info)
                    native_focus = bool(active and self._player_visible and not self._player_occluded
                        and user32.GetGUIThreadInfo(0, ctypes.byref(info)) and self._player_hwnd
                        and (info.hwndFocus == self._player_hwnd or user32.IsChild(self._player_hwnd, info.hwndFocus)))
                    if not native_focus or self._input_focused:
                        held.clear()
                        continue
                    now = time.monotonic()
                    for vk in KEY_CODES:
                        if not user32.GetAsyncKeyState(vk) & 0x8000:
                            held.pop(vk, None)
                            continue
                        due = held.get(vk)
                        if due is not None and now < due:
                            continue
                        payload = key_payload(vk,
                            ctrl=bool(user32.GetAsyncKeyState(0x11) & 0x8000),
                            alt=bool(user32.GetAsyncKeyState(0x12) & 0x8000),
                            shift=bool(user32.GetAsyncKeyState(0x10) & 0x8000),
                            meta=bool(user32.GetAsyncKeyState(0x5B) & 0x8000 or user32.GetAsyncKeyState(0x5C) & 0x8000),
                            repeat=due is not None)
                        held[vk] = now + (0.38 if due is None else 0.11)
                        self._emit_input_event("cinema-native-key", payload)
                except (OSError, ValueError, RuntimeError, AttributeError):
                    logger.debug("Native input bridge unavailable", exc_info=True)

        self._hotkey_thread = threading.Thread(target=_hotkey_loop, daemon=True, name="EmbeddedPlayerInputBridge")
        self._hotkey_thread.start()

    def _emit_input_event(self, name: str, payload: Any) -> None:
        import json

        if _window:
            _window.evaluate_js(
                f"window.dispatchEvent(new CustomEvent({json.dumps(name)}, "
                f"{{detail: {json.dumps(payload)}}}))"
            )

    def set_player_bounds(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        viewport_width: float = 0,
        viewport_height: float = 0,
        clip_top: float = 36,
        clip_left: float = 0,
        clip_right: float = 0,
        clip_bottom: float = 0,
    ) -> bool:
        if not self._is_fullscreen and not self._is_pip:
            self._inline_bounds = {
                "x": float(x),
                "y": float(y),
                "width": float(width),
                "height": float(height),
                "viewport_width": float(viewport_width),
                "viewport_height": float(viewport_height),
                "clip_top": float(clip_top),
                "clip_left": float(clip_left),
                "clip_right": float(clip_right),
                "clip_bottom": float(clip_bottom),
            }
        self._last_bounds = {
            "x": float(x),
            "y": float(y),
            "width": float(width),
            "height": float(height),
            "viewport_width": float(viewport_width),
            "viewport_height": float(viewport_height),
            "clip_top": float(clip_top),
            "clip_left": float(clip_left),
            "clip_right": float(clip_right),
            "clip_bottom": float(clip_bottom),
        }
        self._player_visible = True
        self.ensure_player_hwnd()

        def _apply():
            if not self._viewport_panel or not self._mpv_panel or not _window or not _window.native:
                return
            if getattr(self, "_player_occluded", False):
                if self._viewport_panel.Visible:
                    self._viewport_panel.Visible = False
                return
            form = _window.native
            cw = int(form.ClientSize.Width)
            ch = int(form.ClientSize.Height)

            mpv_child_hwnd = None
            if self._player_hwnd and os.name == "nt":
                try:
                    import ctypes

                    user32 = ctypes.windll.user32
                    user32.FindWindowExW.restype = ctypes.c_void_p
                    user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
                    mpv_child_hwnd = user32.FindWindowExW(self._player_hwnd, None, "mpv", None)
                    if mpv_child_hwnd:
                        user32.EnableWindow(mpv_child_hwnd, True)
                        style = user32.GetWindowLongW(mpv_child_hwnd, -16)
                        if (style & 0x08000000) or not user32.IsWindowEnabled(mpv_child_hwnd):
                            user32.SetWindowLongW(mpv_child_hwnd, -16, style & ~0x08000000)
                            user32.SetWindowPos(mpv_child_hwnd, 0, 0, 0, 0, 0, 0x0027)
                except (AttributeError, OSError, TypeError, ValueError) as error:
                    logger.debug("Failed to update embedded MPV window style: %s", error)

            if self._is_fullscreen:
                import System.Windows.Forms as WinForms
                screen = WinForms.Screen.FromControl(form) or WinForms.Screen.PrimaryScreen
                sb = screen.Bounds
                w = max(cw, int(sb.Width))
                h = max(ch, int(sb.Height))
                self._viewport_panel.SetBounds(0, 0, w, h)
                self._mpv_panel.SetBounds(0, 0, w, h)
                if mpv_child_hwnd:
                    try:
                        ctypes.windll.user32.MoveWindow(mpv_child_hwnd, 0, 0, w, h, True)
                    except (AttributeError, OSError, RuntimeError) as error:
                        logger.debug("Failed to resize embedded MPV window: %s", error)
                if not self._viewport_panel.Visible:
                    self._viewport_panel.Visible = True
                self._viewport_panel.BringToFront()
                return

            if self._is_pip:
                return

            fallback_scale = float(getattr(form, "_scale", 1.0) or 1.0)
            scale_x = (cw / viewport_width) if viewport_width > 0 else fallback_scale
            scale_y = (ch / viewport_height) if viewport_height > 0 else fallback_scale

            px = round(x * scale_x)
            py = round(y * scale_y)
            pw = max(1, round(width * scale_x))
            ph = max(1, round(height * scale_y))

            c_top = round(clip_top * scale_y)
            c_left = round(clip_left * scale_x)
            c_right = round(clip_right * scale_x) if clip_right > 0 else cw
            c_bottom = round(clip_bottom * scale_y) if clip_bottom > 0 else ch

            vis_left = max(px, c_left)
            vis_top = max(py, c_top)
            vis_right = min(px + pw, c_right)
            vis_bottom = min(py + ph, c_bottom)
            vis_w = vis_right - vis_left
            vis_h = vis_bottom - vis_top

            if vis_w <= 0 or vis_h <= 0 or width <= 0 or height <= 0:
                if self._viewport_panel.Visible:
                    self._viewport_panel.Visible = False
                return

            self._viewport_panel.SetBounds(vis_left, vis_top, vis_w, vis_h)
            self._mpv_panel.SetBounds(px - vis_left, py - vis_top, pw, ph)
            if mpv_child_hwnd:
                try:
                    ctypes.windll.user32.MoveWindow(mpv_child_hwnd, 0, 0, pw, ph, True)
                except (AttributeError, OSError, RuntimeError) as error:
                    logger.debug("Failed to resize embedded MPV window: %s", error)
            if not self._viewport_panel.Visible:
                self._viewport_panel.Visible = True
            self._viewport_panel.BringToFront()

        return self._invoke_ui(_apply, sync=False)

    def set_player_occluded(self, occluded: bool) -> bool:
        self._player_occluded = bool(occluded)

        def _apply_occluded():
            if not self._viewport_panel:
                return
            if self._player_occluded:
                had_native_focus = self._viewport_panel.ContainsFocus
                if self._viewport_panel.Visible:
                    self._viewport_panel.Visible = False
                if had_native_focus and _window:
                    browser_control = getattr(_window.native, "webview", None)
                    if browser_control is not None:
                        browser_control.Focus()
            else:
                if self._player_visible and not self._viewport_panel.Visible:
                    self._viewport_panel.Visible = True
                    self._viewport_panel.BringToFront()

        self._invoke_ui(_apply_occluded, sync=False)
        return True

    def hide_player_panel(self) -> bool:
        self._player_visible = False
        self._last_bounds = None
        self._inline_bounds = None
        if self._is_pip:
            self.set_pip(False)
        if self._is_fullscreen:
            self.set_fullscreen(False)

        def _hide():
            if self._viewport_panel and self._viewport_panel.Visible:
                self._viewport_panel.Visible = False

        return self._invoke_ui(_hide, sync=False)

    def set_fullscreen(self, fullscreen: bool) -> bool:
        target = bool(fullscreen)
        if self._is_fullscreen == target:
            return self._is_fullscreen
        self._capture_geometry()
        self._geometry_suspended = True

        # Seamlessly transition from PiP to fullscreen if PiP was active
        if target and self._is_pip:
            self._is_pip = False
            if self._pre_pip_bounds is not None:
                self._pre_fs_bounds = self._pre_pip_bounds
                self._pre_pip_bounds = None
            if self._pre_pip_window_state is not None:
                self._pre_fs_window_state = self._pre_pip_window_state
                self._pre_pip_window_state = None

        now = time.time()
        if not target:
            self._last_fs_exit_time = now
        self._last_fs_toggle_time = now
        self._is_fullscreen = target

        def _apply_fs():
            if not _window or not _window.native:
                self._geometry_suspended = False
                return
            import clr

            clr.AddReference("System.Windows.Forms")
            import ctypes
            from ctypes import wintypes

            import System.Windows.Forms as WinForms

            class _MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]

            form = _window.native

            try:
                user32 = ctypes.windll.user32
                dwmapi = ctypes.windll.dwmapi
                hwnd = int(form.Handle.ToInt64())

                # Set 64-bit safe argtypes
                dwmapi.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(_MARGINS)]
                dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
                dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
                dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

                if target:
                    # Save state and bounds before fullscreen (never save Minimized state or offscreen bounds)
                    cur_ws = getattr(form, "WindowState", None)
                    if self._pre_fs_window_state is None:
                        if cur_ws is not None and cur_ws != getattr(WinForms.FormWindowState, "Minimized", 1):
                            self._pre_fs_window_state = int(cur_ws)
                        else:
                            self._pre_fs_window_state = 0

                    if self._pre_fs_bounds is None:
                        cur_l = int(form.Left)
                        cur_t = int(form.Top)
                        cur_w = int(form.Width)
                        cur_h = int(form.Height)
                        if cur_l > -10000 and cur_w >= 300 and cur_h >= 200:
                            self._pre_fs_bounds = (cur_l, cur_t, cur_w, cur_h)
                        else:
                            self._pre_fs_bounds = None

                    form.is_fullscreen = True
                    # Keep WindowState as Normal so Windows does not reserve a 1-pixel maximized border
                    if form.WindowState != WinForms.FormWindowState.Normal:
                        form.WindowState = WinForms.FormWindowState.Normal
                    form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
                    form.TopMost = True

                    # Remove DWM glass frame margin completely in fullscreen
                    zero_margins = _MARGINS(0, 0, 0, 0)
                    dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(zero_margins))

                    # Disable non-client rendering policy completely in fullscreen (DWMWA_NCRENDERING_POLICY = 2, DWMNCRP_DISABLED = 1)
                    val_nc = ctypes.c_int(1)
                    dwmapi.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(val_nc), ctypes.sizeof(val_nc))

                    # Disable window rounding (DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_DONOTROUND = 1)
                    val_corner = ctypes.c_int(1)
                    dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val_corner), ctypes.sizeof(val_corner))

                    # Remove border color (DWMWA_BORDER_COLOR = 34, DWMWA_COLOR_NONE = 0xFFFFFFFE)
                    val_border = ctypes.c_int(ctypes.c_int32(0xFFFFFFFE).value)
                    dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(val_border), ctypes.sizeof(val_border))

                    screen = WinForms.Screen.FromControl(form) or WinForms.Screen.PrimaryScreen
                    sb = screen.Bounds
                    form.SetBounds(sb.X, sb.Y, sb.Width, sb.Height)
                    user32.SetWindowPos(
                        hwnd,
                        -1,  # HWND_TOPMOST
                        sb.X,
                        sb.Y,
                        sb.Width,
                        sb.Height,
                        0x0040 | 0x0020,  # SWP_SHOWWINDOW | SWP_FRAMECHANGED
                    )

                    # Directly size panels and mpv child window to cover the screen
                    cw = int(form.ClientSize.Width)
                    ch = int(form.ClientSize.Height)
                    w = max(cw, int(sb.Width))
                    h = max(ch, int(sb.Height))
                    if self._viewport_panel and self._mpv_panel:
                        if self._player_visible and not getattr(self, "_player_occluded", False):
                            self._viewport_panel.SetBounds(0, 0, w, h)
                            self._mpv_panel.SetBounds(0, 0, w, h)
                            if self._player_hwnd:
                                try:
                                    user32.FindWindowExW.restype = ctypes.c_void_p
                                    user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
                                    mpv_child_hwnd = user32.FindWindowExW(self._player_hwnd, None, "mpv", None)
                                    if mpv_child_hwnd:
                                        user32.EnableWindow(mpv_child_hwnd, True)
                                        user32.MoveWindow(mpv_child_hwnd, 0, 0, w, h, True)
                                except (AttributeError, OSError, TypeError, ValueError) as error:
                                    logger.debug("Failed to resize fullscreen MPV window: %s", error)
                            if not self._viewport_panel.Visible:
                                self._viewport_panel.Visible = True
                            self._viewport_panel.BringToFront()
                        else:
                            if self._viewport_panel.Visible:
                                self._viewport_panel.Visible = False
                else:
                    form.is_fullscreen = False
                    form.TopMost = False

                    if (
                        self._viewport_panel
                        and (not self._player_visible or getattr(self, "_player_occluded", False))
                        and self._viewport_panel.Visible
                    ):
                        self._viewport_panel.Visible = False

                    # Restore DWM frame shadow for windowed frameless mode
                    shadow_margins = _MARGINS(1, 1, 1, 1)
                    dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(shadow_margins))

                    # Restore DWM non-client rendering policy (DWMWA_NCRENDERING_POLICY = 2, DWMNCRP_ENABLED = 2)
                    val_nc = ctypes.c_int(2)
                    dwmapi.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(val_nc), ctypes.sizeof(val_nc))

                    # Restore default corner rounding (DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_DEFAULT = 0)
                    val_corner = ctypes.c_int(0)
                    dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val_corner), ctypes.sizeof(val_corner))

                    # Restore default border color (DWMWA_BORDER_COLOR = 34, DWMWA_COLOR_DEFAULT = 0xFFFFFFFF)
                    val_border = ctypes.c_int(ctypes.c_int32(0xFFFFFFFF).value)
                    dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(val_border), ctypes.sizeof(val_border))

                    # Never restore to Minimized state
                    target_ws = WinForms.FormWindowState(
                        self._pre_fs_window_state if self._pre_fs_window_state is not None else 0
                    )
                    form.WindowState = WinForms.FormWindowState.Normal

                    screen = WinForms.Screen.FromControl(form) or WinForms.Screen.PrimaryScreen
                    wa = screen.WorkingArea

                    saved_b = self._normal_geometry_bounds(self._pre_fs_bounds)
                    if (
                        saved_b is not None
                        and isinstance(saved_b, (list, tuple))
                        and len(saved_b) == 4
                        and saved_b[0] > -10000
                        and saved_b[2] >= 300
                        and saved_b[3] >= 200
                    ):
                        form.SetBounds(int(saved_b[0]), int(saved_b[1]), int(saved_b[2]), int(saved_b[3]))
                    else:
                        w = min(config.WINDOW_WIDTH, wa.Width)
                        h = min(config.WINDOW_HEIGHT, wa.Height)
                        x = wa.Left + max(0, (wa.Width - w) // 2)
                        y = wa.Top + max(0, (wa.Height - h) // 2)
                        form.SetBounds(x, y, w, h)

                    self._pre_fs_window_state = None
                    self._pre_fs_bounds = None

                    if target_ws == WinForms.FormWindowState.Maximized:
                        form.WindowState = target_ws

                    user32.SetWindowPos(
                        hwnd,
                        -2,  # HWND_NOTOPMOST
                        0,
                        0,
                        0,
                        0,
                        0x0001 | 0x0002 | 0x0040 | 0x0020,  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW | SWP_FRAMECHANGED
                    )
                    user32.SetForegroundWindow(hwnd)
                # Restore the actual system cursor on the WinForms UI thread.
                # MPV's child HWND can delegate WM_SETCURSOR to these parent panels.
                form.Cursor = WinForms.Cursors.Default
                WinForms.Cursor.Current = WinForms.Cursors.Default
            except Exception:
                logger.exception("[GUI] Error applying DWM and SetWindowPos for fullscreen")
            finally:
                self._geometry_suspended = False
                self._capture_geometry()

        if not self._invoke_ui(_apply_fs, sync=False):
            self._geometry_suspended = False

        if not target:
            if self._player_visible and not getattr(self, "_player_occluded", False):
                bounds = self._inline_bounds or self._last_bounds
                if bounds:
                    self.set_player_bounds(**bounds)
            else:
                def _ensure_panel_hidden():
                    if self._viewport_panel and self._viewport_panel.Visible:
                        self._viewport_panel.Visible = False

                self._invoke_ui(_ensure_panel_hidden, sync=False)
        return self._is_fullscreen

    def toggle_fullscreen(self) -> bool:
        now = time.time()
        if now - self._last_fs_toggle_time < 0.4:
            return self._is_fullscreen
        return self.set_fullscreen(not self._is_fullscreen)

    def is_fullscreen(self) -> bool:
        return self._is_fullscreen

    def is_pip(self) -> bool:
        return self._is_pip

    def set_pip(self, enabled: bool) -> bool:
        target = bool(enabled)
        if self._is_pip == target:
            return self._is_pip
        self._capture_geometry()

        if target and self._is_fullscreen:
            self.set_fullscreen(False)

        self._is_pip = target
        self._geometry_suspended = True

        def _apply_pip():
            if not _window or not getattr(_window, "native", None):
                self._geometry_suspended = False
                return
            import clr

            clr.AddReference("System.Windows.Forms")
            import ctypes

            import System.Windows.Forms as WinForms

            form = _window.native
            try:
                user32 = ctypes.windll.user32
                hwnd = int(form.Handle.ToInt64())

                pip_w = 420
                header_h = 32
                video_h = 236
                total_h = header_h + video_h

                if target:
                    cur_ws = getattr(form, "WindowState", None)
                    if self._pre_pip_window_state is None:
                        if cur_ws is not None and cur_ws != getattr(WinForms.FormWindowState, "Minimized", 1):
                            self._pre_pip_window_state = int(cur_ws)
                        else:
                            self._pre_pip_window_state = 0

                    if self._pre_pip_bounds is None:
                        cur_l = int(form.Left)
                        cur_t = int(form.Top)
                        cur_w = int(form.Width)
                        cur_h = int(form.Height)
                        if cur_l > -10000 and cur_w >= 300 and cur_h >= 200:
                            self._pre_pip_bounds = (cur_l, cur_t, cur_w, cur_h)
                        else:
                            self._pre_pip_bounds = None

                    screen = WinForms.Screen.FromControl(form) or WinForms.Screen.PrimaryScreen
                    wa = screen.WorkingArea
                    pip_x = int(wa.Right - pip_w - 24)
                    pip_y = int(wa.Bottom - total_h - 24)
                    if self._geometry and self._geometry.state.get('pip'):
                        restored = self._geometry.restore(native_displays(webview), pip=True)
                        pip_x, pip_y, pip_w, total_h = restored['bounds']
                        video_h = max(1, total_h-header_h)

                    if form.WindowState != WinForms.FormWindowState.Normal:
                        form.WindowState = WinForms.FormWindowState.Normal

                    form.TopMost = True
                    form.SetBounds(pip_x, pip_y, pip_w, total_h)
                    user32.SetWindowPos(
                        hwnd,
                        -1,  # HWND_TOPMOST
                        pip_x,
                        pip_y,
                        pip_w,
                        total_h,
                        0x0040 | 0x0020,  # SWP_SHOWWINDOW | SWP_FRAMECHANGED
                    )

                    if self._viewport_panel and self._mpv_panel:
                        self._viewport_panel.SetBounds(0, header_h, pip_w, video_h)
                        self._mpv_panel.SetBounds(0, 0, pip_w, video_h)
                        if self._player_hwnd:
                            with suppress(Exception):
                                user32.FindWindowExW.restype = ctypes.c_void_p
                                user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
                                mpv_child_hwnd = user32.FindWindowExW(self._player_hwnd, None, "mpv", None)
                                if mpv_child_hwnd:
                                    user32.EnableWindow(mpv_child_hwnd, True)
                                    user32.MoveWindow(mpv_child_hwnd, 0, 0, pip_w, video_h, True)
                        if not self._viewport_panel.Visible:
                            self._viewport_panel.Visible = True
                        self._viewport_panel.BringToFront()
                else:
                    form.TopMost = False
                    target_ws = WinForms.FormWindowState(
                        self._pre_pip_window_state if self._pre_pip_window_state is not None else 0
                    )
                    form.WindowState = WinForms.FormWindowState.Normal

                    screen = WinForms.Screen.FromControl(form) or WinForms.Screen.PrimaryScreen
                    wa = screen.WorkingArea

                    saved_b = self._normal_geometry_bounds(self._pre_pip_bounds)
                    if (
                        saved_b is not None
                        and isinstance(saved_b, (list, tuple))
                        and len(saved_b) == 4
                        and saved_b[0] > -10000
                        and saved_b[2] >= 300
                        and saved_b[3] >= 200
                    ):
                        form.SetBounds(int(saved_b[0]), int(saved_b[1]), int(saved_b[2]), int(saved_b[3]))
                    else:
                        w = min(config.WINDOW_WIDTH, wa.Width)
                        h = min(config.WINDOW_HEIGHT, wa.Height)
                        x = wa.Left + max(0, (wa.Width - w) // 2)
                        y = wa.Top + max(0, (wa.Height - h) // 2)
                        form.SetBounds(x, y, w, h)

                    self._pre_pip_window_state = None
                    self._pre_pip_bounds = None

                    if target_ws == WinForms.FormWindowState.Maximized:
                        form.WindowState = target_ws

                    user32.SetWindowPos(
                        hwnd,
                        -2,  # HWND_NOTOPMOST
                        0,
                        0,
                        0,
                        0,
                        0x0001 | 0x0002 | 0x0040 | 0x0020,  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW | SWP_FRAMECHANGED
                    )
                    user32.SetForegroundWindow(hwnd)
            except Exception:
                logger.exception("[GUI] Error toggling PiP mode")
            finally:
                self._geometry_suspended = False
                self._capture_geometry()

        if not self._invoke_ui(_apply_pip, sync=False):
            self._geometry_suspended = False

        if not target and self._player_visible:
            bounds = self._inline_bounds or self._last_bounds
            if bounds:
                self.set_player_bounds(**bounds)
        return self._is_pip

    def toggle_pip(self) -> bool:
        return self.set_pip(not self._is_pip)

    def minimize(self) -> bool:
        if _window:
            try:
                _window.minimize()
                return True
            except Exception:
                logger.exception("Failed to minimize window")
        return False

    def maximize(self) -> bool:
        if _window:
            try:
                _window.maximize()
                self._is_maximized = True
                return True
            except Exception:
                logger.exception("Failed to maximize window")
        return False

    def show(self) -> bool:
        """Show window from tray, restore normal size/state, and activate."""
        if _window:
            try:
                if self._is_pip:
                    self.set_pip(False)
                _window.show()
                _window.restore()
                self._is_maximized = False
                self.ensure_player_hwnd()
                if os.name == "nt" and getattr(_window, "native", None):
                    try:
                        import ctypes

                        hwnd = _window.native.Handle.ToInt32()
                        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                    except Exception:
                        logger.exception("Failed to activate shown window")
                return True
            except Exception:
                logger.exception("Failed to show window")
        return False

    def restore(self) -> bool:
        if _window:
            try:
                if self._is_pip:
                    self.set_pip(False)
                    return True
                if self._is_fullscreen:
                    self.set_fullscreen(False)
                    return True
                _window.show()
                _window.restore()
                self._is_maximized = False
                self.ensure_player_hwnd()
                if os.name == "nt" and getattr(_window, "native", None):
                    try:
                        import ctypes

                        hwnd = _window.native.Handle.ToInt32()
                        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                    except Exception:
                        logger.exception("Failed to activate restored window")
                return True
            except Exception:
                logger.exception("Failed to restore window")
        return False

    def toggle_maximize(self) -> bool:
        if _window:
            if self._is_pip:
                self.set_pip(False)
            if self._is_fullscreen:
                self.set_fullscreen(False)
                return self.is_maximized()
            if self.is_maximized():
                return not self.restore()
            else:
                return self.maximize()
        return False

    def is_maximized(self) -> bool:
        if _window and getattr(_window, "native", None):
            try:
                # Windows Forms: FormWindowState.Maximized is 2
                state_val = getattr(_window.native, "WindowState", None)
                if state_val is not None:
                    return int(state_val) == 2 or str(state_val).lower() == "maximized"
            except (AttributeError, ValueError, TypeError) as e:
                logger.debug("Failed to determine window state from native handle: %s", e)
        return self._is_maximized

    def close(self) -> bool:
        if _window:
            try:
                _window.destroy()
                return True
            except Exception:
                logger.exception("Failed to close window")
        if self._browser_proc and getattr(self._browser_proc, "poll", lambda: 0)() is None:
            try:
                self._browser_proc.terminate()
            except OSError:
                pass
        if self._server:
            self._server.should_exit = True
            return True
        return False

    def save_backup(self) -> dict[str, str | bool]:
        """Create a backup and save it through the native file chooser."""
        if not _window or not webview:
            return {"saved": False, "error": "Desktop window is unavailable"}

        backup_path: Path | None = None
        try:
            backup_path = SettingsService(None, lambda: "").create_backup_zip()
            destination = _window.create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename="pirate_cinema_backup.zip",
                file_types=("ZIP archive (*.zip)",),
            )
            if not destination:
                return {"saved": False, "cancelled": True}

            if isinstance(destination, (list, tuple)):
                destination = destination[0]
            target = Path(str(destination))
            if target.suffix.lower() != ".zip":
                target = target.with_suffix(".zip")
            shutil.copyfile(backup_path, target)
            return {"saved": True, "path": str(target)}
        except (OSError, RuntimeError) as error:
            logger.exception("Failed to save backup through native dialog")
            return {"saved": False, "error": str(error)}
        finally:
            if backup_path:
                backup_path.unlink(missing_ok=True)


window_api = WindowApi()


def is_native_gui_available() -> bool:
    """Check if native pywebview backend (WebKitGTK on Linux) can be loaded safely."""
    if webview is None:
        return False

    # User override via env var
    gui_env = os.environ.get("PIRATE_CINEMA_GUI", "").strip().lower()
    if gui_env in ("browser", "web"):
        logger.info("[GUI] PIRATE_CINEMA_GUI=%s requested, using browser app mode", gui_env)
        return False
    if gui_env in ("webview", "gtk"):
        return True

    if sys.platform != "linux" and not sys.platform.startswith("linux"):
        return True

    return False


CHROMIUM_BINARIES: list[str] = [
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "brave-browser",
    "brave",
    "microsoft-edge-stable",
    "microsoft-edge",
    "vivaldi-stable",
    "vivaldi",
    "opera",
    "yandex-browser",
]

GECKO_BINARIES: list[str] = [
    "firefox",
    "firefox-esr",
    "librewolf",
    "waterfox",
    "floorp",
]


def find_available_browser() -> tuple[str, bool] | None:
    """Find an available browser on the system.

    Returns a tuple of (executable_path, is_chromium) or None.
    """
    custom_browser = _load_settings().get("browser_path")
    if custom_browser:
        p = Path(custom_browser).expanduser()
        if p.is_file():
            is_chrom = any(
                c in p.name.lower()
                for c in ("chrome", "chromium", "brave", "edge", "vivaldi", "opera")
            )
            return str(p), is_chrom

    for name in CHROMIUM_BINARIES:
        path = shutil.which(name)
        if path:
            return path, True

    if sys.platform == "win32":
        for env_var in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env_var)
            if not base:
                continue
            candidates = [
                Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                Path(base) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
            ]
            for c in candidates:
                if c.is_file():
                    return str(c), True

    if sys.platform == "darwin":
        mac_candidates = [
            ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", True),
            ("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser", True),
            ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", True),
            ("/Applications/Firefox.app/Contents/MacOS/firefox", False),
        ]
        for path_str, is_chrom in mac_candidates:
            if Path(path_str).is_file():
                return path_str, is_chrom

    for name in GECKO_BINARIES:
        path = shutil.which(name)
        if path:
            return path, False

    return None


def open_browser_window(app_url: str) -> tuple[subprocess.Popen | None, bool]:
    """Launch the application URL in a dedicated browser window.

    Returns (process_handle, is_app_mode).
    """
    browser_info = find_available_browser()
    browser_env = system_process_env()
    if browser_info:
        browser_bin, is_chromium = browser_info
        if is_chromium:
            profile_dir = get_data_dir() / "browser_profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                browser_bin,
                f"--app={app_url}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                f"--window-size={config.WINDOW_WIDTH},{config.WINDOW_HEIGHT}",
            ]
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                cmd.append("--no-sandbox")
            try:
                proc = subprocess.Popen(cmd, env=browser_env)
                logger.info("[GUI] Launched Chromium App Mode: %s", browser_bin)
                return proc, True
            except OSError as err:
                logger.warning("[GUI] Failed to launch %s with --app: %s", browser_bin, err)

        try:
            proc = subprocess.Popen([browser_bin, "--new-window", app_url], env=browser_env)
            logger.info("[GUI] Launched browser in new window: %s", browser_bin)
            return proc, False
        except OSError as err:
            logger.warning("[GUI] Failed to launch %s: %s", browser_bin, err)

    if shutil.which("wslview"):
        try:
            proc = subprocess.Popen(["wslview", app_url], env=browser_env)
            logger.info("[GUI] Opened URL via wslview: %s", app_url)
            return proc, False
        except OSError:
            pass

    if sys.platform == "linux" and shutil.which("cmd.exe"):
        try:
            proc = subprocess.Popen(["cmd.exe", "/c", "start", app_url], env=browser_env)
            logger.info("[GUI] Opened URL via Windows host (cmd.exe): %s", app_url)
            return proc, False
        except OSError:
            pass

    if shutil.which("xdg-open"):
        try:
            proc = subprocess.Popen(["xdg-open", app_url], env=browser_env)
            logger.info("[GUI] Opened URL via xdg-open: %s", app_url)
            return proc, False
        except OSError:
            pass

    import webbrowser

    if not webbrowser.open(app_url, new=1):
        raise RuntimeError(
            f"Could not open a browser. Install Chromium or Firefox, or open {app_url} manually."
        )
    logger.info("[GUI] Opened URL via python webbrowser module: %s", app_url)
    return None, False


def launch_browser_app(
    server: uvicorn.Server,
    on_frontend_ready: Callable[[], None] | None = None,
    start_minimized: bool = False,
) -> None:
    """Run Pirate Cinema using an external/dedicated browser (App Mode)."""
    gui_host = "127.0.0.1" if config.APP_HOST in ("0.0.0.0", "") else config.APP_HOST
    app_url = f"http://{gui_host}:{config.APP_PORT}"
    lang = _load_settings().get("language", DEFAULT_LANG)
    static_dir = BASE_DIR / "static"

    if on_frontend_ready is not None:
        try:
            on_frontend_ready()
        except (RuntimeError, OSError, AttributeError):
            logger.debug("Failed to close splash on browser launch")

    if not start_minimized:
        logger.info("[GUI] Starting Pirate Cinema in Browser App Mode at %s", app_url)
        browser_proc, is_app_mode = open_browser_window(app_url)
        window_api.set_browser_process(browser_proc, server)
    else:
        logger.info("[GUI] Starting Pirate Cinema in Browser App Mode (minimized to tray) at %s", app_url)
        browser_proc, is_app_mode = None, False

    def on_tray_show():
        open_browser_window(app_url)

    def on_tray_exit():
        logger.info("[TRAY] Exit clicked in browser mode. Cleaning up...")
        server.should_exit = True
        torrserver_process.stop()
        tray.stop_tray()
        if browser_proc and browser_proc.poll() is None:
            try:
                browser_proc.terminate()
            except OSError:
                pass
        os._exit(0)

    tray_icon_path = static_dir / "tray.png"
    if not tray_icon_path.exists():
        tray_icon_path = static_dir / "favicon.png"
    tray.start_tray(
        icon_path=tray_icon_path,
        on_show=on_tray_show,
        on_exit=on_tray_exit,
        show_text=t("tray_show", lang=lang),
        exit_text=t("tray_exit", lang=lang),
    )

    start_time = time.time()
    try:
        while not server.should_exit:
            if browser_proc and is_app_mode:
                poll_res = browser_proc.poll()
                if poll_res is not None:
                    elapsed = time.time() - start_time
                    if elapsed > 2.0:
                        prefs = _load_settings()
                        if not prefs.get("minimize_to_tray", False) or not tray.is_tray_running():
                            logger.info("[GUI] Browser app window closed by user. Exiting...")
                            break
                        else:
                            logger.info("[GUI] Browser window closed; remaining in background tray.")
                            browser_proc = None
                            window_api.set_browser_process(None, server)
                    else:
                        logger.info("[GUI] Browser process exited immediately (delegated to existing session).")
                        browser_proc = None
                        window_api.set_browser_process(None, server)
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("[GUI] KeyboardInterrupt received. Exiting...")
    finally:
        tray.stop_tray()
        server.should_exit = True
        torrserver_process.stop()
        if browser_proc and browser_proc.poll() is None:
            try:
                browser_proc.terminate()
            except OSError:
                pass
        os._exit(0)


def launch_gui(
    server: uvicorn.Server,
    on_frontend_ready: Callable[[], None] | None = None,
    start_minimized: bool = False,
):
    global _window

    window_api.set_frontend_ready_callback(on_frontend_ready)

    if not is_native_gui_available():
        launch_browser_app(
            server,
            on_frontend_ready=on_frontend_ready,
            start_minimized=start_minimized,
        )
        return

    lang = _load_settings().get("language", DEFAULT_LANG)
    static_dir = BASE_DIR / "static"
    gui_host = "127.0.0.1" if config.APP_HOST in ("0.0.0.0", "") else config.APP_HOST
    app_url = f"http://{gui_host}:{config.APP_PORT}"

    def on_tray_show():
        window_api.show()

    def on_tray_exit():
        logger.info("[TRAY] Exit clicked. Cleaning up...")
        server.should_exit = True
        torrserver_process.stop()
        tray.stop_tray()
        if window_api._geometry:
            window_api._geometry.flush()
        os._exit(0)

    # Настройки области перетаскивания pywebview
    if webview:
        webview.settings["DRAG_REGION_SELECTOR"] = ".pywebview-drag-region"
        webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True

    init_x = None
    init_y = None
    if os.name == "nt":
        try:
            import ctypes

            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            init_x = max(0, (sw - config.WINDOW_WIDTH) // 2)
            init_y = max(0, (sh - config.WINDOW_HEIGHT) // 2)
        except (AttributeError, OSError) as error:
            logger.debug("Could not read display metrics for initial centering: %s", error)

    try:
        _window = webview.create_window(
            config.APP_TITLE,
            app_url,
            width=config.WINDOW_WIDTH,
            height=config.WINDOW_HEIGHT,
            x=init_x,
            y=init_y,
            resizable=True,
            frameless=True,
            easy_drag=False,
            background_color=config.WINDOW_BG,
            js_api=window_api,
            hidden=start_minimized,
        )

        window_api._geometry = WindowGeometry(_load_settings(), _save_settings)
        geometry_restored = False

        def on_shown():
            nonlocal geometry_restored
            window_api.ensure_player_hwnd()
            window_api.dismiss_startup_splash()
            if geometry_restored:
                return
            geometry_restored = True
            def restore_geometry():
                window_api._geometry_suspended = True
                try:
                    restored = window_api._geometry.restore(native_displays(webview),
                        default_size=(config.WINDOW_WIDTH, config.WINDOW_HEIGHT))
                    if restored:
                        x, y, width, height = restored['bounds']
                        if os.name == 'nt':
                            import System.Windows.Forms as forms
                            form = _window.native
                            form.SetBounds(x, y, width, height)
                            if restored['maximized']:
                                form.WindowState = forms.FormWindowState.Maximized
                            form.LocationChanged += window_api._capture_geometry
                            form.SizeChanged += window_api._capture_geometry
                        else:
                            _window.resize(width, height)
                            _window.move(x, y)
                            if restored['maximized']:
                                _window.maximize()
                        window_api._is_maximized = restored['maximized']
                except (OSError, AttributeError, RuntimeError, ImportError):
                    logger.debug('Window placement restore unavailable', exc_info=True)
                finally:
                    window_api._geometry_suspended = False
                    window_api._capture_geometry()
            if os.name == 'nt':
                window_api._invoke_ui(restore_geometry, sync=False)
            else:
                restore_geometry()

        def on_maximized():
            window_api._is_maximized = True
            if os.name != 'nt':
                window_api._capture_geometry()

        def on_restored():
            window_api._is_maximized = False
            if os.name != 'nt':
                window_api._capture_geometry()

        def on_loaded():
            window_api.dismiss_startup_splash()

        _window.events.shown += on_shown
        _window.events.loaded += on_loaded
        _window.events.maximized += on_maximized
        _window.events.restored += on_restored
        if os.name != 'nt':
            _window.events.moved += window_api._capture_geometry
            _window.events.resized += window_api._capture_geometry

        def initialize_tray():
            window_api.dismiss_startup_splash()
            tray_icon_path = static_dir / "tray.png"
            if not tray_icon_path.exists():
                tray_icon_path = static_dir / "favicon.png"
            tray.start_tray(
                icon_path=tray_icon_path,
                on_show=on_tray_show,
                on_exit=on_tray_exit,
                show_text=t("tray_show", lang=lang),
                exit_text=t("tray_exit", lang=lang),
            )

        def on_closing():
            if window_api._geometry:
                window_api._geometry.flush()
            prefs = _load_settings()
            if not prefs.get("close_behavior_configured", False):
                if os.name != "nt":
                    return True

                import ctypes

                response = ctypes.windll.user32.MessageBoxW(
                    0,
                    "Да — сворачивать приложение в трей.\n"
                    "Нет — полностью закрывать приложение.\n\n"
                    "Этот выбор можно изменить в настройках.",
                    "Закрытие Pirate Cinema",
                    0x00000003 | 0x00000020,
                )
                if response == 2:  # Cancel
                    return False

                minimize_to_tray = response == 6  # Yes
                _save_settings(
                    {
                        "minimize_to_tray": minimize_to_tray,
                        "close_behavior_configured": True,
                    }
                )
                prefs["minimize_to_tray"] = minimize_to_tray

            if prefs.get("minimize_to_tray", False):
                if _window:
                    _window.hide()
                return False  # Отменяет закрытие окна
            return True

        def on_closed():
            if window_api._geometry:
                window_api._geometry.flush()
            logger.info("[GUI] Window closed.")
            tray.stop_tray()
            server.should_exit = True
            torrserver_process.stop()

        _window.events.closing += on_closing
        _window.events.closed += on_closed

        # Путь к иконке окна Windows (заменяет дефолтную python/webview)
        app_icon = static_dir / "icon.ico"
        if not app_icon.exists():
            app_icon = BASE_DIR / "build" / "icon.ico"
        if not app_icon.exists():
            app_icon = BASE_DIR / "assets" / "brand" / "icon.ico"

        webview.start(
            initialize_tray,
            icon=str(app_icon) if app_icon.exists() else None,
        )
    except (Exception, BaseException) as err:  # noqa: BLE001
        logger.warning(
            "[GUI] Native webview start failed: %s. Falling back to Browser App Mode.",
            err,
        )
        _window = None
        launch_browser_app(server, on_frontend_ready=on_frontend_ready)
        return

    # Очистка при завершении основного цикла окон
    tray.stop_tray()
    server.should_exit = True
    torrserver_process.stop()
    os._exit(0)
