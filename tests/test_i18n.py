from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import i18n
import storage
from gamepads import MODEL_ORDER, MODELS
from i18n import CHINESE, CHINESE_TEXT, ENGLISH, set_language, tr
from render import compact_number, written
from storage import GAMEPAD_DEVICE, KEYBOARD_DEVICE, SettingsStore, StatsStore
from ui import MainWindow


SOURCES = ("ui.py", "gallery.py", "main.py", "render.py", "pad_canvas.py")

QApplication.instance() or QApplication([])


class SpeakingChinese:
    """Run a block with the window speaking Chinese, whatever it spoke before."""

    def __init__(self, code: str = CHINESE) -> None:
        self.code = code

    def __enter__(self) -> None:
        self.saved = i18n.language()
        set_language(self.code)

    def __exit__(self, *_) -> None:
        set_language(self.saved)


class TemporaryDataDir:
    def __enter__(self) -> Path:
        self._temporary = tempfile.TemporaryDirectory()
        self._saved = storage.DATA_DIR, storage.STATS_PATH, storage.SETTINGS_PATH
        directory = Path(self._temporary.name)
        storage.DATA_DIR = directory
        storage.STATS_PATH = directory / "stats.json"
        storage.SETTINGS_PATH = directory / "settings.json"
        return directory

    def __exit__(self, *_) -> None:
        storage.DATA_DIR, storage.STATS_PATH, storage.SETTINGS_PATH = self._saved
        self._temporary.cleanup()


class TableTests(unittest.TestCase):
    def test_every_string_the_window_says_has_a_second_language(self) -> None:
        """A label with no entry falls back to English and shows up mid-Chinese.

        The fallback is deliberate -- a missing entry must never blank a
        button -- which is exactly why nothing catches one on its own. This
        reads the strings back out of the source and asks the table for each.
        """
        here = Path(__file__).resolve().parent.parent
        quoted = r'"((?:[^"\\]|\\.)*)"'
        missing: list[str] = []
        for name in SOURCES:
            text = (here / name).read_text(encoding="utf-8")
            for call in re.finditer(r"tr\(\s*((?:" + quoted + r"\s*)+)", text, re.S):
                source = "".join(re.findall(quoted, call.group(1)))
                if source and source not in CHINESE_TEXT:
                    missing.append(f"{name}: {source}")
            for call in re.finditer(
                r"\.(?:label|tip)\(\s*[^,]+,\s*" + quoted + r"(?:\s*,\s*" + quoted + r")?",
                text,
                re.S,
            ):
                for source in call.groups():
                    if source and source not in CHINESE_TEXT:
                        missing.append(f"{name}: {source}")
        self.assertEqual(missing, [])

    def test_the_pads_keep_the_names_on_their_boxes(self) -> None:
        """A model is called what its box calls it, in either language.

        The four boards are sizes and are read as sizes, so they are named in
        the language the window is speaking. A pad is a product: Wired had a
        Chinese reading here once and it turned the name of a model into the
        name of a category, which is not what the other three are.
        """
        with SpeakingChinese():
            for model_id in MODEL_ORDER:
                name = MODELS[model_id].name
                self.assertEqual(tr(name), name)

    def test_the_chinese_never_leaves_a_placeholder_behind(self) -> None:
        """A translation that drops a {name} formats into a hole or an error."""
        holes = re.compile(r"\{(\w+)\}")
        for source, chinese in CHINESE_TEXT.items():
            self.assertEqual(
                set(holes.findall(source)),
                set(holes.findall(chinese)),
                f"placeholders differ: {source}",
            )


class NumberTests(unittest.TestCase):
    def test_each_language_shortens_in_the_units_it_counts_in(self) -> None:
        self.assertEqual(compact_number(999), "999")
        self.assertEqual(compact_number(11_329), "11.3K")
        self.assertEqual(compact_number(2_400_000), "2.4M")
        with SpeakingChinese():
            # Chinese groups digits in fours, so it stays written out until
            # 10,000 -- which is where 万 begins -- and shortens from there.
            self.assertEqual(compact_number(9_999), "9,999")
            self.assertEqual(compact_number(11_329), "1.1万")
            self.assertEqual(compact_number(107_148), "10.7万")
            self.assertEqual(compact_number(240_000_000), "2.4亿")

    def test_both_devices_write_a_count_out_to_the_same_point(self) -> None:
        """The keyboard and the pad print the same total the same way."""
        self.assertEqual(written(9_999), "9,999")
        self.assertEqual(written(50_000), compact_number(50_000))


