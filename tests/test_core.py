from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import storage
from gamepad_hook import BUTTON_BITS, XINPUT_GAMEPAD, GamepadHook, deaden
import pad_reference as REF
from gamepads import MODEL_ORDER, MODELS, callout_box
from hook import LLKHF_EXTENDED, normalize_key
from layouts import LAYOUTS, LAYOUT_ORDER

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath


def _rect(box) -> QPainterPath:
    """A chip as a path, so it can be asked what it lands on."""
    x, y, width, height = box
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, width, height), height * 0.5, height * 0.5)
    return path


def _path(ring) -> QPainterPath:
    """A traced footprint as a path, so two of them can be asked to intersect."""
    path = QPainterPath()
    path.moveTo(QPointF(*ring[0]))
    for point in ring[1:]:
        path.lineTo(QPointF(*point))
    path.closeSubpath()
    return path


class LayoutTests(unittest.TestCase):
    def test_the_boards_are_the_four_in_the_reference_picture(self) -> None:
        """Four shapes, largest first, at the sizes they are named by.

        The picture calls them full size, TKL / 87 keys, 60% and 75%; the list
        offers them in size order instead, since that is what the reader is
        picking from. A board that has drifted off its key count is no longer
        the one it is named after, which is the other failure this catches.
        """
        self.assertEqual(LAYOUT_ORDER, ("full", "tkl", "75", "60"))
        self.assertEqual(set(LAYOUTS), set(LAYOUT_ORDER))
        counts = {layout_id: len(LAYOUTS[layout_id].keys) for layout_id in LAYOUT_ORDER}
        self.assertEqual(counts, {"full": 104, "tkl": 87, "60": 61, "75": 83})
        # ...and the list runs down those counts rather than around them.
        self.assertEqual(
            [counts[layout_id] for layout_id in LAYOUT_ORDER],
            sorted(counts.values(), reverse=True),
        )
        names = [LAYOUTS[layout_id].name for layout_id in LAYOUT_ORDER]
        self.assertEqual(names, ["Full Size", "TKL 87", "75%", "60%"])

    def test_the_60_percent_board_is_the_letters_and_nothing_around_them(self) -> None:
        keys = {key.key_id for key in LAYOUTS["60"].keys}
        self.assertEqual(keys & {"F1", "F12", "UP", "DOWN", "INSERT", "NUM0", "PRTSC"}, set())
        self.assertLessEqual({"GRAVE", "BACKSPACE", "ENTER", "SPACE", "RCTRL"}, keys)

    def test_the_75_percent_board_folds_its_arrows_into_the_last_two_rows(self) -> None:
        """The picture's 75%: one navigation key per row down the right edge.

        Its right-hand column runs from the number row to the Shift row, the
        up arrow sits at the end of the Shift row with that column still to
        its right, and left, down and right close the bottom row -- so the
        board keeps a straight right edge all the way down instead of the
        stepped one a board with a nav block has.
        """
        keys = {key.key_id: key for key in LAYOUTS["75"].keys}
        column = keys["HOME"].x
        for key_id, row in (("HOME", 1), ("PAGEUP", 2), ("PAGEDOWN", 3), ("END", 4)):
            with self.subTest(key=key_id):
                self.assertAlmostEqual(keys[key_id].x, column, places=6)
                self.assertAlmostEqual(keys[key_id].y, 1.14 * row, places=6)
        # The up arrow shares the Shift row, one slot left of the column...
        self.assertAlmostEqual(keys["UP"].y, keys["END"].y, places=6)
        self.assertLess(keys["UP"].x, column)
        # ...and the other three finish the row below, right out to the edge.
        self.assertAlmostEqual(keys["RIGHT"].x, column, places=6)
        self.assertAlmostEqual(keys["DOWN"].x, keys["UP"].x, places=6)
        self.assertLess(keys["LEFT"].x, keys["DOWN"].x)
        for key_id in ("LEFT", "DOWN", "RIGHT"):
            self.assertAlmostEqual(keys[key_id].y, 1.14 * 5, places=6)
        # A 75% has a function row and no numpad, and no Menu key to spare.
        self.assertIn("F12", keys)
        self.assertNotIn("NUM0", keys)
        self.assertNotIn("MENU", keys)

    def test_layout_keys_are_unique_and_do_not_overlap(self) -> None:
        for layout_name, layout in LAYOUTS.items():
            with self.subTest(layout=layout_name):
                ids = [key.key_id for key in layout.keys]
                self.assertEqual(len(ids), len(set(ids)))
                for index, first in enumerate(layout.keys):
                    self.assertLessEqual(first.x + first.width, layout.width + 0.001)
                    self.assertLessEqual(first.y + first.height, layout.height + 0.001)
                    for second in layout.keys[index + 1 :]:
                        overlap = (
                            first.x < second.x + second.width - 1e-6
                            and second.x < first.x + first.width - 1e-6
                            and first.y < second.y + second.height - 1e-6
                            and second.y < first.y + first.height - 1e-6
                        )
                        self.assertFalse(overlap, f"{layout_name}: {first.key_id}/{second.key_id}")


