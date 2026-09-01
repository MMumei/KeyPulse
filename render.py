from __future__ import annotations

"""The bits the keyboard and the controller draw themselves with.

Both views are the same idea: a solid lying on a desk, lit from above and to
the left, seen through one shared camera, with a heat-coloured cap per input
and a legend on top of it. Everything that does not depend on which device is
on screen lives here, so the two canvases only describe their own geometry.
"""

import math
import time
from typing import Iterable, Sequence

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPolygonF,
    QRegion,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from i18n import CHINESE, language


CANVAS_BG = QColor("#FFFFFF")
ACCENT = QColor("#1FA58E")
WHITE = QColor("#FFFFFF")
ZOOM_MIN = 60
ZOOM_MAX = 230

# A single analogous ramp (pale mint -> teal -> deep teal) keeps the heat map
# in the same colour family as the rest of the interface.
IDLE_CAP = QColor("#EDF2F0")
ACTIVE_CAP = QColor("#8CF0D8")
CAP_SHADE = QColor("#5E706B")
CAP_EDGE = QColor("#94A5A0")
HEAT_STOPS = (
    (0.00, QColor("#DFEDE8")),
    (0.32, QColor("#A9DFCE")),
    (0.58, QColor("#69C7B0")),
    (0.80, QColor("#33A891")),
    (1.00, QColor("#15806F")),
)

# --- Scene geometry, in key units (1.0 == one 1u keycap pitch) --------------
PITCH_DEG = 51.0          # camera elevation above the deck plane
CAMERA_DISTANCE = 25.0    # smaller == stronger perspective
CAP_HEIGHT = 0.48         # keycap height above the plate
CASE_DEPTH = 1.02         # chassis thickness below the plate
WELL_DROP = 0.08          # how deep the key well is recessed
DECK_PAD_X = 0.36
DECK_PAD_TOP = 0.42
DECK_PAD_BOTTOM = 0.32
CANVAS_PAD = 26           # breathing room around the projected chassis
GROUND_PAD = 22           # extra room for the contact shadow and light spill
PULSE_SECONDS = 0.38
SINK_SECONDS = 0.11

# --- Backlighting ----------------------------------------------------------
# A spectrum wave travelling across the board, the way every mainstream
# per-key board ships out of the box. The light is the only place full
# saturation is allowed: caps, cards and chrome all stay on the mint ramp, so
# the heat map is never competing with the lighting for the same colours.
WAVE_STOPS = 13           # gradient stops one wave is sampled at
WAVE_SPREAD = 0.78        # how much of the hue circle fits across the board
WAVE_SATURATION = 0.74
# All of the light belongs around the switches: an LED lives under each one
# and there is none anywhere else, so the plate between the blocks keeps the
# colour it is moulded in.
LIGHT_RIM = 118           # the pool right at the foot of a cap
STRIKE_SECONDS = 0.30     # how long a key stays lit white after it is hit

# Per-face shading of a keycap, indexed by the edge of the top face the flank
# hangs from: 0 back, 1 right, 2 front, 3 left. The light sits above and to
# the left, so the left flank stays the brightest one.
FACE_SHADE = (0.56, 0.40, 0.48, 0.24)


def compact_number(value: int) -> str:
    """A count short enough for a card, in the units its language counts in.

    English groups digits in threes and so shortens with K, M and B. Chinese
    groups them in fours and shortens with 万 and 亿, which is the whole
    reason this is not one format string with a suffix table hung off it:
    330.0K is a number a Chinese reader has to convert before it means
    anything, and 33.0万 is the same number already converted.
    """
    if language() == CHINESE:
        if value < 10_000:
            return f"{value:,}"
        if value < 100_000_000:
            return f"{value / 10_000:.1f}万"
        return f"{value / 100_000_000:.1f}亿"
    if value < 1_000:
        return f"{value:,}"
    if value < 1_000_000:
        return f"{value / 1_000:.1f}K"
    if value < 1_000_000_000:
        return f"{value / 1_000_000:.1f}M"
    return f"{value / 1_000_000_000:.1f}B"