class WindowTests(unittest.TestCase):
    def _window(self) -> MainWindow:
        return MainWindow(
            StatsStore(device=KEYBOARD_DEVICE),
            StatsStore(device=GAMEPAD_DEVICE),
            SettingsStore(frozen=True),
        )

    def test_the_light_says_the_same_thing_on_both_devices(self) -> None:
        with TemporaryDataDir():
            window = self._window()
            window.on_pad_connection(0)
            for device in (KEYBOARD_DEVICE, GAMEPAD_DEVICE):
                window._device_chosen(device)
                self.assertEqual(window.status_text.text(), tr("●  LIVE"))
            with SpeakingChinese():
                window.retranslate()
                for device in (KEYBOARD_DEVICE, GAMEPAD_DEVICE):
                    window._device_chosen(device)
                    self.assertEqual(window.status_text.text(), "●  监听中")
                window._device_chosen(GAMEPAD_DEVICE)
                window.on_pad_connection(-1)
                self.assertEqual(window.status_text.text(), "○  未连接手柄")
            window.quitting = True
            window.close()

    def test_throwing_the_switch_twice_leaves_the_window_where_it_started(self) -> None:
        with TemporaryDataDir():
            window = self._window()
            set_language(ENGLISH)
            window.retranslate()
            before = window.total_card.caption.text()
            window._toggle_language()
            self.assertNotEqual(window.total_card.caption.text(), before)
            window._toggle_language()
            self.assertEqual(window.total_card.caption.text(), before)
            self.assertEqual(i18n.language(), ENGLISH)
            window.quitting = True
            window.close()


class HeaderTests(unittest.TestCase):
    def test_the_light_goes_out_on_the_wall(self) -> None:
        """The gallery watches nothing, so it has no status to report."""
        with TemporaryDataDir():
            window = MainWindow(
                StatsStore(device=KEYBOARD_DEVICE),
                StatsStore(device=GAMEPAD_DEVICE),
                SettingsStore(frozen=True),
            )
            window.show()
            self.assertTrue(window.status_text.isVisible())
            window._show_page("gallery")
            self.assertFalse(window.status_text.isVisible())
            window._show_page("monitor")
            self.assertTrue(window.status_text.isVisible())
            window.quitting = True
            window.close()


class HookReportTests(unittest.TestCase):
    """The header must not invent a failure, nor keep one that went away."""

    def _window(self) -> MainWindow:
        return MainWindow(
            StatsStore(device=KEYBOARD_DEVICE),
            StatsStore(device=GAMEPAD_DEVICE),
            SettingsStore(frozen=True),
        )

    def test_a_hook_that_comes_up_late_still_says_it_came_up(self) -> None:
        with TemporaryDataDir():
            window = self._window()
            # Whenever it arrives, an empty message means the hook is up.
            window.on_hook_ready("")
            self.assertEqual(window.status_text.text(), tr("●  LIVE"))
            window.quitting = True
            window.close()

    def test_the_light_names_the_device_that_failed(self) -> None:
        with TemporaryDataDir():
            window = self._window()
            window.on_hook_ready(
                "Keyboard monitoring failed (Windows error {code}).", {"code": 5}
            )
            window.set_pad_error("No XInput runtime was found, so controllers cannot be read.")
            window._device_chosen(KEYBOARD_DEVICE)
            keyboard = window.status_text.text()
            window._device_chosen(GAMEPAD_DEVICE)
            self.assertNotEqual(window.status_text.text(), keyboard)
            with SpeakingChinese():
                window.retranslate()
                window._device_chosen(KEYBOARD_DEVICE)
                self.assertEqual(window.status_text.text(), "●  键盘异常")
                self.assertIn("5", window.status_text.toolTip())
                window._device_chosen(GAMEPAD_DEVICE)
                self.assertEqual(window.status_text.text(), "●  手柄异常")
            window.quitting = True
            window.close()

    def test_a_worry_the_hook_takes_back_leaves_the_header(self) -> None:
        with TemporaryDataDir():
            window = self._window()
            window.on_hook_ready("Keyboard monitoring error")
            self.assertNotEqual(window.status_text.text(), tr("●  LIVE"))
            window.on_hook_ready("")
            self.assertEqual(window.status_text.text(), tr("●  LIVE"))
            window.quitting = True
            window.close()


if __name__ == "__main__":
    unittest.main()
