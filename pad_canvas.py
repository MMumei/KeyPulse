from __future__ import annotations

"""The controller view.

A copy of the reference picture, drawn rather than photographed. The picture
is looked at straight on -- there is no side wall anywhere in it, on the shell
or on a button -- so nothing here is extruded and the whole of the pad's depth
is carried by the shading instead: a dome across every raised face, a shadow
crescent along the far wall of every recess, a lit lip along the near one.

Every dimension comes from ``pad_reference`` and every colour in the palette
below was sampled off the picture, so the two can be put side by side and
compared. What the canvas adds to the picture is the part a picture cannot
have: a press lights the control that was pressed, the two sticks lean where
the real ones are being held, and every control carries its count -- the four
readout bars on the bar itself, the rest on a chip beside them.

The shell, the shoulder and everything scored into them never change between
frames, so they are painted once into a backdrop pixmap when the projection
moves and blitted after that. Only the controls are redrawn, and only the
ones the damaged region actually touches.
"""

import math
import time

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QRegion,
)

import pad_reference as REF
from gamepads import (
    DEFAULT_MODEL,
    MODELS,
    STICK_TRAVEL,
    PadElement,
    PadLayout,
    PadLight,
    callout_box,
)
from render import (
    CANVAS_BG,
    DeviceCanvas,
    PULSE_SECONDS,
    SINK_SECONDS,
    WHITE,
    frame_for,
    mix,
    Projection,
    ring_path,
    written,
)


# Straight at the face, and orthographic: the picture has no vanishing point
# in it, so the camera must not either.
PAD_PITCH_DEG = 90.0
PAD_DISTANCE = 1.0e7


def _c(value: str) -> QColor:
    return QColor(value)


# --- the palette, sampled off the reference picture -------------------------

# The shell. Brightest across the top, falling away towards the grips, with
# the rim in shade and a lit line just inside it.
SHELL_STOPS = (
    (0.00, _c("#E9EFEE")),
    (0.18, _c("#E8EEED")),
    (0.45, _c("#E4EAE9")),
    (0.72, _c("#DFE7E5")),
    (0.90, _c("#D9E1DF")),
    (1.00, _c("#CBD6D4")),
)
SHELL_RIM_SHADE = QColor(96, 124, 118, 48)
SHELL_RIM_LIGHT = QColor(255, 255, 255, 205)
SHELL_EDGE = QColor(152, 186, 178, 120)

# The mint. One family across every control: a lit arc just inside the top
# rim, a body that falls away downwards, and a dark rim underneath.
FACE_STOPS = (
    (0.00, _c("#96C7BB")),
    (0.09, _c("#E3F3F0")),
    (0.16, _c("#BDDBD5")),
    (0.28, _c("#ABCFC8")),
    (0.42, _c("#8FBEB5")),
    (0.52, _c("#7FB4A9")),
    (0.72, _c("#78AC9F")),
    (0.92, _c("#73A497")),
    (1.00, _c("#6C9A90")),
)
BAR_STOPS = (
    (0.00, _c("#67978D")),
    (0.10, _c("#95C3B8")),
    (0.30, _c("#89BBB2")),
    (0.55, _c("#82B8AD")),
    (0.75, _c("#7EB4A9")),
    (0.90, _c("#70A599")),
    (1.00, _c("#65938A")),
)
SMALL_STOPS = (
    (0.00, _c("#738E85")),
    (0.10, _c("#CCE5DF")),
    (0.26, _c("#B3D5CF")),
    (0.43, _c("#9DCCC2")),
    (0.67, _c("#8EC2B7")),
    (0.84, _c("#80B5AA")),
    (1.00, _c("#65958B")),
)
CROSS_STOPS = (
    (0.00, _c("#55796F")),
    (0.07, _c("#DEF0EC")),
    (0.13, _c("#8BBAB0")),
    (0.25, _c("#80B1A7")),
    (0.37, _c("#7BABA1")),
    (0.52, _c("#86B7AD")),
    (0.66, _c("#8FC1B7")),
    (0.82, _c("#8DC0B5")),
    (0.95, _c("#83B5AB")),
    (1.00, _c("#6F9790")),
)
CAP_STOPS = (
    (0.00, _c("#6D9C91")),
    (0.06, _c("#7CAEA3")),
    (0.22, _c("#85B7AC")),
    (0.32, _c("#8CBCB2")),
    (0.42, _c("#96C3B8")),
    (0.68, _c("#98C5BC")),
    (0.78, _c("#9BC9C0")),
    (0.90, _c("#A6CFC7")),
    (1.00, _c("#ADD3CB")),
)
FLANGE_STOPS = (
    (0.00, _c("#9AC3BC")),
    (0.35, _c("#8CB7AD")),
    (0.75, _c("#A1C8BF")),
    (1.00, _c("#B7D6CE")),
)
SHOULDER_STOPS = (
    (0.00, _c("#B1CFC9")),
    (0.45, _c("#A8C9C2")),
    (1.00, _c("#98BCB5")),
)
PANEL_STOPS = (
    (0.00, _c("#9FC3BC")),
    (0.35, _c("#A7C8C1")),
    (0.66, _c("#B5D4CD")),
    (0.85, _c("#A3C5BF")),
    (1.00, _c("#88ABA4")),
)
# The smooth flanks either side of the pebbled panel on a trigger paddle,
# read across the paddle from its outer edge inwards.
PADDLE_STOPS = (
    (0.00, _c("#8CB2AA")),
    (0.30, _c("#A8C8C1")),
    (0.46, _c("#B6D3CC")),
    (0.62, _c("#B6D3CC")),
    (0.88, _c("#A2C7BF")),
    (1.00, _c("#93BAB2")),
)
PADDLE_FOOT_STOPS = (
    (0.00, QColor(70, 110, 102, 0)),
    (0.58, QColor(70, 110, 102, 0)),
    (1.00, QColor(70, 110, 102, 54)),
)

# The floor of a stick well, and the wall round it: deepest in shade at the
# top, where the wall is turned away from the light, and almost gone at the
# bottom where the flange standing in it comes up to meet the rim.
WELL_FLOOR_STOPS = (
    (0.00, _c("#CFEBE6")),
    (0.55, _c("#BEE0DA")),
    (1.00, _c("#A6CBC3")),
)
WELL_WALL_STOPS = (
    (0.00, QColor(72, 104, 98, 232)),
    (0.45, QColor(92, 126, 118, 186)),
    (1.00, QColor(120, 156, 148, 120)),
)
# The rim of a moulding: catching the light along the top of it, in shade
# underneath, exactly as the picture draws every button on the pad.
RIM_STOPS = (
    (0.00, _c("#C4E0D9")),
    (0.40, _c("#8FB9B0")),
    (1.00, _c("#5C8B81")),
)
CONTACT_SHADE = QColor(58, 90, 84, 54)    # what a moulding drops on the shell


