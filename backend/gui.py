"""Desktop UI & Tray Manager."""

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
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
from backend.infrastructure.torrserver import process as torrserver_process
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
        self._player_visible = False
        self._viewport_panel = None
        self._mpv_panel = None
        self._player_hwnd: int | None = None
        self._last_bounds: dict[str, float] | None = None
        self._inline_bounds: dict[str, float] | None = None
        self._pre_fs_window_state = None
        self._pre_fs_bounds = None
        self._key_preview_set = False
        self._hotkey_running = False
        self._hotkey_thread: threading.Thread | None = None
        self._last_esc_time: float = 0.0
        self._last_fs_exit_time: float = 0.0
        self._last_fs_toggle_time: float = 0.0
        self._form_hwnd: int | None = None
        self._on_frontend_ready: Callable[[], None] | None = None
        self._browser_proc: Any = None
        self._server: Any = None

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
        try:
            import clr

            clr.AddReference("System")
            import System

            if getattr(form, "InvokeRequired", False):
                if sync:
                    form.Invoke(System.Action(fn))
                else:
                    form.BeginInvoke(System.Action(fn))
            else:
                fn()
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

            if not self._key_preview_set:
                form.KeyPreview = True

                def on_key_down(sender, e):
                    try:
                        from System.Windows.Forms import Keys

                        from backend.api.deps import get_playback_service

                        svc = get_playback_service()

                        if e.KeyCode == Keys.Escape:
                            now = time.time()
                            if now - self._last_esc_time < 0.35 or now - self._last_fs_exit_time < 0.6:
                                e.Handled = True
                                return
                            self._last_esc_time = now
                            if self._is_fullscreen:
                                self._last_fs_exit_time = now
                                self.set_fullscreen(False)
                            e.Handled = True
                        elif e.KeyCode == Keys.F:
                            now = time.time()
                            if now - self._last_fs_toggle_time < 0.4:
                                e.Handled = True
                                return
                            if self._player_visible:
                                self.toggle_fullscreen()
                                e.Handled = True
                        elif e.KeyCode == Keys.Space:
                            if self._player_visible:
                                svc.send_command(["cycle", "pause"])
                                e.Handled = True
                        elif e.KeyCode == Keys.Left:
                            if self._player_visible:
                                svc.send_command(["seek", -10, "relative"])
                                e.Handled = True
                        elif e.KeyCode == Keys.Right:
                            if self._player_visible:
                                svc.send_command(["seek", 10, "relative"])
                                e.Handled = True
                        elif e.KeyCode == Keys.Up:
                            if self._player_visible:
                                svc.send_command(["add", "volume", 5])
                                e.Handled = True
                        elif e.KeyCode == Keys.Down:
                            if self._player_visible:
                                svc.send_command(["add", "volume", -5])
                                e.Handled = True
                        elif e.KeyCode == Keys.M:
                            if self._player_visible:
                                svc.send_command(["cycle", "mute"])
                                e.Handled = True
                        elif e.KeyCode == Keys.Q:
                            if self._player_visible:
                                svc.stop()
                                self.hide_player_panel()
                                e.Handled = True
                    except Exception:
                        logger.exception("[GUI] Error handling form key down")

                form.KeyDown += on_key_down
                self._key_preview_set = True

            viewport = WinForms.Panel()
            viewport.BackColor = Drawing.Color.Black
            viewport.Visible = False
            viewport.SetBounds(0, 0, 800, 450)

            mpv_host = WinForms.Panel()
            mpv_host.BackColor = Drawing.Color.Black
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
        if self._hotkey_running:
            return
        self._hotkey_running = True

        def _hotkey_loop():
            import ctypes

            try:
                user32 = ctypes.windll.user32
            except (AttributeError, OSError) as error:
                logger.debug("Global hotkeys are unavailable: %s", error)
                return

            VK_ESCAPE = 0x1B
            VK_SPACE = 0x20
            VK_LEFT = 0x25
            VK_UP = 0x26
            VK_RIGHT = 0x27
            VK_DOWN = 0x28
            VK_F = 0x46
            VK_Q = 0x51
            VK_M = 0x4D

            watched_keys = [
                VK_ESCAPE,
                VK_Q,
                VK_F,
                VK_SPACE,
                VK_LEFT,
                VK_RIGHT,
                VK_UP,
                VK_DOWN,
                VK_M,
            ]
            prev_pressed: dict[int, bool] = {}

            while self._hotkey_running:
                try:
                    time.sleep(0.03)
                    if not self._player_visible or not self._form_hwnd:
                        time.sleep(0.05)
                        continue

                    form_hwnd = self._form_hwnd
                    fg_hwnd = user32.GetForegroundWindow()
                    if not fg_hwnd:
                        continue

                    is_our_app = False
                    if fg_hwnd == form_hwnd or user32.IsChild(form_hwnd, fg_hwnd) or self._player_hwnd and (
                        fg_hwnd == self._player_hwnd
                        or user32.IsChild(self._player_hwnd, fg_hwnd)
                    ):
                        is_our_app = True

                    if not is_our_app:
                        continue

                    for vk in watched_keys:
                        is_down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                        was_down = prev_pressed.get(vk, False)
                        prev_pressed[vk] = is_down

                        if is_down and not was_down:
                            self._handle_global_hotkey(vk, fg_hwnd)
                except Exception:
                    logger.debug("[GUI] Hotkey listener exception", exc_info=True)

        t = threading.Thread(
            target=_hotkey_loop, daemon=True, name="EmbeddedPlayerHotkeyListener"
        )
        t.start()
        self._hotkey_thread = t

    def _handle_global_hotkey(self, vk: int, fg_hwnd: int) -> None:
        try:
            import ctypes

            from backend.api.deps import get_playback_service

            svc = get_playback_service()

            VK_ESCAPE = 0x1B
            VK_SPACE = 0x20
            VK_LEFT = 0x25
            VK_UP = 0x26
            VK_RIGHT = 0x27
            VK_DOWN = 0x28
            VK_F = 0x46
            VK_Q = 0x51
            VK_M = 0x4D

            if vk == VK_ESCAPE:
                now = time.time()
                if now - self._last_esc_time < 0.35 or now - self._last_fs_exit_time < 0.6:
                    return
                self._last_esc_time = now
                if self._is_fullscreen:
                    self._last_fs_exit_time = now
                    self.set_fullscreen(False)

            elif vk == VK_Q:
                if self._player_visible:
                    svc.stop()
                    self.hide_player_panel()

            elif vk == VK_F:
                now = time.time()
                if now - self._last_fs_toggle_time < 0.4:
                    return
                if self._player_visible:
                    self.toggle_fullscreen()

            elif self._is_fullscreen or (
                self._player_hwnd
                and (
                    fg_hwnd == self._player_hwnd
                    or (
                        ctypes.windll.user32.IsChild(self._player_hwnd, fg_hwnd)
                        if hasattr(ctypes, "windll")
                        else False
                    )
                )
            ):
                if vk == VK_SPACE:
                    svc.send_command(["cycle", "pause"])
                elif vk == VK_LEFT:
                    svc.send_command(["seek", -10, "relative"])
                elif vk == VK_RIGHT:
                    svc.send_command(["seek", 10, "relative"])
                elif vk == VK_UP:
                    svc.send_command(["add", "volume", 5])
                elif vk == VK_DOWN:
                    svc.send_command(["add", "volume", -5])
                elif vk == VK_M:
                    svc.send_command(["cycle", "mute"])
        except Exception:
            logger.exception("[GUI] Error in global hotkey handler")

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
        if not self._is_fullscreen:
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
            form = _window.native
            cw = int(form.ClientSize.Width)
            ch = int(form.ClientSize.Height)

            mpv_child_hwnd = None
            if self._player_hwnd and os.name == "nt":
                try:
                    import ctypes

                    user32 = ctypes.windll.user32
                    mpv_child_hwnd = user32.FindWindowExW(self._player_hwnd, 0, "mpv", 0)
                    if mpv_child_hwnd:
                        user32.EnableWindow(mpv_child_hwnd, True)
                        style = user32.GetWindowLongW(mpv_child_hwnd, -16)
                        if style & 0x08000000:
                            user32.SetWindowLongW(mpv_child_hwnd, -16, style & ~0x08000000)
                            user32.SetWindowPos(mpv_child_hwnd, 0, 0, 0, 0, 0, 0x0027)
                except (AttributeError, OSError, RuntimeError) as error:
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

    def hide_player_panel(self) -> bool:
        self._player_visible = False
        self._last_bounds = None
        self._inline_bounds = None
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

        now = time.time()
        if not target:
            self._last_fs_exit_time = now
        self._last_fs_toggle_time = now
        self._is_fullscreen = target

        def _apply_fs():
            if not _window or not _window.native:
                return
            import clr

            clr.AddReference("System.Windows.Forms")
            import ctypes

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
                cur_fs = bool(getattr(form, "is_fullscreen", False))
                if target != cur_fs:
                    if hasattr(form, "toggle_fullscreen"):
                        form.toggle_fullscreen()
                    elif hasattr(_window, "toggle_fullscreen"):
                        _window.toggle_fullscreen()
            except Exception:
                logger.exception("[GUI] Error invoking BrowserView toggle_fullscreen")

            try:
                user32 = ctypes.windll.user32
                dwmapi = ctypes.windll.dwmapi
                hwnd = int(form.Handle.ToInt64())
                if target:
                    # Remove DWM glass frame margin completely in fullscreen
                    zero_margins = _MARGINS(0, 0, 0, 0)
                    dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(zero_margins))

                    # Disable window rounding (DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_DONOTROUND = 1)
                    val_corner = ctypes.c_int(1)
                    dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val_corner), ctypes.sizeof(val_corner))

                    # Remove border color (DWMWA_BORDER_COLOR = 34, DWMWA_COLOR_NONE = 0xFFFFFFFE)
                    val_border = ctypes.c_int(ctypes.c_int32(0xFFFFFFFE).value)
                    dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(val_border), ctypes.sizeof(val_border))

                    screen = WinForms.Screen.FromControl(form) or WinForms.Screen.PrimaryScreen
                    sb = screen.Bounds
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
                    w = int(sb.Width)
                    h = int(sb.Height)
                    if self._viewport_panel and self._mpv_panel:
                        self._viewport_panel.SetBounds(0, 0, w, h)
                        self._mpv_panel.SetBounds(0, 0, w, h)
                        if self._player_hwnd:
                            try:
                                mpv_child_hwnd = user32.FindWindowExW(self._player_hwnd, 0, "mpv", 0)
                                if mpv_child_hwnd:
                                    user32.MoveWindow(mpv_child_hwnd, 0, 0, w, h, True)
                            except (AttributeError, OSError, RuntimeError) as error:
                                logger.debug("Failed to resize fullscreen MPV window: %s", error)
                        if not self._viewport_panel.Visible:
                            self._viewport_panel.Visible = True
                        self._viewport_panel.BringToFront()
                else:
                    # Restore DWM frame shadow for windowed frameless mode
                    shadow_margins = _MARGINS(1, 1, 1, 1)
                    dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(shadow_margins))

                    # Restore default corner rounding (DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_DEFAULT = 0)
                    val_corner = ctypes.c_int(0)
                    dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val_corner), ctypes.sizeof(val_corner))

                    # Restore default border color (DWMWA_BORDER_COLOR = 34, DWMWA_COLOR_DEFAULT = 0xFFFFFFFF)
                    val_border = ctypes.c_int(ctypes.c_int32(0xFFFFFFFF).value)
                    dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(val_border), ctypes.sizeof(val_border))

                    user32.SetWindowPos(
                        hwnd,
                        -2,  # HWND_NOTOPMOST
                        0,
                        0,
                        0,
                        0,
                        0x0001 | 0x0002 | 0x0040 | 0x0020,  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW | SWP_FRAMECHANGED
                    )
            except Exception:
                logger.exception("[GUI] Error applying DWM and SetWindowPos for fullscreen")

        self._invoke_ui(_apply_fs, sync=False)

        if not target and self._player_visible:
            bounds = self._inline_bounds or self._last_bounds
            if bounds:
                self.set_player_bounds(**bounds)
        return self._is_fullscreen

    def toggle_fullscreen(self) -> bool:
        now = time.time()
        if now - self._last_fs_toggle_time < 0.4:
            return self._is_fullscreen
        return self.set_fullscreen(not self._is_fullscreen)

    def is_fullscreen(self) -> bool:
        return self._is_fullscreen

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

    def restore(self) -> bool:
        if _window:
            try:
                if self._is_fullscreen:
                    self.set_fullscreen(False)
                    return True
                _window.restore()
                self._is_maximized = False
                return True
            except Exception:
                logger.exception("Failed to restore window")
        return False

    def toggle_maximize(self) -> bool:
        if _window:
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

    # Pre-check display
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        logger.info("[GUI] Neither DISPLAY nor WAYLAND_DISPLAY is set. Using browser mode.")
        return False

    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401

        try:
            gi.require_version("WebKit2", "4.1")
        except (ValueError, AttributeError):
            gi.require_version("WebKit2", "4.0")

        from gi.repository import WebKit2

        if hasattr(WebKit2, "get_major_version"):
            WebKit2.get_major_version()
        return True
    except (Exception, BaseException) as err:  # noqa: BLE001
        logger.warning(
            "[GUI] Native WebKitGTK is unavailable or incompatible on this Linux system (%s). "
            "Falling back to Browser App Mode (zero extra dependencies required).",
            err,
        )
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
                proc = subprocess.Popen(cmd)
                logger.info("[GUI] Launched Chromium App Mode: %s", browser_bin)
                return proc, True
            except OSError as err:
                logger.warning("[GUI] Failed to launch %s with --app: %s", browser_bin, err)

        try:
            proc = subprocess.Popen([browser_bin, "--new-window", app_url])
            logger.info("[GUI] Launched browser in new window: %s", browser_bin)
            return proc, False
        except OSError as err:
            logger.warning("[GUI] Failed to launch %s: %s", browser_bin, err)

    if shutil.which("xdg-open"):
        try:
            proc = subprocess.Popen(["xdg-open", app_url])
            logger.info("[GUI] Opened URL via xdg-open: %s", app_url)
            return proc, False
        except OSError:
            pass

    import webbrowser

    webbrowser.open(app_url, new=1)
    logger.info("[GUI] Opened URL via python webbrowser module: %s", app_url)
    return None, False


