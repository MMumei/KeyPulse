from __future__ import annotations

import hashlib
import os
import unittest
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gamepads import MODEL_ORDER, MODELS
from layouts import LAYOUT_ORDER
from pad_canvas import GamepadCanvas
from storage import DEFAULT_SETTINGS, GAMEPAD_DEVICE, KEYBOARD_DEVICE, SettingsStore, StatsStore
from render import IDLE_CAP
from ui import HALO_LIGHT, KeyboardCanvas, MainWindow, ToggleSwitch, render_snapshot_image


class LightingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_rgb_wave_changes_between_frames(self) -> None:
        canvas = KeyboardCanvas(StatsStore())
        canvas.set_layout("tkl")
        canvas.set_zoom(60)
        canvas.show()
        self.app.processEvents()
        first = canvas.grab().toImage()
        QTest.qWait(180)
        self.app.processEvents()
        second = canvas.grab().toImage()
        first_hash = hashlib.sha256(bytes(first.constBits())).digest()
        second_hash = hashlib.sha256(bytes(second.constBits())).digest()
        self.assertNotEqual(first_hash, second_hash)
        canvas.close()

    def test_first_keystroke_updates_an_initially_empty_heat_map(self) -> None:
        stats = StatsStore()
        canvas = KeyboardCanvas(stats)
        canvas.set_layout("tkl")

        self.assertEqual(canvas._peak(), 0)
        stats.record("A")
        canvas.pulse("A")

        self.assertEqual(canvas._peak(), 1)
        self.assertNotEqual(canvas._heat_color(1).name(), IDLE_CAP.name())
        canvas.close()

    def test_pulse_does_not_restart_animation_while_suspended(self) -> None:
        stats = StatsStore()
        canvas = KeyboardCanvas(stats)
        canvas.show()
        self.app.processEvents()
        canvas.suspend()

        stats.record("A")
        canvas.pulse("A")

        self.assertFalse(canvas._animation.isActive())
        canvas.resume()
        self.assertTrue(canvas._animation.isActive())
        canvas.close()


class LightSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _digest(canvas) -> bytes:
        image = canvas.grab().toImage()
        return hashlib.sha256(bytes(image.constBits())).digest()

    def test_the_light_goes_out_and_comes_back(self) -> None:
        canvas = KeyboardCanvas(StatsStore())
        canvas.set_layout("tkl")
        canvas.set_zoom(60)
        canvas.show()
        self.app.processEvents()
        self.assertTrue(canvas._light_timer.isActive())
        lit = self._digest(canvas)

        canvas.set_lighting(False)
        self.app.processEvents()
        # Nothing is shimmering any more, so nothing asks for a frame...
        self.assertFalse(canvas._light_timer.isActive())
        dark = self._digest(canvas)
        self.assertNotEqual(lit, dark)
        QTest.qWait(180)
        self.app.processEvents()
        self.assertEqual(self._digest(canvas), dark)

        canvas.set_lighting(True)
        self.app.processEvents()
        self.assertTrue(canvas._light_timer.isActive())
        self.assertNotEqual(self._digest(canvas), dark)
        canvas.close()

    def test_a_dark_board_stays_dark_across_a_keystroke(self) -> None:
        stats = StatsStore()
        canvas = KeyboardCanvas(stats)
        canvas.set_layout("tkl")
        canvas.set_zoom(60)
        canvas.set_lighting(False)
        canvas.show()
        self.app.processEvents()
        before = self._digest(canvas)
        stats.record("A")
        canvas.pulse("A")
        self.app.processEvents()
        # The cap still answers -- the press feedback is the app's, not the
        # board's -- but no light timer was started behind it.
        self.assertNotEqual(self._digest(canvas), before)
        self.assertFalse(canvas._light_timer.isActive())
        canvas.close()

    def test_the_underglow_holds_one_colour_while_the_wave_moves(self) -> None:
        """Two layers, two jobs: the wave travels, the halo underneath does not."""
        canvas = KeyboardCanvas(StatsStore())
        canvas.set_layout("tkl")
        canvas.set_zoom(80)

        def strip(phase: float) -> bytes:
            canvas._light_phase = phase
            canvas._wave_cache = ()
            image = QImage(200, 60, QImage.Format.Format_RGB32)
            image.fill(QColor("#ffffff"))
            painter = QPainter(image)
            canvas._draw_light_band(
                painter, QPointF(4, 6), QPointF(196, 6), QPointF(4, 54), QPointF(196, 54)
            )
            painter.end()
            return hashlib.sha256(bytes(image.constBits())).digest()

        blank = QImage(200, 60, QImage.Format.Format_RGB32)
        blank.fill(QColor("#ffffff"))
        blank_hash = hashlib.sha256(bytes(blank.constBits())).digest()
        # Something is painted there...
        self.assertNotEqual(strip(0.0), blank_hash)
        # ...and it is the same something wherever the wave has got to.
        self.assertEqual(strip(0.0), strip(0.37))
        self.assertEqual(strip(0.0), strip(0.74))
        # The colour it holds is the console's own mint, not a hue off the wheel.
        self.assertEqual(HALO_LIGHT.name(), "#33c6ac")
        canvas.close()

    def test_a_dark_pad_shows_its_lamps_unlit(self) -> None:
        canvas = GamepadCanvas(StatsStore(device=GAMEPAD_DEVICE))
        canvas.set_layout("ps")
        canvas.set_zoom(120)
        canvas.show()
        self.app.processEvents()
        lit = self._digest(canvas)
        canvas.set_lighting(False)
        self.app.processEvents()
        self.assertNotEqual(self._digest(canvas), lit)
        canvas.close()

    def test_an_unlit_run_is_archived_unlit(self) -> None:
        stats = StatsStore()
        for _ in range(30):
            stats.record("A")
        moment = datetime(2026, 8, 30, 13, 42)
        lit = render_snapshot_image(stats, "tkl", moment, KEYBOARD_DEVICE, True)
        dark = render_snapshot_image(stats, "tkl", moment, KEYBOARD_DEVICE, False)
        self.assertEqual(lit.size(), dark.size())
        self.assertNotEqual(
            hashlib.sha256(bytes(lit.constBits())).digest(),
            hashlib.sha256(bytes(dark.constBits())).digest(),
        )