# Where a count stops being written out and starts being shortened. One rule
# for the whole app: the same total has to look the same whichever device is
# on screen, and a keycap is the tightest room any of them has to print in.
WRITTEN_OUT_BELOW = 10_000


def written(count: int) -> str:
    """A count as a device prints it on itself.

    Written out while it is short enough to be, shortened once it is not --
    which in Chinese is the same threshold either way, because that is exactly
    where 万 begins.
    """
    return compact_number(count) if count >= WRITTEN_OUT_BELOW else f"{count:,}"


def mix(first: QColor, second: QColor, amount: float) -> QColor:
    amount = max(0.0, min(1.0, amount))
    return QColor(
        round(first.red() + (second.red() - first.red()) * amount),
        round(first.green() + (second.green() - first.green()) * amount),
        round(first.blue() + (second.blue() - first.blue()) * amount),
    )


def lerp(first: QPointF, second: QPointF, amount: float) -> QPointF:
    return QPointF(
        first.x() + (second.x() - first.x()) * amount,
        first.y() + (second.y() - first.y()) * amount,
    )


def signed_area(points: Sequence[QPointF]) -> float:
    total = 0.0
    for index, current in enumerate(points):
        following = points[(index + 1) % len(points)]
        total += current.x() * following.y() - following.x() * current.y()
    return total


def faces_camera(quad: Sequence[QPointF]) -> bool:
    # Side quads are built as [top_a, top_b, base_b, base_a]. In screen space
    # (y pointing down) only the faces turned towards the viewer wind
    # counter-clockwise, which the shoelace sum reports as negative.
    return signed_area(quad) < 0.0


def shifted(points: Iterable[QPointF], dx: float = 0.0, dy: float = 0.0) -> QPolygonF:
    return QPolygonF([QPointF(point.x() + dx, point.y() + dy) for point in points])


def _corner_ratio(point: QPointF, neighbour: QPointF, radius: float) -> float:
    span = math.hypot(neighbour.x() - point.x(), neighbour.y() - point.y())
    return 0.5 if span < 1e-6 else min(0.5, radius / span)


def rounded_path(points: Sequence[QPointF], radius: float) -> QPainterPath:
    """Round every corner by the same number of pixels.

    Rounding by a fraction of each edge would blow the ends off a space bar
    while barely touching a 1u cap, so the radius is absolute.
    """
    path = QPainterPath()
    if len(points) < 3:
        return path
    for index, point in enumerate(points):
        previous = points[index - 1]
        following = points[(index + 1) % len(points)]
        entry = point + (previous - point) * _corner_ratio(point, previous, radius)
        exit_point = point + (following - point) * _corner_ratio(point, following, radius)
        if index == 0:
            path.moveTo(entry)
        else:
            path.lineTo(entry)
        path.quadTo(point, exit_point)
    path.closeSubpath()
    return path


def inset_ring(points: Sequence[QPointF], distance: float) -> list[QPointF]:
    """Walk a ring inwards along its own normals, by the same pixels everywhere.

    Shrinking towards the centroid would fold a pad outline through itself
    where the grips meet the shell; offsetting each vertex along the average
    of its two edge normals holds even through those notches. A negative
    distance pushes the ring outwards instead.
    """
    count = len(points)
    result: list[QPointF] = []
    for index, point in enumerate(points):
        total_x = total_y = 0.0
        for first, second in ((points[index - 1], point), (point, points[(index + 1) % count])):
            dx, dy = second.x() - first.x(), second.y() - first.y()
            span = math.hypot(dx, dy)
            if span > 1e-9:
                total_x += -dy / span
                total_y += dx / span
        span = math.hypot(total_x, total_y)
        if span < 1e-9:
            result.append(point)
            continue
        result.append(QPointF(
            point.x() + total_x / span * distance,
            point.y() + total_y / span * distance,
        ))
    return result