DPAD_ARMS = {"DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"}


class PadModelTests(unittest.TestCase):
    def test_the_pads_are_the_four_in_the_reference_picture(self) -> None:
        """Xbox, DualSense, Switch Pro, and a plain wired pad -- in that order."""
        self.assertEqual(MODEL_ORDER, ("xbox", "ps", "switch", "wired"))
        self.assertEqual(set(MODELS), set(MODEL_ORDER))
        names = [MODELS[model_id].name for model_id in MODEL_ORDER]
        self.assertEqual(names, ["Xbox", "PlayStation", "Switch Pro", "Wired"])

    def test_the_wired_pad_is_not_the_xbox_pad_drawn_twice(self) -> None:
        """The two share an arrangement on purpose, and still read apart.

        A pad Windows sees as XInput is an Xbox pad as far as this screen
        goes -- same sticks, same D-pad, same four faces -- so the picture's
        fourth pad keeps all of that. What it does not keep is the marks the
        first-party pad carries, and it brings marks of its own instead: a
        lead out of the top and the turbo and mode pair, against the share
        button, the lit ring and the pairing pinhole. Drop those and the
        gallery is offering the same drawing under two names.
        """
        xbox, wired = MODELS["xbox"], MODELS["wired"]
        ids = {model: {e.element_id for e in model.elements} for model in (xbox, wired)}
        self.assertEqual(ids[xbox] - ids[wired], {"SHARE"})
        self.assertEqual(ids[wired] - ids[xbox], {"TURBO", "MODE"})
        self.assertTrue(wired.cable)
        self.assertFalse(xbox.cable)
        self.assertIsNone(wired.led)
        self.assertIsNotNone(xbox.led)
        self.assertEqual(wired.lights, ())
        # None of the three is anything XInput reports, so none is counted.
        for model in (xbox, wired):
            for element in model.elements:
                if element.element_id in ("SHARE", "TURBO", "MODE"):
                    self.assertFalse(element.counted, element.element_id)
        # The lead rises into the notch between the shoulders, which is empty
        # on every model -- so carrying one costs no height and switching
        # models never resizes the picture under the pointer.
        sizes = {(MODELS[m].width, MODELS[m].height) for m in MODEL_ORDER}
        self.assertEqual(len(sizes), 1)

    def test_each_pad_puts_the_hands_where_its_own_picture_does(self) -> None:
        """The one thing a model changes: which control stands where.

        A DualSense is the odd one out -- its two sticks are level with each
        other at the bottom and the D-pad takes the corner an Xbox pad keeps
        its left stick in. The other three share the Xbox arrangement, stick
        high on the left and D-pad below it.
        """
        def where(model_id: str, element_id: str) -> tuple[float, float]:
            element = next(
                e for e in MODELS[model_id].elements if e.element_id == element_id
            )
            return element.x, element.y

        for model_id in ("xbox", "switch", "wired"):
            with self.subTest(model=model_id):
                stick_x, stick_y = where(model_id, "LS")
                pad_x, pad_y = where(model_id, "DPAD")
                self.assertLess(stick_y, pad_y)          # stick above the pad
                self.assertLess(stick_x, REF.AXIS)       # both on the left
                self.assertLess(pad_x, REF.AXIS)

        left_x, left_y = where("ps", "LS")
        right_x, right_y = where("ps", "RS")
        pad_x, pad_y = where("ps", "DPAD")
        # Sides by side, mirrored about the pad's own centre line...
        self.assertAlmostEqual(left_y, right_y, places=4)
        self.assertAlmostEqual(left_x + right_x, REF.AXIS * 2, places=4)
        # ...with the D-pad up where the other pads keep the left stick...
        self.assertLess(pad_y, left_y)
        # ...and the PS button on the floor between the two sticks.
        guide_x, guide_y = where("ps", "GUIDE")
        self.assertAlmostEqual(guide_x, REF.AXIS, places=4)
        self.assertGreater(guide_y, pad_y)
        self.assertLess(left_x, guide_x)
        self.assertLess(guide_x, right_x)

    @staticmethod
    def _within(point, ring) -> bool:
        """Ray casting: is this point inside the shell silhouette?"""
        x, y = point
        inside = False
        for index, (ax, ay) in enumerate(ring):
            bx, by = ring[(index + 1) % len(ring)]
            if (ay > y) != (by > y):
                crossing = ax + (y - ay) / (by - ay) * (bx - ax)
                if crossing > x:
                    inside = not inside
        return inside

    def test_elements_are_unique_and_stand_on_the_shell(self) -> None:
        """Nothing floats beside the pad.

        A bumper hanging half off the top edge, or a trigger out in the white
        with nothing under it, is the thing that made these look wrong; every
        footprint has to land inside the silhouette.
        """
        for model_id in MODEL_ORDER:
            model = MODELS[model_id]
            with self.subTest(model=model_id):
                ids = [element.element_id for element in model.elements]
                self.assertEqual(len(ids), len(set(ids)))
                for element in model.elements:
                    for point in element.outline:
                        self.assertTrue(
                            self._within(point, model.outline),
                            f"{model_id}: {element.element_id} hangs off the shell",
                        )
                for lamp in model.lights:
                    for point in lamp.outline:
                        self.assertTrue(self._within(point, model.outline), lamp.light_id)

    def test_nothing_standing_on_the_shell_runs_into_anything_else(self) -> None:
        """No two controls share any ground.

        The footprints here are traced off the reference picture rather than
        laid out on a grid, so the bounding boxes of two of them overlap all
        the time -- a bumper band sweeps in under the trigger housing above
        it without the two ever touching. What has to hold is the thing the
        boxes were standing in for: the outlines themselves stay clear of
        each other.
        """
        for model_id in MODEL_ORDER:
            standing = [
                element for element in MODELS[model_id].elements
                if element.kind not in ("arm", "cross")
            ]
            paths = {e.element_id: _path(e.outline) for e in standing}
            with self.subTest(model=model_id):
                for index, first in enumerate(standing):
                    for second in standing[index + 1 :]:
                        self.assertFalse(
                            paths[first.element_id].intersects(paths[second.element_id]),
                            f"{model_id}: {first.element_id}/{second.element_id}",
                        )

    def test_each_d_pad_direction_sits_inside_its_own_cross(self) -> None:
        """The four directions are regions of one moulding, not four caps.

        A D-pad is a single cross with no seam to stand a separate cap on, so
        the arms are never drawn on their own: the cross paints each limb in
        the colour that limb's own count earns, clipped to its own outline.
        That only works while every arm is a patch of the cross it belongs to.
        """
        for model_id in MODEL_ORDER:
            elements = MODELS[model_id].elements
            cross = [e for e in elements if e.kind == "cross"]
            arms = [e for e in elements if e.kind == "arm"]
            with self.subTest(model=model_id):
                self.assertEqual(len(cross), 1)
                self.assertEqual({a.element_id for a in arms}, DPAD_ARMS)
                for arm in arms:
                    self.assertTrue(
                        self._within((arm.x, arm.y), cross[0].outline),
                        f"{model_id}: {arm.element_id} is not on the cross",
                    )

    def test_every_model_shows_every_button_xinput_reports(self) -> None:
        reported = {name for _, name in BUTTON_BITS} | {"LT", "RT"}
        for model_id in MODEL_ORDER:
            shown = {
                element.element_id for element in MODELS[model_id].elements if element.counted
            }
            with self.subTest(model=model_id):
                self.assertEqual(reported - shown, set())

    def test_every_counted_element_is_named(self) -> None:
        """A count still has to be able to say which button it belongs to.

        The pad draws no legends at the moment, but the summary cards and the
        archived snapshots read these names, so a counted element without one
        would report a number with nothing attached to it.
        """
        for model_id in MODEL_ORDER:
            for element in MODELS[model_id].elements:
                if not element.counted:
                    continue
                with self.subTest(model=model_id, element=element.element_id):
                    self.assertTrue(element.label)

    def test_the_traced_shapes_arrive_at_the_models_untouched(self) -> None:
        """Every model carries the reference silhouette, exactly.

        This is the whole point of ``pad_reference``: the shell, the shoulder
        and the paddle on it are copies of the picture rather than impressions
        of one, so they must reach the models with nothing done to them on the
        way but the shift that carries the model to the origin.
        """
        for model_id in MODEL_ORDER:
            model = MODELS[model_id]
            for name, drawn, traced in (
                ("outline", model.outline, REF.BODY),
                ("shoulder", model.shoulder, REF.SHOULDER),
                ("paddle", model.paddles[0], REF.PADDLE),
                ("panel", model.panels[0], REF.PANEL),
            ):
                with self.subTest(model=model_id, shape=name):
                    self.assertEqual(len(drawn), len(traced))
                    dx = drawn[0][0] - traced[0][0]
                    dy = drawn[0][1] - traced[0][1]
                    for point, source in zip(drawn, traced):
                        self.assertAlmostEqual(point[0] - source[0], dx, places=6)
                        self.assertAlmostEqual(point[1] - source[1], dy, places=6)

    def test_the_shoulder_is_mirrored_and_so_is_everything_paired(self) -> None:
        """The pad is symmetric about the line the picture is symmetric about.

        The reference was drawn by hand and its halves differ by a couple of
        pixels; the trace averages that out, and every pair placed here has to
        keep the agreement rather than re-introduce the wobble.
        """
        model = MODELS["xbox"]
        axis = REF.AXIS + (model.outline[0][0] - REF.BODY[0][0])
        by_id = {element.element_id: element for element in model.elements}
        for left, right in (("LT", "RT"), ("LB", "RB"), ("BACK", "START")):
            with self.subTest(pair=f"{left}/{right}"):
                first, second = by_id[left], by_id[right]
                self.assertAlmostEqual(first.x + second.x, axis * 2, places=4)
                self.assertAlmostEqual(first.y, second.y, places=4)
                self.assertAlmostEqual(first.width, second.width, places=4)
        # The right paddle is the left one reflected, point for point.
        for left, right in zip(model.paddles[0], model.paddles[1]):
            self.assertAlmostEqual(left[0] + right[0], axis * 2, places=4)
            self.assertAlmostEqual(left[1], right[1], places=4)

    def test_only_the_four_readout_bars_carry_a_number(self) -> None:
        """The picture prints a count inside the triggers and bumpers, and
        inside nothing else. Every other button is bare in the picture and
        bare here too -- its count is hung beside it instead."""
        for model_id in MODEL_ORDER:
            with self.subTest(model=model_id):
                showing = {
                    element.element_id
                    for element in MODELS[model_id].elements
                    if element.shows_count
                }
                self.assertEqual(showing, {"LT", "RT", "LB", "RB"})

    def test_the_only_count_a_pad_keeps_to_itself_is_the_guide_button(self) -> None:
        """A count nothing shows is a count nobody has -- with one exception.

        Every counted control has to put its number somewhere: the four bars
        print theirs inside themselves and the rest hang theirs off a leader.
        The guide button is the one the reference picture leaves unmarked, so
        it is left unmarked here; it is also the one button on the pad nobody
        presses to play. Anything else counting in silence is a mistake, and
        so is a chip on something that is never reported.
        """
        for model_id in MODEL_ORDER:
            with self.subTest(model=model_id):
                silent = set()
                for element in MODELS[model_id].elements:
                    if not element.counted:
                        self.assertIsNone(element.callout, element.element_id)
                    elif not (element.shows_count or element.callout is not None):
                        silent.add(element.element_id)
                self.assertEqual(silent, {"GUIDE"}, model_id)

    def test_no_count_is_written_over_anything(self) -> None:
        """The chips stand in bare shell, and share none of it.

        Where each one goes was measured by eye against the reference
        picture, which is exactly the kind of thing that stays right until
        somebody moves a button. A chip is as wide as the number on it, so
        the check is made at the width a long count needs rather than at
        today's -- a pad played for a month writes 34.9K where a new one
        writes 12.
        """
        long_count = 0.62      # what five characters take, in pad units
        height = 0.22
        for model_id in MODEL_ORDER:
            model = MODELS[model_id]
            chips = {
                element.element_id: callout_box(element, long_count, height)
                for element in model.elements
                if element.callout is not None
            }
            with self.subTest(model=model_id):
                for element in model.elements:
                    footprint = _path(element.outline)
                    for owner, box in chips.items():
                        if owner == element.element_id or element.kind in ("cross", "arm"):
                            continue
                        self.assertFalse(
                            footprint.intersects(_rect(box)),
                            f"{model_id}: {owner} is written over {element.element_id}",
                        )
                names = sorted(chips)
                for index, first in enumerate(names):
                    for second in names[index + 1 :]:
                        self.assertFalse(
                            _rect(chips[first]).intersects(_rect(chips[second])),
                            f"{model_id}: {first} and {second} are written on each other",
                        )

    def test_every_chip_is_on_the_pad_it_belongs_to(self) -> None:
        """A number floating in the white beside the shell reads as a caption
        for the whole pad rather than for the button it came off."""
        for model_id in MODEL_ORDER:
            model = MODELS[model_id]
            with self.subTest(model=model_id):
                for element in model.elements:
                    box = callout_box(element, 0.62, 0.22)
                    if box is None:
                        continue
                    x, y, width, height = box
                    self.assertTrue(
                        self._within((x + width * 0.5, y + height * 0.5), model.outline),
                        f"{model_id}: {element.element_id} writes off the shell",
                    )

    def test_each_stick_is_three_circles_that_sit_low_in_its_own_well(self) -> None:
        """A stick points at the viewer, so its cap projects below its well.

        The three circles never share a centre -- that offset is the only
        place the picture admits to having a camera position at all -- and the
        cap has to stay inside the mouth of the well it stands in.
        """
        for model_id in MODEL_ORDER:
            for element in MODELS[model_id].elements:
                if element.kind != "stick":
                    continue
                with self.subTest(model=model_id, stick=element.element_id):
                    well, flange, cap = element.rings
                    self.assertGreater(flange[1], well[1])
                    self.assertGreater(cap[1], flange[1])
                    self.assertGreater(well[2], flange[2])
                    self.assertGreater(flange[2], cap[2])
                    self.assertLess(cap[1] + cap[3], well[1] + well[3] + 1e-9)


class GamepadHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pressed: list[str] = []
        self.released: list[str] = []
        self.hook = GamepadHook(self.pressed.append, self.released.append)

    def test_dead_zone_is_taken_out_of_a_thumbstick(self) -> None:
        self.assertEqual(deaden(4000, 7849), 0.0)
        self.assertEqual(deaden(-4000, 7849), 0.0)
        self.assertAlmostEqual(deaden(32767, 7849), 1.0)
        self.assertAlmostEqual(deaden(-32767, 7849), -1.0)
        self.assertGreater(deaden(20000, 7849), 0.0)

    def test_only_edges_are_reported(self) -> None:
        pad = XINPUT_GAMEPAD()
        pad.wButtons = 0x1000 | 0x0100          # A and the left bumper
        self.hook._apply(pad)
        self.assertEqual(sorted(self.pressed), ["FACE_DOWN", "LB"])
        self.hook._apply(pad)                   # still held: still one press
        self.assertEqual(sorted(self.pressed), ["FACE_DOWN", "LB"])
        pad.wButtons = 0x0100
        self.hook._apply(pad)
        self.assertEqual(self.released, ["FACE_DOWN"])

    def test_a_trigger_takes_a_firmer_pull_than_it_takes_to_stay_down(self) -> None:
        pad = XINPUT_GAMEPAD()
        pad.bRightTrigger = 30                  # past release, short of press
        self.hook._apply(pad)
        self.assertEqual(self.pressed, [])
        pad.bRightTrigger = 200
        self.hook._apply(pad)
        self.assertEqual(self.pressed, ["RT"])
        pad.bRightTrigger = 30                  # eased off, but still held
        self.hook._apply(pad)
        self.assertEqual(self.released, [])
        pad.bRightTrigger = 0
        self.hook._apply(pad)
        self.assertEqual(self.released, ["RT"])

    def test_a_pad_unplugged_mid_press_releases_what_it_held(self) -> None:
        pad = XINPUT_GAMEPAD()
        pad.wButtons = 0x8000
        self.hook._apply(pad)
        self.hook._release_all()
        self.assertEqual(self.released, ["FACE_UP"])

    def test_a_resting_stick_is_only_reported_once(self) -> None:
        seen: list[tuple[float, float, float, float]] = []
        hook = GamepadHook(lambda _: None, lambda _: None, lambda *axes: seen.append(axes))
        pad = XINPUT_GAMEPAD()
        pad.sThumbLX = 3000                     # inside the dead zone
        hook._apply(pad)
        hook._apply(pad)
        self.assertEqual(seen, [])
        pad.sThumbLX = 30000
        hook._apply(pad)
        self.assertEqual(len(seen), 1)
        self.assertGreater(seen[0][0], 0.8)


