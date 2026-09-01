from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KeySpec:
    key_id: str
    label: str
    x: float
    y: float
    width: float = 1.0
    height: float = 1.0


@dataclass(frozen=True)
class KeyboardLayout:
    layout_id: str
    name: str
    keys: tuple[KeySpec, ...]
    width: float
    height: float


GAP = 0.14
ROW = 1.14


def _row(y: float, items: list[tuple], start: float = 0.0) -> list[KeySpec]:
    keys: list[KeySpec] = []
    x = start
    for item in items:
        if item[0] == "_":
            x += float(item[1])
            continue
        key_id, label = item[0], item[1]
        width = float(item[2]) if len(item) > 2 else 1.0
        keys.append(KeySpec(key_id, label, x, y, width))
        x += width + GAP
    return keys


NUMBERS = [
    ("GRAVE", "`"), ("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"),
    ("5", "5"), ("6", "6"), ("7", "7"), ("8", "8"), ("9", "9"),
    ("0", "0"), ("MINUS", "-"), ("EQUAL", "="), ("BACKSPACE", "Backspace", 2.0),
]
Q_ROW = [
    ("TAB", "Tab", 1.5), ("Q", "Q"), ("W", "W"), ("E", "E"), ("R", "R"),
    ("T", "T"), ("Y", "Y"), ("U", "U"), ("I", "I"), ("O", "O"),
    ("P", "P"), ("LBRACKET", "["), ("RBRACKET", "]"), ("BACKSLASH", "\\", 1.5),
]
A_ROW = [
    ("CAPSLOCK", "Caps", 1.8), ("A", "A"), ("S", "S"), ("D", "D"), ("F", "F"),
    ("G", "G"), ("H", "H"), ("J", "J"), ("K", "K"), ("L", "L"),
    ("SEMICOLON", ";"), ("QUOTE", "'"), ("ENTER", "Enter", 2.26),
]
Z_ROW = [
    ("LSHIFT", "Shift", 2.25), ("Z", "Z"), ("X", "X"), ("C", "C"),
    ("V", "V"), ("B", "B"), ("N", "N"), ("M", "M"), ("COMMA", ","),
    ("PERIOD", "."), ("SLASH", "/"), ("RSHIFT", "Shift", 2.95),
]
BOTTOM = [
    ("LCTRL", "Ctrl", 1.4), ("LWIN", "Win", 1.25), ("LALT", "Alt", 1.25),
    ("SPACE", "Space", 6.25), ("RALT", "Alt", 1.25), ("RWIN", "Win", 1.25),
    ("MENU", "Menu", 1.25), ("RCTRL", "Ctrl", 1.4),
]


def _standard_alpha(y0: float = 1.55) -> list[KeySpec]:
    keys: list[KeySpec] = []
    keys += _row(y0, NUMBERS)
    keys += _row(y0 + ROW, Q_ROW)
    keys += _row(y0 + ROW * 2, A_ROW)
    keys += _row(y0 + ROW * 3, Z_ROW)
    keys += _row(y0 + ROW * 4, BOTTOM)
    return keys


def _function_row() -> list[KeySpec]:
    """Esc, the twelve F keys in their three groups, and the three above Ins."""
    return _row(0.0, [
        ("ESC", "Esc"), ("_", 0.55),
        ("F1", "F1"), ("F2", "F2"), ("F3", "F3"), ("F4", "F4"), ("_", 0.35),
        ("F5", "F5"), ("F6", "F6"), ("F7", "F7"), ("F8", "F8"), ("_", 0.35),
        ("F9", "F9"), ("F10", "F10"), ("F11", "F11"), ("F12", "F12"),
        ("_", 0.56), ("PRTSC", "PrtSc"), ("SCRLK", "ScrLk"), ("PAUSE", "Pause"),
    ])


def _nav_cluster(x: float, y: float) -> list[KeySpec]:
    keys: list[KeySpec] = []
    keys += _row(y, [("INSERT", "Ins"), ("HOME", "Home"), ("PAGEUP", "PgUp")], x)
    keys += _row(y + ROW, [("DELETE", "Del"), ("END", "End"), ("PAGEDOWN", "PgDn")], x)
    keys += _row(y + ROW * 3, [("_", 1.0 + GAP), ("UP", "↑")], x)
    keys += _row(y + ROW * 4, [("LEFT", "←"), ("DOWN", "↓"), ("RIGHT", "→")], x)
    return keys


