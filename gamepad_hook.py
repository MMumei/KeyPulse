from __future__ import annotations

"""XInput polling for the controller view.

Windows has no low-level hook for gamepads the way it has for keyboards, so a
pad has to be asked for its state instead. This thread polls the slot a
controller is plugged into at 125 Hz and reports edges only, which is what the
counters and the canvas both want; the analogue sticks are reported as
positions, purely so the on-screen sticks can lean the same way.
"""

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable


ERROR_SUCCESS = 0
MAX_SLOTS = 4

# XInput's own dead zones, so a resting stick reads as centred.
LEFT_DEADZONE = 7849
RIGHT_DEADZONE = 8689
# A trigger is a 0-255 axis; press and release at different points so a finger
# resting on the edge does not chatter.
TRIGGER_PRESS = 40
TRIGGER_RELEASE = 22

BUTTON_BITS: tuple[tuple[int, str], ...] = (
    (0x0001, "DPAD_UP"),
    (0x0002, "DPAD_DOWN"),
    (0x0004, "DPAD_LEFT"),
    (0x0008, "DPAD_RIGHT"),
    (0x0010, "START"),
    (0x0020, "BACK"),
    (0x0040, "LS"),
    (0x0080, "RS"),
    (0x0100, "LB"),
    (0x0200, "RB"),
    (0x0400, "GUIDE"),
    (0x1000, "FACE_DOWN"),
    (0x2000, "FACE_RIGHT"),
    (0x4000, "FACE_LEFT"),
    (0x8000, "FACE_UP"),
)


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


def _load_xinput():
    """The newest XInput present, plus its undocumented Guide-aware entry.

    ``XInputGetState`` masks the Guide button off; ordinal 100 is the same
    call without that mask and has shipped in every version since 1.3. Fall
    back to the documented export when it is missing, and simply never see
    a Guide press there.
    """
    for name in ("XInput1_4.dll", "XInput1_3.dll", "XInput9_1_0.dll"):
        try:
            library = ctypes.WinDLL(name)
        except OSError:
            continue
        get_state = None
        try:
            get_state = library[100]
        except (AttributeError, ValueError, OSError):
            get_state = None
        if get_state is None:
            get_state = library.XInputGetState
        get_state.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
        get_state.restype = wintypes.DWORD
        return library, get_state, name
    return None, None, ""


def deaden(value: int, deadzone: int) -> float:
    """A thumbstick axis as -1.0 .. 1.0, with the dead zone taken out."""
    magnitude = abs(value)
    if magnitude <= deadzone:
        return 0.0
    span = 32767.0 - deadzone
    scaled = min(1.0, (magnitude - deadzone) / span)
    return scaled if value > 0 else -scaled


class GamepadHook(threading.Thread):
    """Polls the first connected pad and reports button edges and stick travel.

    ``on_axes`` is handed ``(left_x, left_y, right_x, right_y)`` with y already
    flipped to point the way the screen does, and only when it actually moves.
    ``on_connection`` reports the slot number, or -1 once every pad is gone.
    """

    def __init__(
        self,
        on_press: Callable[[str], None],
        on_release: Callable[[str], None],
        on_axes: Callable[[float, float, float, float], None] | None = None,
        on_connection: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(name="KeyPulseGamepadHook", daemon=True)
        self.on_press = on_press
        self.on_release = on_release
        self.on_axes = on_axes
        self.on_connection = on_connection
        # English, and put into words by the window that shows it.
        self.error: str | None = None
        self.error_params: dict = {}
        self.slot = -1
        self.runtime = ""
        self._library = None
        # Not _stop: Thread already uses that name internally, and shadowing
        # it breaks join().
        self._stopping = threading.Event()
        self._ready = threading.Event()
        self._held: set[str] = set()
        self._axes = (0.0, 0.0, 0.0, 0.0)

    # -- lifecycle ---------------------------------------------------------

    def wait_until_ready(self, timeout: float = 2.0) -> bool:
        self._ready.wait(timeout)
        return self.error is None

    def stop(self) -> None:
        self._stopping.set()

    # -- polling -----------------------------------------------------------

    def run(self) -> None:
        # Held on the instance so the DLL outlives the entry point taken out
        # of it, whatever ctypes does with its own references.
        self._library, get_state, self.runtime = _load_xinput()
        if get_state is None:
            self.error = "No XInput runtime was found, so controllers cannot be read."
            self._ready.set()
            return
        self._ready.set()

        state = XINPUT_STATE()
        slot = -1
        packet = -1
        # Polling an empty slot is slow enough to matter, so an unplugged pad
        # is looked for a few times a second rather than every frame.
        next_scan = 0.0
        while not self._stopping.is_set():
            now = time.monotonic()
            if slot < 0:
                if now >= next_scan:
                    next_scan = now + 1.0
                    for candidate in range(MAX_SLOTS):
                        if get_state(candidate, ctypes.byref(state)) == ERROR_SUCCESS:
                            slot = candidate
                            packet = -1
                            self.slot = slot
                            self._announce(slot)
                            break
                self._stopping.wait(0.10)
                continue

            if get_state(slot, ctypes.byref(state)) != ERROR_SUCCESS:
                self._release_all()
                slot = -1
                self.slot = -1
                self._announce(-1)
                next_scan = now + 0.5
                continue

            if state.dwPacketNumber != packet:
                packet = state.dwPacketNumber
                self._apply(state.Gamepad)
            self._stopping.wait(0.008)

        self._release_all()

    def _announce(self, slot: int) -> None:
        if self.on_connection is not None:
            self.on_connection(slot)

    def _apply(self, pad: XINPUT_GAMEPAD) -> None:
        held = {name for bit, name in BUTTON_BITS if pad.wButtons & bit}
        for trigger, name in ((pad.bLeftTrigger, "LT"), (pad.bRightTrigger, "RT")):
            threshold = TRIGGER_RELEASE if name in self._held else TRIGGER_PRESS
            if trigger >= threshold:
                held.add(name)

        for name in held - self._held:
            self.on_press(name)
        for name in self._held - held:
            self.on_release(name)
        self._held = held

        # Rounded, so the last bit of noise on a resting stick does not wake
        # the canvas up a hundred times a second.
        self._push_axes((
            round(deaden(pad.sThumbLX, LEFT_DEADZONE), 3),
            round(-deaden(pad.sThumbLY, LEFT_DEADZONE), 3),
            round(deaden(pad.sThumbRX, RIGHT_DEADZONE), 3),
            round(-deaden(pad.sThumbRY, RIGHT_DEADZONE), 3),
        ))

    def _push_axes(self, axes: tuple[float, float, float, float]) -> None:
        if axes == self._axes:
            return
        self._axes = axes
        if self.on_axes is not None:
            self.on_axes(*axes)

    def _release_all(self) -> None:
        for name in self._held:
            self.on_release(name)
        self._held = set()
        self._push_axes((0.0, 0.0, 0.0, 0.0))