class HookMappingTests(unittest.TestCase):
    def test_common_keys(self) -> None:
        self.assertEqual(normalize_key(0x41, 0x1E, 0), "A")
        self.assertEqual(normalize_key(0x70, 0x3B, 0), "F1")
        self.assertEqual(normalize_key(0x0D, 0x1C, 0), "ENTER")
        self.assertEqual(normalize_key(0x0D, 0x1C, LLKHF_EXTENDED), "NUMENTER")
        self.assertEqual(normalize_key(0x10, 0x36, 0), "RSHIFT")
        self.assertEqual(normalize_key(0x11, 0x1D, LLKHF_EXTENDED), "RCTRL")


class TemporaryDataDir:
    """Point storage at a scratch folder for the length of a test."""

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


class SettingsTests(unittest.TestCase):
    def test_the_first_start_is_the_only_one_that_decides_anything(self) -> None:
        """What KeyPulse is out of the box, and how long it gets to say so.

        The lighting starts off and travels in the file like any other
        setting. Starting with Windows is not in the file at all -- it is a
        registry entry -- so `first_run` is what keeps that decision to the
        one start it belongs to: the file is written there and then, and a
        user who switches it off afterwards does not find it back on.
        """
        with TemporaryDataDir():
            settings = storage.SettingsStore()
            self.assertTrue(settings.first_run)
            self.assertFalse(settings.get("lighting"))
            self.assertFalse(settings.get("gamepad_lighting"))
            self.assertEqual(settings.get("device"), storage.KEYBOARD_DEVICE)

            settings.save()
            self.assertFalse(storage.SettingsStore().first_run)

    def test_a_frozen_store_never_reaches_the_file(self) -> None:
        with TemporaryDataDir():
            frozen = storage.SettingsStore(frozen=True)
            frozen.set("zoom", 200)
            self.assertEqual(frozen.get("zoom"), 200)
            self.assertFalse(storage.SETTINGS_PATH.exists())


