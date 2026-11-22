"""Event-driven window placement and geometry calculations independent of native GUI."""

import logging
import math
import os
import threading
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Display:
    name: str
    x: int
    y: int
    width: int
    height: int
    dpi: int = 96


def _number(value: Any, fallback: Any) -> Any:
    if isinstance(value, bool):
        return fallback
    try:
        number = float(value)
        return round(number) if math.isfinite(number) and abs(number) <= 100000 else fallback
    except (TypeError, ValueError, OverflowError):
        return fallback


def _to_int(val: Any, default: int = 0) -> int:
    if val is None or isinstance(val, bool):
        return default
    try:
        return int(float(val))
    except (TypeError, ValueError, OverflowError):
        return default


def _extract_rect(obj: Any) -> tuple[int, int, int, int]:
    """Safely extract (x, y, width, height) from various rect/display representations."""
    if isinstance(obj, (list, tuple)) and len(obj) >= 4:
        return _to_int(obj[0], 0), _to_int(obj[1], 0), _to_int(obj[2], 1920), _to_int(obj[3], 1080)
    if isinstance(obj, dict):
        x = obj.get("X") if obj.get("X") is not None else obj.get("x", obj.get("Left", obj.get("left", 0)))
        y = obj.get("Y") if obj.get("Y") is not None else obj.get("y", obj.get("Top", obj.get("top", 0)))
        w = obj.get("Width") if obj.get("Width") is not None else obj.get("width", 1920)
        h = obj.get("Height") if obj.get("Height") is not None else obj.get("height", 1080)
        return _to_int(x, 0), _to_int(y, 0), _to_int(w, 1920), _to_int(h, 1080)
    x = getattr(obj, "X", getattr(obj, "x", getattr(obj, "Left", getattr(obj, "left", 0))))
    y = getattr(obj, "Y", getattr(obj, "y", getattr(obj, "Top", getattr(obj, "top", 0))))
    w = getattr(obj, "Width", getattr(obj, "width", 1920))
    h = getattr(obj, "Height", getattr(obj, "height", 1080))
    return _to_int(x, 0), _to_int(y, 0), _to_int(w, 1920), _to_int(h, 1080)


def placement(
    saved: Any,
    displays: list[Display],
    *,
    pip: bool = False,
    default_size: tuple[int, int] = (1280, 800),
) -> dict[str, Any] | None:
    """Scale within the saved monitor, then clamp to an available work area."""
    if not displays:
        return None
    saved = saved if isinstance(saved, dict) else {}
    bounds = saved.get("bounds")
    valid = isinstance(bounds, (list, tuple)) and len(bounds) == 4
    bounds = bounds if valid else [None] * 4
    display = next((d for d in displays if d.name == saved.get("monitor")), None)
    old_area = saved.get("work_area")
    same_monitor = display is not None
    if display is None:
        display = displays[0]
    factor = display.dpi / max(48, _number(saved.get("dpi"), display.dpi)) if same_monitor else 1
    minimum = (280, 180) if pip else (640, 420)
    default = (420, 268) if pip else default_size
    max_w = max(640, int(display.width * 0.45)) if pip else display.width
    max_h = max(480, int(display.height * 0.45)) if pip else display.height
    raw_w = round(max(1, _number(bounds[2], default[0])) * factor)
    raw_h = round(max(1, _number(bounds[3], default[1])) * factor)
    if pip and (raw_w > max_w or raw_h > max_h):
        raw_w, raw_h = default[0], default[1]
    width = min(max_w, max(minimum[0], raw_w))
    height = min(max_h, max(minimum[1], raw_h))
    x = display.x + (display.width - width) // 2
    y = display.y + (display.height - height) // 2
    if valid and same_monitor and isinstance(old_area, dict):
        x = display.x + round((_number(bounds[0], x) - _number(old_area.get("x"), display.x)) * factor)
        y = display.y + round((_number(bounds[1], y) - _number(old_area.get("y"), display.y)) * factor)
    x = max(display.x, min(display.x + display.width - width, x))
    y = max(display.y, min(display.y + display.height - height, y))
    return {
        "bounds": [x, y, width, height],
        "monitor": display.name,
        "dpi": display.dpi,
        "work_area": asdict(display),
        "maximized": bool(saved.get("maximized")) and not pip,
    }


