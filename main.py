from __future__ import annotations

import argparse
import ctypes
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from gamepad_hook import GamepadHook
from hook import GlobalKeyboardHook
from i18n import ENGLISH, set_language, tr
from storage import (
    DataFolderError,
    GAMEPAD_DEVICE,
    KEYBOARD_DEVICE,
    adopt_orphaned_snapshots,
    adopt_orphaned_state,
    ensure_data_dir,
    file_loose_runs,
    set_startup_enabled,
    SettingsStore,
    StatsStore,
)
from ui import MainWindow, app_icon


# Plausible counts for --demo and for the screenshots used in the docs.
DEMO_COUNTS: dict[str, int] = {
    "SPACE": 11329, "LCTRL": 9555, "BACKSPACE": 9382, "S": 4667,
    "TAB": 4311, "DOWN": 4148, "RIGHT": 4029, "ENTER": 3856,
    "C": 3655, "LEFT": 3651, "T": 3368, "R": 3061, "E": 3204,
    "G": 2737, "D": 2623, "F": 2589, "J": 2358, "P": 2390,
    "A": 2232, "W": 2258, "H": 2288, "O": 2230, "N": 2123,
    "LALT": 1924, "U": 1844, "Y": 1760, "L": 1513, "M": 1473,
    "B": 1356, "LSHIFT": 1235, "K": 1220, "Q": 1085,
    "F1": 24, "F2": 157, "F4": 67, "F5": 121, "F8": 28,
    "NUM1": 190, "NUM2": 352, "NUM3": 164, "NUM4": 69,
    "NUM5": 121, "NUM6": 88, "NUM0": 267, "NUMENTER": 46,
}


# The same, for a pad that has been played with for an evening or two.
DEMO_PAD_COUNTS: dict[str, int] = {
    "FACE_DOWN": 3184, "FACE_RIGHT": 1276, "FACE_LEFT": 942, "FACE_UP": 611,
    "LT": 2870, "RT": 4402, "LB": 1533, "RB": 1988,
    "LS": 517, "RS": 1104, "START": 233, "BACK": 96, "GUIDE": 41,
    "DPAD_UP": 688, "DPAD_DOWN": 731, "DPAD_LEFT": 542, "DPAD_RIGHT": 559,
}


class KeyboardBridge(QObject):
    pressed = Signal(str)
    released = Signal(str)
    ready = Signal(str, object)


class GamepadBridge(QObject):
    pressed = Signal(str)
    released = Signal(str)
    axes = Signal(float, float, float, float)
    connection = Signal(int)