class StorageTests(unittest.TestCase):
    def test_counts_round_trip(self) -> None:
        with TemporaryDataDir():
            stats = storage.StatsStore()
            stats.record("A")
            stats.record("A")
            stats.record("ENTER")
            stats.save()
            loaded = storage.StatsStore.load()
            self.assertEqual(loaded.total, 3)
            self.assertEqual(loaded.count("A"), 2)
            self.assertEqual(loaded.count("ENTER"), 1)
            payload = json.loads(storage.STATS_PATH.read_text(encoding="utf-8"))
            self.assertIn("privacy", payload)

    def test_archive_then_reset(self) -> None:
        with TemporaryDataDir() as directory:
            stats = storage.StatsStore()
            for _ in range(5):
                stats.record("A")
            stats.record("ENTER")

            path = stats.archive({"ENTER": "Enter"})
            # Each device files into its own folder under snapshots/.
            self.assertEqual(
                path.parent, directory / storage.SNAPSHOT_DIR_NAME / "keyboard"
            )
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["total_keystrokes"], 6)
            self.assertEqual(snapshot["distinct_keys"], 2)
            self.assertEqual(snapshot["keys"]["A"], 5)
            # Busiest key first, and key ids carry their on-screen label.
            self.assertEqual(snapshot["ranking"][0], {"key": "A", "label": "A", "count": 5})
            self.assertEqual(snapshot["ranking"][1]["label"], "Enter")

            stats.reset()
            self.assertEqual(stats.total, 0)
            self.assertEqual(stats.count("A"), 0)
            self.assertEqual(stats.today_total, 0)
            self.assertIsNone(stats.favorite)
            self.assertEqual(storage.StatsStore.load().total, 0)
            # The archive outlives the reset that produced it.
            self.assertTrue(path.exists())

            # A second reset in the same second must not overwrite the first.
            stats.record("B")
            self.assertNotEqual(stats.archive().name, path.name)