GUIDE_STOPS = (
    (0.00, _c("#484949")),
    (0.16, _c("#828283")),
    (0.45, _c("#494A4A")),
    (1.00, _c("#2A2F30")),
)
GUIDE_RING_STOPS = (
    (0.00, _c("#E6F4FC")),
    (0.45, _c("#D2ECFA")),
    (1.00, _c("#C3DEEF")),
)
# The lead of a wired pad: the shell's own family of greens, taken a couple
# of shades down so it reads as rubber rather than as more housing.
CABLE_STOPS = (
    (0.00, _c("#8FB3AC")),
    (0.40, _c("#A3C5BE")),
    (0.70, _c("#98BCB5")),
    (1.00, _c("#7FA49C")),
)
GUIDE_RING = _c("#D5EDFB")
GUIDE_RING_DARK = _c("#C7CFD4")
LED_ON = _c("#B6C9E2")

LEGEND = QColor(255, 255, 255, 246)
GLYPH_INK = QColor(74, 112, 105, 220)     # the arrows and icons, cut in dark

# A count hung off a control: the leader drawn to it, and the white the chip
# is haloed in so it reads against the shell wherever on it the chip lands.
CALLOUT_LINE = QColor(104, 152, 143, 215)
CALLOUT_HALO = QColor(255, 255, 255, 238)

# A press lights the control that was pressed. Nothing else on the pad
# changes colour, so this is the only place a tone outside the picture's own
# palette is allowed.
PRESSED = _c("#D8F6EC")
PRESS_GLOW = QColor(120, 235, 205)

# Type sizes, in pad units, measured off the picture.
BAR_TYPE = 0.176
FACE_TYPE = 0.320
MINOR_TYPE = 0.200
STICK_TYPE = 0.272

# A callout chip: a stadium the height of the numeral it carries, which is a
# circle while the count is short and grows sideways once it is not.
CALLOUT_TYPE = 0.150
CALLOUT_H = 0.2200
CALLOUT_SIDE = 0.1000     # the room either side of the number inside the chip
CALLOUT_PEN = 0.0170      # the leader
CALLOUT_DOT = 0.0330      # the mark it lands on the control with
CALLOUT_HALO_PEN = 0.0440

# How much of a stick's deflection the collar under the cap picks up: a real
# stick pivots at its base, so the top of it travels and the collar hardly
# does.
FLANGE_LEAN = 0.34

# Texture. The grip panel on a trigger is pebbled and a stick flange is
# knurled; both are scattered from a fixed seed so they never crawl between
# frames.
PEBBLE_STEP = 0.045
PEBBLE_R = 0.0125
# Scratches per square pixel of the flange, so the milling stays as fine at
# one zoom as at another instead of turning to noise when the pad is small.
KNURL_DENSITY = 0.16
KNURL_MAX = 2400


def _stops(gradient, stops, colour=None, amount: float = 0.0, alpha: float = 1.0):
    for position, tone in stops:
        shifted = mix(tone, colour, amount) if colour else QColor(tone)
        if alpha != 1.0:
            shifted.setAlpha(round(tone.alpha() * alpha))
        gradient.setColorAt(position, shifted)
    return gradient


def _vertical(bounds: QRectF, stops, colour=None, amount: float = 0.0,
              alpha: float = 1.0) -> QLinearGradient:
    gradient = QLinearGradient(
        QPointF(bounds.center().x(), bounds.top()),
        QPointF(bounds.center().x(), bounds.bottom()),
    )
    return _stops(gradient, stops, colour, amount, alpha)


class _Scatter:
    """A fixed pseudo-random sequence, so a texture never crawls."""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & 0xFFFFFFFF or 1

    def next(self) -> float:
        # xorshift32: cheap, repeatable, and good enough to break up a grid.
        state = self._state
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        self._state = state
        return state / 4294967296.0

    def spread(self, amount: float) -> float:
        return (self.next() - 0.5) * 2.0 * amount


def _shrunk(path: QPainterPath, factor: float) -> QPainterPath:
    """The same shape pulled in about its own middle."""
    bounds = path.boundingRect()
    centre = bounds.center()
    shape = QPainterPath(path)
    shape.translate(-centre.x(), -centre.y())
    scaled = QPainterPath()
    for index in range(shape.elementCount()):
        element = shape.elementAt(index)
        point = QPointF(element.x * factor + centre.x(), element.y * factor + centre.y())
        if element.isMoveTo():
            scaled.moveTo(point)
        else:
            scaled.lineTo(point)
    scaled.closeSubpath()
    return scaled


def _inside(point, ring) -> bool:
    x, y = point
    inside = False
    for index, (ax, ay) in enumerate(ring):
        bx, by = ring[(index + 1) % len(ring)]
        if (ay > y) != (by > y):
            if ax + (y - ay) / (by - ay) * (bx - ax) > x:
                inside = not inside
    return inside