def acquire_single_instance() -> int | None:
    if sys.platform != "win32":
        return 1
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\KeyPulse-9C8C7799-8D2A-4D84-9B79-51406F4818CC")
    if not handle or kernel32.GetLastError() == 183:
        return None
    return handle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--screenshot", type=str)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--no-hook", action="store_true")
    # Which device a --screenshot run should capture, and in which size.
    parser.add_argument("--device", choices=(KEYBOARD_DEVICE, GAMEPAD_DEVICE))
    parser.add_argument("--layout", type=str)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName("KeyPulse")
    app.setApplicationDisplayName("KeyPulse")
    app.setOrganizationName("KeyPulse")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)

    if not args.screenshot:
        try:
            # KeyPulse used to keep everything in a folder of its own on the D:
            # drive rather than beside the program. Anyone starting this build
            # over that one still has their counts and their settings sitting
            # there, so they are brought home before either is read -- if they
            # were not, the first start would look like a wipe.
            adopt_orphaned_state()
        except Exception:
            # Nothing here is allowed to stop KeyPulse from starting; the worst
            # case is the same first start it would have had anyway.
            pass

    # Settings are read before anything can go wrong, so even a box reporting
    # a failed start speaks the language the window was last left in.
    settings = SettingsStore(frozen=bool(args.screenshot))
    set_language(str(settings.get("language", ENGLISH)))

    try:
        ensure_data_dir()
    except DataFolderError as error:
        # The sentence is ours and belongs in the chosen language; the reason
        # under it comes from the OS, which has already picked its own.
        QMessageBox.critical(
            None,
            tr("Startup Error"),
            tr(error.message).format(**error.params) + "\n\n" + error.reason,
        )
        return 2
    except Exception as error:
        QMessageBox.critical(None, tr("Startup Error"), str(error))
        return 2

    if not args.screenshot:
        try:
            # The archive is put in order before the window is built, so the
            # wall opens with every picture on it rather than with the ones
            # filed since the folder last moved. What is already home comes
            # first: every build before the device folders wrote straight into
            # snapshots/, and those runs are moved down into the folder of the
            # device that filed them. Only then are the folders KeyPulse used
            # to write to read, so a run that was in both places has already
            # been filed under its own name and is not copied in beside itself.
            file_loose_runs()
            adopt_orphaned_snapshots()
        except Exception:
            # An archive that cannot be copied is still readable where it is.
            # Nothing here is allowed to stop KeyPulse from starting.
            pass

    mutex = None if args.screenshot else acquire_single_instance()
    if not args.screenshot and mutex is None:
        if not args.background:
            QMessageBox.information(
                None, tr("Already Running"), tr("Open KeyPulse from the system tray.")
            )
        return 0

    if settings.first_run and not args.screenshot:
        # Out of the box KeyPulse starts with Windows and counts in the
        # background, which is the only way a first day's counts are the whole
        # day's. It is written down here, once and only on the first start, so
        # the switch in the header stays wherever the user leaves it.
        try:
            set_startup_enabled(True)
        except Exception:
            # A locked-down registry is no reason not to start counting now.
            pass
        settings.save()

    stats = StatsStore.load(KEYBOARD_DEVICE)
    pad_stats = StatsStore.load(GAMEPAD_DEVICE)
    if args.demo:
        stats.counts = dict(DEMO_COUNTS)
        stats.total = sum(DEMO_COUNTS.values())
        pad_stats.counts = dict(DEMO_PAD_COUNTS)
        pad_stats.total = sum(DEMO_PAD_COUNTS.values())
    # The window opens on the keyboard every time, whichever device the switch
    # was left on. Both are counted the whole time either way, so which one was
    # last on screen is not a preference worth restoring: the keyboard is the
    # device every machine has, and it is the one KeyPulse is opened to look
    # at. A --screenshot run is the exception -- it is told what to shoot.
    settings.values["device"] = args.device or KEYBOARD_DEVICE
    if args.layout:
        key = "gamepad_model" if settings.values.get("device") == GAMEPAD_DEVICE else "layout"
        settings.values[key] = args.layout
    window = MainWindow(stats, pad_stats, settings)

    bridge = KeyboardBridge()
    bridge.pressed.connect(window.on_key_press)
    bridge.released.connect(window.on_key_release)
    bridge.ready.connect(window.on_hook_ready)
    pad_bridge = GamepadBridge()
    pad_bridge.pressed.connect(window.on_pad_press)
    pad_bridge.released.connect(window.on_pad_release)
    pad_bridge.axes.connect(window.on_pad_axes)
    pad_bridge.connection.connect(window.on_pad_connection)

    hook = None
    pad_hook = None
    if not args.no_hook and not args.screenshot and sys.platform == "win32":
        # The hook reports for itself once it knows, so nothing here waits on
        # a clock that a slow machine can outrun.
        hook = GlobalKeyboardHook(
            bridge.pressed.emit, bridge.released.emit, bridge.ready.emit
        )
        hook.start()
        pad_hook = GamepadHook(
            pad_bridge.pressed.emit,
            pad_bridge.released.emit,
            pad_bridge.axes.emit,
            pad_bridge.connection.emit,
        )
        pad_hook.start()
        if not pad_hook.wait_until_ready():
            window.set_pad_error(
                pad_hook.error or "Controller monitoring error", pad_hook.error_params
            )

    def save_all() -> None:
        stats.save()
        pad_stats.save()

    save_timer = QTimer()
    save_timer.setInterval(1000)
    save_timer.timeout.connect(save_all)
    save_timer.start()

    if args.screenshot:
        target = Path(args.screenshot).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        window.show()

        def take_screenshot() -> None:
            window.grab().save(str(target), "PNG")
            window.quitting = True
            app.quit()

        QTimer.singleShot(900, take_screenshot)
    elif args.background:
        window.hide()
    else:
        window.show()

    result = app.exec()
    if not args.screenshot:
        stats.save(force=True)
        pad_stats.save(force=True)
    if hook:
        hook.stop()
        hook.join(timeout=2.0)
    if pad_hook:
        pad_hook.stop()
        pad_hook.join(timeout=2.0)
    if mutex and sys.platform == "win32":
        ctypes.windll.kernel32.CloseHandle(mutex)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