class DeviceStatsTests(unittest.TestCase):
    def test_each_device_keeps_its_own_counts_in_one_file(self) -> None:
        with TemporaryDataDir():
            keyboard = storage.StatsStore.load(storage.KEYBOARD_DEVICE)
            gamepad = storage.StatsStore.load(storage.GAMEPAD_DEVICE)
            keyboard.record("A")
            keyboard.record("A")
            gamepad.record("FACE_DOWN")
            # Both write the same file, so neither may take the other with it.
            keyboard.save()
            gamepad.save()
            keyboard.save(force=True)

            self.assertEqual(storage.StatsStore.load().count("A"), 2)
            reloaded = storage.StatsStore.load(storage.GAMEPAD_DEVICE)
            self.assertEqual(reloaded.count("FACE_DOWN"), 1)
            self.assertEqual(reloaded.total, 1)
            self.assertEqual(reloaded.count("A"), 0)

    def test_a_file_from_before_the_split_still_loads(self) -> None:
        with TemporaryDataDir():
            storage.STATS_PATH.write_text(
                json.dumps({"version": 1, "total_keystrokes": 7, "keys": {"A": 7}}),
                encoding="utf-8",
            )
            self.assertEqual(storage.StatsStore.load().count("A"), 7)
            self.assertEqual(storage.StatsStore.load(storage.GAMEPAD_DEVICE).total, 0)

    def test_a_pad_archive_does_not_collide_with_a_keyboard_one(self) -> None:
        with TemporaryDataDir():
            moment = datetime(2026, 8, 30, 13, 42, 5)
            keyboard = storage.StatsStore(device=storage.KEYBOARD_DEVICE)
            keyboard.record("A")
            gamepad = storage.StatsStore(device=storage.GAMEPAD_DEVICE)
            gamepad.record("FACE_DOWN")
            first = keyboard.archive({}, moment)
            second = gamepad.archive({"FACE_DOWN": "A"}, moment)
            self.assertNotEqual(first.name, second.name)
            self.assertIn("gamepad", second.name)
            payload = json.loads(second.read_text(encoding="utf-8"))
            self.assertEqual(payload["device"], storage.GAMEPAD_DEVICE)
            self.assertEqual(payload["ranking"][0]["label"], "A")