def convex_hull(points: Sequence[QPointF]) -> list[QPointF]:
    """The silhouette of a convex solid, from the corners of its two faces."""
    ordered = sorted({(round(p.x(), 3), round(p.y(), 3)) for p in points})
    if len(ordered) < 3:
        return [QPointF(x, y) for x, y in ordered]

    def turn(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    chain: list[tuple[float, float]] = []
    for pass_points in (ordered, reversed(ordered)):
        start = len(chain) + 1
        for point in pass_points:
            while len(chain) > start and turn(chain[-2], chain[-1], point) <= 0:
                chain.pop()
            chain.append(point)
        chain.pop()
    return [QPointF(x, y) for x, y in chain]


def ring_path(points: Sequence[QPointF]) -> QPainterPath:
    """A closed path straight through an already-smooth ring of points."""
    path = QPainterPath()
    if len(points) < 3:
        return path
    path.moveTo(points[0])
    for point in points[1:]:
        path.lineTo(point)
    path.closeSubpath()
    return path


class Projection:
    """One-point perspective for a device lying on a desk.

    Scene space is ``(x right, y towards the viewer, z up from the plate)``
    measured in key units. The camera looks down at ``PITCH_DEG`` from a
    finite distance, so far rows land higher *and* narrower than near ones,
    and every keycap away from the centre line shows one of its flanks.
    """

    __slots__ = (
        "unit", "origin", "_centre_x", "_centre_y", "_sin", "_cos", "_distance",
    )

    def __init__(
        self,
        width: float,
        height: float,
        unit: float,
        pitch_deg: float = PITCH_DEG,
        distance: float = CAMERA_DISTANCE,
    ) -> None:
        self.unit = unit
        self.origin = QPointF(0.0, 0.0)
        self._centre_x = width * 0.5
        self._centre_y = height * 0.5
        self._distance = distance
        pitch = math.radians(pitch_deg)
        self._sin = math.sin(pitch)
        self._cos = math.cos(pitch)

    def raw(self, x: float, y: float, z: float = 0.0) -> QPointF:
        away = self._centre_y - y
        distance = self._distance + away * self._cos - z * self._sin
        scale = self._distance / max(1.0, distance) * self.unit
        return QPointF(
            (x - self._centre_x) * scale,
            -(away * self._sin + z * self._cos) * scale,
        )

    def at(self, x: float, y: float, z: float = 0.0) -> QPointF:
        point = self.raw(x, y, z)
        return QPointF(point.x() + self.origin.x(), point.y() + self.origin.y())

    def quad(self, corners: Sequence[tuple[float, float]], z: float = 0.0) -> list[QPointF]:
        return [self.at(x, y, z) for x, y in corners]

    def ring(self, points: Sequence[tuple[float, float]], z: float = 0.0) -> list[QPointF]:
        return [self.at(x, y, z) for x, y in points]


def unit_for_zoom(zoom: int) -> float:
    return 58.0 * zoom / 100.0


def frame_for(projection: Projection, samples: Iterable[tuple[float, float, float]]) -> tuple[QSize, QPointF]:
    """Canvas size and drawing origin that hold every sampled scene point."""
    xs: list[float] = []
    ys: list[float] = []
    for x, y, z in samples:
        point = projection.raw(x, y, z)
        xs.append(point.x())
        ys.append(point.y())
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    size = QSize(
        math.ceil(max_x - min_x) + CANVAS_PAD * 2,
        math.ceil(max_y - min_y) + CANVAS_PAD * 2 + GROUND_PAD,
    )
    return size, QPointF(CANVAS_PAD - min_x, CANVAS_PAD - min_y)


class DeviceCanvas(QWidget):
    """Shared machinery: heat colours, the halo, pulses and clipped repaints.

    Subclasses own their geometry. They fill in ``layout_spec`` and
    ``_draw_order``, answer ``_frame`` with the canvas the current zoom needs,
    cache the screen rectangle of every moving part in ``_measure_regions``,
    and paint in ``paintEvent``.
    """

    def __init__(self, stats, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stats = stats
        self.zoom = 78
        self.layout_spec = None
        self._draw_order: tuple = ()
        self._active: dict[str, float] = {}
        self._peak_cache: int | None = None
        self._heat_cache: dict[int, QColor] = {}
        self._light_phase = 0.0
        self._wave_cache: tuple[QColor, ...] = ()
        # Whether this device's own lighting is switched on. Off means the
        # board is dark -- no wave, no halo, no strike -- and the light timer
        # never runs, so an unlit board costs nothing between keystrokes.
        self.lighting = True
        self._projection = Projection(1.0, 1.0, unit_for_zoom(self.zoom))
        self._suspended = False
        # Screen-space bookkeeping so a repaint can be clipped to the part of
        # the scene that actually moved. A full frame costs tens of
        # milliseconds, which is enough to stall a window drag on its own.
        self._key_rects: tuple[QRect, ...] = ()
        self._key_rect_by_id: dict[str, QRect] = {}
        self._light_region = QRegion()
        self.canvas_size = QSize(1, 1)
        # Which parts of the next frame have to be rebuilt. A lighting tick
        # damages only the gaps between the caps, so it must not drag the caps
        # -- by far the most expensive thing on the canvas -- along with it.
        self._light_tick = False
        self._caps_pending = False
        self._cap_damage = QRegion()
        self._legend_fonts: dict[tuple[str, str, str], QFont] = {}

        self._animation = QTimer(self)
        self._animation.setInterval(16)
        self._animation.timeout.connect(self._animate)
        self._light_timer = QTimer(self)
        self._light_timer.setInterval(50)
        self._light_timer.timeout.connect(self._advance_lighting)

        # Every paint fills its own clip rect, so Qt need not clear first.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # -- geometry, filled in by the subclass --------------------------------

    def _frame(self, unit: float) -> tuple[QSize, QPointF]:
        raise NotImplementedError

    def _measure_regions(self) -> None:
        raise NotImplementedError

    def _counted_ids(self) -> Iterable[str]:
        raise NotImplementedError

    # -- state -------------------------------------------------------------

    def set_zoom(self, zoom: int) -> None:
        zoom = max(ZOOM_MIN, min(ZOOM_MAX, int(zoom)))
        if zoom == self.zoom:
            return
        self.zoom = zoom
        self._rebuild_projection()
        self.update()

    def set_lighting(self, on: bool) -> None:
        on = bool(on)
        if on == self.lighting:
            return
        self.lighting = on
        self._wave_cache = ()
        if on and self.isVisible() and not self._suspended:
            self._light_timer.start()
        elif not on:
            self._light_timer.stop()
        self.redraw_caps()

    def size_for_zoom(self, zoom: int) -> QSize:
        return self._frame(unit_for_zoom(zoom))[0]

    def redraw_caps(self) -> None:
        """Repaint everything, caps included, on the next frame."""
        self._caps_pending = True
        self._cap_damage = QRegion(self.rect())
        self.update()

    def damage_cap(self, key_id: str) -> None:
        """Repaint one input and the ground it lights, and nothing else."""
        rect = self._key_rect_by_id.get(key_id)
        if rect is None:
            return
        self._caps_pending = True
        self._cap_damage = self._cap_damage.united(QRegion(rect))
        self.update(rect)

    def caps_to_redraw(self, event) -> QRegion | None:
        """Where this frame has to put caps down again, or None for nowhere.

        Read once at the top of a paint, and it resets what it read: a frame
        the light timer asked for gets None, one a keystroke asked for gets
        just that key, and one Qt asked for itself gets whatever Qt exposed.
        """
        pending, damage, tick = self._caps_pending, self._cap_damage, self._light_tick
        self._caps_pending, self._cap_damage, self._light_tick = False, QRegion(), False
        exposed = event.region()
        if tick and not pending and self._owned_by_lighting(exposed):
            return None
        return damage if not damage.isEmpty() else exposed

    def _owned_by_lighting(self, exposed: QRegion) -> bool:
        """Whether a lighting frame may leave every cap where it already is.

        A tick asks for the gaps between the caps and nothing else, but Qt
        merges its own damage into the same frame -- a resize, a move inside
        the scroll area, a plain expose -- and a swap of layout or zoom hands
        it several of those in a row. Painting one of them as a lighting
        frame would wipe the caps out of it and put nothing back, leaving a
        board of bare light that no later tick ever repairs, since the ticks
        that follow keep clear of the caps. So the shortcut is only taken
        where the light actually reaches.
        """
        return QRegion(exposed).subtracted(self._light_region).isEmpty()

    def _make_projection(self, unit: float) -> Projection:
        """The camera this device is seen through, at the given key unit.

        Shared by ``_frame`` and by the rebuild, so a subclass that wants its
        own elevation -- a pad is looked at from higher up than a keyboard --
        only has to say so once.
        """
        return Projection(self.layout_spec.width, self.layout_spec.height, unit)

    def _rebuild_projection(self) -> None:
        unit = unit_for_zoom(self.zoom)
        size, origin = self._frame(unit)
        projection = self._make_projection(unit)
        projection.origin = origin
        self._projection = projection
        self._legend_fonts.clear()
        # The widget is still the size the last projection left it, so what
        # _measure_regions builds has to be sized from here, not from self.
        self.canvas_size = size
        self._measure_regions()
        self.setFixedSize(size)
        self._caps_pending = True
        self._cap_damage = QRegion(QRect(0, 0, size.width(), size.height()))

    def pulse(self, key_id: str) -> None:
        # Counts only ever grow, so the peak can be nudged instead of rescanned.
        # Nudging it on every keystroke would rescale, and so repaint, the whole
        # heat map for a colour shift nobody can see, so the busiest key is let
        # run a little ahead of the peak before the board is redrawn; a count
        # above the peak simply saturates at the top of the ramp.
        count = self.stats.count(key_id)
        peak = self._peak_cache
        rescaled = peak is not None and count > peak and (
            peak < 64 or count > peak * 1.02 + 8
        )
        if rescaled:
            self._peak_cache = count
            self._heat_cache.clear()
        if not self.isVisible():
            # A device the window is not showing -- the other half of the
            # switch, or the whole window sitting in the tray -- keeps its
            # counts and its heat scale current but has nothing to animate.
            return
        self._active[key_id] = time.monotonic()
        if not self._suspended and not self._animation.isActive():
            self._animation.start()
        if rescaled:
            self.redraw_caps()
        else:
            self.damage_cap(key_id)

    def refresh_counts(self) -> None:
        """Re-read every count from the store, after it changed behind our back."""
        self._peak_cache = None
        self._heat_cache.clear()
        self.redraw_caps()

    def release(self, key_id: str) -> None:
        # Keep a short afterglow so fast taps remain visible.
        if key_id in self._active:
            self._active[key_id] = min(self._active[key_id], time.monotonic() - 0.04)

    def _animate(self) -> None:
        now = time.monotonic()
        # Collect the rectangles before the expired keys are dropped: the last
        # frame of a pulse still has to wipe the glow it leaves behind.
        region = QRegion()
        for key_id in self._active:
            rect = self._key_rect_by_id.get(key_id)
            if rect is not None:
                region = region.united(rect)
        self._active = {
            key: started for key, started in self._active.items() if now - started < PULSE_SECONDS
        }
        if not self._active:
            self._animation.stop()
        self._caps_pending = True
        self._cap_damage = self._cap_damage.united(region)
        self.update(region)

    def _advance_lighting(self) -> None:
        if not self.lighting or self._light_region.isEmpty():
            # Nothing on this device changes colour -- a pad whose real
            # counterpart ships unlit, say. Asking for a frame here would
            # only leave the caps flag set for whoever paints next.
            return
        self._light_phase = (self._light_phase + 0.0094) % 1.0
        self._wave_cache = ()
        self._light_tick = True
        region = QRegion(self._light_region)
        for key_id in self._active:
            # A struck input paints a ring on the plate around itself; the
            # lighting has to bring it along or it would clip that ring.
            rect = self._key_rect_by_id.get(key_id)
            if rect is not None:
                region = region.united(QRegion(rect))
                self._caps_pending = True
                self._cap_damage = self._cap_damage.united(QRegion(rect))
        self.update(region)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # Qt paints an exposed widget without being asked, and that frame has
        # to carry the caps whatever the light timer was in the middle of.
        self._caps_pending = True
        if self.lighting and not self._suspended:
            self._light_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        # Nothing to shimmer while the window sits in the tray.
        self._light_timer.stop()
        super().hideEvent(event)

    def suspend(self) -> None:
        """Hold the animations, for gestures that need the main thread."""
        self._suspended = True
        self._light_timer.stop()
        self._animation.stop()

    def resume(self) -> None:
        self._suspended = False
        if not self.isVisible():
            return
        if self.lighting:
            self._light_timer.start()
        if self._active and not self._animation.isActive():
            self._animation.start()

    # -- colour ------------------------------------------------------------

    def _peak(self) -> int:
        if self._peak_cache is None:
            self._peak_cache = max(
                (self.stats.count(key_id) for key_id in self._counted_ids()), default=0
            )
        return self._peak_cache

    def _heat_color(self, count: int) -> QColor:
        peak = self._peak()
        if count <= 0 or peak <= 0:
            return IDLE_CAP
        cached = self._heat_cache.get(count)
        if cached is not None:
            return cached
        # Logarithmic scaling keeps both ordinary and very frequent keys distinguishable.
        strength = max(0.0, min(1.0, math.log1p(count) / math.log1p(peak)))
        color = HEAT_STOPS[-1][1]
        for index in range(len(HEAT_STOPS) - 1):
            low_stop, low_color = HEAT_STOPS[index]
            high_stop, high_color = HEAT_STOPS[index + 1]
            if strength <= high_stop:
                span = high_stop - low_stop
                ratio = 0.0 if span <= 0 else (strength - low_stop) / span
                color = mix(low_color, high_color, ratio)
                break
        self._heat_cache[count] = color
        return color

    @staticmethod
    def _luminance(color: QColor) -> float:
        return (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255.0

    def wave_color(self, position: float) -> QColor:
        """The colour the wave is showing at ``position`` (0..1) right now."""
        hue = (self._light_phase + position * WAVE_SPREAD) % 1.0
        return QColor.fromHsvF(hue, WAVE_SATURATION, 1.0)

    def _wave_colors(self) -> tuple[QColor, ...]:
        if not self._wave_cache:
            self._wave_cache = tuple(
                self.wave_color(index / (WAVE_STOPS - 1)) for index in range(WAVE_STOPS)
            )
        return self._wave_cache

    def _wave_gradient(self, start: QPointF, end: QPointF, alpha: int) -> QLinearGradient:
        gradient = QLinearGradient(start, end)
        for index, color in enumerate(self._wave_colors()):
            tinted = QColor(color)
            tinted.setAlpha(alpha)
            gradient.setColorAt(index / (WAVE_STOPS - 1), tinted)
        return gradient

    # -- legends -----------------------------------------------------------

    def _draw_legend(
        self,
        painter: QPainter,
        key_id: str,
        label: str,
        count: int,
        face: QRectF,
        cap: QColor,
        show_count: bool = True,
        inline: bool = False,
    ) -> None:
        if face.width() < 8 or face.height() < 8:
            return
        # Legends flip to light type once the cap is dark enough that dark
        # type would stop being readable.
        if self._luminance(cap) < 0.55:
            label_color = QColor(255, 255, 255, 246)
            count_color = QColor(255, 255, 255, 210)
        else:
            label_color = QColor("#223B35")
            count_color = QColor("#47605A") if count else QColor(122, 142, 136, 128)

        unit = self._projection.unit

        def fitted(area: QRectF, share: float) -> int:
            # A cap is a wide box, so the key unit sets the type size; a
            # bumper is a shallow one, and there the height has to, or the
            # legend would spill over the edge of the face it belongs to.
            return max(6, min(int(unit * share), int(area.height() * 0.58)))

        if not show_count:
            painter.setFont(self._legend_font(
                key_id, "label", label,
                fitted(face, 0.165 if len(label) > 4 else 0.205),
                QFont.Weight.DemiBold, face.width() - 3,
            ))
            painter.setPen(label_color)
            painter.drawText(face, Qt.AlignmentFlag.AlignCenter, label)
            return

        count_text = written(count)
        if inline:
            # A bumper is a long shallow bar. Stacking a name over a counter
            # there would force it to be deep enough to look like a lozenge
            # rather than the strip of moulding it is, so the two sit side by
            # side instead and the bar keeps its real proportions.
            room = QRectF(face.left() + face.width() * 0.06, face.top(),
                          face.width() * 0.88, face.height())
            painter.setFont(self._legend_font(
                key_id, "label", label, fitted(room, 0.150), QFont.Weight.DemiBold,
                room.width() * 0.45,
            ))
            painter.setPen(label_color)
            painter.drawText(
                room, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label
            )
            painter.setFont(self._legend_font(
                key_id, "count", count_text, fitted(room, 0.135), QFont.Weight.Medium,
                room.width() * 0.52,
            ))
            painter.setPen(count_color)
            painter.drawText(
                room, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, count_text
            )
            return

        label_area = QRectF(
            face.left(), face.top() + face.height() * 0.04, face.width(), face.height() * 0.50
        )
        count_area = QRectF(
            face.left(), face.top() + face.height() * 0.50, face.width(), face.height() * 0.44
        )

        painter.setFont(self._legend_font(
            key_id, "label", label,
            fitted(label_area, 0.165 if len(label) > 4 else 0.205),
            QFont.Weight.DemiBold, label_area.width() - 3,
        ))
        painter.setPen(label_color)
        painter.drawText(label_area, Qt.AlignmentFlag.AlignCenter, label)

        painter.setFont(self._legend_font(
            key_id, "count", count_text,
            fitted(count_area, 0.155), QFont.Weight.Medium, count_area.width() - 3,
        ))
        painter.setPen(count_color)
        painter.drawText(count_area, Qt.AlignmentFlag.AlignCenter, count_text)

    def _legend_font(
        self, key_id: str, role: str, text: str, size: int, weight: QFont.Weight, width: float
    ) -> QFont:
        """The largest font at or below ``size`` whose ``text`` fits ``width``.

        Measuring a string is one of the more expensive things a frame does,
        and the answer only moves when the projection or the text does, so the
        fitted font is memoised per key and dropped with the projection.
        """
        cache_key = (key_id, role, text)
        font = self._legend_fonts.get(cache_key)
        if font is not None:
            return font
        font = QFont("Segoe UI Variable", size, weight)
        while size > 5 and QFontMetrics(font).horizontalAdvance(text) > width:
            size -= 1
            font.setPointSize(size)
        if len(self._legend_fonts) > 2048:
            # Counters keep minting new strings; start over rather than grow.
            self._legend_fonts.clear()
        self._legend_fonts[cache_key] = font
        return font