class SnapshotImageTests(unittest.TestCase):
    MOMENT = datetime(2026, 8, 30, 13, 42)

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _digest(image) -> bytes:
        return hashlib.sha256(bytes(image.constBits())).digest()

    def test_every_layout_renders_something(self) -> None:
        stats = StatsStore()
        for _ in range(3):
            stats.record("A")
        for layout_id in LAYOUT_ORDER:
            with self.subTest(layout=layout_id):
                image = render_snapshot_image(stats, layout_id, self.MOMENT)
                self.assertGreater(image.width(), 800)
                self.assertGreater(image.height(), 400)
                # The page colour frames the composition...
                self.assertEqual(image.pixelColor(2, 2).name(), "#f3f6f4")
                # ...and something was actually drawn inside it.
                blank = image.copy()
                blank.fill(image.pixelColor(2, 2))
                self.assertNotEqual(self._digest(image), self._digest(blank))

    def test_snapshot_follows_the_counts_on_the_board(self) -> None:
        idle = render_snapshot_image(StatsStore(), "tkl", self.MOMENT)
        busy = StatsStore()
        for _ in range(500):
            busy.record("A")
        used = render_snapshot_image(busy, "tkl", self.MOMENT)
        self.assertEqual(idle.size(), used.size())
        self.assertNotEqual(self._digest(idle), self._digest(used))

    def test_snapshot_size_ignores_the_window(self) -> None:
        # A run filed from a small window must archive as legibly as any other.
        stats = StatsStore()
        stats.record("A")
        first = render_snapshot_image(stats, "tkl", self.MOMENT)
        canvas = KeyboardCanvas(stats)
        canvas.set_layout("tkl")
        canvas.set_zoom(60)
        second = render_snapshot_image(stats, "tkl", self.MOMENT)
        self.assertEqual(first.size(), second.size())
        canvas.close()


class BacklightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_the_lit_gaps_never_touch_a_keycap(self) -> None:
        """The whole reason a wave is affordable: it repaints no caps.

        If the lattice ever overlapped a cap, a lighting frame would paint
        over one without redrawing it, and the board would erode.
        """
        canvas = KeyboardCanvas(StatsStore())
        for layout_id in ("tkl", "full", "60"):
            canvas.set_layout(layout_id)
            canvas.set_zoom(90)
            with self.subTest(layout=layout_id):
                lattice = canvas._light_region
                self.assertFalse(lattice.isEmpty())
                for key in canvas.layout_spec.keys:
                    silhouette = canvas._key_rect_by_id[key.key_id]
                    # The padded rect may clip the lattice; the drawn cap
                    # inside it must not.
                    self.assertFalse(lattice.contains(silhouette.center()))
        canvas.close()

    def test_a_lighting_frame_asks_for_no_caps_and_a_keystroke_does(self) -> None:
        canvas = KeyboardCanvas(StatsStore())
        canvas.set_layout("tkl")
        canvas.show()
        self.app.processEvents()

        class Event:
            def __init__(self, region):
                self._region = region

            def region(self):
                return self._region

        canvas._advance_lighting()
        self.assertIsNone(canvas.caps_to_redraw(Event(canvas._light_region)))
        # ...and reading it resets it, so the next frame is a normal one.
        self.assertIsNotNone(canvas.caps_to_redraw(Event(canvas._light_region)))

        canvas._advance_lighting()
        canvas.damage_cap("A")
        asked = canvas.caps_to_redraw(Event(canvas._light_region))
        self.assertIsNotNone(asked)
        self.assertTrue(asked.intersects(canvas._key_rect_by_id["A"]))
        canvas.close()

    def test_an_expose_during_a_tick_still_puts_the_caps_back(self) -> None:
        """A lighting frame may only skip the caps where the light reaches.

        Swapping the layout or the zoom resizes the canvas and moves it inside
        the scroll area, and Qt merges its own full-widget damage into
        whatever frame comes next. If that frame were taken for a lighting
        tick it would wipe every cap and put nothing back, and no later tick
        would repair it -- the ticks that follow keep clear of the caps.
        """
        canvas = KeyboardCanvas(StatsStore())
        canvas.set_layout("tkl")
        canvas.show()
        self.app.processEvents()

        class Event:
            def __init__(self, region):
                self._region = region

            def region(self):
                return self._region

        whole = QRegion(canvas.rect())
        canvas._advance_lighting()
        asked = canvas.caps_to_redraw(Event(whole))
        self.assertIsNotNone(asked)
        for key_id in ("A", "ESC", "SPACE"):
            self.assertTrue(asked.intersects(canvas._key_rect_by_id[key_id]))
        canvas.close()

    def test_a_layout_swap_under_a_lit_board_keeps_its_keys(self) -> None:
        canvas = KeyboardCanvas(StatsStore())
        canvas.set_zoom(60)
        canvas.show()
        self.app.processEvents()
        canvas._light_timer.stop()

        for layout_id in ("tkl", "60", "full"):
            with self.subTest(layout=layout_id):
                canvas.set_layout(layout_id)
                self.app.processEvents()
                whole = canvas.grab().toImage()
                # A tick left outstanding by the swap, then the full-widget
                # repaint the resize asks for.
                canvas._light_tick = True
                canvas._caps_pending = False
                canvas._cap_damage = QRegion()
                after = canvas.grab().toImage()
                self.assertEqual(
                    hashlib.sha256(bytes(whole.constBits())).digest(),
                    hashlib.sha256(bytes(after.constBits())).digest(),
                )
        canvas.close()

    def test_the_wave_shows_through_the_gaps(self) -> None:
        canvas = KeyboardCanvas(StatsStore())
        canvas.set_layout("60")
        canvas.set_zoom(90)
        canvas.show()
        self.app.processEvents()
        canvas.suspend()
        first = canvas.grab().toImage()
        for _ in range(12):
            canvas._light_phase = (canvas._light_phase + 0.0094) % 1.0
        canvas._wave_cache = ()
        canvas._rim_phase = None
        canvas.redraw_caps()
        self.app.processEvents()
        second = canvas.grab().toImage()
        self.assertNotEqual(
            hashlib.sha256(bytes(first.constBits())).digest(),
            hashlib.sha256(bytes(second.constBits())).digest(),
        )
        canvas.close()