class OrphanedArchiveTests(unittest.TestCase):
    """Runs filed while KeyPulse kept its files somewhere else still count.

    The folder moved once, and the gallery went blank with it: the pictures
    were on disk the whole time, just not where the wall was looking. These
    cover the way back.
    """

    def test_runs_left_in_an_older_folder_are_brought_home(self) -> None:
        with TemporaryDataDir() as home:
            with tempfile.TemporaryDirectory() as raw:
                older = Path(raw) / storage.SNAPSHOT_DIR_NAME
                older.mkdir(parents=True)
                run = older / "keypulse-2026-08-30_194607.json"
                run.write_text(
                    json.dumps({"kind": "reset_snapshot", "total_keystrokes": 12}),
                    encoding="utf-8",
                )
                run.with_suffix(".png").write_bytes(b"not really a picture")
                # Anything that is not a run KeyPulse filed stays where it is.
                (older / "keypulse-notes.json").write_text("{}", encoding="utf-8")
                (older / "Test.json").write_text(
                    json.dumps({"kind": "reset_snapshot"}), encoding="utf-8"
                )

                adopted = storage.adopt_orphaned_snapshots([Path(raw)])
                self.assertEqual([path.name for path in adopted], [run.name])
                # An archive that names no device was filed by the keyboard,
                # since it is the only device the build that wrote it counted.
                archive = home / storage.SNAPSHOT_DIR_NAME
                brought = archive / "keyboard" / run.name
                self.assertTrue(brought.exists())
                self.assertTrue(brought.with_suffix(".png").exists())
                self.assertFalse((archive / "keyboard" / "Test.json").exists())
                # The original is copied, never moved out from under whoever
                # else might still be reading it.
                self.assertTrue(run.exists())

                # Running again adopts nothing and overwrites nothing.
                brought.write_text("edited", encoding="utf-8")
                self.assertEqual(storage.adopt_orphaned_snapshots([Path(raw)]), [])
                self.assertEqual(brought.read_text(encoding="utf-8"), "edited")

    def test_the_folder_in_use_is_never_searched_as_an_older_one(self) -> None:
        with TemporaryDataDir() as home:
            self.assertNotIn(home.resolve(), storage.legacy_data_dirs())
            # ...and every candidate is absolute, so none of them can follow
            # the working directory around the way the first ones did.
            for folder in storage.legacy_data_dirs():
                self.assertTrue(folder.is_absolute())

    def test_deleting_a_run_deletes_the_copy_an_older_folder_holds(self) -> None:
        """Taking an exhibit down has to take it down for good.

        Every start copies runs out of the folders older builds used, so a run
        the wall shows can have a twin sitting in one of them. Deleting the
        copy the wall happened to read and leaving the twin is not a deletion:
        the next start adopts the twin straight back and the exhibit the user
        deleted is hanging there again.
        """
        with TemporaryDataDir() as home:
            with tempfile.TemporaryDirectory() as raw:
                older = Path(raw)
                name = "keypulse-2026-08-30_194607"
                # One in the folder the current build writes, one lying loose
                # in the archive the way every build before the device folders
                # wrote: a deletion has to reach both.
                live_folder = home / storage.SNAPSHOT_DIR_NAME / "keyboard"
                loose_folder = older / storage.SNAPSHOT_DIR_NAME
                for folder in (live_folder, loose_folder):
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / f"{name}.json").write_text(
                        json.dumps({"kind": "reset_snapshot", "total_keystrokes": 9}),
                        encoding="utf-8",
                    )
                    (folder / f"{name}.png").write_bytes(b"a picture")

                saved = storage._home_candidates
                storage._home_candidates = lambda: [home, older]
                try:
                    live = live_folder / f"{name}.json"
                    self.assertEqual(storage.remove_snapshot(live), [])
                    for folder in (live_folder, loose_folder):
                        for suffix in (".json", ".png"):
                            leftover = folder / f"{name}{suffix}"
                            self.assertFalse(leftover.exists(), leftover)
                    # ...so there is nothing left for the next start to adopt.
                    self.assertEqual(storage.adopt_orphaned_snapshots([older]), [])
                    # Deleting one that is already gone is not a failure.
                    self.assertEqual(storage.remove_snapshot(live), [])
                finally:
                    storage._home_candidates = saved

    def test_the_home_is_the_folder_the_program_sits_in(self) -> None:
        """Everything lands beside KeyPulse.exe, not in a folder of its own.

        An early build filed the counts and the whole archive into D:/KeyPulse
        whatever machine it was run on and wherever the program had been put,
        which is a folder nobody handed a copy of KeyPulse would think to look
        in -- and one that does not go away when the program does.
        """
        self.assertEqual(storage._choose_home(), storage._program_dir())
        self.assertTrue(storage._choose_home().is_absolute())
        self.assertEqual(storage._choose_home(), storage._choose_home())
        # ...and the folder it used to file into is still searched, so an
        # upgrade finds what the old build left behind there.
        self.assertIn(Path("D:/") / storage.APP_NAME, storage._home_candidates())

    def test_the_counts_come_home_from_an_older_folder_too(self) -> None:
        """A run's files can be copied one by one. stats.json cannot.

        It is one live file, so there is nothing to merge and only one
        question: which copy was written last. Bringing that one across is
        what stops the first start on a new build looking like a wipe.
        """
        with TemporaryDataDir() as home:
            with tempfile.TemporaryDirectory() as raw:
                older = Path(raw)
                saved = storage._home_candidates
                storage._home_candidates = lambda: [home, older]
                try:
                    (older / "stats.json").write_text(
                        json.dumps({"total_keystrokes": 4419}), encoding="utf-8"
                    )
                    self.assertEqual(
                        [path.name for path in storage.adopt_orphaned_state()], ["stats.json"]
                    )
                    self.assertEqual(storage.StatsStore.load().total, 0)
                    brought = json.loads(storage.STATS_PATH.read_text(encoding="utf-8"))
                    self.assertEqual(brought["total_keystrokes"], 4419)

                    # What is home already and newer stays: counting since the
                    # move is not thrown away by the folder it moved out of.
                    stats = storage.StatsStore()
                    stats.record("A")
                    stats.save()
                    self.assertEqual(storage.adopt_orphaned_state(), [])
                    self.assertEqual(storage.StatsStore.load().count("A"), 1)
                finally:
                    storage._home_candidates = saved