def find_display(
    displays: list[Display],
    name: str | None = None,
    point: tuple[int, int] | list[int] | None = None,
) -> Display | None:
    """Find a display by device name or containing a specific (x, y) coordinate."""
    if not displays:
        return None
    if name:
        match = next((d for d in displays if d.name == name), None)
        if match:
            return match
    if point and len(point) >= 2:
        px, py = int(point[0]), int(point[1])
        match = next(
            (d for d in displays if d.x <= px < d.x + d.width and d.y <= py < d.y + d.height),
            None,
        )
        if match:
            return match
    return displays[0]


def find_display_for_bounds(
    displays: list[Display],
    bounds: list[int] | tuple[int, int, int, int],
) -> Display:
    """Find the display that contains the origin or majority of the given bounds."""
    if not displays:
        return Display("default", 0, 0, 1920, 1080)
    if isinstance(bounds, (list, tuple)) and len(bounds) >= 2:
        bx, by = int(bounds[0]), int(bounds[1])
        display = find_display(displays, point=(bx, by))
        if display:
            return display
    return displays[0]


def calculate_fullscreen_bounds(
    screen_bounds: Any,
    client_size: Any = None,
) -> tuple[tuple[int, int, int, int], tuple[int, int]]:
    """
    Calculate target window bounds and child panel/viewport size for fullscreen mode.
    Returns: ((x, y, width, height), (viewport_width, viewport_height))
    """
    sx, sy, sw, sh = _extract_rect(screen_bounds)
    cw, ch = 0, 0
    if client_size is not None:
        if isinstance(client_size, (list, tuple)) and len(client_size) >= 2:
            cw, ch = int(client_size[0]), int(client_size[1])
        elif hasattr(client_size, "Width") and hasattr(client_size, "Height"):
            cw, ch = int(client_size.Width), int(client_size.Height)
        elif isinstance(client_size, dict):
            cw = _to_int(client_size.get("Width", client_size.get("width", 0)), 0)
            ch = _to_int(client_size.get("Height", client_size.get("height", 0)), 0)
    vw = max(cw, sw)
    vh = max(ch, sh)
    return (sx, sy, sw, sh), (vw, vh)