class ZoomCostTests(unittest.TestCase):
    """A wheel turn walks the zoom through a dozen projections and shows one.

    Both devices used to do their most expensive piece of work inside every
    one of those rebuilds -- stroking the backlight for the board, repainting
    the shell for the pad -- and then throw eleven of the twelve away before
    anything drew them. That is what a wheel turn felt like. Both now wait
    for a frame that actually wants them.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _board(self) -> KeyboardCanvas:
        canvas = KeyboardCanvas(StatsStore(device=KEYBOARD_DEVICE))
        canvas.set_layout("full")
        canvas.set_lighting(True)
        canvas.set_zoom(96)
        canvas.resize(canvas.canvas_size)
        return canvas

    def test_a_zoom_leaves_the_costly_work_to_the_frame_that_wants_it(self) -> None:
        board = self._board()
        self.assertIsNone(board._rim_map)
        board.grab()
        self.assertIsNotNone(board._rim_map)
        # ...and the next notch drops it again rather than redrawing it.
        board.set_zoom(104)
        self.assertIsNone(board._rim_map)

        pad = GamepadCanvas(StatsStore(device=GAMEPAD_DEVICE))
        pad.set_layout("xbox")
        pad.set_zoom(120)
        pad.resize(pad.canvas_size)
        self.assertIsNone(pad._backdrop)
        pad.grab()
        self.assertIsNotNone(pad._backdrop)
        pad.set_zoom(128)
        self.assertIsNone(pad._backdrop)

    def test_a_board_mid_gesture_goes_without_the_light_and_pays_it_back(self) -> None:
        board = self._board()
        board.suspend()
        board.grab()
        # Nothing was stroked, and the board knows it owes a frame.
        self.assertIsNone(board._rim_map)
        self.assertTrue(board._rim_owed)
        board.resume()
        self.assertFalse(board._rim_owed)
        board.grab()
        self.assertIsNotNone(board._rim_map)

    def test_an_unlit_board_never_strokes_the_light_at_all(self) -> None:
        board = self._board()
        board.set_lighting(False)
        board.grab()
        self.assertIsNone(board._rim_map)

    def test_the_picture_is_the_same_whenever_the_work_is_done(self) -> None:
        """Deferring it is a saving, not a change: the frames must match."""
        for layout_id in LAYOUT_ORDER:
            for lighting in (True, False):
                shots = []
                for eager in (False, True):
                    canvas = KeyboardCanvas(StatsStore(device=KEYBOARD_DEVICE))
                    canvas.set_layout(layout_id)
                    canvas.set_lighting(lighting)
                    canvas.set_zoom(96)
                    canvas.resize(canvas.canvas_size)
                    if eager:
                        canvas._stroke_rim()
                    canvas.redraw_caps()
                    shots.append(canvas.grab().toImage())
                with self.subTest(layout=layout_id, lighting=lighting):
                    self.assertEqual(shots[0], shots[1])

        for model_id in MODEL_ORDER:
            shots = []
            for eager in (False, True):
                canvas = GamepadCanvas(StatsStore(device=GAMEPAD_DEVICE))
                canvas.set_layout(model_id)
                canvas.set_lighting(True)
                canvas.set_zoom(130)
                canvas.resize(canvas.canvas_size)
                if eager:
                    canvas._backdrop = canvas._paint_backdrop()
                canvas.redraw_caps()
                shots.append(canvas.grab().toImage())
            with self.subTest(model=model_id):
                self.assertEqual(shots[0], shots[1])


class PadLightingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_only_pads_whose_originals_are_lit_carry_lamps(self) -> None:
        lit = {model_id: MODELS[model_id].lights for model_id in MODEL_ORDER}
        # An Xbox button is backlit, a DualSense has its light bar, a Switch
        # Pro has its player slots. A plain wired pad has nothing.
        self.assertEqual(len(lit["xbox"]), 1)
        self.assertEqual(len(lit["ps"]), 2)
        self.assertEqual(len(lit["switch"]), 4)
        self.assertEqual(lit["wired"], ())
        # Only the light bar changes colour; the rest are fixed white.
        self.assertTrue(all(lamp.animated for lamp in lit["ps"]))
        self.assertFalse(any(lamp.animated for lamp in lit["xbox"] + lit["switch"]))
        # One controller paired lights one player slot.
        self.assertEqual(sum(lamp.lit for lamp in lit["switch"]), 1)

    def test_an_unlit_pad_never_asks_for_a_lighting_frame(self) -> None:
        canvas = GamepadCanvas(StatsStore(device=GAMEPAD_DEVICE))
        canvas.show()
        self.app.processEvents()
        for model_id, animated in (("wired", False), ("xbox", False), ("ps", True)):
            canvas.set_layout(model_id)
            with self.subTest(model=model_id):
                self.assertEqual(not canvas._light_region.isEmpty(), animated)
                phase = canvas._light_phase
                canvas._advance_lighting()
                self.assertEqual(canvas._light_phase != phase, animated)
                self.assertEqual(canvas._light_tick, animated)
                canvas._light_tick = False
        canvas.close()


class GamepadCanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_every_model_draws_something(self) -> None:
        stats = StatsStore(device=GAMEPAD_DEVICE)
        stats.record("FACE_DOWN")
        canvas = GamepadCanvas(stats)
        canvas.set_zoom(90)
        for model_id in MODEL_ORDER:
            with self.subTest(model=model_id):
                canvas.set_layout(model_id)
                image = canvas.grab().toImage()
                self.assertGreater(image.width(), 200)
                blank = image.copy()
                blank.fill(image.pixelColor(1, 1))
                self.assertNotEqual(
                    hashlib.sha256(bytes(image.constBits())).digest(),
                    hashlib.sha256(bytes(blank.constBits())).digest(),
                )
        canvas.close()

    def test_a_leaning_stick_repaints_and_a_still_one_does_not(self) -> None:
        canvas = GamepadCanvas(StatsStore(device=GAMEPAD_DEVICE))
        canvas.set_zoom(90)
        canvas.show()
        self.app.processEvents()
        # Hold the halo still, or the shimmer would move the pixels by itself.
        canvas.suspend()
        centred = canvas.grab().toImage()
        canvas.set_axes(1.0, -1.0, 0.0, 0.0)
        self.app.processEvents()
        pushed = canvas.grab().toImage()
        self.assertNotEqual(
            hashlib.sha256(bytes(centred.constBits())).digest(),
            hashlib.sha256(bytes(pushed.constBits())).digest(),
        )
        canvas.set_axes(1.0, -1.0, 0.0, 0.0)
        self.app.processEvents()
        again = canvas.grab().toImage()
        self.assertEqual(
            hashlib.sha256(bytes(pushed.constBits())).digest(),
            hashlib.sha256(bytes(again.constBits())).digest(),
        )
        canvas.close()

    def test_the_pad_snapshot_names_its_own_model(self) -> None:
        stats = StatsStore(device=GAMEPAD_DEVICE)
        for _ in range(40):
            stats.record("FACE_DOWN")
        image = render_snapshot_image(stats, "ps", datetime(2026, 8, 30, 13, 42), GAMEPAD_DEVICE)
        self.assertGreater(image.width(), 600)
        self.assertEqual(image.pixelColor(2, 2).name(), "#f3f6f4")


def fresh_settings() -> SettingsStore:
    """Defaults that never reach the disk, whatever the real settings say."""
    settings = SettingsStore(frozen=True)
    settings.values = DEFAULT_SETTINGS.copy()
    return settings


class ToggleSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_the_whole_switch_takes_a_click(self) -> None:
        """It looks like a 46px pill, so all 46px of it have to answer.

        A plain QCheckBox only accepts clicks inside the indicator its style
        would have drawn, which left the knob -- the obvious place to aim --
        among the two thirds that did nothing.
        """
        switch = ToggleSwitch()
        switch.show()
        self.app.processEvents()
        dead = []
        for x in range(1, switch.width(), 3):
            for y in range(1, switch.height(), 3):
                switch.setChecked(False)
                QTest.mouseClick(switch, Qt.MouseButton.LeftButton, pos=QPoint(x, y))
                if not switch.isChecked():
                    dead.append((x, y))
        self.assertEqual(dead, [])

        # ...and a click on the knob of a switch that is on turns it off again.
        switch.setChecked(True)
        QTest.mouseClick(
            switch, Qt.MouseButton.LeftButton, pos=QPoint(switch.width() - 8, 13)
        )
        self.assertFalse(switch.isChecked())
        switch.close()

    def test_both_switches_in_the_window_answer_at_their_far_edge(self) -> None:
        settings = fresh_settings()
        window = MainWindow(
            StatsStore(device=KEYBOARD_DEVICE), StatsStore(device=GAMEPAD_DEVICE), settings
        )
        window.show()
        self.app.processEvents()
        light = window.light_toggle
        far = QPoint(light.width() - 6, light.height() // 2)
        # The lighting is off out of the box, so the far edge is what has to
        # turn it on -- the switch is 46px wide and all 46 of them count.
        self.assertFalse(light.isChecked())
        QTest.mouseClick(light, Qt.MouseButton.LeftButton, pos=far)
        self.assertTrue(light.isChecked())
        self.assertTrue(window.canvas.lighting)
        # The startup switch is the same widget; only its far edge is checked
        # here, since flipping it for real would write to the registry.
        self.assertTrue(window.startup_toggle.hitButton(far))
        window.quitting = True
        window.close()


class DeviceSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_the_switch_moves_the_whole_window_to_the_other_device(self) -> None:
        settings = fresh_settings()
        if True:
            keyboard = StatsStore(device=KEYBOARD_DEVICE)
            gamepad = StatsStore(device=GAMEPAD_DEVICE)
            window = MainWindow(keyboard, gamepad, settings)

            window.on_key_press("A")
            window.on_pad_press("FACE_DOWN")
            window.on_pad_press("FACE_DOWN")
            # Each device counts on its own, whichever one is on screen.
            self.assertEqual(keyboard.count("A"), 1)
            self.assertEqual(gamepad.count("FACE_DOWN"), 2)
            self.assertEqual(window.total_card.value.text(), "1")
            self.assertEqual(window.favorite_card.caption.text(), "TOP KEY")

            window._device_chosen(GAMEPAD_DEVICE)
            self.assertEqual(window.stack.currentWidget(), window.views[GAMEPAD_DEVICE].scroll)
            self.assertEqual(window.total_card.value.text(), "2")
            self.assertEqual(window.favorite_card.caption.text(), "TOP BUTTON")
            self.assertEqual(window.control_label.text(), "MODEL")
            self.assertEqual(settings.get("device"), GAMEPAD_DEVICE)
            # The size list follows the device, not the other way round.
            models = [window.layout_combo.itemData(i) for i in range(window.layout_combo.count())]
            self.assertEqual(models, list(MODEL_ORDER))

            window.layout_combo.setCurrentIndex(models.index("switch"))
            self.assertEqual(window.pad_canvas.layout_spec.layout_id, "switch")
            self.assertEqual(settings.get("gamepad_model"), "switch")
            # ...and the keyboard is exactly where it was left.
            window._device_chosen(KEYBOARD_DEVICE)
            self.assertEqual(window.control_label.text(), "LAYOUT")
            self.assertEqual(window.total_card.value.text(), "1")
            window.quitting = True
            window.close()

    def test_the_light_switch_belongs_to_the_device_on_screen(self) -> None:
        settings = fresh_settings()
        window = MainWindow(
            StatsStore(device=KEYBOARD_DEVICE), StatsStore(device=GAMEPAD_DEVICE), settings
        )
        # Both devices start unlit, which is what a first start looks like.
        self.assertFalse(window.light_toggle.isChecked())

        window.light_toggle.setChecked(True)
        self.assertTrue(window.canvas.lighting)
        self.assertTrue(settings.get("lighting"))
        # The pad kept its own, and the switch follows the device across.
        self.assertFalse(window.pad_canvas.lighting)
        window._device_chosen(GAMEPAD_DEVICE)
        self.assertFalse(window.light_toggle.isChecked())
        window.light_toggle.setChecked(True)
        self.assertTrue(window.pad_canvas.lighting)
        self.assertTrue(settings.get("gamepad_lighting"))

        window._device_chosen(KEYBOARD_DEVICE)
        self.assertTrue(window.light_toggle.isChecked())
        window.light_toggle.setChecked(False)
        self.assertFalse(window.canvas.lighting)
        self.assertFalse(settings.get("lighting"))
        window.quitting = True
        window.close()

    def test_a_missing_pad_only_shows_on_the_pad(self) -> None:
        settings = fresh_settings()
        if True:
            window = MainWindow(
                StatsStore(device=KEYBOARD_DEVICE), StatsStore(device=GAMEPAD_DEVICE), settings
            )
            window.on_pad_connection(-1)
            self.assertEqual(window.status_text.text(), "●  LIVE")
            window._device_chosen(GAMEPAD_DEVICE)
            self.assertIn("NO GAMEPAD", window.status_text.text())
            # A pad that is plugged in is read exactly as the keyboard is, so
            # the header says the same word for both; which slot it landed in
            # is a detail for the tooltip.
            window.on_pad_connection(0)
            self.assertEqual(window.status_text.text(), "●  LIVE")
            self.assertIn("1", window.status_text.toolTip())
            window.quitting = True
            window.close()


if __name__ == "__main__":
    unittest.main()
