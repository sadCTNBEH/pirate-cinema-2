"""Translate Windows virtual keys to layout-independent browser key codes."""

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
) -> dict:
    return {
        "code": KEY_CODES[vk],
        "ctrlKey": ctrl,
        "altKey": alt,
        "shiftKey": shift,
        "metaKey": meta,
        "repeat": repeat,
    }