def calculate_restore_bounds(
    work_area: Any,
    saved_bounds: list[int] | tuple[int, int, int, int] | None = None,
    default_size: tuple[int, int] = (1280, 800),
    min_size: tuple[int, int] = (300, 200),
) -> tuple[int, int, int, int]:
    """
    Calculate window bounds when restoring from fullscreen, PiP, or maximized state.
    Uses saved_bounds if valid; otherwise centers default_size within work_area.
    """
    wax, way, waw, wah = _extract_rect(work_area)
    if (
        saved_bounds is not None
        and isinstance(saved_bounds, (list, tuple))
        and len(saved_bounds) >= 4
        and saved_bounds[0] > -10000
        and saved_bounds[2] >= min_size[0]
        and saved_bounds[3] >= min_size[1]
    ):
        return int(saved_bounds[0]), int(saved_bounds[1]), int(saved_bounds[2]), int(saved_bounds[3])

    w = min(int(default_size[0]), waw)
    h = min(int(default_size[1]), wah)
    x = wax + max(0, (waw - w) // 2)
    y = way + max(0, (wah - h) // 2)
    return x, y, w, h


def calculate_pip_bounds(
    work_area: Any,
    saved_pip_bounds: list[int] | tuple[int, int, int, int] | None = None,
    default_pip_size: tuple[int, int] = (420, 268),
    header_height: int = 32,
    margin: int = 24,
) -> tuple[int, int, int, int, int]:
    """
    Calculate PiP window bounds and embedded video height.
    Returns: (pip_x, pip_y, pip_w, total_h, video_h)
    """
    wax, way, waw, wah = _extract_rect(work_area)
    max_pip_w = max(640, int(waw * 0.45))
    max_pip_h = max(480, int(wah * 0.45))

    if (
        saved_pip_bounds is not None
        and isinstance(saved_pip_bounds, (list, tuple))
        and len(saved_pip_bounds) >= 4
        and saved_pip_bounds[0] > -10000
        and 200 <= saved_pip_bounds[2] <= max_pip_w
        and 120 <= saved_pip_bounds[3] <= max_pip_h
    ):
        pip_x = int(saved_pip_bounds[0])
        pip_y = int(saved_pip_bounds[1])
        pip_w = int(saved_pip_bounds[2])
        total_h = int(saved_pip_bounds[3])
        pip_x = max(wax, min(wax + waw - pip_w, pip_x))
        pip_y = max(way, min(way + wah - total_h, pip_y))
        video_h = max(1, total_h - header_height)
        return pip_x, pip_y, pip_w, total_h, video_h

    pip_w, total_h = int(default_pip_size[0]), int(default_pip_size[1])
    pip_x = wax + waw - pip_w - margin
    pip_y = way + wah - total_h - margin
    video_h = max(1, total_h - header_height)
    return pip_x, pip_y, pip_w, total_h, video_h


def calculate_initial_bounds(
    settings: dict[str, Any] | None,
    displays: list[Display] | None = None,
    default_size: tuple[int, int] = (1280, 800),
    webview: Any = None,
) -> tuple[int, int, int, int, bool]:
    """
    Determine initial window bounds and maximized state at startup.
    Returns: (x, y, width, height, maximized)
    """
    if displays is None:
        displays = native_displays(webview)

    if not displays:
        return 0, 0, default_size[0], default_size[1], False

    if isinstance(settings, dict):
        raw_geom = settings.get("window_geometry", {})
        if isinstance(raw_geom, dict) and raw_geom.get("normal"):
            restored = placement(raw_geom.get("normal"), displays, default_size=default_size)
            if restored and "bounds" in restored:
                bx, by, bw, bh = restored["bounds"]
                return bx, by, bw, bh, bool(restored.get("maximized", False))

    primary = displays[0]
    w = min(primary.width, default_size[0])
    h = min(primary.height, default_size[1])
    x = primary.x + max(0, (primary.width - w) // 2)
    y = primary.y + max(0, (primary.height - h) // 2)
    return x, y, w, h, False


def extract_window_state_and_bounds(
    window: Any,
    displays: list[Display] | None = None,
    webview: Any = None,
    fallback_is_maximized: bool = False,
) -> tuple[list[int], Display, bool, bool] | None:
    """
    Extract (bounds, display, is_maximized, is_minimized) from a pywebview window.
    Returns None if window is not ready or minimized.
    """
    if not window:
        return None
    if displays is None:
        displays = native_displays(webview)
    if not displays:
        return None

    if os.name == "nt" and getattr(window, "native", None):
        form = window.native
        try:
            state = int(form.WindowState)
        except (TypeError, ValueError):
            state = 0
        is_minimized = state == 1
        is_maximized = state == 2
        if is_minimized:
            return None
        rect = form.RestoreBounds if is_maximized else form.Bounds
        bounds = [int(rect.X), int(rect.Y), int(rect.Width), int(rect.Height)]
        try:
            name = str(
                __import__("System.Windows.Forms", fromlist=["Screen"]).Screen.FromControl(form).DeviceName
            )
            display = find_display(displays, name=name) or displays[0]
        except Exception:
            display = find_display_for_bounds(displays, bounds)
        return bounds, display, is_maximized, is_minimized
    else:
        try:
            bounds = [int(window.x), int(window.y), int(window.width), int(window.height)]
            display = find_display_for_bounds(displays, bounds)
            return bounds, display, bool(fallback_is_maximized), False
        except (AttributeError, TypeError):
            return None


class WindowGeometry:
    def __init__(self, settings: dict[str, Any] | None, save: Any, delay: float = 0.4):
        raw = settings.get("window_geometry", {}) if isinstance(settings, dict) else {}
        self.state = dict(raw) if isinstance(raw, dict) else {}
        # Sanitize corrupted/oversized pip state if present
        if isinstance(self.state.get("pip"), dict):
            pip_b = self.state["pip"].get("bounds")
            if isinstance(pip_b, (list, tuple)) and len(pip_b) >= 4:
                if pip_b[2] > 640 or pip_b[3] > 480:
                    self.state.pop("pip", None)
        self.save = save
        self.delay = delay
        self.lock = threading.RLock()
        self.timer: threading.Timer | None = None

    def remember(
        self,
        bounds: list[int] | tuple[int, int, int, int],
        display: Display | None,
        *,
        pip: bool = False,
        maximized: bool = False,
        fullscreen: bool = False,
        minimized: bool = False,
    ) -> None:
        if fullscreen or minimized or not display or len(bounds) != 4:
            return
        normalized = [_number(v, None) for v in bounds]
        if any(v is None for v in normalized) or normalized[2] < 200 or normalized[3] < 120:
            return
        if pip:
            max_w = max(640, int(display.width * 0.45))
            max_h = max(480, int(display.height * 0.45))
            if normalized[2] > max_w or normalized[3] > max_h:
                return
        record = {
            "bounds": normalized,
            "monitor": display.name,
            "dpi": display.dpi,
            "work_area": asdict(display),
            "maximized": bool(maximized) and not pip,
        }
        with self.lock:
            key = "pip" if pip else "normal"
            if self.state.get(key) == record:
                return
            self.state[key] = record
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(self.delay, self.flush)
            self.timer.daemon = True
            self.timer.start()

    def restore(
        self,
        displays: list[Display],
        *,
        pip: bool = False,
        default_size: tuple[int, int] = (1280, 800),
    ) -> dict[str, Any] | None:
        with self.lock:
            return placement(
                self.state.get("pip" if pip else "normal"),
                displays,
                pip=pip,
                default_size=default_size,
            )

    def flush(self) -> None:
        with self.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None
            if self.state:
                self.save({"window_geometry": dict(self.state)})


class WindowGeometryManager:
    """High-level manager coordinating geometry persistence and window state."""

    def __init__(
        self,
        geometry: WindowGeometry,
        webview: Any = None,
        default_size: tuple[int, int] = (1280, 800),
    ):
        self.geometry = geometry
        self.webview = webview
        self.default_size = default_size
        self.suspended = False

    def capture(
        self,
        window: Any,
        *,
        displays: list[Display] | None = None,
        is_pip: bool = False,
        is_maximized: bool = False,
        is_fullscreen: bool = False,
    ) -> bool:
        if self.suspended or is_fullscreen or not window:
            return False
        extracted = extract_window_state_and_bounds(
            window,
            displays=displays,
            webview=self.webview,
            fallback_is_maximized=is_maximized,
        )
        if not extracted:
            return False
        bounds, display, state_maximized, is_minimized = extracted
        if is_minimized:
            return False
        if state_maximized and self.geometry.state.get("normal"):
            bounds = self.geometry.state["normal"]["bounds"]
        self.geometry.remember(bounds, display, pip=is_pip, maximized=state_maximized)
        return True

    def apply_to_window(
        self,
        window: Any,
        *,
        displays: list[Display] | None = None,
        pip: bool = False,
        on_change: Any = None,
    ) -> dict[str, Any] | None:
        """Apply restored placement to the given window."""
        if displays is None:
            displays = native_displays(self.webview)
        restored = self.geometry.restore(displays, pip=pip, default_size=self.default_size)
        if not restored or not window:
            return None

        x, y, width, height = restored["bounds"]
        maximized = bool(restored.get("maximized", False))

        if os.name == "nt" and getattr(window, "native", None):
            import System.Windows.Forms as forms

            form = window.native
            form.SetBounds(x, y, width, height)
            if maximized:
                form.WindowState = forms.FormWindowState.Maximized
            if on_change:
                form.LocationChanged += on_change
                form.SizeChanged += on_change
        else:
            if hasattr(window, "resize"):
                window.resize(width, height)
            if hasattr(window, "move"):
                window.move(x, y)
            if maximized and hasattr(window, "maximize"):
                window.maximize()

        return restored

    def flush(self) -> None:
        self.geometry.flush()


def native_displays(webview: Any = None) -> list[Display]:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        try:
            import clr

            clr.AddReference("System.Windows.Forms")
            import System.Windows.Forms as forms

            result = []
            screens = sorted(forms.Screen.AllScreens, key=lambda screen: not screen.Primary)
            for screen in screens:
                area = screen.WorkingArea
                dpi = 96
                try:
                    user32, shcore = ctypes.windll.user32, ctypes.windll.shcore
                    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
                    user32.MonitorFromPoint.restype = wintypes.HANDLE
                    shcore.GetDpiForMonitor.argtypes = [
                        wintypes.HANDLE,
                        ctypes.c_int,
                        ctypes.POINTER(wintypes.UINT),
                        ctypes.POINTER(wintypes.UINT),
                    ]
                    dx, dy = wintypes.UINT(), wintypes.UINT()
                    monitor = user32.MonitorFromPoint(wintypes.POINT(area.X + 1, area.Y + 1), 2)
                    if shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                        dpi = dx.value
                except (OSError, AttributeError):
                    pass
                result.append(Display(str(screen.DeviceName), area.X, area.Y, area.Width, area.Height, dpi))
            return result
        except Exception as error:
            logger.debug("WinForms display discovery unavailable: %s", error)

    if webview and hasattr(webview, "screens"):
        result = []
        for screen in webview.screens:
            frame = getattr(screen, "frame", None)
            if frame is not None and hasattr(frame, "availableGeometry"):
                area = frame.availableGeometry()
                name = str(frame.name())
                result.append(Display(name, area.x(), area.y(), area.width(), area.height()))
            else:
                result.append(Display(f"{screen.x},{screen.y}", screen.x, screen.y, screen.width, screen.height))
        return result

    return []