class GamepadCanvas(DeviceCanvas):
    def __init__(self, stats, parent=None) -> None:
        super().__init__(stats, parent)
        self._axes = (0.0, 0.0, 0.0, 0.0)
        self._controls: tuple[PadElement, ...] = ()
        self._arms: tuple[PadElement, ...] = ()
        self._backdrop: QPixmap | None = None
        self._body = QPainterPath()
        self._body_bounds = QRectF()
        self._shoulder = QPainterPath()
        self._paddles: tuple[QPainterPath, ...] = ()
        self._pebbles: tuple[tuple[QPointF, float], ...] = ()
        self._knurls: dict[str, QPainterPath] = {}
        self._fonts: dict[tuple[str, int], QFont] = {}
        self.set_layout(DEFAULT_MODEL)

    # -- state -------------------------------------------------------------

    def set_layout(self, model_id: str) -> None:
        model: PadLayout = MODELS.get(model_id, MODELS[DEFAULT_MODEL])
        self.layout_spec = model
        # The grip is moulded into this model's panels, so it is this model's.
        self._pebble_cache = None
        # Far edge first, so a control nearer the viewer overlaps the one
        # behind it the way the picture has them overlap.
        def near(element: PadElement) -> tuple[float, float]:
            return element.y + element.height * 0.5, element.x

        self._controls = tuple(sorted(
            (e for e in model.elements if e.kind != "arm"), key=near
        ))
        self._arms = tuple(e for e in model.elements if e.kind == "arm")
        self._draw_order = self._controls
        self._peak_cache = None
        self._heat_cache.clear()
        self._rebuild_projection()
        self.update()

    def set_axes(self, left_x: float, left_y: float, right_x: float, right_y: float) -> None:
        axes = (left_x, left_y, right_x, right_y)
        if axes == self._axes:
            return
        self._axes = axes
        region = QRegion()
        for element in self._controls:
            if element.kind == "stick":
                region = region.united(self._key_rect_by_id.get(element.element_id, QRect()))
        self._caps_pending = True
        self._cap_damage = self._cap_damage.united(region)
        self.update(region)

    def _deflection(self, element: PadElement) -> tuple[float, float]:
        left_x, left_y, right_x, right_y = self._axes
        x, y = (left_x, left_y) if element.axis == "left" else (right_x, right_y)
        return x * STICK_TRAVEL, y * STICK_TRAVEL

    def _counted_ids(self):
        return [e.element_id for e in self.layout_spec.elements if e.counted]

    # -- geometry ----------------------------------------------------------

    def _make_projection(self, unit: float) -> Projection:
        model = self.layout_spec
        return Projection(model.width, model.height, unit, PAD_PITCH_DEG, PAD_DISTANCE)

    def _frame(self, unit: float) -> tuple[QSize, QPointF]:
        model = self.layout_spec
        projection = self._make_projection(unit)
        samples = [(x, y, 0.0) for x, y in model.outline]
        samples += [(x, y, 0.0) for x, y in model.shoulder]
        return frame_for(projection, samples)

    def _at(self, x: float, y: float) -> QPointF:
        return self._projection.at(x, y)

    def _ring(self, points) -> list[QPointF]:
        return self._projection.ring(points)

    def _path(self, points) -> QPainterPath:
        return ring_path(self._ring(points))

    def _u(self, value: float) -> float:
        """A length in pad units, in device pixels."""
        return value * self._projection.unit

    def _callout_font(self) -> QFont:
        return self._font(CALLOUT_TYPE, QFont.Weight.Medium)

    def _callout_shape(self, element: PadElement,
                       text: str) -> tuple[QRectF, QPointF, QPointF] | None:
        """The chip, the dot on the control, and where the leader joins it.

        Where it stands is worked out in pad units, by the pad; all that is
        added here is how wide the number on it has to be.
        """
        mark = element.callout
        if mark is None:
            return None
        room = QFontMetricsF(self._callout_font()).horizontalAdvance(text)
        width = max(CALLOUT_H, room / self._projection.unit + CALLOUT_SIDE * 2)
        x, y, w, h = callout_box(element, width, CALLOUT_H)
        chip = QRectF(self._at(x, y), self._at(x + w, y + h))
        if mark.side in ("left", "right"):
            sign = 1.0 if mark.side == "right" else -1.0
            dot = self._at(element.x + sign * element.width * 0.5, element.y)
            join = QPointF(chip.left() if sign > 0 else chip.right(),
                           chip.center().y())
        else:
            sign = 1.0 if mark.side == "below" else -1.0
            dot = self._at(element.x, element.y + sign * element.height * 0.5)
            join = QPointF(chip.center().x(),
                           chip.top() if sign > 0 else chip.bottom())
        return chip, dot, join

    def _callout_leader(self, element: PadElement, chip: QRectF,
                        dot: QPointF, join: QPointF) -> QPainterPath:
        """The line from the control to its chip.

        Straight when the chip is square on to the control, a square corner
        when it has been carried up out of the way, and a flattened S when it
        has only been carried a little -- which is the line the picture draws
        between a button and a number that does not sit level with it.
        """
        mark = element.callout
        path = QPainterPath(dot)
        sideways = mark.side in ("left", "right")
        if abs(dot.x() - join.x()) < 0.5 and abs(dot.y() - join.y()) < 0.5:
            return path
        if mark.elbow and sideways:
            sign = 1.0 if mark.side == "right" else -1.0
            turn = join.x() + sign * chip.height() * 0.5
            path.lineTo(QPointF(turn, dot.y()))
            path.lineTo(QPointF(turn, chip.center().y()))
        elif mark.elbow:
            sign = 1.0 if mark.side == "below" else -1.0
            turn = join.y() + sign * chip.height() * 0.5
            path.lineTo(QPointF(dot.x(), turn))
            path.lineTo(QPointF(chip.center().x(), turn))
        elif sideways and abs(dot.y() - join.y()) > 0.5:
            reach = (join.x() - dot.x()) * 0.55
            path.cubicTo(QPointF(dot.x() + reach, dot.y()),
                         QPointF(join.x() - reach, join.y()), join)
        elif not sideways and abs(dot.x() - join.x()) > 0.5:
            reach = (join.y() - dot.y()) * 0.55
            path.cubicTo(QPointF(dot.x(), dot.y() + reach),
                         QPointF(join.x(), join.y() - reach), join)
        else:
            path.lineTo(join)
        return path

    def _callout_room(self, element: PadElement) -> QRectF | None:
        """The chip at its widest, so a growing count never outruns its rect.

        What is damaged when a control is pressed is worked out once per
        projection, and the number on the chip goes on getting longer after
        that, so the room kept for it is measured against the longest count
        either language can write rather than against today's.
        """
        widest = None
        for sample in ("8,888", "88.8万", "888.8K"):
            shape = self._callout_shape(element, sample)
            if shape is None:
                return None
            widest = shape[0] if widest is None else widest.united(shape[0])
        return widest

    def _measure_regions(self) -> None:
        """Rebuild everything the projection moves, and repaint the backdrop.

        The shell costs far more to draw than the controls standing on it and
        never changes once the zoom has settled, so it is painted once here
        and blitted afterwards. Nothing in this method may depend on a count,
        a press or a stick position.
        """
        model = self.layout_spec
        self._body = self._path(model.outline)
        self._body_bounds = self._body.boundingRect()
        self._shoulder = self._path(model.shoulder) if model.shoulder else QPainterPath()
        self._paddles = tuple(self._path(ring) for ring in model.paddles)

        rects: dict[str, QRect] = {}
        for element in model.elements:
            ring = self._ring(element.outline)
            # Slack for the shadow under a moulding and for the ring a
            # pressed one paints outside its own outline.
            rects[element.element_id] = (
                QPolygonF(ring).boundingRect().adjusted(-10, -10, 10, 10).toAlignedRect()
            )
        # A chip and its leader are repainted with the control they belong
        # to, so they have to be inside the rectangle that control damages.
        for element in model.elements:
            room = self._callout_room(element)
            if room is not None:
                rects[element.element_id] = rects[element.element_id].united(
                    room.adjusted(-6, -6, 6, 6).toAlignedRect()
                )
        self._key_rect_by_id = rects
        self._key_rects = tuple(rects[e.element_id] for e in self._draw_order)

        self._pebbles = self._scatter_pebbles()
        self._knurls = {
            element.element_id: self._scatter_knurl(element.rings[1])
            for element in model.elements if element.kind == "stick"
        }
        self._light_region = self._lamp_region()
        self._fonts.clear()
        # The shell is repainted by the first frame that needs it, not here.
        # A wheel turn rebuilds the projection at every notch and shows one of
        # them, so painting the shell eagerly meant painting eleven pads into
        # pixmaps that were thrown away before anything drew them -- the frame
        # already knows how to fill this in when it finds it empty.
        self._backdrop = None

    def _lamp_region(self) -> QRegion:
        """Where a colour-changing lamp reaches, and nowhere else."""
        lit = QRegion()
        for lamp in self.layout_spec.lights:
            if not lamp.animated:
                continue
            ring = self._ring(lamp.outline)
            reach = round(self._u(lamp.reach)) + 4
            lit = lit.united(
                QPolygonF(ring).boundingRect()
                .adjusted(-reach, -reach, reach, reach).toAlignedRect()
            )
        return lit

    def _pebble_field(self) -> tuple[tuple[float, float, float], ...]:
        """Where the domes on the trigger panels sit, in pad units.

        The field is jittered, but it is jittered onto the shell rather than
        onto the screen, so a zoom does not move a single dome relative to the
        panel it is moulded into -- only the camera looking at them changes.
        Walking the grid again at every notch of the wheel, and asking of
        every point on it whether the panel contains it, was work the zoom
        paid for and threw away. It is worked out once per model instead.
        """
        if self._pebble_cache is not None:
            return self._pebble_cache
        field: list[tuple[float, float, float]] = []
        for index, panel in enumerate(self.layout_spec.panels):
            scatter = _Scatter(0x9E3779B1 + index * 7919)
            left = min(x for x, _ in panel)
            top = min(y for _, y in panel)
            steps_x = max(1, int((max(x for x, _ in panel) - left) / PEBBLE_STEP))
            steps_y = max(1, int((max(y for _, y in panel) - top) / PEBBLE_STEP))
            for row in range(steps_y + 1):
                for column in range(steps_x + 1):
                    # The scatter is walked in exactly the order it always
                    # was, skips included: it is a fixed sequence, and taking
                    # one draw from it out of turn would re-roll the grip.
                    x = left + column * PEBBLE_STEP + scatter.spread(PEBBLE_STEP * 0.42)
                    y = top + row * PEBBLE_STEP + scatter.spread(PEBBLE_STEP * 0.42)
                    if not _inside((x, y), panel):
                        continue
                    field.append((x, y, 0.7 + scatter.next() * 0.6))
        self._pebble_cache = tuple(field)
        return self._pebble_cache

    def _scatter_pebbles(self) -> tuple[tuple[QPointF, float], ...]:
        """The moulded grip on a trigger panel, put where the camera sees it."""
        radius = self._u(PEBBLE_R)
        if radius < 0.35:
            return ()
        return tuple(
            (self._at(x, y), radius * size) for x, y, size in self._pebble_field()
        )

    # -- the backdrop ------------------------------------------------------

    def _paint_backdrop(self) -> QPixmap:
        ratio = self.devicePixelRatioF() or 1.0
        size = self.canvas_size
        pixmap = QPixmap(
            max(1, int(size.width() * ratio)), max(1, int(size.height() * ratio))
        )
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(CANVAS_BG)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_shadow(painter)
        self._draw_cable(painter)
        self._draw_shell(painter)
        self._draw_dishes(painter)
        self._draw_hexagon(painter)
        self._draw_shoulder(painter)
        for lamp in self.layout_spec.lights:
            if not lamp.animated:
                self._draw_lamp(painter, lamp)
        self._draw_led(painter)
        painter.end()
        return pixmap

    def _draw_shadow(self, painter: QPainter) -> None:
        """What the pad drops on the desk, faked by stacked offset passes."""
        painter.setPen(Qt.PenStyle.NoPen)
        lift = max(1.0, self._u(0.02))
        for step in range(5):
            share = step / 4.0
            painter.setBrush(QColor(64, 92, 86, round(24 - 19 * share)))
            painter.translate(0.0, lift * (1.0 + share * 5.0))
            painter.drawPath(self._body)
            painter.translate(0.0, -lift * (1.0 + share * 5.0))

    def _draw_shell(self, painter: QPainter) -> None:
        """The moulded front of the pad: a ground tone, then its curvature.

        A pad's front is not a flat panel -- it crowns between the grips and
        rolls away in every direction -- so the colour is laid down first and
        the shape put on top of it as light: a dome pooled high and centred,
        the whole rim falling into shade, and a lit line just inside the edge
        where the front shell laps over the back one.
        """
        bounds = self._body_bounds
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_vertical(bounds, SHELL_STOPS))
        painter.drawPath(self._body)

        painter.save()
        painter.setClipPath(self._body)
        dome = QRadialGradient(
            QPointF(bounds.center().x(), bounds.top() + bounds.height() * 0.22),
            max(bounds.width(), bounds.height()) * 0.58,
        )
        dome.setColorAt(0.00, QColor(255, 255, 255, 120))
        dome.setColorAt(0.55, QColor(255, 255, 255, 40))
        dome.setColorAt(1.00, QColor(255, 255, 255, 0))
        painter.setBrush(dome)
        painter.drawRect(bounds)

        # The rim, as a wide stroke landing half outside the clip: what stays
        # is a band of shade hugging the whole edge, which is what turns a
        # cut-out shape into something with a thickness.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(SHELL_RIM_SHADE, max(3.0, self._u(0.14))))
        painter.drawPath(self._body)
        painter.setPen(QPen(SHELL_RIM_LIGHT, max(1.4, self._u(0.020))))
        painter.drawPath(self._body.translated(0.0, -max(1.0, self._u(0.012))))
        painter.restore()

        # The mint the picture runs right along the edge itself, where the
        # two halves of the shell meet.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(SHELL_EDGE, max(1.2, self._u(0.014))))
        painter.drawPath(self._body)

    def _draw_dishes(self, painter: QPainter) -> None:
        """The shallow saucers the D-pad and the two sticks are set into.

        Barely there in the picture -- a rim of shade above, a lit lip below
        -- but they are what stops the cross and the wells reading as parts
        laid on a flat sheet.
        """
        painter.setPen(Qt.PenStyle.NoPen)
        for element in self.layout_spec.elements:
            if element.kind == "stick":
                radius = element.width * 0.66
            elif element.kind == "cross":
                radius = element.width * 0.54
            else:
                continue
            centre = self._at(element.x, element.y)
            reach = self._u(radius)
            lift = max(1.0, self._u(0.020))
            # A ring of light with no edge to it: a radial ramp that comes up
            # towards the rim and falls away again, so the saucer shows as a
            # change of tone rather than as a drawn circle.
            for offset, tone in ((lift, QColor(255, 255, 255, 150)),
                                 (-lift, QColor(104, 136, 130, 46))):
                halo = QRadialGradient(
                    QPointF(centre.x(), centre.y() + offset), reach
                )
                clear = QColor(tone)
                clear.setAlpha(0)
                halo.setColorAt(0.00, clear)
                halo.setColorAt(0.62, clear)
                halo.setColorAt(0.88, tone)
                halo.setColorAt(1.00, clear)
                painter.setBrush(halo)
                painter.drawEllipse(QPointF(centre.x(), centre.y() + offset),
                                    reach, reach)

    def _draw_cable(self, painter: QPainter) -> None:
        """The lead a wired pad comes with, painted before the shell is.

        It goes down first so the shell lands on top of its foot: a cable that
        finished at the edge of the housing would read as a stick glued to the
        pad rather than as a lead coming out of it.
        """
        rings = self.layout_spec.cable
        if not rings:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        for ring in rings:
            path = self._path(ring)
            bounds = path.boundingRect()
            painter.setBrush(QColor(70, 110, 102, 38))
            painter.drawPath(self._path(tuple((x + 0.02, y + 0.02) for x, y in ring)))
            painter.setBrush(_vertical(bounds, CABLE_STOPS))
            painter.drawPath(path)
            # One highlight down the left of the round, the way the triggers
            # and the stick flanges catch the same light.
            sheen = QRectF(bounds.left(), bounds.top(),
                           max(1.0, bounds.width() * 0.34), bounds.height())
            painter.setBrush(QColor(255, 255, 255, 46))
            painter.drawRect(sheen.adjusted(bounds.width() * 0.16, bounds.height() * 0.06,
                                            0.0, -bounds.height() * 0.06))

    def _draw_hexagon(self, painter: QPainter) -> None:
        """The panel scored into the shell around the guide button."""
        hexagon = self.layout_spec.hexagon
        if not hexagon:
            return
        points = self._ring(hexagon)
        line = QPolygonF(points)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        width = max(1.6, self._u(REF.HEX_PEN))
        painter.setPen(QPen(QColor(148, 194, 184, 235), width,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawPolyline(line)
        painter.setPen(QPen(QColor(255, 255, 255, 170), max(1.0, width * 0.36),
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawPolyline(QPolygonF([
            QPointF(point.x(), point.y() + width * 0.82) for point in points
        ]))

    def _draw_shoulder(self, painter: QPainter) -> None:
        """The mint trim across the top, with a trigger paddle at each end.

        The trim and the two paddles are one continuous piece of moulding in
        the picture, so they are filled as one shape and the parts told apart
        afterwards by the lines between them: a lit rim round each paddle, a
        dark one along both edges of the whole run.
        """
        if self._shoulder.isEmpty():
            return
        bounds = self._shoulder.boundingRect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_vertical(bounds, SHOULDER_STOPS))
        painter.drawPath(self._shoulder)

        painter.save()
        painter.setClipPath(self._shoulder)
        for index, paddle in enumerate(self._paddles):
            self._draw_paddle(painter, index, paddle)
        # Both edges of the whole run fall into shade: wide strokes of the
        # silhouette, each landing half outside the clip, so what is left is
        # a band that darkens towards either edge and leaves the middle of
        # the trim as the lit crest the picture gives it.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(74, 118, 109, 72), max(2.0, self._u(0.070))))
        painter.drawPath(self._shoulder)
        painter.setPen(QPen(QColor(64, 106, 98, 88), max(1.4, self._u(0.026))))
        painter.drawPath(self._shoulder)
        painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(96, 138, 130, 120), max(1.0, self._u(0.011))))
        painter.drawPath(self._shoulder)
        # The lit line the shell catches just under the trim.
        painter.save()
        painter.setClipPath(self._body)
        painter.setPen(QPen(QColor(255, 255, 255, 200), max(1.2, self._u(0.018))))
        painter.drawPath(self._shoulder.translated(0.0, max(1.2, self._u(0.017))))
        painter.restore()

    def _draw_paddle(self, painter: QPainter, index: int, paddle: QPainterPath) -> None:
        """One trigger paddle: a smooth flank each side of a pebbled panel."""
        bounds = paddle.boundingRect()
        painter.setPen(Qt.PenStyle.NoPen)
        left = QPointF(bounds.left(), bounds.center().y())
        right = QPointF(bounds.right(), bounds.center().y())
        # The wide smooth flank is on the outboard side of each paddle, so
        # the right-hand one reads its ramp the other way round.
        flank = QLinearGradient(*((left, right) if index == 0 else (right, left)))
        painter.setBrush(_stops(flank, PADDLE_STOPS))
        painter.drawPath(paddle)
        # The paddle leans away at its foot, so the bottom of it falls into
        # shade whichever flank the light is coming across.
        painter.setBrush(_vertical(bounds, PADDLE_FOOT_STOPS))
        painter.drawPath(paddle)

        panel = self._path(self.layout_spec.panels[index])
        painter.setBrush(_vertical(panel.boundingRect(), PANEL_STOPS))
        painter.drawPath(panel)
        self._draw_pebbles(painter, panel)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 190), max(1.0, self._u(0.009))))
        painter.drawPath(panel)
        painter.setPen(QPen(QColor(255, 255, 255, 120), max(1.0, self._u(0.009))))
        painter.drawPath(paddle)

    def _draw_pebbles(self, painter: QPainter, panel: QPainterPath) -> None:
        if not self._pebbles:
            return
        painter.save()
        painter.setClipPath(panel, Qt.ClipOperation.IntersectClip)
        painter.setPen(Qt.PenStyle.NoPen)
        lift = max(0.4, self._u(0.007))
        for centre, radius in self._pebbles:
            painter.setBrush(QColor(96, 136, 128, 72))
            painter.drawEllipse(QPointF(centre.x(), centre.y() + lift), radius, radius)
            painter.setBrush(QColor(236, 249, 245, 120))
            painter.drawEllipse(centre, radius, radius)
        painter.restore()

    def _draw_led(self, painter: QPainter) -> None:
        """The pinhole indicator the picture puts under the guide button."""
        led = self.layout_spec.led
        if led is None:
            return
        centre = self._at(*led)
        radius = max(1.0, self._u(REF.LED_R))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(120, 140, 170, 70))
        painter.drawEllipse(centre, radius * 1.9, radius * 1.9)
        painter.setBrush(LED_ON)
        painter.drawEllipse(centre, radius, radius)

    def _draw_lamp(self, painter: QPainter, lamp: PadLight) -> None:
        """One lamp: a bloom that keeps the lamp's own shape, and a hot core.

        Widest and faintest pass first, each landing inside the one before
        it, which is what builds the falloff instead of flattening it.
        """
        colour = self.wave_color(0.0) if lamp.animated else QColor(lamp.colour)
        path = ring_path(self._ring(lamp.outline))
        spread = self._u(lamp.reach)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(150, 166, 162, 130))
        painter.drawPath(path)
        if not lamp.lit or not self.lighting:
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for step in range(4, 0, -1):
            share = step / 4.0
            tint = QColor(colour)
            tint.setAlpha(round(14 + 34 * (1.0 - share)))
            painter.setPen(QPen(tint, max(1.0, spread * 2.0 * share)))
            painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawPath(path)
        painter.setBrush(mix(colour, WHITE, 0.62))
        painter.drawPath(_shrunk(path, 0.52))

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        caps = self.caps_to_redraw(event)
        region = caps if caps is not None else self._light_region
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._backdrop is None or self._backdrop.devicePixelRatio() != (
            self.devicePixelRatioF() or 1.0
        ):
            # A window dragged onto a screen of a different scale needs the
            # backdrop again at that scale before anything can be blitted.
            self._backdrop = self._paint_backdrop()
        # Qt clips the blit to the region it asked for, so the whole backdrop
        # can be handed over and the damaged part is what actually lands.
        painter.drawPixmap(0, 0, self._backdrop)
        for lamp in self.layout_spec.lights:
            if lamp.animated:
                self._draw_lamp(painter, lamp)
        for element in self._controls:
            if not region.intersects(self._key_rect_by_id[element.element_id]):
                continue
            if element.kind == "stick":
                self._draw_stick(painter, element)
            elif element.kind == "cross":
                self._draw_cross(painter, element)
            elif element.kind == "guide":
                self._draw_guide(painter, element)
            elif element.kind == "pill":
                self._draw_bar(painter, element)
            elif element.kind == "small":
                self._draw_small(painter, element)
            else:
                self._draw_face(painter, element)
        # The chips last, and in one pass of their own: a chip stands in
        # the gap beside its control and can reach across the ground another
        # one is drawn on, so none of them may be painted over.
        for element in self.layout_spec.elements:
            if element.callout is None:
                continue
            if region.intersects(self._key_rect_by_id[element.element_id]):
                self._draw_callout(painter, element)
        self._draw_trigger_glow(painter)
        painter.end()

    def _press(self, element_id: str) -> tuple[float, float]:
        started = self._active.get(element_id)
        if started is None:
            return 0.0, 0.0
        elapsed = time.monotonic() - started
        if not 0.0 <= elapsed < PULSE_SECONDS:
            return 0.0, 0.0
        return (
            max(0.0, 1.0 - elapsed / PULSE_SECONDS),
            max(0.0, 1.0 - elapsed / SINK_SECONDS),
        )

    def _seat(self, painter: QPainter, path: QPainterPath, depth: float) -> None:
        """What a raised moulding drops on the shell it stands on.

        This is the whole of the third dimension in a picture drawn straight
        at the face. The light is above, so every moulding in the reference
        lays a crescent of shade below itself and catches a pale one along the
        lip above -- and that is what stops it reading as a sticker.
        """
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(CONTACT_SHADE)
        painter.drawPath(path.translated(0.0, depth * 1.5))
        painter.setBrush(QColor(255, 255, 255, 150))
        painter.drawPath(path.translated(0.0, -depth * 0.55))

    def _glow(self, painter: QPainter, path: QPainterPath, glow: float) -> None:
        if glow <= 0.0:
            return
        painter.setPen(QPen(QColor(PRESS_GLOW.red(), PRESS_GLOW.green(),
                                   PRESS_GLOW.blue(), int(165 * glow)),
                            max(2.0, self._u(0.05))))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)

    def _moulding(self, painter: QPainter, path: QPainterPath, stops,
                  glow: float, sink: float) -> QRectF:
        """Fill one raised control, and rim it top and bottom."""
        depth = max(1.4, self._u(0.022)) * (1.0 - 0.6 * sink)
        self._seat(painter, path, depth)
        self._glow(painter, path, glow)
        bounds = path.boundingRect()
        painter.setBrush(_vertical(bounds, stops, PRESSED, glow * 0.72))
        painter.setPen(QPen(QBrush(_vertical(bounds, RIM_STOPS, PRESSED, glow * 0.6)),
                            max(1.0, self._u(0.011))))
        painter.drawPath(path)
        return bounds

    def _draw_face(self, painter: QPainter, element: PadElement) -> None:
        glow, sink = self._press(element.element_id)
        path = self._path(element.outline)
        bounds = self._moulding(painter, path, FACE_STOPS, glow, sink)
        self._legend(painter, element.glyph or element.label, bounds,
                     FACE_TYPE if element.width > 0.5 else MINOR_TYPE,
                     QFont.Weight.Medium)

    def _draw_small(self, painter: QPainter, element: PadElement) -> None:
        glow, sink = self._press(element.element_id)
        path = self._path(element.outline)
        bounds = self._moulding(painter, path, SMALL_STOPS, glow, sink)
        self._draw_icon(painter, element.glyph, bounds)

    def _draw_bar(self, painter: QPainter, element: PadElement) -> None:
        """One readout bar: its name at the left end, its count at the right.

        These four are the only controls the picture prints a number on, so
        they are the only ones that carry theirs inside themselves; every
        other count on the pad is hung beside its control instead.
        """
        glow, sink = self._press(element.element_id)
        path = self._path(element.outline)
        bounds = self._moulding(painter, path, BAR_STOPS, glow, sink)
        count = self.stats.count(element.element_id)
        text = written(count)
        inset = self._u(0.135)
        room = QRectF(bounds.left() + inset, bounds.top(),
                      bounds.width() - inset * 2, bounds.height())
        painter.setFont(self._font(BAR_TYPE, QFont.Weight.Medium))
        painter.setPen(LEGEND)
        painter.drawText(room, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         element.label)
        painter.setFont(self._font(BAR_TYPE, QFont.Weight.Normal))
        painter.drawText(room, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         text)

    def _draw_callout(self, painter: QPainter, element: PadElement) -> None:
        """One count, written beside the control it belongs to.

        The picture prints a number on the four readout bars and leaves the
        rest of the pad bare, which is fine for a picture and no use for a
        counter, so every other control is given its number here: a chip in
        the nearest bare piece of shell, on a line back to the control, and
        lit with it when it is pressed so the two read as one thing.
        """
        text = written(self.stats.count(element.element_id))
        shape = self._callout_shape(element, text)
        if shape is None:
            return
        chip, dot, join = shape
        glow, _ = self._press(element.element_id)

        pen = QPen(CALLOUT_LINE, max(1.0, self._u(CALLOUT_PEN)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._callout_leader(element, chip, dot, join))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(CALLOUT_LINE)
        spot = max(1.2, self._u(CALLOUT_DOT))
        painter.drawEllipse(dot, spot, spot)

        stadium = QPainterPath()
        stadium.addRoundedRect(chip, chip.height() * 0.5, chip.height() * 0.5)
        self._seat(painter, stadium, max(1.0, self._u(0.016)))
        painter.setPen(QPen(CALLOUT_HALO, max(1.0, self._u(CALLOUT_HALO_PEN))))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(stadium)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_vertical(chip, SMALL_STOPS, PRESSED, glow * 0.72))
        painter.drawPath(stadium)
        painter.setFont(self._callout_font())
        painter.setPen(LEGEND)
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_guide(self, painter: QPainter, element: PadElement) -> None:
        """The Xbox button: a lit ring with the moulded sphere sunk in it."""
        glow, _ = self._press(element.element_id)
        centre = self._at(element.x, element.y)
        outer = self._u(element.width * 0.5)
        inner = outer * (REF.GUIDE_R / REF.GUIDE_RING_R)
        painter.setPen(Qt.PenStyle.NoPen)

        lit = self.lighting
        # The shell catches a little of the ring: a breath of light around it,
        # not the halo a lamp sunk into the plate would throw.
        if lit:
            bloom = QColor(GUIDE_RING)
            bloom.setAlpha(round(22 + 120 * glow))
            painter.setBrush(bloom)
            painter.drawEllipse(centre, outer * (1.10 + 0.16 * glow),
                                outer * (1.10 + 0.16 * glow))
        ring = QRectF(centre.x() - outer, centre.y() - outer, outer * 2, outer * 2)
        if lit:
            painter.setBrush(_vertical(ring, GUIDE_RING_STOPS, WHITE, glow * 0.7))
        else:
            painter.setBrush(GUIDE_RING_DARK)
        painter.drawEllipse(ring)

        sphere = QRectF(centre.x() - inner, centre.y() - inner, inner * 2, inner * 2)
        painter.setBrush(QColor(40, 44, 45, 70))
        painter.drawEllipse(sphere.translated(0.0, inner * 0.05))
        painter.setBrush(_vertical(sphere, GUIDE_STOPS))
        painter.drawEllipse(sphere)
        self._draw_nexus(painter, centre, inner)

    def _draw_nexus(self, painter: QPainter, centre: QPointF, radius: float) -> None:
        """The X the sphere carries.

        Two strokes, each bowed away from the middle so they cross a little
        above the centre and splay at both ends, clipped to the sphere the way
        the mark is cut into it.
        """
        if radius < 4.0:
            return
        sphere = QPainterPath()
        sphere.addEllipse(centre, radius, radius)
        painter.save()
        painter.setClipPath(sphere)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(250, 252, 252))
        for sign in (1.0, -1.0):
            painter.drawPath(self._nexus_arm(centre, radius, sign))
        painter.restore()

    @staticmethod
    def _nexus_arm(centre: QPointF, radius: float, sign: float) -> QPainterPath:
        """One of the mark's two strokes.

        Broad where it leaves the top of the sphere and tapering to a point
        near the bottom of it, with the whole stroke bowed away from the
        middle so the two of them cross above centre and splay at both ends.
        """
        start = (centre.x() - 0.60 * radius * sign, centre.y() - 1.02 * radius)
        control = (centre.x() - 0.10 * radius * sign, centre.y() - 0.22 * radius)
        end = (centre.x() + 0.55 * radius * sign, centre.y() + 0.86 * radius)
        steps = 20
        left: list[QPointF] = []
        right: list[QPointF] = []
        for step in range(steps + 1):
            t = step / steps
            inverse = 1.0 - t
            x = inverse * inverse * start[0] + 2 * inverse * t * control[0] + t * t * end[0]
            y = inverse * inverse * start[1] + 2 * inverse * t * control[1] + t * t * end[1]
            dx = 2 * inverse * (control[0] - start[0]) + 2 * t * (end[0] - control[0])
            dy = 2 * inverse * (control[1] - start[1]) + 2 * t * (end[1] - control[1])
            span = math.hypot(dx, dy) or 1.0
            half = radius * (0.052 + 0.190 * inverse ** 0.62)
            nx, ny = -dy / span * half, dx / span * half
            left.append(QPointF(x + nx, y + ny))
            right.append(QPointF(x - nx, y - ny))
        path = QPainterPath()
        path.moveTo(left[0])
        for point in left[1:]:
            path.lineTo(point)
        for point in reversed(right):
            path.lineTo(point)
        path.closeSubpath()
        return path

    def _draw_cross(self, painter: QPainter, element: PadElement) -> None:
        """The D-pad: one moulded cross, four directions coloured inside it.

        A real cross has no seam a separate cap could stand on, and the
        picture draws none, so the moulding is one shape and a press is laid
        onto it afterwards -- clipped to the cross, so the join between two
        limbs is a change of tone and never an edge.
        """
        live = max((self._press(arm.element_id)[0] for arm in self._arms), default=0.0)
        sunk = max((self._press(arm.element_id)[1] for arm in self._arms), default=0.0)
        path = self._path(element.outline)
        self._moulding(painter, path, CROSS_STOPS, 0.0, sunk)
        # The cross carries a hard dark rim the round buttons do not: it is
        # the one moulding on the pad with a wall standing up round its face.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(62, 102, 96, 190), max(1.4, self._u(0.026))))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 120), max(1.0, self._u(0.013))))
        painter.drawPath(path.translated(0.0, max(1.0, self._u(0.017))))
        painter.setPen(Qt.PenStyle.NoPen)

        if live > 0.0:
            painter.save()
            painter.setClipPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            for arm in self._arms:
                glow, _ = self._press(arm.element_id)
                if glow <= 0.0:
                    continue
                painter.setBrush(self._limb_tint(arm, glow))
                painter.drawPath(self._path(arm.outline))
            painter.restore()
            self._glow(painter, path, live)

        for arm in self._arms:
            self._draw_chevron(painter, arm)

    def _limb_tint(self, arm: PadElement, glow: float) -> QRadialGradient:
        """The light a pressed direction throws, brightest at its own end."""
        tip = self._at(arm.x, arm.y)
        reach = self._u(max(arm.width, arm.height)) * 1.5
        tint = QRadialGradient(tip, reach)
        hot = QColor(PRESSED)
        hot.setAlpha(int(215 * glow))
        cool = QColor(PRESSED)
        cool.setAlpha(0)
        tint.setColorAt(0.0, hot)
        tint.setColorAt(0.55, QColor(hot.red(), hot.green(), hot.blue(),
                                     int(hot.alpha() * 0.45)))
        tint.setColorAt(1.0, cool)
        return tint

    def _draw_chevron(self, painter: QPainter, arm: PadElement) -> None:
        """The arrow cut into one limb of the cross."""
        span = self._u(min(arm.width, arm.height)) * 0.29
        if span < 2.0:
            return
        centre = self._at(arm.x, arm.y)
        reach = self._u(min(arm.width, arm.height)) * 0.30
        along = {
            "up": (0.0, -1.0), "down": (0.0, 1.0),
            "left": (-1.0, 0.0), "right": (1.0, 0.0),
        }[arm.glyph]
        across = (-along[1], along[0])
        tip = QPointF(centre.x() + along[0] * reach * 0.55,
                      centre.y() + along[1] * reach * 0.55)
        stroke = QPainterPath()
        stroke.moveTo(
            tip.x() - along[0] * span - across[0] * span,
            tip.y() - along[1] * span - across[1] * span,
        )
        stroke.lineTo(tip)
        stroke.lineTo(
            tip.x() - along[0] * span + across[0] * span,
            tip.y() - along[1] * span + across[1] * span,
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(GLYPH_INK, max(1.0, span * 0.22),
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(stroke)
        painter.setPen(Qt.PenStyle.NoPen)

    def _draw_stick(self, painter: QPainter, element: PadElement) -> None:
        """The well, the knurled flange standing in it, and the dished cap.

        The three circles do not share a centre: the flange and the cap sit
        low in the well, which is what a stick pointing at the viewer looks
        like from slightly above, and is the one place the picture admits to
        having a camera position at all.
        """
        glow, sink = self._press(element.element_id)
        (wx, wy, wr, _), flange, cap = element.rings
        dx, dy = self._deflection(element)
        drop = max(1.4, self._u(0.020)) * (1.0 - 0.6 * sink)
        sit = self._units(drop) * 0.3

        well = self._ellipse_path(wx, wy, wr, wr)
        bounds = well.boundingRect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(CONTACT_SHADE)
        painter.drawPath(well.translated(0.0, drop * 1.4))
        painter.setBrush(QColor(255, 255, 255, 150))
        painter.drawPath(well.translated(0.0, -drop * 0.5))
        painter.setBrush(_vertical(bounds, WELL_FLOOR_STOPS))
        painter.drawPath(well)
        # The wall of the recess: a wide stroke of its own mouth, half of it
        # landing outside the clip, which leaves a band of shade all the way
        # round the inside -- deepest at the top, where the wall is turned
        # away from the light.
        painter.save()
        painter.setClipPath(well)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for width, share in ((0.230, 0.33), (0.200, 0.33), (0.170, 0.33), (0.130, 0.33)):
            painter.setPen(QPen(
                QBrush(_vertical(bounds, WELL_WALL_STOPS, alpha=share)),
                max(1.5, self._u(width)),
            ))
            painter.drawPath(well)
        painter.restore()
        painter.setPen(Qt.PenStyle.NoPen)

        self._glow(painter, well, glow)

        # A stick that is being held tilts: the cap goes the whole way, the
        # flange it stands on barely moves, and neither ever leaves the mouth
        # of the well.
        painter.save()
        painter.setClipPath(well)
        base_x, base_y = dx * FLANGE_LEAN, dy * FLANGE_LEAN
        flange_path = self._ellipse_path(
            flange[0] + base_x, flange[1] + base_y + sit, flange[2], flange[3]
        )
        bounds = flange_path.boundingRect()
        painter.setBrush(QColor(64, 100, 94, 52))
        painter.drawPath(flange_path.translated(0.0, drop * 0.7))
        painter.setBrush(_vertical(bounds, FLANGE_STOPS, PRESSED, glow * 0.6))
        painter.drawPath(flange_path)
        self._draw_knurl(painter, element.element_id, flange_path,
                         self._u(base_x), self._u(base_y + sit))

        cap_path = self._ellipse_path(cap[0] + dx, cap[1] + dy + sit, cap[2], cap[3])
        cap_bounds = cap_path.boundingRect()
        painter.setBrush(QColor(64, 100, 94, 64))
        painter.drawPath(cap_path.translated(0.0, drop * 0.9))
        painter.setBrush(_vertical(cap_bounds, CAP_STOPS, PRESSED, glow * 0.7))
        painter.drawPath(cap_path)
        # The dish scooped out of the cap: a hair of light along its near lip.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 96), max(1.0, self._u(0.010))))
        painter.drawPath(cap_path.translated(0.0, max(1.0, self._u(0.012))))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.restore()
        self._legend(painter, element.label, cap_bounds, STICK_TYPE,
                     QFont.Weight.Medium)

    def _scatter_knurl(self, flange) -> QPainterPath:
        """The milled grip round a stick, as one path laid out at rest.

        Short scratches, low in contrast, at a random depth in the outer band
        and leaning off the radius by up to fifty degrees: strictly radial
        ticks read as the spokes of a wheel rather than as milling. Building
        the whole field once and translating it is what lets a stick that is
        being held repaint at frame rate.
        """
        cx, cy, rx, ry = flange
        rx, ry = self._u(rx), self._u(ry)
        path = QPainterPath()
        if min(rx, ry) < 8.0:
            return path
        centre = self._at(cx, cy)
        scatter = _Scatter(0x2545F491)
        for _ in range(min(KNURL_MAX, round(KNURL_DENSITY * rx * ry))):
            angle = scatter.next() * 2.0 * math.pi
            share = 0.73 + scatter.next() * 0.26
            px = centre.x() + rx * math.cos(angle) * share
            py = centre.y() + ry * math.sin(angle) * share
            lean = angle + scatter.spread(0.9)
            reach = (0.035 + scatter.next() * 0.07) * rx
            path.moveTo(px - math.cos(lean) * reach, py - math.sin(lean) * reach)
            path.lineTo(px + math.cos(lean) * reach, py + math.sin(lean) * reach)
        return path

    def _draw_knurl(self, painter: QPainter, element_id: str,
                    flange: QPainterPath, dx: float, dy: float) -> None:
        knurl = self._knurls.get(element_id)
        if knurl is None or knurl.isEmpty():
            return
        bounds = flange.boundingRect()
        # A tick is about a pixel wide however small the pad is drawn, so a
        # milling that reads as texture at full size reads as noise at half
        # of it. Fade it out rather than let it shout.
        opacity = max(0.0, min(1.0, (bounds.width() * 0.5 - 20.0) / 45.0))
        if opacity <= 0.0:
            return
        moved = knurl.translated(dx, dy)
        width = max(0.5, bounds.width() * 0.0065)
        painter.save()
        painter.setOpacity(opacity)
        painter.setClipPath(flange)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(100, 144, 135, 42), width))
        painter.drawPath(moved)
        painter.setPen(QPen(QColor(246, 255, 252, 54), width))
        painter.drawPath(moved.translated(width, width))
        painter.restore()
        painter.setPen(Qt.PenStyle.NoPen)

    def _draw_trigger_glow(self, painter: QPainter) -> None:
        """A pressed trigger lights its paddle as well as its readout bar."""
        for element_id, paddle in zip(("LT", "RT"), self._paddles):
            glow, _ = self._press(element_id)
            if glow <= 0.0:
                continue
            painter.save()
            painter.setClipPath(self._shoulder)
            painter.setPen(Qt.PenStyle.NoPen)
            tint = QColor(PRESSED)
            tint.setAlpha(int(215 * glow))
            painter.setBrush(tint)
            painter.drawPath(paddle)
            painter.restore()

    # -- helpers -----------------------------------------------------------

    def _units(self, pixels: float) -> float:
        return pixels / max(1e-6, self._projection.unit)

    def _ellipse_path(self, cx: float, cy: float, rx: float, ry: float) -> QPainterPath:
        centre = self._at(cx, cy)
        path = QPainterPath()
        path.addEllipse(centre, self._u(rx), self._u(ry))
        return path

    def _font(self, size: float, weight: QFont.Weight) -> QFont:
        pixels = max(6, int(round(self._u(size))))
        cached = self._fonts.get((str(weight), pixels))
        if cached is None:
            cached = QFont("Segoe UI Variable", -1, weight)
            cached.setPixelSize(pixels)
            self._fonts[(str(weight), pixels)] = cached
        return cached

    def _legend(self, painter: QPainter, text: str, bounds: QRectF,
                size: float, weight: QFont.Weight) -> None:
        if not text or bounds.width() < 8:
            return
        font = self._font(size, weight)
        metrics = QFontMetricsF(font)
        while metrics.horizontalAdvance(text) > bounds.width() * 0.86 and font.pixelSize() > 6:
            font = QFont(font)
            font.setPixelSize(font.pixelSize() - 1)
            metrics = QFontMetricsF(font)
        painter.setFont(font)
        painter.setPen(LEGEND)
        painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_icon(self, painter: QPainter, glyph: str, bounds: QRectF) -> None:
        """The view, menu, minus and plus marks, drawn rather than typeset."""
        centre = bounds.center()
        reach = min(bounds.width(), bounds.height()) * 0.30
        width = max(1.2, reach * 0.20)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(GLYPH_INK, width, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if glyph == "menu":
            for share in (-0.62, 0.0, 0.62):
                painter.drawLine(
                    QPointF(centre.x() - reach, centre.y() + reach * share),
                    QPointF(centre.x() + reach, centre.y() + reach * share),
                )
        elif glyph == "view":
            # Two overlapping panes: the copy mark the picture puts here.
            side = reach * 1.05
            painter.drawRect(QRectF(centre.x() - side, centre.y() - side,
                                    side * 1.15, side * 1.15))
            painter.drawRect(QRectF(centre.x() - side * 0.15, centre.y() - side * 0.15,
                                    side * 1.15, side * 1.15))
        elif glyph == "minus":
            painter.drawLine(QPointF(centre.x() - reach, centre.y()),
                             QPointF(centre.x() + reach, centre.y()))
        elif glyph == "plus":
            painter.drawLine(QPointF(centre.x() - reach, centre.y()),
                             QPointF(centre.x() + reach, centre.y()))
            painter.drawLine(QPointF(centre.x(), centre.y() - reach),
                             QPointF(centre.x(), centre.y() + reach))
        painter.setPen(Qt.PenStyle.NoPen)