def launch_browser_app(
    server: uvicorn.Server,
    on_frontend_ready: Callable[[], None] | None = None,
) -> None:
    """Run Pirate Cinema using an external/dedicated browser (App Mode)."""
    app_url = f"http://{config.APP_HOST}:{config.APP_PORT}"
    lang = _load_settings().get("language", DEFAULT_LANG)
    static_dir = BASE_DIR / "static"

    if on_frontend_ready is not None:
        try:
            on_frontend_ready()
        except (RuntimeError, OSError, AttributeError):
            logger.debug("Failed to close splash on browser launch")

    logger.info("[GUI] Starting Pirate Cinema in Browser App Mode at %s", app_url)
    browser_proc, is_app_mode = open_browser_window(app_url)
    window_api.set_browser_process(browser_proc, server)

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
):
    global _window

    window_api.set_frontend_ready_callback(on_frontend_ready)

    if not is_native_gui_available():
        launch_browser_app(server, on_frontend_ready=on_frontend_ready)
        return

    lang = _load_settings().get("language", DEFAULT_LANG)
    static_dir = BASE_DIR / "static"
    app_url = f"http://{config.APP_HOST}:{config.APP_PORT}"

    def on_tray_show():
        if _window:
            try:
                _window.show()
                _window.restore()
            except (RuntimeError, AttributeError, OSError):
                logger.exception("Failed to show window from tray")

    def on_tray_exit():
        logger.info("[TRAY] Exit clicked. Cleaning up...")
        server.should_exit = True
        torrserver_process.stop()
        tray.stop_tray()
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
        )

        def on_shown():
            window_api.ensure_player_hwnd()

            if os.name == "nt":
                def _center():
                    try:
                        import clr

                        clr.AddReference("System.Windows.Forms")
                        import System.Windows.Forms as WinForms

                        form = _window.native
                        screen = (
                            WinForms.Screen.FromControl(form) or WinForms.Screen.PrimaryScreen
                        )
                        wa = screen.WorkingArea
                        w = min(form.Width, wa.Width)
                        h = min(form.Height, wa.Height)
                        x = wa.Left + max(0, (wa.Width - w) // 2)
                        y = wa.Top + max(0, (wa.Height - h) // 2)
                        form.SetBounds(x, y, w, h)
                    except Exception:
                        logger.exception("[GUI] Failed to center window on shown")

                window_api._invoke_ui(_center, sync=False)

        def on_maximized():
            window_api._is_maximized = True

        def on_restored():
            window_api._is_maximized = False

        _window.events.shown += on_shown
        _window.events.maximized += on_maximized
        _window.events.restored += on_restored

        def initialize_tray():
            try:
                screen = webview.screens[0]
                _window.move(
                    max(0, (screen.width - config.WINDOW_WIDTH) // 2),
                    max(0, (screen.height - config.WINDOW_HEIGHT) // 2),
                )
            except (AttributeError, IndexError, RuntimeError):
                logger.debug("Could not center desktop window")

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