def _numpad(x: float, y: float) -> list[KeySpec]:
    keys: list[KeySpec] = []
    keys += _row(y, [("NUMLOCK", "Num"), ("NUMDIV", "/"), ("NUMMUL", "×"), ("NUMSUB", "−")], x)
    keys += _row(y + ROW, [("NUM7", "7"), ("NUM8", "8"), ("NUM9", "9")], x)
    keys.append(KeySpec("NUMADD", "+", x + (1 + GAP) * 3, y + ROW, 1.0, 2.0 + GAP))
    keys += _row(y + ROW * 2, [("NUM4", "4"), ("NUM5", "5"), ("NUM6", "6")], x)
    keys += _row(y + ROW * 3, [("NUM1", "1"), ("NUM2", "2"), ("NUM3", "3")], x)
    keys.append(KeySpec("NUMENTER", "Enter", x + (1 + GAP) * 3, y + ROW * 3, 1.0, 2.0 + GAP))
    keys += _row(y + ROW * 4, [("NUM0", "0", 2.0 + GAP), ("NUMDECIMAL", ".")], x)
    return keys


# The four boards in the reference picture, in the order it numbers them.
# Each one is the picture read row by row: which keys are on it, how wide they
# are, and where the blocks sit relative to each other.


def _full() -> KeyboardLayout:
    """No. 1 -- full size: everything, numpad included."""
    keys = _function_row() + _standard_alpha()
    keys += _nav_cluster(17.45, 1.55)
    keys += _numpad(21.28, 1.55)
    return KeyboardLayout("full", "Full Size", tuple(keys), 25.90, 7.20)


def _tkl() -> KeyboardLayout:
    """No. 2 -- the same board with the numpad cut off, 87 keys.

    The function row keeps its three groups and its PrtSc / ScrLk / Pause,
    and the navigation block keeps all six keys above the arrows: the picture
    loses the numpad and nothing else.
    """
    keys = _function_row() + _standard_alpha() + _nav_cluster(17.45, 1.55)
    return KeyboardLayout("tkl", "TKL 87", tuple(keys), 20.85, 7.20)


def _sixty() -> KeyboardLayout:
    """No. 3 -- 60%: the five letter rows and nothing around them.

    No function row, no navigation block, no arrows. The bottom row is the
    one the picture shows -- three modifiers, the space bar, four more -- and
    every other row is the standard one at its standard width.
    """
    return KeyboardLayout("60", "60%", tuple(_standard_alpha(0.0)), 17.02, 5.66)


def _seventy_five() -> KeyboardLayout:
    """No. 4 -- 75%: the function row kept, everything else pulled in tight.

    The picture packs the navigation keys into a single column down the right
    edge, one key on every row from the numbers to the Shift row. The arrows
    are folded into the two rows below that: the up arrow at the end of the
    Shift row with the column still to its right, and left, down and right
    closing the bottom row, so the right edge stays straight the whole way
    down. The right Shift is shortened and the Menu key dropped to pay for it.
    """
    top = _row(0.0, [
        ("ESC", "Esc"), ("_", 0.18), ("F1", "F1"), ("F2", "F2"), ("F3", "F3"),
        ("F4", "F4"), ("F5", "F5"), ("F6", "F6"), ("F7", "F7"), ("F8", "F8"),
        ("F9", "F9"), ("F10", "F10"), ("F11", "F11"), ("F12", "F12"),
        ("PRTSC", "Prt"), ("DELETE", "Del"),
    ])
    keys = top + _standard_alpha(1.14)
    column = 17.31
    keys += [
        KeySpec("HOME", "Home", column, 1.14),
        KeySpec("PAGEUP", "PgUp", column, 2.28),
        KeySpec("PAGEDOWN", "PgDn", column, 3.42),
        KeySpec("END", "End", column, 4.56),
        KeySpec("UP", "↑", 16.17, 4.56),
    ]
    keys = [key for key in keys if key.key_id != "MENU"]
    keys = [
        KeySpec(k.key_id, k.label, 13.49, k.y, k.width, k.height) if k.key_id == "RCTRL"
        else KeySpec(k.key_id, k.label, k.x, k.y, 1.75, k.height) if k.key_id == "RSHIFT"
        else k
        for k in keys
    ]
    keys += _row(5.70, [("LEFT", "←"), ("DOWN", "↓"), ("RIGHT", "→")], 15.03)
    return KeyboardLayout("75", "75%", tuple(keys), 18.51, 6.80)


LAYOUTS = {
    layout.layout_id: layout
    for layout in (_full(), _tkl(), _sixty(), _seventy_five())
}

# The order the LAYOUT list offers them in: largest board first, down to the
# smallest. It is a list of sizes, so it reads as one -- 104, 87, 83, 61 --
# rather than in the order the reference picture happens to lay them out,
# which put the 61-key board above the 83-key one.
LAYOUT_ORDER = ("full", "tkl", "75", "60")

# Every key id that appears in any layout, mapped to the label the full-size
# board uses for it, so the summary cards never have to rescan the layouts.
# Read back to front so the full-size board, which is first in the list and
# has every key on it, is the one whose label lands last and wins.
KEY_LABELS: dict[str, str] = {
    key.key_id: key.label
    for layout_id in reversed(LAYOUT_ORDER)
    for key in LAYOUTS[layout_id].keys
}
