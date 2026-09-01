from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable


WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
LLKHF_EXTENDED = 0x01


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


VK_MAP: dict[int, str] = {
    0x08: "BACKSPACE", 0x09: "TAB", 0x0D: "ENTER", 0x13: "PAUSE",
    0x14: "CAPSLOCK", 0x1B: "ESC", 0x20: "SPACE", 0x21: "PAGEUP",
    0x22: "PAGEDOWN", 0x23: "END", 0x24: "HOME", 0x25: "LEFT",
    0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN", 0x2C: "PRTSC",
    0x2D: "INSERT", 0x2E: "DELETE", 0x5B: "LWIN", 0x5C: "RWIN",
    0x5D: "MENU", 0x60: "NUM0", 0x61: "NUM1", 0x62: "NUM2",
    0x63: "NUM3", 0x64: "NUM4", 0x65: "NUM5", 0x66: "NUM6",
    0x67: "NUM7", 0x68: "NUM8", 0x69: "NUM9", 0x6A: "NUMMUL",
    0x6B: "NUMADD", 0x6D: "NUMSUB", 0x6E: "NUMDECIMAL", 0x6F: "NUMDIV",
    0x90: "NUMLOCK", 0x91: "SCRLK", 0xA0: "LSHIFT", 0xA1: "RSHIFT",
    0xA2: "LCTRL", 0xA3: "RCTRL", 0xA4: "LALT", 0xA5: "RALT",
    0xBA: "SEMICOLON", 0xBB: "EQUAL", 0xBC: "COMMA", 0xBD: "MINUS",
    0xBE: "PERIOD", 0xBF: "SLASH", 0xC0: "GRAVE", 0xDB: "LBRACKET",
    0xDC: "BACKSLASH", 0xDD: "RBRACKET", 0xDE: "QUOTE",
}
VK_MAP.update({code: chr(code) for code in range(0x41, 0x5B)})
VK_MAP.update({code: chr(code) for code in range(0x30, 0x3A)})
VK_MAP.update({0x70 + index: f"F{index + 1}" for index in range(24)})


def normalize_key(vk_code: int, scan_code: int, flags: int) -> str | None:
    extended = bool(flags & LLKHF_EXTENDED)
    if vk_code == 0x0D and extended:
        return "NUMENTER"
    if vk_code == 0x10:
        return "RSHIFT" if scan_code == 0x36 else "LSHIFT"
    if vk_code == 0x11:
        return "RCTRL" if extended else "LCTRL"
    if vk_code == 0x12:
        return "RALT" if extended else "LALT"
    return VK_MAP.get(vk_code)


class GlobalKeyboardHook(threading.Thread):
    """Counts physical key presses for as long as Windows lets it.

    ``on_ready`` is called once, from this thread, the moment the hook is
    either up or refused: an empty message means it is up, anything else is
    the English sentence for what went wrong plus what fills it.
    """

    def __init__(
        self,
        on_press: Callable[[str], None],
        on_release: Callable[[str], None],
        on_ready: Callable[[str, dict], None] | None = None,
    ):
        super().__init__(name="KeyPulseKeyboardHook", daemon=True)
        self.on_press = on_press
        self.on_release = on_release
        self.on_ready = on_ready
        self._hook = None
        self._thread_id = 0
        self._callback_ref = None
        self._ready = threading.Event()
        # The message stays English and keeps its numbers to one side, so the
        # window can say it in whichever language it is running in.
        self.error: str | None = None
        self.error_params: dict = {}
        self._pressed: set[str] = set()

    def run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetLastError.argtypes = []
        kernel32.GetLastError.restype = wintypes.DWORD
        self._thread_id = kernel32.GetCurrentThreadId()

        @HOOKPROC
        def callback(n_code: int, w_param: int, l_param: int) -> int:
            if n_code >= 0:
                data = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                key_id = normalize_key(data.vkCode, data.scanCode, data.flags)
                if key_id:
                    if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        # Count physical presses, not Windows key-repeat events.
                        if key_id not in self._pressed:
                            self._pressed.add(key_id)
                            self.on_press(key_id)
                    elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                        self._pressed.discard(key_id)
                        self.on_release(key_id)
            return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

        self._callback_ref = callback
        module = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, callback, module, 0)
        if not self._hook:
            # ctypes.get_last_error() only works on a use_last_error=True
            # library; ask Windows directly instead.
            self.error_params = {"code": kernel32.GetLastError()}
            self.error = "Keyboard monitoring failed (Windows error {code})."
            self._ready.set()
            self._announce()
            return
        self._ready.set()
        self._announce()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    def _announce(self) -> None:
        """Say how it went, once, the moment it is known.

        The window used to find out by waiting a fixed two seconds and then
        asking, which cannot tell a hook that was refused from one that has
        not finished going up yet. A machine busy enough to take longer than
        that -- a cold boot with the app set to start with Windows -- read as
        a failure, and nothing ever took it back: the header sat there saying
        the keyboard had a problem while it was quietly counting every key.
        """
        if self.on_ready is not None:
            self.on_ready(self.error or "", dict(self.error_params))

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