class DeviceFolderTests(unittest.TestCase):
    """One folder per device inside snapshots/, and the way into them."""

    def _write_run(self, folder: Path, name: str, device: str | None) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        payload: dict = {"kind": "reset_snapshot", "total_keystrokes": 7}
        if device is not None:
            payload["device"] = device
        path = folder / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.with_suffix(".png").write_bytes(b"a picture")
        return path

    def test_each_device_files_into_its_own_folder(self) -> None:
        with TemporaryDataDir() as home:
            archive = home / storage.SNAPSHOT_DIR_NAME
            moment = datetime(2026, 8, 30, 13, 20, 20)
            keyboard = storage.StatsStore(device=storage.KEYBOARD_DEVICE)
            keyboard.record("A")
            gamepad = storage.StatsStore(device=storage.GAMEPAD_DEVICE)
            gamepad.record("FACE_DOWN")
            self.assertEqual(keyboard.archive({}, moment).parent, archive / "keyboard")
            self.assertEqual(gamepad.archive({}, moment).parent, archive / "gamepad")
            # The names are English, whatever the window is speaking.
            self.assertEqual(
                sorted(path.name for path in archive.iterdir()), ["gamepad", "keyboard"]
            )

    def test_runs_lying_loose_in_the_archive_are_filed_by_device(self) -> None:
        """Every build before the folders wrote one heap. It gets sorted.

        The device is written inside each run, so nothing has to be guessed;
        a run from before there was a pad names none and is the keyboard's.
        """
        with TemporaryDataDir() as home:
            archive = home / storage.SNAPSHOT_DIR_NAME
            self._write_run(archive, "keypulse-2026-08-30_194607", None)
            self._write_run(archive, "keypulse-2026-09-01_120000", storage.KEYBOARD_DEVICE)
            self._write_run(archive, "keypulse-gamepad-2026-09-02_040701", storage.GAMEPAD_DEVICE)
            # Anything that is not a run KeyPulse filed stays where it is.
            (archive / "keypulse-notes.json").write_text("{}", encoding="utf-8")

            filed = storage.file_loose_runs()
            self.assertEqual(
                sorted(path.parent.name for path in filed), ["gamepad", "keyboard", "keyboard"]
            )
            for path in filed:
                # The counts and the picture move as one piece, or not at all.
                self.assertTrue(path.exists())
                self.assertTrue(path.with_suffix(".png").exists())
                self.assertFalse((archive / path.name).exists())
                self.assertFalse((archive / f"{path.stem}.png").exists())
            self.assertTrue((archive / "keypulse-notes.json").exists())
            # Running again moves nothing: there is nothing loose left.
            self.assertEqual(storage.file_loose_runs(), [])

    def test_a_name_already_taken_below_is_left_where_it_is(self) -> None:
        with TemporaryDataDir() as home:
            archive = home / storage.SNAPSHOT_DIR_NAME
            name = "keypulse-2026-08-30_194607"
            self._write_run(archive / "keyboard", name, storage.KEYBOARD_DEVICE)
            loose = self._write_run(archive, name, storage.KEYBOARD_DEVICE)
            self.assertEqual(storage.file_loose_runs(), [])
            self.assertTrue(loose.exists())


if __name__ == "__main__":
    unittest.main()
