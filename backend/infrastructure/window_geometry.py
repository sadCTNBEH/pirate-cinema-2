"""Event-driven window placement, independent of the native GUI for testing."""

import math
import threading
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Display:
    name: str
    x: int
    y: int
    width: int
    height: int
    dpi: int = 96


def _number(value, fallback):
    if isinstance(value, bool):
        return fallback
    try:
        number = float(value)
        return round(number) if math.isfinite(number) and abs(number) <= 100000 else fallback
    except (TypeError, ValueError, OverflowError):
        return fallback


def placement(saved, displays, *, pip=False, default_size=(1280, 800)):
    """Scale within the saved monitor, then clamp to an available work area."""
    if not displays:
        return None
    saved = saved if isinstance(saved, dict) else {}
    bounds = saved.get('bounds')
    valid = isinstance(bounds, (list, tuple)) and len(bounds) == 4
    bounds = bounds if valid else [None]*4
    display = next((d for d in displays if d.name == saved.get('monitor')), None)
    old_area = saved.get('work_area')
    same_monitor = display is not None
    if display is None:
        display = displays[0]
    factor = display.dpi/max(48, _number(saved.get('dpi'), display.dpi)) if same_monitor else 1
    minimum = (280, 180) if pip else (640, 420)
    default = (420, 268) if pip else default_size
    width = min(display.width, max(minimum[0], round(max(1, _number(bounds[2], default[0]))*factor)))
    height = min(display.height, max(minimum[1], round(max(1, _number(bounds[3], default[1]))*factor)))
    x = display.x + (display.width-width)//2
    y = display.y + (display.height-height)//2
    if valid and same_monitor and isinstance(old_area, dict):
        x = display.x + round((_number(bounds[0], x)-_number(old_area.get('x'), display.x))*factor)
        y = display.y + round((_number(bounds[1], y)-_number(old_area.get('y'), display.y))*factor)
    x = max(display.x, min(display.x+display.width-width, x))
    y = max(display.y, min(display.y+display.height-height, y))
    return {'bounds': [x, y, width, height], 'monitor': display.name, 'dpi': display.dpi,
            'work_area': asdict(display), 'maximized': bool(saved.get('maximized')) and not pip}


class WindowGeometry:
    def __init__(self, settings, save, delay=0.4):
        raw = settings.get('window_geometry', {})
        self.state = dict(raw) if isinstance(raw, dict) else {}
        self.save = save
        self.delay = delay
        self.lock = threading.RLock()
        self.timer = None

    def remember(self, bounds, display, *, pip=False, maximized=False, fullscreen=False, minimized=False):
        if fullscreen or minimized or not display or len(bounds) != 4:
            return
        normalized = [_number(v, None) for v in bounds]
        if any(v is None for v in normalized) or normalized[2] < 200 or normalized[3] < 120:
            return
        record = {'bounds': normalized, 'monitor': display.name, 'dpi': display.dpi,
                  'work_area': asdict(display), 'maximized': bool(maximized) and not pip}
        with self.lock:
            key = 'pip' if pip else 'normal'
            if self.state.get(key) == record:
                return
            self.state[key] = record
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(self.delay, self.flush)
            self.timer.daemon = True
            self.timer.start()

    def restore(self, displays, *, pip=False, default_size=(1280, 800)):
        with self.lock:
            return placement(self.state.get('pip' if pip else 'normal'), displays,
                             pip=pip, default_size=default_size)

    def flush(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None
            if self.state:
                self.save({'window_geometry': dict(self.state)})


def native_displays(webview=None):
    import os

    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        import clr
        clr.AddReference('System.Windows.Forms')
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
                shcore.GetDpiForMonitor.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
                dx, dy = wintypes.UINT(), wintypes.UINT()
                monitor = user32.MonitorFromPoint(wintypes.POINT(area.X+1, area.Y+1), 2)
                if shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                    dpi = dx.value
            except (OSError, AttributeError):
                pass
            result.append(Display(str(screen.DeviceName), area.X, area.Y, area.Width, area.Height, dpi))
        return result
    if webview:
        result = []
        for screen in webview.screens:
            frame = getattr(screen, 'frame', None)
            if frame is not None and hasattr(frame, 'availableGeometry'):
                area = frame.availableGeometry()
                name = str(frame.name())
                result.append(Display(name, area.x(), area.y(), area.width(), area.height()))
            else:
                result.append(Display(f'{screen.x},{screen.y}', screen.x, screen.y, screen.width, screen.height))
        return result
    return []
