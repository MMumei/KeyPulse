from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import storage
import gallery
from gallery import FrameCard, Snapshot, read_snapshots
from layouts import KEY_LABELS
from storage import DEFAULT_SETTINGS, GAMEPAD_DEVICE, KEYBOARD_DEVICE, SettingsStore, StatsStore
from ui import MainWindow, render_snapshot_image


class TemporaryDataDir:
    """Point storage -- and so the gallery -- at a scratch folder."""

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


class AnswerTheBox:
    """Answer whatever modal box opens next by clicking one of its roles.

    REMOVE asks before it deletes, so the only way to reach the deletion in a
    test is to answer the question. Patching exec rather than driving the
    dialog keeps the test off the event loop and out of the window manager.
    """

    def __init__(self, role) -> None:
        self.role = role

    def __enter__(self) -> "AnswerTheBox":
        self.saved = QMessageBox.exec
        role = self.role

        def answer(box) -> int:
            for button in box.buttons():
                if box.buttonRole(button) == role:
                    button.click()
                    break
            return 0

        QMessageBox.exec = answer
        return self

    def __exit__(self, *_) -> None:
        QMessageBox.exec = self.saved


def file_a_run(device: str, layout: str, key: str, presses: int, when: datetime) -> Path:
    """Archive a run the way the window does, picture and all."""
    stats = StatsStore(device=device)
    for _ in range(presses):
        stats.record(key)
    stats.started_at = (when - timedelta(hours=5)).isoformat(timespec="seconds")
    path = stats.archive(dict(KEY_LABELS), when, {"layout": layout, "layout_name": layout.upper()})
    render_snapshot_image(stats, layout, when, device).save(str(path.with_suffix(".png")), "PNG")
    return path


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # file_a_run paints a picture for every run it files, and Qt aborts
        # the process outright rather than raising if it is asked to paint
        # one before an application exists.
        cls.app = QApplication.instance() or QApplication([])

    def test_a_run_carries_both_ends_of_its_own_clock(self) -> None:
        with TemporaryDataDir():
            stats = StatsStore()
            self.assertIsNone(stats.started_at)
            stats.record("A")
            self.assertIsNotNone(stats.started_at)
            started = stats.started_at
            stats.save()
            # The clock survives a restart...
            self.assertEqual(StatsStore.load().started_at, started)

            moment = datetime(2026, 8, 30, 13, 42, 5)
            payload = json.loads(stats.archive({}, moment).read_text(encoding="utf-8"))
            self.assertEqual(payload["started_at"], started)
            self.assertEqual(payload["archived_at"], moment.isoformat(timespec="seconds"))

            # ...and the next run starts its own, rather than inheriting one.
            stats.reset()
            self.assertIsNone(stats.started_at)
            self.assertIsNone(StatsStore.load().started_at)

    def test_the_wall_is_filled_oldest_first(self) -> None:
        with TemporaryDataDir():
            base = datetime(2026, 8, 20, 9, 0)
            for day in range(3):
                file_a_run(KEYBOARD_DEVICE, "tkl", "A", 10 + day, base + timedelta(days=day))
            file_a_run(GAMEPAD_DEVICE, "xbox", "FACE_DOWN", 7, base + timedelta(days=1))

            walls = read_snapshots()
            board = walls[KEYBOARD_DEVICE]
            self.assertEqual(len(board), 3)
            # The first run filed is the first print in the album, and the
            # newest one lands after the others rather than ahead of them.
            self.assertEqual([piece.number for piece in board], [1, 2, 3])
            self.assertEqual(board[0].archived_at, base)
            self.assertEqual(board[0].total, 10)
            self.assertEqual(board[-1].archived_at, base + timedelta(days=2))
            self.assertEqual(board[0].layout_name, "TKL")
            self.assertEqual(board[0].date_text, "2026-08-20")
            self.assertIsNotNone(board[0].image_path)
            self.assertGreater(board[0].ratio, 1.0)
            # A run belongs to one wall only, and the pad's is numbered apart.
            pad = walls[GAMEPAD_DEVICE]
            self.assertEqual([piece.number for piece in pad], [1])
            self.assertEqual(pad[0].device, GAMEPAD_DEVICE)
            self.assertEqual(pad[0].noun, "presses")

    def test_an_archive_from_before_the_clock_still_hangs(self) -> None:
        with TemporaryDataDir() as directory:
            older = directory / storage.SNAPSHOT_DIR_NAME
            older.mkdir(parents=True, exist_ok=True)
            path = older / "keypulse-2026-08-30_132001.json"
            path.write_text(
                json.dumps(
                    {
                        "kind": "reset_snapshot",
                        "archived_at": "2026-08-30T13:20:01+08:00",
                        "covers": {"first_day": "2026-08-26", "last_day": "2026-08-30"},
                        "keys": {"A": 3},
                        "total_keystrokes": 3,
                        "ranking": [{"key": "A", "label": "A", "count": 3}],
                    }
                ),
                encoding="utf-8",
            )
            piece = Snapshot.read(path)
            assert piece is not None
            # No device and no start: the keyboard wall, dated by its first day.
            self.assertEqual(piece.device, KEYBOARD_DEVICE)
            self.assertTrue(piece.start_is_day_only)
            self.assertEqual(piece.started_at, datetime(2026, 8, 26))
            self.assertIsNone(piece.image_path)
            self.assertEqual(piece.distinct, 1)

    def test_a_run_hangs_from_its_device_folder_or_from_beside_it(self) -> None:
        """The wall reads the device folders and the archive around them.

        Runs filed by this build are in a folder per device. A run filed by
        any build before them is lying loose in the archive, and is still a
        run: it hangs on the wall whether or not it was ever moved down.
        """
        with TemporaryDataDir() as directory:
            filed = file_a_run(KEYBOARD_DEVICE, "tkl", "A", 4, datetime(2026, 9, 1, 12, 0))
            self.assertEqual(filed.parent.name, "keyboard")
            loose = directory / storage.SNAPSHOT_DIR_NAME / "keypulse-2026-08-30_132001.json"
            loose.write_text(
                json.dumps(
                    {
                        "kind": "reset_snapshot",
                        "archived_at": "2026-08-30T13:20:01+08:00",
                        "keys": {"A": 3},
                        "total_keystrokes": 3,
                    }
                ),
                encoding="utf-8",
            )
            hung = read_snapshots()[KEYBOARD_DEVICE]
            self.assertEqual([piece.json_path.name for piece in hung], [loose.name, filed.name])

            # ...and once it is filed down it is hung once, not twice.
            storage.file_loose_runs()
            hung = read_snapshots()[KEYBOARD_DEVICE]
            self.assertEqual([piece.json_path.name for piece in hung], [loose.name, filed.name])
            self.assertTrue(all(piece.json_path.parent.name == "keyboard" for piece in hung))

    def test_a_file_that_is_not_an_archive_is_not_hung(self) -> None:
        with TemporaryDataDir():
            folder = storage.ensure_snapshot_dir()
            (folder / "notes.json").write_text("{\"kind\": \"something else\"}", encoding="utf-8")
            (folder / "broken.json").write_text("{ not json", encoding="utf-8")
            self.assertEqual(read_snapshots()[KEYBOARD_DEVICE], [])


class GalleryPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _window(self) -> MainWindow:
        settings = SettingsStore(frozen=True)
        settings.values = DEFAULT_SETTINGS.copy()
        return MainWindow(
            StatsStore(device=KEYBOARD_DEVICE), StatsStore(device=GAMEPAD_DEVICE), settings
        )

    def test_the_wall_opens_on_the_device_that_was_on_screen(self) -> None:
        with TemporaryDataDir():
            file_a_run(KEYBOARD_DEVICE, "tkl", "A", 5, datetime(2026, 8, 28, 10, 0))
            file_a_run(GAMEPAD_DEVICE, "xbox", "FACE_DOWN", 9, datetime(2026, 8, 29, 10, 0))
            window = self._window()
            window._device_chosen(GAMEPAD_DEVICE)
            window._show_page("gallery")
            self.assertIs(window.pages.currentWidget(), window.gallery)
            self.assertEqual(window.gallery.device, GAMEPAD_DEVICE)
            self.assertEqual(len(window.gallery.cards), 1)
            self.assertEqual(window.gallery.cards[0].snapshot.total, 9)

            window.gallery.show_device(KEYBOARD_DEVICE)
            self.assertEqual(window.gallery.cards[0].snapshot.total, 5)
            # ...and the monitor is exactly where it was left.
            window._show_page("monitor")
            self.assertIs(window.pages.currentWidget(), window.live_page)
            window.quitting = True
            window.close()

    def test_a_reset_hangs_its_run_on_the_wall(self) -> None:
        with TemporaryDataDir():
            window = self._window()
            for _ in range(4):
                window.on_key_press("A")
            window._show_page("gallery")
            self.assertEqual(window.gallery.cards, [])

            window._show_page("monitor")
            path = file_a_run(KEYBOARD_DEVICE, "tkl", "A", 4, datetime(2026, 8, 30, 12, 0))
            window.gallery.invalidate(path)
            window._show_page("gallery")
            self.assertEqual(len(window.gallery.cards), 1)
            # The run just filed is the one the wall scrolls to.
            self.assertTrue(window.gallery.cards[0].fresh)
            window.quitting = True
            window.close()

    def test_a_card_shows_the_picture_it_was_filed_with(self) -> None:
        with TemporaryDataDir():
            path = file_a_run(KEYBOARD_DEVICE, "tkl", "A", 6, datetime(2026, 8, 30, 12, 0))
            piece = Snapshot.read(path)
            assert piece is not None
            card = FrameCard(piece)
            self.assertIsNone(card._thumb)
            card.load()
            self.assertIsNotNone(card._thumb)
            self.assertLessEqual(
                card._thumb.width() / card._thumb.devicePixelRatio(), card.width()
            )

    def test_a_print_is_mounted_with_its_label_below_the_picture(self) -> None:
        """Even board at the sides and the head, a deeper one at the foot.

        The foot is where the day and the size of the run are written, which
        is the whole reason a print is taller than the picture in it: the
        label sits under the mat the way it does on a mounted photograph,
        rather than on top of the picture it is labelling.
        """
        with TemporaryDataDir():
            path = file_a_run(KEYBOARD_DEVICE, "tkl", "A", 6, datetime(2026, 8, 30, 12, 0))
            piece = Snapshot.read(path)
            assert piece is not None
            card = FrameCard(piece, QSize(360, 160))
            self.assertEqual(card.width(), 360 + gallery.PRINT_BORDER * 2)
            self.assertEqual(card.height(), 160 + gallery.PRINT_BORDER + gallery.PRINT_FOOT)
            self.assertGreater(gallery.PRINT_FOOT, gallery.PRINT_BORDER)

    def test_clicking_a_picture_opens_the_run_behind_it(self) -> None:
        with TemporaryDataDir():
            file_a_run(KEYBOARD_DEVICE, "tkl", "A", 6, datetime(2026, 8, 30, 12, 0))
            window = self._window()
            window.resize(1280, 800)
            window.show()
            window._show_page("gallery")
            card = window.gallery.cards[0]
            QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=card.rect().center())
            self.assertEqual(window.gallery.stack.currentIndex(), 1)
            self.assertIs(window.gallery.detail.snapshot, card.snapshot)
            # Esc hangs it back up.
            QTest.keyClick(window.gallery, Qt.Key.Key_Escape)
            self.assertEqual(window.gallery.stack.currentIndex(), 0)
            window.quitting = True
            window.close()

    def test_the_album_starts_in_the_top_left_and_fills_to_the_right(self) -> None:
        """Print one takes the corner; the next goes beside it, then below."""
        with TemporaryDataDir():
            base = datetime(2026, 8, 1, 9, 0)
            for day in range(7):
                file_a_run(KEYBOARD_DEVICE, "tkl", "A", 5 + day, base + timedelta(days=day))
            window = self._window()
            window.resize(1440, 900)
            window.show()
            window._show_page("gallery")
            self.app.processEvents()
            cards = window.gallery.cards
            self.assertEqual(len(cards), 7)
            # The oldest run is the one in the corner...
            self.assertEqual(cards[0].snapshot.number, 1)
            corner = min(card.x() for card in cards), min(card.y() for card in cards)
            self.assertEqual((cards[0].x(), cards[0].y()), corner)
            # ...the next one sits to its right, on the same line...
            self.assertEqual(cards[1].y(), cards[0].y())
            self.assertGreater(cards[1].x(), cards[0].x())
            # ...every print is cut to the same size...
            self.assertEqual({card.size() for card in cards}, {cards[0].size()})
            # ...and the row wraps rather than running off the wall.
            rows = sorted({card.y() for card in cards})
            self.assertGreater(len(rows), 1)
            first_row = [card for card in cards if card.y() == rows[0]]
            self.assertGreater(len(first_row), 1)
            below = [card for card in cards if card.y() == rows[1]]
            self.assertEqual(below[0].x(), cards[0].x())
            window.quitting = True
            window.close()

    def test_a_print_is_neither_tiny_nor_the_whole_wall(self) -> None:
        with TemporaryDataDir():
            file_a_run(KEYBOARD_DEVICE, "tkl", "A", 9, datetime(2026, 8, 2, 9, 0))
            file_a_run(GAMEPAD_DEVICE, "xbox", "FACE_DOWN", 9, datetime(2026, 8, 2, 9, 5))
            window = self._window()
            window.resize(1440, 900)
            window.show()
            window._show_page("gallery")
            self.app.processEvents()
            for device in (KEYBOARD_DEVICE, GAMEPAD_DEVICE):
                window.gallery.show_device(device)
                self.app.processEvents()
                card = window.gallery.cards[0]
                wall = window.gallery.wall.width()
                self.assertGreater(card.width(), 240)
                self.assertLess(card.width(), wall * 0.62)
                # The mat is cut to the shape of the picture in it, so the
                # picture is never swimming in white. The board around the mat
                # is a mount rather than slack, which is why the shape is
                # measured at the opening and not at the edge of the print.
                opening = (card.width() - gallery.PRINT_BORDER * 2) / (
                    card.height() - gallery.PRINT_BORDER - gallery.PRINT_FOOT
                )
                self.assertAlmostEqual(opening, card.snapshot.ratio, delta=0.06)
            window.quitting = True
            window.close()

    def test_a_full_wall_grows_tall_enough_to_scroll(self) -> None:
        with TemporaryDataDir():
            base = datetime(2026, 8, 1, 9, 0)
            for day in range(12):
                file_a_run(KEYBOARD_DEVICE, "tkl", "A", 5 + day, base + timedelta(days=day))
            window = self._window()
            window.resize(1280, 800)
            window.show()
            window._show_page("gallery")
            self.assertEqual(len(window.gallery.cards), 12)
            wall = window.gallery.wall
            self.assertGreater(wall.minimumHeight(), window.gallery.scroll.viewport().height())
            # Every card is inside the wall it hangs on, none stacked at zero.
            spots = {(card.x(), card.y()) for card in window.gallery.cards}
            self.assertEqual(len(spots), 12)
            for card in window.gallery.cards:
                self.assertLessEqual(card.geometry().right(), wall.width())
            window.quitting = True
            window.close()

    def test_an_empty_wall_says_so_in_the_middle_of_the_card(self) -> None:
        """The notice has to be stretched over the whole wall, not left small.

        The page is filled in before it is brought to the front, so the wall
        is still at its build size when the notice goes up and only grows to
        the width of the card afterwards. Missing that resize left the notice
        parked in the top left corner of an otherwise blank card, which reads
        as the gallery having failed to open rather than as an empty wall.
        """
        with TemporaryDataDir():
            window = self._window()
            window.resize(1280, 800)
            window.show()
            window._show_page("gallery")
            wall = window.gallery.wall
            notice = wall.empty
            self.assertEqual(len(window.gallery.cards), 0)
            self.assertTrue(wall.showing_empty)
            self.assertTrue(notice.isVisible())
            self.assertEqual(notice.size(), wall.size())
            self.assertGreater(wall.width(), 600)
            # And it keeps up when the window is resized under it.
            window.resize(1420, 900)
            self.app.processEvents()
            self.assertEqual(notice.size(), wall.size())
            # Switching walls leaves the notice covering the new one too.
            window.gallery.show_device(GAMEPAD_DEVICE)
            self.app.processEvents()
            self.assertEqual(notice.size(), wall.size())
            window.quitting = True
            window.close()

    def test_a_wall_that_fills_up_puts_the_notice_away(self) -> None:
        with TemporaryDataDir():
            file_a_run(KEYBOARD_DEVICE, "tkl", "A", 7, datetime(2026, 8, 30, 9, 0))
            window = self._window()
            window.resize(1280, 800)
            window.show()
            window._show_page("gallery")
            wall = window.gallery.wall
            self.assertFalse(wall.showing_empty)
            self.assertFalse(wall.empty.isVisible())
            self.assertEqual(len(window.gallery.cards), 1)
            window.quitting = True
            window.close()

    def test_taking_an_exhibit_down_removes_both_of_its_files(self) -> None:
        """REMOVE means the disk, not just the wall.

        This used to delete the two files itself and only check that the wall
        noticed, which left the button that is supposed to delete them never
        actually run by anything.
        """
        with TemporaryDataDir():
            path = file_a_run(KEYBOARD_DEVICE, "tkl", "A", 6, datetime(2026, 8, 30, 12, 0))
            picture = path.with_suffix(".png")
            self.assertTrue(path.exists())
            self.assertTrue(picture.exists())
            window = self._window()
            window._show_page("gallery")
            piece = window.gallery.cards[0].snapshot
            window.gallery.show_detail(piece)
            self.assertEqual(window.gallery.stack.currentIndex(), 1)
            self.assertIn('"total_keystrokes": 6', window.gallery.detail.json_view.toPlainText())
            self.assertIn("2026-08-30", window.gallery.detail.rows["until"].value.text())

            with AnswerTheBox(QMessageBox.ButtonRole.AcceptRole):
                window.gallery.detail._remove()
            self.assertFalse(path.exists())
            self.assertFalse(picture.exists())
            self.assertEqual(window.gallery.cards, [])
            self.assertEqual(window.gallery.stack.currentIndex(), 0)
            window.quitting = True
            window.close()

    def test_cancelling_leaves_the_exhibit_hanging(self) -> None:
        with TemporaryDataDir():
            path = file_a_run(KEYBOARD_DEVICE, "tkl", "A", 6, datetime(2026, 8, 30, 12, 0))
            window = self._window()
            window._show_page("gallery")
            window.gallery.show_detail(window.gallery.cards[0].snapshot)
            with AnswerTheBox(QMessageBox.ButtonRole.RejectRole):
                window.gallery.detail._remove()
            self.assertTrue(path.exists())
            self.assertTrue(path.with_suffix(".png").exists())
            self.assertEqual(len(window.gallery.cards), 1)
            window.quitting = True
            window.close()


    def test_show_file_asks_explorer_for_the_file_not_the_folder(self) -> None:
        """SHOW FILE has to select the file, or it is the FOLDER button twice."""
        with TemporaryDataDir():
            path = file_a_run(KEYBOARD_DEVICE, "tkl", "A", 6, datetime(2026, 8, 30, 12, 0))
            window = self._window()
            window._show_page("gallery")
            window.gallery.show_detail(window.gallery.cards[0].snapshot)

            asked: list[str] = []
            saved = gallery.subprocess.run
            gallery.subprocess.run = lambda command, **kwargs: asked.append(command)
            try:
                window.gallery.detail._show_file()
            finally:
                gallery.subprocess.run = saved

            if sys.platform == "win32":
                self.assertEqual(len(asked), 1)
                # One token, quoted: Explorer reads /select, and the path as a
                # single argument, and a path with a space in it must survive.
                self.assertIn(f'/select,"{path}"', asked[0])
            window.quitting = True
            window.close()


if __name__ == "__main__":
    unittest.main()
