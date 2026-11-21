"""Translate Windows virtual keys to layout-independent browser key codes and bridge OS input."""

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

KEY_CODES = {
    **{i: f"Key{chr(i)}" for i in range(0x41, 0x5B)},
    **{i: f"Digit{chr(i)}" for i in range(0x30, 0x3A)},
    **{i: f"F{i - 0x6F}" for i in range(0x70, 0x88)},
    **{i: f"Numpad{i - 0x60}" for i in range(0x60, 0x6A)},
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x1B: "Escape",
    0x20: "Space",
    0x21: "PageUp",
    0x22: "PageDown",
    0x23: "End",
    0x24: "Home",
    0x25: "ArrowLeft",
    0x26: "ArrowUp",
    0x27: "ArrowRight",
    0x28: "ArrowDown",
    0x2D: "Insert",
    0x2E: "Delete",
    0xBA: "Semicolon",
    0xBB: "Equal",
    0xBC: "Comma",
    0xBD: "Minus",
    0xBE: "Period",
    0xBF: "Slash",
    0xC0: "Backquote",
    0xDB: "BracketLeft",
    0xDC: "Backslash",
    0xDD: "BracketRight",
    0xDE: "Quote",
}


def key_payload(
    vk: int,
    *,
    ctrl: bool = False,
    alt: bool = False,
    shift: bool = False,
    meta: bool = False,
    repeat: bool = False,
) -> dict[str, Any]:
    return {
        "code": KEY_CODES[vk],
        "ctrlKey": ctrl,
        "altKey": alt,
        "shiftKey": shift,
        "metaKey": meta,
        "repeat": repeat,
    }


def dispatch_browser_event(window: Any, name: str, payload: Any) -> bool:
    """Safely dispatch a CustomEvent into the pywebview browser DOM."""
    if not window:
        return False
    try:
        script = (
            f"window.dispatchEvent(new CustomEvent({json.dumps(name)}, "
            f"{{detail: {json.dumps(payload)}}}))"
        )
        window.evaluate_js(script)
        return True
    except (RuntimeError, OSError, AttributeError) as err:
        logger.debug("Failed to dispatch browser event %s: %s", name, err)
        return False


class NativeInputBridge:
    """Bridge native Windows keyboard and window focus state to UI action events."""

    def __init__(
        self,
        emit_fn: Callable[[str, Any], None] | None = None,
    ):
        self.emit_fn = emit_fn
        self._running = False
        self._thread: threading.Thread | None = None
        self._form_hwnd: int | None = None
        self._player_hwnd: int | None = None
        self._player_visible: bool = False
        self._player_occluded: bool = False
        self._input_focused: bool = False
        self._held: dict[int, float] = {}
        self._previous_active: bool | None = None

    def set_hwnds(self, form_hwnd: int | None, player_hwnd: int | None) -> None:
        self._form_hwnd = form_hwnd
        self._player_hwnd = player_hwnd

    def set_state(
        self,
        *,
        player_visible: bool | None = None,
        player_occluded: bool | None = None,
        input_focused: bool | None = None,
    ) -> None:
        if player_visible is not None:
            self._player_visible = bool(player_visible)
        if player_occluded is not None:
            self._player_occluded = bool(player_occluded)
        if input_focused is not None:
            self._input_focused = bool(input_focused)
            if self._input_focused:
                self._held.clear()

    def start(self) -> None:
        if self._running or os.name != "nt":
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="EmbeddedPlayerInputBridge",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._held.clear()
        self._thread = None

    def is_running(self) -> bool:
        return self._running

    def poll_once(self, user32: Any = None) -> None:
        """Execute a single polling tick. Can be called directly in tests with a mock user32."""
        if user32 is None:
            if os.name != "nt":
                return
            import ctypes

            try:
                user32 = ctypes.windll.user32
            except (AttributeError, OSError):
                return

        import ctypes
        from ctypes import wintypes

        class GUIThreadInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND),
                ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND),
                ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT),
            ]

        try:
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
            foreground = user32.GetForegroundWindow()
            active = bool(
                foreground
                and self._form_hwnd
                and (
                    foreground == self._form_hwnd
                    or user32.IsChild(self._form_hwnd, foreground)
                )
            )
            if active != self._previous_active:
                if self.emit_fn:
                    self.emit_fn("cinema-native-focus", active)
                self._previous_active = active

            info = GUIThreadInfo()
            info.cbSize = ctypes.sizeof(info)
            native_focus = bool(
                active
                and self._player_visible
                and not self._player_occluded
                and user32.GetGUIThreadInfo(0, ctypes.byref(info))
                and self._player_hwnd
                and (
                    info.hwndFocus == self._player_hwnd
                    or user32.IsChild(self._player_hwnd, info.hwndFocus)
                )
            )
            if not native_focus or self._input_focused:
                self._held.clear()
                return

            now = time.monotonic()
            for vk in KEY_CODES:
                if not (user32.GetAsyncKeyState(vk) & 0x8000):
                    self._held.pop(vk, None)
                    continue
                due = self._held.get(vk)
                if due is not None and now < due:
                    continue
                payload = key_payload(
                    vk,
                    ctrl=bool(user32.GetAsyncKeyState(0x11) & 0x8000),
                    alt=bool(user32.GetAsyncKeyState(0x12) & 0x8000),
                    shift=bool(user32.GetAsyncKeyState(0x10) & 0x8000),
                    meta=bool(
                        (user32.GetAsyncKeyState(0x5B) & 0x8000)
                        or (user32.GetAsyncKeyState(0x5C) & 0x8000)
                    ),
                    repeat=(due is not None),
                )
                self._held[vk] = now + (0.38 if due is None else 0.11)
                if self.emit_fn:
                    self.emit_fn("cinema-native-key", payload)
        except (OSError, ValueError, RuntimeError, AttributeError):
            logger.debug("Native input bridge poll unavailable", exc_info=True)

    def _run_loop(self) -> None:
        try:
            import ctypes

            user32 = ctypes.windll.user32
        except (AttributeError, OSError):
            return

        while self._running:
            time.sleep(0.03 if self._player_visible else 0.15)
            self.poll_once(user32)
