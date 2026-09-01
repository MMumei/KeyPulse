from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QCloseEvent,
    QFont,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QStyle,
    QStyleOption,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from gallery import GalleryPage
from gamepads import BUTTON_LABELS, DEFAULT_MODEL, MODEL_ORDER, MODELS
from i18n import LANGUAGE_BUTTON, Wording, other_language, set_language, tr
from layouts import KEY_LABELS, LAYOUT_ORDER, LAYOUTS, KeyboardLayout, KeySpec
from pad_canvas import GamepadCanvas
from render import (
    ACCENT,
    ACTIVE_CAP,
    LIGHT_RIM,
    STRIKE_SECONDS,
    CANVAS_BG,
    CAP_EDGE,
    CAP_HEIGHT,
    CAP_SHADE,
    CASE_DEPTH,
    DECK_PAD_BOTTOM,
    DECK_PAD_TOP,
    DECK_PAD_X,
    FACE_SHADE,
    PULSE_SECONDS,
    SINK_SECONDS,
    WELL_DROP,
    WHITE,
    ZOOM_MAX,
    ZOOM_MIN,
    DeviceCanvas,
    Projection,
    compact_number,
    convex_hull,
    faces_camera,
    frame_for,
    inset_ring,
    lerp,
    mix,
    rounded_path,
    shifted,
)
from storage import (
    DEFAULT_SETTINGS,
    GAMEPAD_DEVICE,
    KEYBOARD_DEVICE,
    SNAPSHOT_DIR_NAME,
    SettingsStore,
    StatsStore,
    is_startup_enabled,
    set_startup_enabled,
)


# Width in key units and opacity of each pass of the pool a switch throws
# onto the plate, widest and faintest first.
RIM_PASSES = ((0.36, 52), (0.20, 80), (0.09, LIGHT_RIM))

# The halo strip along the chassis and the pool it throws on the desk are the
# board's underglow, and they are deliberately not part of the wave above
# them: one steady mint, the console's own accent, so the two layers read as
# what they are instead of two rainbows competing across the same board.
HALO_LIGHT = QColor("#33C6AC")


def halo(alpha: int) -> QColor:
    """The underglow colour, at the strength one of its passes wants."""
    return QColor(HALO_LIGHT.red(), HALO_LIGHT.green(), HALO_LIGHT.blue(), alpha)

# The three things the light beside the title can be saying, and how each one
# is dressed. LIVE is the ordinary answer on both devices -- KeyPulse is
# reading what is on screen -- so it stays a quiet word next to KEYPULSE.
# The other two are things to notice, and they are worn as a chip: MISSING is
# the amber of something waiting to be plugged in, ALERT the red of something
# that went wrong. Nothing here changes the height of the header row, which
# the buttons beside it set.
LIVE, MISSING, ALERT = "live", "missing", "alert"

STATUS_STYLE = {
    LIVE: "color: #159078;",
    MISSING: (
        "color: #a3711b; background: #fdf4e4; border: 1px solid #f0dfc0;"
        "border-radius: 9px; padding: 2px 9px;"
    ),
    ALERT: (
        "color: #b7483f; background: #fdf1ef; border: 1px solid #f1d3ce;"
        "border-radius: 9px; padding: 2px 9px;"
    ),
}

KEY_INSET = 0.06        # the gap the light comes up through, in key units
WELL_INSET = 0.24       # how far the plate sits inside the shell
LIGHT_CLEARANCE = 3.0   # pixels of plate a cap keeps to itself, for its shadow


def measure(layout: KeyboardLayout, unit: float) -> tuple[QSize, QPointF]:
    """Canvas size and drawing origin for a layout at a given key-unit size."""
    projection = Projection(layout.width, layout.height, unit)
    samples = [
        (x, y, z)
        for x in (-DECK_PAD_X, layout.width + DECK_PAD_X)
        for y in (-DECK_PAD_TOP, layout.height + DECK_PAD_BOTTOM)
        for z in (-CASE_DEPTH, CAP_HEIGHT)
    ]
    return frame_for(projection, samples)


def app_icon(size: int = 128) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#F7FAF8"))
    painter.setPen(QPen(QColor("#C8D8D2"), max(2, size // 32)))
    painter.drawRoundedRect(QRectF(4, 4, size - 8, size - 8), size * 0.24, size * 0.24)
    key_size = size * 0.23
    gap = size * 0.055
    start = (size - (key_size * 3 + gap * 2)) / 2
    for row in range(3):
        for col in range(3):
            rect = QRectF(start + col * (key_size + gap), start + row * (key_size + gap), key_size, key_size)
            active = (row, col) == (1, 1)
            painter.setBrush(ACCENT if active else QColor("#C7D4D0"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, size * 0.04, size * 0.04)
    painter.end()
    return QIcon(pixmap)


def add_soft_shadow(widget: QWidget, blur: int = 28, y_offset: int = 7, alpha: int = 24) -> None:
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y_offset)
    shadow.setColor(QColor(42, 66, 58, alpha))
    widget.setGraphicsEffect(shadow)


class ToggleSwitch(QCheckBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(46, 26)

    def hitButton(self, pos: QPoint) -> bool:  # noqa: N802
        """The whole pill takes a click, not just the box a checkbox would have.

        QCheckBox accepts clicks only inside the indicator its style would
        draw -- about 15px at the left edge -- and this one is painted as a
        46px switch instead. So two thirds of what looks clickable was dead,
        the knob of a switch that is on among it, and the toggle read as one
        that ignores clicks at random.
        """
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#39B9A1") if self.isChecked() else QColor("#D8E1DE"))
        painter.drawRoundedRect(QRectF(1, 2, 44, 22), 11, 11)
        painter.setBrush(WHITE)
        painter.setPen(QPen(QColor(40, 70, 62, 22), 0.8))
        painter.drawEllipse(QRectF(23 if self.isChecked() else 3, 4, 18, 18))
        painter.end()


class KeyboardScrollArea(QScrollArea):
    """An endless whiteboard the device floats on.

    The wheel scales the device and nothing else -- the card around it keeps
    the size the window gave it, however far the board is zoomed in -- and a
    drag slides the view under the pointer, so a board grown past the card is
    still reachable without a scrollbar cutting across it.
    """

    zoom_requested = Signal(int, QPointF)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._panning = False
        self._grabbed = QPoint()
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            # The pointer is the anchor: what is under it stays under it.
            self.zoom_requested.emit(1 if delta > 0 else -1, event.position())
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._panning = True
            self._grabbed = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._panning:
            super().mouseMoveEvent(event)
            return
        point = event.position().toPoint()
        delta = point - self._grabbed
        self._grabbed = point
        for bar, step in (
            (self.horizontalScrollBar(), delta.x()),
            (self.verticalScrollBar(), delta.y()),
        ):
            bar.setValue(bar.value() - step)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            self._panning = False
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def pan_to(self, x: int, y: int) -> None:
        """Slide the view so the given canvas pixel lands where it was asked.

        Called straight after the widget was resized, before Qt has had a
        chance to work the new scrollbar ranges out, so the value is clamped
        here against the geometry we already know rather than by the bar.
        """
        widget = self.widget()
        if widget is None:
            return
        viewport = self.viewport().size()
        for bar, wanted, room in (
            (self.horizontalScrollBar(), x, widget.width() - viewport.width()),
            (self.verticalScrollBar(), y, widget.height() - viewport.height()),
        ):
            bar.setRange(0, max(0, room))
            bar.setValue(max(0, min(max(0, room), wanted)))


class KeyboardCanvas(DeviceCanvas):
    def __init__(self, stats: StatsStore, parent: QWidget | None = None) -> None:
        super().__init__(stats, parent)
        self._rim_edges = QPainterPath()
        # Whether a frame went out without the backlight because a gesture was
        # still moving the board. The debt is paid the moment it settles.
        self._rim_owed = False
        self.set_layout("full")

    def resume(self) -> None:
        super().resume()
        if self._rim_owed:
            self._rim_owed = False
            self.redraw_caps()

    # -- state -------------------------------------------------------------

    def set_layout(self, layout_id: str) -> None:
        self.layout_spec = LAYOUTS.get(layout_id, LAYOUTS["full"])
        # Painter's algorithm: far rows go down first so the near ones can
        # overlap them with their flanks.
        self._draw_order = tuple(
            sorted(self.layout_spec.keys, key=lambda key: (key.y + key.height, key.x))
        )
        self._peak_cache = None
        self._heat_cache.clear()
        self._rebuild_projection()
        self.update()

    def _frame(self, unit: float) -> tuple[QSize, QPointF]:
        return measure(self.layout_spec, unit)

    def _counted_ids(self):
        return [key.key_id for key in self.layout_spec.keys]

    def _measure_regions(self) -> None:
        """Cache the screen rectangle each moving part of the scene occupies.

        None of this changes between frames, so the repaint paths can ask what
        they have to invalidate instead of falling back to the whole widget.
        """
        projection = self._projection
        layout = self.layout_spec

        rects: list[QRect] = []
        silhouettes: list[QRegion] = []
        edges = QPainterPath()
        radius = projection.unit * 0.13
        for key in self._draw_order:
            corners = (
                (key.x + KEY_INSET, key.y + KEY_INSET),
                (key.x + key.width - KEY_INSET, key.y + KEY_INSET),
                (key.x + key.width - KEY_INSET, key.y + key.height - KEY_INSET),
                (key.x + KEY_INSET, key.y + key.height - KEY_INSET),
            )
            base = projection.quad(corners)
            points = base + projection.quad(corners, CAP_HEIGHT)
            # Slack for the contact shadow under the cap and for the glow ring
            # an active key paints outside its own outline.
            rects.append(QPolygonF(points).boundingRect().adjusted(-8, -8, 8, 8).toAlignedRect())
            # The lit edge of the switch housing, right at the foot of the cap.
            edges.addPath(rounded_path(base, radius))
            # A cap keeps the light off itself and off its own contact shadow,
            # so the glow can be repainted without repainting any cap.
            hull = convex_hull(points)
            silhouettes.append(QRegion(
                QPolygonF(inset_ring(hull, -LIGHT_CLEARANCE)).toPolygon()
            ))
        self._key_rects = tuple(rects)
        self._key_rect_by_id = {key.key_id: rect for key, rect in zip(self._draw_order, rects)}
        self._build_rim_map(edges)

        left, right = -DECK_PAD_X, layout.width + DECK_PAD_X
        top, bottom = -DECK_PAD_TOP, layout.height + DECK_PAD_BOTTOM
        outline = ((left, top), (right, top), (right, bottom), (left, bottom))
        deck = projection.quad(outline)
        floor = projection.quad(outline, -CASE_DEPTH)

        # The backlight washes the whole plate; what is actually *seen* of it
        # is the lattice the caps leave behind, and that is what a lighting
        # frame repaints.
        inner = (
            (left + WELL_INSET, top + WELL_INSET),
            (right - WELL_INSET, top + WELL_INSET),
            (right - WELL_INSET, bottom - WELL_INSET + 0.02),
            (left + WELL_INSET, bottom - WELL_INSET + 0.02),
        )
        well = projection.quad(inner, -WELL_DROP)
        self._well_path = rounded_path(well, projection.unit * 0.11)
        self._wave_start = QPointF(well[0].x(), well[0].y())
        self._wave_end = QPointF(well[2].x(), well[2].y())
        # One region with a hole per cap, rather than a ring around each: it
        # covers more plate than the light actually reaches, but a plate fill
        # is cheap and a region of 87 separate annuli is not.
        lattice = QRegion(QPolygonF(well).toPolygon())
        for silhouette in silhouettes:
            lattice = lattice.subtracted(silhouette)

        # The shimmer only reaches the chassis flanks that face the camera and
        # the light they spill onto the desk, so keep those as a region rather
        # than one rectangle spanning the whole board.
        region = QRegion(lattice)
        for index in range(4):
            following = (index + 1) % 4
            quad = [deck[index], deck[following], floor[following], floor[index]]
            if faces_camera(quad):
                region = region.united(
                    QPolygonF(quad).boundingRect().adjusted(-2, -2, 2, 2).toAlignedRect()
                )
        spill = QPolygonF([
            QPointF(floor[3].x() - 4, floor[3].y() + 2),
            QPointF(floor[2].x() + 4, floor[2].y() + 2),
            QPointF(floor[2].x() - 14, floor[2].y() + 18),
            QPointF(floor[3].x() + 14, floor[3].y() + 18),
        ])
        self._light_region = region.united(
            spill.boundingRect().adjusted(-2, -2, 2, 2).toAlignedRect()
        )

    def _build_rim_map(self, edges: QPainterPath) -> None:
        """Keep the housing outlines. Stroking them waits until one is needed.

        Stroking a hundred rounded outlines three times over costs more than
        everything else a rebuild does put together, and it buys nothing at
        all unless the lighting is on and a frame is about to paint it. A
        wheel turn walks the zoom through a dozen rebuilds and shows one of
        them, so a rebuild that strokes eagerly pays for eleven boards nobody
        ever sees -- which is what made a wheel turn stutter.
        """
        self._rim_edges = edges
        self._rim_map = None
        self._rim_tinted = None
        self._rim_phase = None

    def _stroke_rim(self) -> None:
        """The shape of the light, in white, at the projection it belongs to.

        Only its colour is renewed per frame, in ``_tinted_rim``; blitting the
        result costs essentially nothing, which is what lets the wave animate.
        """
        ratio = self.devicePixelRatioF()
        size = self.canvas_size * ratio
        self._rim_map = QPixmap(size)
        self._rim_map.setDevicePixelRatio(ratio)
        self._rim_map.fill(Qt.GlobalColor.transparent)
        unit = self._projection.unit
        painter = QPainter(self._rim_map)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Three outlines of the same shape, narrowing and brightening: the
        # falloff is what separates a lit board from a coloured one.
        for width, alpha in RIM_PASSES:
            painter.setPen(QPen(QColor(255, 255, 255, alpha), max(1.2, unit * width)))
            painter.drawPath(self._rim_edges)
        painter.end()
        self._rim_tinted = QPixmap(size)
        # A bare QPixmap has no alpha channel, and everything the rim map does
        # not cover would then blit as opaque black over the whole case.
        self._rim_tinted.fill(Qt.GlobalColor.transparent)
        self._rim_tinted.setDevicePixelRatio(ratio)
        self._rim_phase = None

    def _tinted_rim(self) -> QPixmap:
        """The rim map in the colours the wave is showing this instant."""
        if self._rim_map is None:
            self._stroke_rim()
        if self._rim_phase == self._light_phase:
            return self._rim_tinted
        painter = QPainter(self._rim_tinted)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawPixmap(0, 0, self._rim_map)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(
            QRect(QPoint(0, 0), self.canvas_size),
            self._wave_gradient(self._wave_start, self._wave_end, 255),
        )
        painter.end()
        self._rim_phase = self._light_phase
        return self._rim_tinted

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        # Qt has already clipped the painter to the damaged region; dropping
        # the keys outside it is what keeps a shimmer step or a single
        # keystroke from costing a whole frame of the board. A lighting frame
        # asks for no caps at all -- the backlight only ever shows in the gaps
        # between them, which is exactly where a real board puts it.
        caps = self.caps_to_redraw(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(event.rect(), CANVAS_BG)
        self._draw_case(painter, shell=caps is not None)
        self._draw_backlight(painter)
        if caps is not None:
            for key, bounds in zip(self._draw_order, self._key_rects):
                if caps.intersects(bounds):
                    self._draw_key(painter, key)
        painter.end()

    def _draw_backlight(self, painter: QPainter) -> None:
        """The per-key LEDs, seen the only way they ever are: from underneath.

        Two passes over the whole plate, both hidden under the caps drawn
        afterwards. The wash is the bloom the switch housings throw onto the
        plate; the stroke is the hot ring at the foot of each cap, which is
        the part that actually reads as light coming up out of the board.
        """
        if not self.lighting:
            return
        if self._rim_map is None and self._suspended:
            # A gesture is in flight -- a wheel turn, a drag -- so the board is
            # about to move again. Stroking the light for a projection with
            # that little left to live is the one thing a zoom cannot afford,
            # so the frame goes out without it and owes it. Only the glow at
            # the foot of the caps is missing meanwhile, and the pointer
            # settles long before an eye finds it gone.
            self._rim_owed = True
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPixmap(0, 0, self._tinted_rim())

    def _draw_case(self, painter: QPainter, shell: bool = True) -> None:
        """The chassis under the keys.

        A lighting frame passes ``shell=False``: the parts of the case that
        never change -- the contact shadow on the desk and the top bezel --
        lie outside the plate or under it, so repainting them would only cost
        the frame the whole board over again. The halo and the light it
        spills onto the desk do change, so those are always drawn.
        """
        projection = self._projection
        layout = self.layout_spec
        left, right = -DECK_PAD_X, layout.width + DECK_PAD_X
        top, bottom = -DECK_PAD_TOP, layout.height + DECK_PAD_BOTTOM
        outline = ((left, top), (right, top), (right, bottom), (left, bottom))
        deck = projection.quad(outline)
        floor = projection.quad(outline, -CASE_DEPTH)

        painter.setPen(Qt.PenStyle.NoPen)
        radius = projection.unit * 0.2
        # Stacked passes that shrink as they drop fake a penumbra far more
        # cheaply than a real blur.
        for step in range(5 if shell else 0):
            spread = step / 4.0
            bleed = 6.0 - 12.0 * spread
            painter.setBrush(QColor(34, 54, 48, round(30 - 22 * spread)))
            painter.drawPath(rounded_path(
                [
                    QPointF(
                        point.x() + (bleed if index in (0, 3) else -bleed),
                        point.y() + 3 + 15 * spread,
                    )
                    for index, point in enumerate(floor)
                ],
                radius,
            ))

        # Light spilling from the halo onto the desk in front of the board.
        if self.lighting:
            painter.setBrush(halo(26))
            painter.drawPath(rounded_path([
                QPointF(floor[3].x() - 4, floor[3].y() + 2),
                QPointF(floor[2].x() + 4, floor[2].y() + 2),
                QPointF(floor[2].x() - 14, floor[2].y() + 18),
                QPointF(floor[3].x() + 14, floor[3].y() + 18),
            ], radius))

        # Machined chassis: only the flanks actually turned towards the camera
        # are drawn, which is what makes the block read as solid.
        for index in range(4):
            following = (index + 1) % 4
            quad = [deck[index], deck[following], floor[following], floor[index]]
            if not faces_camera(quad):
                continue
            shell = QLinearGradient(deck[index], floor[index])
            shell.setColorAt(0.00, QColor("#E9EFEC"))
            shell.setColorAt(0.15, QColor("#D3DCD8"))
            shell.setColorAt(0.70, QColor("#ACB9B4"))
            shell.setColorAt(1.00, QColor("#87948F"))
            painter.setBrush(shell)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF(quad))
            self._draw_light_band(painter, deck[index], deck[following], floor[index], floor[following])

        # Top shell and a shallow inset key well give the clean bezel of a
        # CNC aluminium board.
        if shell:
            deck_gradient = QLinearGradient(deck[0], deck[3])
            deck_gradient.setColorAt(0.0, QColor("#FBFCFC"))
            deck_gradient.setColorAt(0.46, QColor("#EFF4F2"))
            deck_gradient.setColorAt(1.0, QColor("#DFE8E5"))
            painter.setBrush(deck_gradient)
            painter.setPen(QPen(QColor("#C7D3CF"), 1.15))
            painter.drawPath(rounded_path(deck, projection.unit * 0.16))

        inner = (
            (left + WELL_INSET, top + WELL_INSET),
            (right - WELL_INSET, top + WELL_INSET),
            (right - WELL_INSET, bottom - WELL_INSET + 0.02),
            (left + WELL_INSET, bottom - WELL_INSET + 0.02),
        )
        well = projection.quad(inner, -WELL_DROP)
        lip = projection.quad(inner)
        # The far inner wall of the well is the only one the camera can see.
        painter.setPen(Qt.PenStyle.NoPen)
        if shell:
            painter.setBrush(QColor("#B9C7C2"))
            painter.drawPolygon(QPolygonF([lip[0], lip[1], well[1], well[0]]))
        # The plate the switches sit on, kept a shade deeper than the shell so
        # the backlight painted over it next has something to read against.
        well_gradient = QLinearGradient(well[0], well[3])
        well_gradient.setColorAt(0.0, QColor("#DBE5E1"))
        well_gradient.setColorAt(1.0, QColor("#E8EFEC"))
        painter.setBrush(well_gradient)
        painter.setPen(QPen(QColor("#C3D0CB"), 0.9))
        painter.drawPath(self._well_path)

    def _draw_light_band(
        self, painter: QPainter, top_a: QPointF, top_b: QPointF, bottom_a: QPointF, bottom_b: QPointF
    ) -> None:
        """Halo lighting recessed behind a diffuser in one chassis flank."""

        def band(low: float, high: float) -> list[QPointF]:
            return [
                lerp(top_a, bottom_a, low), lerp(top_b, bottom_b, low),
                lerp(top_b, bottom_b, high), lerp(top_a, bottom_a, high),
            ]

        painter.setPen(Qt.PenStyle.NoPen)
        if self.lighting:
            painter.setBrush(halo(42))
            painter.drawPolygon(QPolygonF(band(0.34, 0.74)))
            painter.setBrush(halo(235))
        else:
            # Switched off, the diffuser does not disappear -- it goes back to
            # the milky white strip it is moulded from, with no bloom around it.
            painter.setBrush(QColor("#DCE4E1"))
        painter.setPen(QPen(QColor(255, 255, 255, 105), 0.8))
        painter.drawPath(rounded_path(band(0.45, 0.59), self._projection.unit * 0.04))

        painter.setPen(Qt.PenStyle.NoPen)
        rail = QLinearGradient(lerp(top_a, bottom_a, 0.74), bottom_a)
        rail.setColorAt(0.0, QColor("#A9B5B1"))
        rail.setColorAt(1.0, QColor("#7E8B87"))
        painter.setBrush(rail)
        painter.drawPolygon(QPolygonF(band(0.74, 1.0)))

        painter.setPen(QPen(QColor(255, 255, 255, 92), 0.9))
        painter.drawLine(lerp(top_a, bottom_a, 0.07), lerp(top_b, bottom_b, 0.07))
        painter.setPen(QPen(QColor("#6D7B76"), 1.0))
        painter.drawLine(bottom_a, bottom_b)

    def _draw_key(self, painter: QPainter, key: KeySpec) -> None:
        started = self._active.get(key.key_id)
        elapsed = time.monotonic() - started if started is not None else None
        active = elapsed is not None and 0.0 <= elapsed < PULSE_SECONDS
        glow = max(0.0, 1.0 - elapsed / PULSE_SECONDS) if active else 0.0
        sink = max(0.0, 1.0 - elapsed / SINK_SECONDS) if active else 0.0

        count = self.stats.count(key.key_id)
        cap = ACTIVE_CAP if active else self._heat_color(count)

        projection = self._projection
        corners = (
            (key.x + KEY_INSET, key.y + KEY_INSET),
            (key.x + key.width - KEY_INSET, key.y + KEY_INSET),
            (key.x + key.width - KEY_INSET, key.y + key.height - KEY_INSET),
            (key.x + KEY_INSET, key.y + key.height - KEY_INSET),
        )
        top_z = CAP_HEIGHT * (1.0 - 0.62 * sink)
        base = projection.quad(corners)
        top = projection.quad(corners, top_z)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(38, 62, 56, 30))
        painter.drawPolygon(shifted(base, 0, 2.0))
        if glow > 0.0:
            # Reactive lighting: the LED under a struck switch goes to white
            # and falls back into the wave, so a burst of typing reads as a
            # trail of sparks across the board. With the light off there is no
            # LED to flash -- only the mint ring below, which is the app's own
            # feedback rather than the board's.
            if self.lighting:
                strike = max(0.0, 1.0 - (time.monotonic() - started) / STRIKE_SECONDS)
                painter.setBrush(QColor(255, 255, 255, int(90 * strike)))
                painter.setPen(QPen(QColor(255, 255, 255, int(175 * strike)),
                                    max(2.0, projection.unit * 0.12)))
                painter.drawPath(rounded_path(list(shifted(base, 0, 1)), projection.unit * 0.13))
            painter.setBrush(QColor(102, 232, 202, int(70 * glow)))
            painter.setPen(QPen(QColor(31, 165, 142, int(150 * glow)), 4))
            painter.drawPath(rounded_path(list(shifted(base, 0, 2)), projection.unit * 0.13))
            painter.setPen(Qt.PenStyle.NoPen)

        # Extruded flanks. Which of them are visible depends on where the cap
        # sits relative to the centre line, so let the winding decide.
        for index in range(4):
            following = (index + 1) % 4
            quad = [top[index], top[following], base[following], base[index]]
            if not faces_camera(quad):
                continue
            flank = mix(cap, CAP_SHADE, FACE_SHADE[index])
            gradient = QLinearGradient(top[index], base[index])
            gradient.setColorAt(0.0, mix(flank, WHITE, 0.18))
            gradient.setColorAt(0.55, flank)
            gradient.setColorAt(1.0, mix(flank, CAP_SHADE, 0.30))
            painter.setBrush(gradient)
            painter.drawPolygon(QPolygonF(quad))

        top_gradient = QLinearGradient(top[0], top[3])
        top_gradient.setColorAt(0.0, mix(cap, WHITE, 0.38))
        top_gradient.setColorAt(0.52, mix(cap, WHITE, 0.11))
        top_gradient.setColorAt(1.0, mix(cap, QColor("#D6E0DD"), 0.14))
        painter.setBrush(top_gradient)
        painter.setPen(QPen(mix(cap, CAP_EDGE, 0.34), 0.9))
        painter.drawPath(rounded_path(top, projection.unit * 0.13))

        # The scooped top of a sculpted cap: a sheen fading from the far wall
        # of the dish towards the viewer. Inset in key units rather than as a
        # share of the cap, so a space bar keeps a 1u-sized scoop.
        scoop = min(key.width, key.height) * 0.13
        dish = projection.quad(
            (
                (corners[0][0] + scoop, corners[0][1] + scoop),
                (corners[1][0] - scoop, corners[1][1] + scoop),
                (corners[2][0] - scoop, corners[2][1] - scoop),
                (corners[3][0] + scoop, corners[3][1] - scoop),
            ),
            top_z,
        )
        sheen = QLinearGradient(dish[0], dish[3])
        sheen.setColorAt(0.0, QColor(255, 255, 255, 92))
        sheen.setColorAt(0.5, QColor(255, 255, 255, 20))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(sheen)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(rounded_path(dish, projection.unit * 0.10))

        # A hairline along the far edge reads as the sculpted lip of the cap.
        painter.setPen(QPen(QColor(255, 255, 255, 130), 0.9))
        painter.drawLine(lerp(top[0], top[1], 0.12), lerp(top[0], top[1], 0.88))

        face = QPolygonF(top).boundingRect().adjusted(3, 1, -3, -1)
        self._draw_legend(painter, key.key_id, key.label, count, face, cap)


class ShadowBackdrop(QWidget):
    """Page background that paints the drop shadow of the cards on it.

    A ``QGraphicsDropShadowEffect`` renders its whole widget into an offscreen
    pixmap and blurs it again every time *anything inside* repaints, so one
    pulsing keycap redrew and re-blurred the entire keyboard card. Stacked
    translucent rounded rectangles behind the card look the same from a step
    back and cost nothing per frame: this only repaints when the page does.
    """

    SHADOW_COLOR = QColor(42, 66, 58)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[list] = []

    def add_card(self, card: QWidget, radius: float, blur: float, offset: float, alpha: int) -> None:
        self._cards.append([card, radius, blur, offset, alpha, self._where(card)])
        card.installEventFilter(self)

    def _where(self, card: QWidget) -> QRect:
        """A card's rectangle in the backdrop's own coordinates.

        Cards live a page or two down the tree now that the window stacks a
        monitor page and a gallery page, so their geometry is relative to that
        page rather than to the backdrop the shadow is painted on. Walked by
        hand rather than by mapTo(), because a card is registered while it is
        still being built and has yet to join the tree.
        """
        corner = QPoint(0, 0)
        widget = card
        while widget is not None and widget is not self:
            corner += widget.pos()
            widget = widget.parentWidget()
        return QRect(corner, card.size())

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() in (event.Type.Move, event.Type.Resize, event.Type.Show, event.Type.Hide):
            self._invalidate(watched)
        return super().eventFilter(watched, event)

    def _invalidate(self, card: QWidget) -> None:
        """Repaint the fringe a card's shadow occupies, old place and new.

        Deliberately not ``update()``: repainting the whole page would damage
        the cards on it too, and redrawing the keyboard is the one thing a
        resize cannot afford to do on every step of the drag.
        """
        for entry in self._cards:
            if entry[0] is not card:
                continue
            _, _, blur, offset, _, previous = entry
            reach = round(blur * 0.5 + abs(offset)) + 2
            current = self._where(card)
            entry[5] = current
            halo = QRegion(previous.adjusted(-reach, -reach, reach, reach)).united(
                QRegion(current.adjusted(-reach, -reach, reach, reach))
            )
            if card.isVisible():
                halo = halo.subtracted(QRegion(current))
            self.update(halo)
            return

    def paintEvent(self, event) -> None:  # noqa: N802
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for card, radius, blur, offset, alpha, _ in self._cards:
            # isVisible(), not isHidden(): the page a card sits on can be the
            # one the stack is not showing, and the card itself knows nothing
            # about that. Its shadow must not outlive the page.
            if not card.isVisible():
                continue
            body = QRectF(self._where(card))
            # Passes that shrink as they stack build a penumbra; the card
            # itself is opaque, so only the fringe outside it is ever seen.
            # Each pass is faint enough that the ten of them together land on
            # the opacity the blurred effect used to reach at the edge.
            steps = 10
            colour = QColor(self.SHADOW_COLOR)
            colour.setAlpha(max(1, round(alpha * 0.9 / steps)))
            painter.setBrush(colour)
            for step in range(steps):
                grow = blur * 0.5 * (1.0 - step / steps)
                painter.drawRoundedRect(
                    body.adjusted(-grow, -grow + offset, grow, grow + offset),
                    radius + grow,
                    radius + grow,
                )


class StatCard(QFrame):
    def __init__(
        self, caption: str = "", value: str = "0", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("statCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(4)
        self.caption = QLabel(caption)
        self.caption.setObjectName("statCaption")
        self.value = QLabel(value)
        self.value.setObjectName("statValue")
        layout.addWidget(self.caption)
        layout.addWidget(self.value)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        add_soft_shadow(self, blur=24, y_offset=5, alpha=18)

    def set_value(self, value: str) -> None:
        self.value.setText(value)

    def set_caption(self, caption: str) -> None:
        self.caption.setText(caption)


# The archived picture is rendered off-screen at a fixed size, so a run filed
# from a small window is as legible as one filed from a maximised one.
# A pad is less than half the width of a board in key units, so it is drawn
# larger to land on a comparable picture.
SNAPSHOT_ZOOM = {KEYBOARD_DEVICE: 140, GAMEPAD_DEVICE: 165}
SNAPSHOT_MARGIN = 44
SNAPSHOT_CARD_PAD = 26

# How much of the card each device is fitted into when the window works its
# own zoom out. Neither of them fills it. A board fitted edge to edge comes to
# within a few pixels of the card down both sides, which reads as a board too
# big for the room rather than as one filling it; the pad is worse off again,
# since its outline is close to the card's own proportions and an edge-to-edge
# fit presses it against all four sides at once. The two numbers differ
# because the shapes do: a board is twice as wide as it is deep and only ever
# runs out of width, so a little off the width is all it asks for. The wheel
# still takes either of them past its share on request.
BOARD_FIT_SHARE = 0.92
PAD_FIT_SHARE = 0.80


def snapshot_font(size: int, weight: QFont.Weight, spacing: float = 0.0) -> QFont:
    font = QFont()
    font.setFamilies(["Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI"])
    font.setPixelSize(size)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def render_snapshot_image(
    stats: StatsStore,
    layout_id: str,
    moment: datetime,
    device: str = KEYBOARD_DEVICE,
    lighting: bool = True,
) -> QImage:
    """The device as it stood, laid out the way the window itself presents it."""
    pad = device == GAMEPAD_DEVICE
    board = GamepadCanvas(stats) if pad else KeyboardCanvas(stats)
    board.set_layout(layout_id)
    board.set_zoom(SNAPSHOT_ZOOM[device])
    # The archive is a picture of what was on screen, lights and all -- so a
    # board filed with its lighting off is filed dark.
    board.set_lighting(lighting)
    keyboard = board.grab()
    # grab() hands back a pixmap tagged with the screen's scale factor. Clearing
    # the tag keeps its width in the same units as the geometry below, and the
    # extra pixels a scaled screen gives us simply land in the file.
    keyboard.setDevicePixelRatio(1.0)

    inset = SNAPSHOT_CARD_PAD
    card_width = keyboard.width() + inset * 2
    card_height = keyboard.height() + inset * 2
    header_height, stats_height, footer_height = 30, 78, 18
    width = card_width + SNAPSHOT_MARGIN * 2
    height = (
        SNAPSHOT_MARGIN * 2
        + header_height + 20 + stats_height + 16 + card_height + 14 + footer_height
    )

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#f3f6f4"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    left = SNAPSHOT_MARGIN
    top = SNAPSHOT_MARGIN
    header = QRect(left, top, card_width, header_height)
    painter.setFont(snapshot_font(22, QFont.Weight.ExtraBold, 2.0))
    painter.setPen(QColor("#17352f"))
    painter.drawText(header, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "KEYPULSE")
    painter.setFont(snapshot_font(12, QFont.Weight.DemiBold))
    painter.setPen(QColor("#7a8c86"))
    painter.drawText(
        header,
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        tr("ARCHIVED  {moment}").format(moment=f"{moment:%Y-%m-%d %H:%M}"),
    )
    top += header_height + 20

    labels = board.layout_spec.labels() if pad else KEY_LABELS
    favorite = stats.favorite
    top_key = "—"
    if favorite is not None:
        key_id, count = favorite
        top_key = f"{labels.get(key_id, key_id)}  ·  {compact_number(count)}"
    # Same 3:2:2 rhythm, tinted first card and type scale as the live window.
    cards = (
        (tr("TOTAL"), compact_number(stats.total), QColor("#e8f6f1"), QColor("#cfe9e0")),
        (tr("TODAY"), compact_number(stats.today_total), QColor("#ffffff"), QColor("#e7ecea")),
        (
            tr("TOP BUTTON") if pad else tr("TOP KEY"),
            top_key, QColor("#ffffff"), QColor("#e7ecea"),
        ),
    )
    gap = 12
    span = card_width - gap * 2
    widths = [round(span * share / 7) for share in (3, 2, 2)]
    widths[2] = span - widths[0] - widths[1]
    x = left
    for (caption, value, fill, border), card_w in zip(cards, widths):
        painter.setBrush(fill)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(QRectF(x + 0.5, top + 0.5, card_w - 1, stats_height - 1), 15, 15)
        text = QRect(x + 20, top + 15, card_w - 40, 20)
        painter.setFont(snapshot_font(12, QFont.Weight.Medium))
        painter.setPen(QColor("#7a8c86"))
        painter.drawText(text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, caption)
        painter.setFont(snapshot_font(23, QFont.Weight.Bold))
        painter.setPen(QColor("#183a32"))
        painter.drawText(
            QRect(x + 20, top + 37, card_w - 40, 30),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            value,
        )
        x += card_w + gap
    top += stats_height + 16

    painter.setBrush(QColor("#ffffff"))
    painter.setPen(QPen(QColor("#e3eae7"), 1))
    painter.drawRoundedRect(QRectF(left + 0.5, top + 0.5, card_width - 1, card_height - 1), 17, 17)
    painter.drawPixmap(left + inset, top + inset, keyboard)
    top += card_height + 14

    days = sorted(stats.daily)
    covered = f"{days[0]} → {days[-1]}" if len(days) > 1 else (days[0] if days else "—")
    footer = QRect(left, top, card_width, footer_height)
    painter.setFont(snapshot_font(12, QFont.Weight.Medium))
    painter.setPen(QColor("#94a5a0"))
    painter.drawText(
        footer,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        tr("{layout}  ·  {count} buttons used" if pad
           else "{layout}  ·  {count} keys used").format(
            layout=tr(board.layout_spec.name), count=len(stats.counts)
        ),
    )
    painter.drawText(footer, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, covered)
    painter.end()
    return image


class DeviceView:
    """One device's canvas plus the settings keys and wording that go with it."""

    def __init__(
        self,
        device: str,
        canvas: DeviceCanvas,
        scroll: KeyboardScrollArea,
        stats: StatsStore,
        options: tuple[tuple[str, str], ...],
        control: str,
        layout_key: str,
        zoom_key: str,
        default_layout: str,
        default_zoom: int,
        top_caption: str,
        light_key: str,
        fit_share: float = 1.0,
    ) -> None:
        self.device = device
        self.canvas = canvas
        self.scroll = scroll
        self.stats = stats
        self.options = options
        self.control = control
        self.layout_key = layout_key
        self.zoom_key = zoom_key
        self.default_layout = default_layout
        self.default_zoom = default_zoom
        self.top_caption = top_caption
        self.light_key = light_key
        # How much of the card the automatic fit is allowed to fill. One means
        # edge to edge; less than one holds the device back to the size it
        # looks right at, and the wheel still takes it past that on request.
        self.fit_share = fit_share
        self.manual_zoom = False

    def labels(self) -> dict[str, str]:
        spec = self.canvas.layout_spec
        if hasattr(spec, "labels"):
            return {**BUTTON_LABELS, **spec.labels()}
        return KEY_LABELS


class MainWindow(QMainWindow):
    def __init__(
        self, stats: StatsStore, gamepad_stats: StatsStore, settings: SettingsStore
    ) -> None:
        super().__init__()
        self.stats = stats
        self.gamepad_stats = gamepad_stats
        self.settings = settings
        self.quitting = False
        # Every fixed string on screen, so throwing the language switch can
        # reach the ones that were set once, while the window was being built.
        self.wording = Wording()
        # The header light is kept as the facts behind it rather than as the
        # sentence it ends up saying, so the sentence can be written out again
        # in whichever language is in force when it is next refreshed.
        self._pad_slot = -1
        self._errors: dict[str, tuple[str, dict]] = {}
        self.setWindowTitle("KeyPulse")
        self.setWindowIcon(app_icon())
        self.resize(1440, 900)
        self.setMinimumSize(1120, 720)
        self.setStyleSheet(STYLE)

        root = self._backdrop = ShadowBackdrop()
        root.setObjectName("root")
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(34, 24, 34, 22)
        page.setSpacing(16)

        self.canvas = KeyboardCanvas(stats)
        self.canvas.set_layout(str(settings.get("layout", "full")))
        self.canvas.set_zoom(int(settings.get("zoom", 78)))
        self.canvas.set_lighting(bool(settings.get("lighting", DEFAULT_SETTINGS["lighting"])))
        self.pad_canvas = GamepadCanvas(gamepad_stats)
        self.pad_canvas.set_layout(str(settings.get("gamepad_model", DEFAULT_MODEL)))
        self.pad_canvas.set_zoom(int(settings.get("gamepad_zoom", 130)))
        self.pad_canvas.set_lighting(
            bool(settings.get("gamepad_lighting", DEFAULT_SETTINGS["gamepad_lighting"]))
        )

        self.stack = QStackedWidget()
        self.views = {
            KEYBOARD_DEVICE: DeviceView(
                KEYBOARD_DEVICE, self.canvas, self._build_scroll(self.canvas), stats,
                tuple((LAYOUTS[layout_id].name, layout_id) for layout_id in LAYOUT_ORDER),
                "LAYOUT", "layout", "zoom", "full", 78, "TOP KEY", "lighting", BOARD_FIT_SHARE,
            ),
            GAMEPAD_DEVICE: DeviceView(
                GAMEPAD_DEVICE, self.pad_canvas, self._build_scroll(self.pad_canvas), gamepad_stats,
                tuple((MODELS[model_id].name, model_id) for model_id in MODEL_ORDER),
                "MODEL", "gamepad_model", "gamepad_zoom", DEFAULT_MODEL, 130,
                "TOP BUTTON", "gamepad_lighting", PAD_FIT_SHARE,
            ),
        }
        for view in self.views.values():
            self.stack.addWidget(view.scroll)
        wanted = str(settings.get("device", KEYBOARD_DEVICE))
        self.device = wanted if wanted in self.views else KEYBOARD_DEVICE

        page.addLayout(self._build_header())

        # Two pages under one header: the live device, and the wall of runs
        # already filed. Only the body swaps; the title, the status light and
        # the two buttons belong to both.
        self.live_page = QWidget()
        live = QVBoxLayout(self.live_page)
        live.setContentsMargins(0, 0, 0, 0)
        live.setSpacing(16)
        live.addLayout(self._build_stats())
        live.addWidget(self._build_toolbar())
        live.addWidget(self._build_keyboard_panel(), 100)
        # Any space the keyboard card does not need collects here, so the rows
        # above keep their natural rhythm instead of drifting apart.
        live.addStretch(1)

        self.gallery = GalleryPage()
        self._backdrop.add_card(self.gallery.panel, radius=17, blur=32, offset=8, alpha=22)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.live_page)
        self.pages.addWidget(self.gallery)
        page.addWidget(self.pages, 1)

        # Resizes arrive in bursts; one deferred refit per burst is enough.
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(0)
        self._refit_timer.timeout.connect(self._enforce_zoom_fit)

        # ...and the same burst is a drag in progress, during which the canvas
        # should stay out of the way. This fires once the pointer settles.
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(170)
        self._idle_timer.timeout.connect(self._resume_canvas)

        # The zoom a wheel turn comes to rest on, held back from the settings
        # file until the turn is over.
        self._zoom_to_save: tuple[str, int] | None = None
        self._zoom_save_timer = QTimer(self)
        self._zoom_save_timer.setSingleShot(True)
        self._zoom_save_timer.setInterval(450)
        self._zoom_save_timer.timeout.connect(self._save_zoom)

        self._setup_tray()
        self._show_device(self.device)
        self._refit_timer.start()

    # -- construction ------------------------------------------------------

    def _build_scroll(self, canvas: DeviceCanvas) -> KeyboardScrollArea:
        scroll = KeyboardScrollArea()
        scroll.setObjectName("keyboardScroll")
        scroll.setWidget(canvas)
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.zoom_requested.connect(self._wheel_zoom)
        return scroll

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        title = QLabel("KEYPULSE")
        title.setObjectName("title")
        row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        self.status_text = QLabel(tr("●  LIVE"))
        self.status_text.setObjectName("statusLive")
        row.addWidget(self.status_text, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        row.addWidget(self._build_page_switch(), 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(4)
        reset = QPushButton()
        reset.setObjectName("resetButton")
        self.wording.label(
            reset,
            "RESET",
            "Archive the counts of the device on screen, then start from zero",
        )
        reset.clicked.connect(self._reset_counts)
        row.addWidget(reset)
        row.addWidget(self._build_language_button())
        return row

    def _build_language_button(self) -> QPushButton:
        """The whole of the second language, in one button at the end of the row.

        It wears the name of the language it would take you to rather than of
        the one already on screen, which is the only way one button can say
        what it does without a second word beside it explaining the first. Its
        width is fixed so EN and 中文 stand in the same place instead of
        shuffling the header along every time it is pressed.
        """
        button = self.language_button = QPushButton()
        button.setObjectName("ghostButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedWidth(62)
        button.clicked.connect(self._toggle_language)
        self._refresh_language_button()
        return button

    def _refresh_language_button(self) -> None:
        wanted = other_language()
        self.language_button.setText(LANGUAGE_BUTTON[wanted])
        self.language_button.setToolTip(tr(
            "Switch the interface to Chinese" if wanted == "zh"
            else "Switch the interface to English"
        ))

    def _toggle_language(self) -> None:
        self.settings.set("language", set_language(other_language()))
        self.retranslate()

    def retranslate(self) -> None:
        """Say the whole window again, in the language now in force."""
        self.wording.apply()
        self._refresh_language_button()
        # Everything written afresh each time it is shown -- the control
        # label, the list of shapes, the caption over the top key, the status
        # light -- is put back by pointing the window at the device it is
        # already on.
        self._show_device(self.device)
        self.gallery.retranslate()

    def _build_page_switch(self) -> QFrame:
        """MONITOR or GALLERY, in the same pill the device switch uses."""
        frame = QFrame()
        frame.setObjectName("segment")
        row = QHBoxLayout(frame)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(3)
        self.page_group = QButtonGroup(self)
        self.page_group.setExclusive(True)
        self._page_buttons: dict[str, QPushButton] = {}
        for name, text, hint in (
            ("monitor", "MONITOR", "Watch the device you are using"),
            ("gallery", "GALLERY", "Every run archived so far, hung on a wall"),
        ):
            button = QPushButton()
            button.setObjectName("segmentButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.wording.label(button, text, hint)
            button.clicked.connect(lambda _checked, key=name: self._show_page(key))
            self.page_group.addButton(button)
            self._page_buttons[name] = button
            row.addWidget(button)
        self._page_buttons["monitor"].setChecked(True)
        return frame

    def _build_stats(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.today_card = StatCard()
        self.total_card = StatCard()
        self.total_card.setObjectName("statCardAccent")
        # The third caption names the device on screen, so the switch between
        # them writes it rather than this row fixing it.
        self.favorite_card = StatCard(value="—")
        self.wording.label(self.today_card.caption, "TODAY")
        self.wording.label(self.total_card.caption, "TOTAL")
        row.addWidget(self.total_card, 3)
        row.addWidget(self.today_card, 2)
        row.addWidget(self.favorite_card, 2)
        return row

    def _build_toolbar(self) -> QFrame:
        toolbar = QFrame()
        toolbar.setObjectName("toolbar")
        toolbar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        add_soft_shadow(toolbar, blur=24, y_offset=5, alpha=16)
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(18, 12, 18, 12)
        row.setSpacing(12)

        row.addWidget(self._small_label("SHOW"), 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._build_device_switch(), 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(8)

        self.control_label = self._small_label()
        row.addWidget(self.control_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.layout_combo = QComboBox()
        self.layout_combo.setMinimumWidth(170)
        self.layout_combo.currentIndexChanged.connect(self._layout_changed)
        row.addWidget(self.layout_combo)

        row.addStretch(1)
        row.addWidget(self._small_label("LIGHT"))
        self.light_toggle = ToggleSwitch()
        self.wording.tip(
            self.light_toggle, "Turn the lighting of the device on screen on or off"
        )
        self.light_toggle.toggled.connect(self._light_toggled)
        row.addWidget(self.light_toggle)
        row.addSpacing(14)
        row.addWidget(self._small_label("STARTUP"))
        self.startup_toggle = ToggleSwitch()
        self.wording.tip(
            self.startup_toggle, "Start counting in the background when Windows starts"
        )
        self.startup_toggle.setChecked(is_startup_enabled())
        self.startup_toggle.toggled.connect(self._startup_toggled)
        row.addWidget(self.startup_toggle)
        return toolbar

    def _build_device_switch(self) -> QFrame:
        """Two segments, one per device, sharing one pill."""
        frame = QFrame()
        frame.setObjectName("segment")
        row = QHBoxLayout(frame)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(3)
        self.device_group = QButtonGroup(self)
        self.device_group.setExclusive(True)
        self._device_buttons: dict[str, QPushButton] = {}
        for device, text, hint in (
            (KEYBOARD_DEVICE, "KEYBOARD", "Show the keyboard and its key counts"),
            (GAMEPAD_DEVICE, "GAMEPAD", "Show the controller and its button counts"),
        ):
            button = QPushButton()
            button.setObjectName("segmentButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.wording.label(button, text, hint)
            button.clicked.connect(lambda _checked, name=device: self._device_chosen(name))
            self.device_group.addButton(button)
            self._device_buttons[device] = button
            row.addWidget(button)
        return frame

    def _build_keyboard_panel(self) -> QFrame:
        panel = self.keyboard_panel = QFrame()
        panel.setObjectName("keyboardPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(0)
        layout.addWidget(self.stack, 1)
        self.wording.tip(panel, "Scroll to zoom the device, drag to slide it")
        # Painted by the backdrop rather than by an effect on the card: see
        # ShadowBackdrop for why the keyboard cannot afford the latter.
        self._backdrop.add_card(panel, radius=17, blur=32, offset=8, alpha=22)
        return panel

    def _small_label(self, text: str = "") -> QLabel:
        """One of the small grey captions in the toolbar.

        A caption that names the device on screen is left blank here and
        written by the switch between them; the rest say the same thing for as
        long as the window is open, so they are registered as fixed.
        """
        label = QLabel()
        label.setObjectName("controlLabel")
        if text:
            self.wording.label(label, text)
        return label

    def _show_page(self, name: str) -> None:
        """Put the monitor or the gallery on screen, whichever was asked for."""
        self._page_buttons[name].setChecked(True)
        # The light reports on the device being watched. The wall is not
        # watching anything -- it is a room full of runs that already ended --
        # so on that page the header is the title alone.
        self.status_text.setVisible(name != "gallery")
        if name == "gallery":
            # The wall opens on the device that was on screen, and reads the
            # folder only when it is actually looked at.
            self.gallery.opened(self.device)
            self.pages.setCurrentWidget(self.gallery)
            self.gallery.setFocus()
        else:
            self.pages.setCurrentWidget(self.live_page)
            self._refit_timer.start()

    # -- devices -----------------------------------------------------------

    def _view(self) -> DeviceView:
        return self.views[self.device]

    def _device_chosen(self, device: str) -> None:
        if device == self.device:
            return
        self._show_device(device)
        self.settings.set("device", device)

    def _show_device(self, device: str) -> None:
        """Put one device on screen and point every control at it."""
        self.device = device
        view = self._view()
        self._device_buttons[device].setChecked(True)
        self.stack.setCurrentWidget(view.scroll)
        self.control_label.setText(tr(view.control))

        self.layout_combo.blockSignals(True)
        self.layout_combo.clear()
        for name, layout_id in view.options:
            self.layout_combo.addItem(tr(name), layout_id)
        chosen = str(self.settings.get(view.layout_key, view.default_layout))
        index = self.layout_combo.findData(chosen)
        if index < 0:
            # A name left behind by a build that had more shapes than this one
            # does. The canvas has already fallen back on its own, so pick the
            # same one here and write it back: a setting that names a shape
            # nothing can draw would sit there confusing the two of them for
            # as long as it went untouched.
            index = 0
            chosen = str(self.layout_combo.itemData(0))
            view.canvas.set_layout(chosen)
            self.settings.set(view.layout_key, chosen)
        self.layout_combo.setCurrentIndex(index)
        self.layout_combo.blockSignals(False)

        self.light_toggle.blockSignals(True)
        self.light_toggle.setChecked(
            bool(self.settings.get(view.light_key, DEFAULT_SETTINGS[view.light_key]))
        )
        self.light_toggle.blockSignals(False)

        self.favorite_card.set_caption(tr(view.top_caption))
        self._refresh_summary()
        self._refresh_status()
        self._refit_timer.start()

    def _status(self) -> tuple[str, str, str]:
        """What the light in the header says about the device on screen.

        It reports the same thing on both sides: whether the device being
        shown is one KeyPulse is actually reading. A pad that is plugged in is
        LIVE exactly as the keyboard is -- which slot it landed in is a detail
        for the tooltip, not a second thing for the header to say -- and a pad
        that is not plugged in says so, in the one place the answer belongs.
        """
        failure = self._errors.get(self.device)
        if failure is not None:
            return (
                ALERT,
                tr("●  KEYBOARD ERROR" if self.device == KEYBOARD_DEVICE
                   else "●  GAMEPAD ERROR"),
                tr(failure[0]).format(**failure[1]),
            )
        if self.device == KEYBOARD_DEVICE:
            return LIVE, tr("●  LIVE"), tr("Every key on this machine is being counted.")
        if self._pad_slot < 0:
            return (
                MISSING,
                tr("○  NO GAMEPAD"),
                tr("No controller is connected. Plug one in and KeyPulse finds it on its own."),
            )
        slot = self._pad_slot + 1
        return (
            LIVE,
            tr("●  LIVE"),
            tr("Reading the controller in slot {slot}.").format(slot=slot),
        )

    def _refresh_status(self) -> None:
        """Write the light out, in the colours the state it reports wears.

        Reading a device is the ordinary case, so it stays a word beside the
        title. Anything else is worth noticing, and a chip is how the header
        notices it without a second row or a dialog.
        """
        state, text, hint = self._status()
        self.status_text.setText(text)
        self.status_text.setStyleSheet(STATUS_STYLE[state])
        self.status_text.setToolTip(hint)

    # -- dialogs -----------------------------------------------------------

    def _dialog(self, title: str, message: str, detail: str = "") -> QMessageBox:
        """A message box that inherits the window's palette instead of the system one."""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(message)
        if detail:
            box.setInformativeText(detail)
        # QMessageBox sizes itself to the text alone and settles on a column
        # narrow enough to wrap mid-thought. An invisible row of the right
        # width is the supported way to give it a floor.
        grid = box.layout()
        if isinstance(grid, QGridLayout):
            grid.addItem(
                QSpacerItem(430, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed),
                grid.rowCount(),
                0,
                1,
                grid.columnCount(),
            )
        return box

    @staticmethod
    def _mark_danger(button: QPushButton) -> None:
        # The style sheet is resolved once, when the button joins the box, so a
        # name set afterwards only takes effect if the button is re-polished.
        button.setObjectName("dangerButton")
        button.style().unpolish(button)
        button.style().polish(button)

    def _reset_counts(self) -> None:
        """Archive and clear the device on screen, leaving the other one alone."""
        view = self._view()
        stats = view.stats
        board = self.device == KEYBOARD_DEVICE
        if stats.total <= 0:
            box = self._dialog(
                tr("Reset"),
                tr("No keystrokes to reset." if board else "No button presses to reset."),
                tr(
                    "The board is already at zero, so there is no run worth archiving."
                    if board else
                    "The pad is already at zero, so there is no run worth archiving."
                ),
            )
            box.addButton(tr("OK"), QMessageBox.ButtonRole.AcceptRole)
            box.exec()
            return

        box = self._dialog(
            tr("Reset counts"),
            tr("Reset every keyboard count to zero?" if board
               else "Reset every gamepad count to zero?"),
            tr(
                "The current run — {total} keystrokes across {distinct} keys — is hung in the "
                "gallery first, as a picture of the board plus the counts behind it. The other "
                "device keeps its own counts."
                if board else
                "The current run — {total} button presses across {distinct} buttons — is hung in the "
                "gallery first, as a picture of the pad plus the counts behind it. The other "
                "device keeps its own counts."
            ).format(total=f"{stats.total:,}", distinct=len(stats.counts)),
        )
        confirm = box.addButton(tr("Archive and reset"), QMessageBox.ButtonRole.AcceptRole)
        self._mark_danger(confirm)
        cancel = box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() is not confirm:
            return

        moment = datetime.now().astimezone()
        path: Path | None = None
        try:
            path = stats.archive(
                view.labels(),
                moment,
                {
                    "layout": view.canvas.layout_spec.layout_id,
                    "layout_name": view.canvas.layout_spec.name,
                },
            )
            picture = path.with_suffix(".png")
            image = render_snapshot_image(
                stats,
                view.canvas.layout_spec.layout_id,
                moment,
                self.device,
                view.canvas.lighting,
            )
            if not image.save(str(picture), "PNG"):
                raise RuntimeError(
                    tr("The picture {file} could not be written.").format(file=picture.name)
                )
        except Exception as error:
            # Nothing is cleared unless the whole archive is safely on disk, and
            # a half-written pair is worse than none.
            if path is not None:
                for leftover in (path, path.with_suffix(".png")):
                    try:
                        leftover.unlink()
                    except OSError:
                        pass
            failed = self._dialog(
                tr("Reset failed"),
                tr("The snapshot could not be written, so the counts were kept."),
                str(error),
            )
            failed.addButton(tr("OK"), QMessageBox.ButtonRole.AcceptRole)
            failed.exec()
            return

        stats.reset()
        view.canvas.refresh_counts()
        self._refresh_summary()
        # The wall now has one more picture on it than it knows about.
        self.gallery.invalidate(path)

        done = self._dialog(
            tr("Counts reset"),
            tr("The board is back to zero." if board else "The pad is back to zero."),
            tr(
                "The run it just finished is hanging in the gallery, kept on disk as {file} with "
                "the same counts as .json beside it."
            ).format(file=f"{SNAPSHOT_DIR_NAME}\\{path.parent.name}\\{path.stem}.png"),
        )
        show = done.addButton(tr("Open gallery"), QMessageBox.ButtonRole.ActionRole)
        close = done.addButton(tr("Done"), QMessageBox.ButtonRole.AcceptRole)
        done.setDefaultButton(close)
        done.exec()
        if done.clickedButton() is show:
            self._show_page("gallery")

    # -- tray --------------------------------------------------------------

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu()
        show_action = QAction(self)
        self.wording.label(show_action, "Open")
        show_action.triggered.connect(self.show_from_tray)
        quit_action = QAction(self)
        self.wording.label(quit_action, "Exit")
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_from_tray()

    def show_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def quit_app(self) -> None:
        self.quitting = True
        # A zoom still waiting on its timer would be lost with the window.
        self._save_zoom()
        self.stats.save(force=True)
        self.gamepad_stats.save(force=True)
        self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._save_zoom()
        if self.quitting or not bool(self.settings.get("close_to_tray", True)):
            event.accept()
            return
        event.ignore()
        self.hide()
        if not bool(self.settings.get("tray_hint_shown", False)):
            self.tray.showMessage(
                tr("Still running"),
                tr("KeyPulse is in the system tray."),
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
            self.settings.set("tray_hint_shown", True)

    # -- sizing ------------------------------------------------------------

    def _layout_changed(self) -> None:
        view = self._view()
        layout_id = str(self.layout_combo.currentData())
        view.canvas.set_layout(layout_id)
        self.settings.set(view.layout_key, layout_id)
        view.manual_zoom = False
        self._refit_timer.start()

    def _max_fitting_zoom(self) -> int:
        view = self._view()
        viewport = view.scroll.viewport().size()
        if viewport.width() < 100 or viewport.height() < 100:
            # Nothing worth measuring yet -- the window is still being put
            # together. Leave the zoom where it is rather than write a guess
            # into the settings that the first real resize has to undo.
            return view.canvas.zoom
        # A keyboard is wide and shallow, so filling the card is what it wants:
        # it runs out of width long before it runs out of height. A pad is
        # nearly the card's own shape, and a fit that fills the card leaves it
        # pressed against every edge. Fitting it inside a share of the card
        # instead keeps the margin it is drawn to sit in, at any window size.
        width = round((viewport.width() - 4) * view.fit_share)
        height = round((viewport.height() - 4) * view.fit_share)

        def fits(zoom: int) -> bool:
            size = view.canvas.size_for_zoom(zoom)
            return size.width() <= width and size.height() <= height

        # The projected size grows monotonically with the zoom, so bisect
        # instead of walking every step of the range.
        low, high = ZOOM_MIN, ZOOM_MAX
        if fits(high):
            return high
        while low < high:
            middle = (low + high + 1) // 2
            if fits(middle):
                low = middle
            else:
                high = middle - 1
        return low

    def _wheel_zoom(self, direction: int, pointer: QPointF | None = None) -> None:
        """Scale the device on the whiteboard, and only the device.

        The card the board sits on is furniture: it belongs to the window, and
        a wheel turn is not allowed to resize it. So the zoom runs to the full
        range whatever the viewport measures, and anything that no longer fits
        is reached by dragging the board instead.
        """
        view = self._view()
        canvas = view.canvas
        step = max(3, round(canvas.zoom * 0.06))
        target = max(ZOOM_MIN, min(ZOOM_MAX, canvas.zoom + (step if direction > 0 else -step)))
        if target == canvas.zoom:
            return
        view.manual_zoom = True

        # Where the pointer is over the board right now, as a share of it, so
        # the same spot can be put back under the pointer afterwards.
        viewport = view.scroll.viewport()
        if pointer is None:
            pointer = QPointF(viewport.width() * 0.5, viewport.height() * 0.5)
        held = canvas.mapFrom(viewport, pointer.toPoint())
        share_x = held.x() / max(1, canvas.width())
        share_y = held.y() / max(1, canvas.height())

        canvas.set_zoom(target)
        # Settings are fsynced when they are written, and a turn of the wheel
        # is a dozen notches: the zoom it comes to rest on is the one worth
        # keeping, so the write waits for the wheel to stop.
        self._zoom_to_save = (view.zoom_key, target)
        self._zoom_save_timer.start()
        self._anchor(view, share_x, share_y, pointer)
        # The board is going to move again in a few milliseconds. Standing the
        # animations down for the length of the gesture is what the window
        # already does for a drag, and a wheel turn asks the same of it.
        self._pause_canvas()

    def _anchor(
        self, view: DeviceView, share_x: float, share_y: float, pointer: QPointF
    ) -> None:
        """Put the share of the board that was under the pointer back under it."""
        canvas = view.canvas
        wanted_x = round(share_x * canvas.width() - pointer.x())
        wanted_y = round(share_y * canvas.height() - pointer.y())
        view.scroll.pan_to(wanted_x, wanted_y)
        # The scroll area works its own ranges out once Qt has processed the
        # resize; re-apply the same offset then, or a board grown past the
        # card would snap back to the clamp the old range imposed.
        QTimer.singleShot(0, lambda: view.scroll.pan_to(wanted_x, wanted_y))

    def _enforce_zoom_fit(self) -> None:
        # A hidden monitor has no viewport worth measuring; refitting against
        # one would shrink the board to nothing behind the gallery's back.
        if hasattr(self, "pages") and self.pages.currentWidget() is not self.live_page:
            return
        view = self._view()
        # Once the wheel has been touched the zoom is the user's: resizing the
        # window pans the whiteboard, it never rescales what is on it.
        if view.manual_zoom:
            return
        target = self._max_fitting_zoom()
        if target != view.canvas.zoom:
            view.canvas.set_zoom(target)
            self.settings.set(view.zoom_key, target)

    def _save_zoom(self) -> None:
        """Write back the zoom the wheel finished on, if it has not been."""
        pending, self._zoom_to_save = self._zoom_to_save, None
        if pending is not None:
            self.settings.set(*pending)

    def _pause_canvas(self) -> None:
        # Windows runs a modal loop while a window is dragged or resized, so
        # every frame the canvas paints in that window is one the gesture has
        # to wait behind. Park the animations until the pointer settles.
        if not hasattr(self, "_idle_timer"):
            return
        self._view().canvas.suspend()
        self._idle_timer.start()

    def _resume_canvas(self) -> None:
        self._view().canvas.resume()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self._pause_canvas()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._pause_canvas()
        if hasattr(self, "_refit_timer"):
            self._refit_timer.start()

    def _light_toggled(self, checked: bool) -> None:
        """Switch the lighting of the device on screen, and remember it."""
        view = self._view()
        view.canvas.set_lighting(checked)
        self.settings.set(view.light_key, checked)

    def _startup_toggled(self, checked: bool) -> None:
        try:
            set_startup_enabled(checked)
        except Exception as error:
            self.startup_toggle.blockSignals(True)
            self.startup_toggle.setChecked(not checked)
            self.startup_toggle.blockSignals(False)
            # tr() on the reason as well: ours are in the table, and the ones
            # Windows raises have already been put into the user's language
            # by Windows, so either way it comes back saying the right thing.
            box = self._dialog(
                tr("Startup Error", "startup"),
                tr("The startup setting could not be changed."),
                tr(str(error)),
            )
            box.addButton(tr("OK"), QMessageBox.ButtonRole.AcceptRole)
            box.exec()

    # -- input -------------------------------------------------------------

    def on_key_press(self, key_id: str) -> None:
        self.stats.record(key_id)
        self.canvas.pulse(key_id)
        if self.device == KEYBOARD_DEVICE:
            self._refresh_summary()

    def on_key_release(self, key_id: str) -> None:
        self.canvas.release(key_id)

    def on_pad_press(self, button_id: str) -> None:
        self.gamepad_stats.record(button_id)
        self.pad_canvas.pulse(button_id)
        if self.device == GAMEPAD_DEVICE:
            self._refresh_summary()

    def on_pad_release(self, button_id: str) -> None:
        self.pad_canvas.release(button_id)

    def on_pad_axes(self, left_x: float, left_y: float, right_x: float, right_y: float) -> None:
        self.pad_canvas.set_axes(left_x, left_y, right_x, right_y)

    def on_pad_connection(self, slot: int) -> None:
        # A pad the reader can see is a pad the reader can read, whatever it
        # had to say for itself when it started up.
        self._pad_slot = slot
        self._errors.pop(GAMEPAD_DEVICE, None)
        if self.device == GAMEPAD_DEVICE:
            self._refresh_status()

    def _refresh_summary(self) -> None:
        view = self._view()
        stats = view.stats
        self.today_card.set_value(compact_number(stats.today_total))
        self.total_card.set_value(compact_number(stats.total))
        favorite = stats.favorite
        if favorite is None:
            self.favorite_card.set_value("—")
            return
        key_id, count = favorite
        labels = view.labels()
        self.favorite_card.set_value(f"{labels.get(key_id, key_id)}  ·  {compact_number(count)}")

    def on_hook_ready(self, message: str, params: dict | None = None) -> None:
        """The keyboard hook, reporting how it went. Empty means it is up.

        Both answers arrive here, and either one replaces whatever the header
        was saying: the hook is the only thing that knows, and it is allowed
        to take back a worry as well as raise one. The message is English and
        is put into words when it is shown.
        """
        if message:
            self._errors[KEYBOARD_DEVICE] = (message, params or {})
        else:
            self._errors.pop(KEYBOARD_DEVICE, None)
        if self.device == KEYBOARD_DEVICE:
            self._refresh_status()

    def set_pad_error(self, message: str, params: dict | None = None) -> None:
        self._errors[GAMEPAD_DEVICE] = (message, params or {})
        if self.device == GAMEPAD_DEVICE:
            self._refresh_status()


STYLE = """
QWidget#root {
    background: #f3f6f4;
    color: #18312c;
    font-family: "Segoe UI Variable", "Microsoft YaHei UI";
}
QLabel#title { color: #17352f; font-size: 20px; font-weight: 800; letter-spacing: 2px; }
QPushButton#ghostButton {
    color: #365c53; background: #ffffff; border: 1px solid #dce6e2;
    border-radius: 10px; padding: 9px 15px; font-weight: 600;
}
QPushButton#ghostButton:hover { color: #167d6c; border-color: #8fc9bb; background: #f6fbf9; }
QPushButton#ghostButton:pressed { background: #edf6f3; }
/* Same silhouette as the ghost buttons beside it, so the header stays one row
   of equals; only the hover state admits that this one ends the current run. */
QPushButton#resetButton {
    color: #365c53; background: #ffffff; border: 1px solid #dce6e2;
    border-radius: 10px; padding: 9px 15px; font-weight: 600;
}
QPushButton#resetButton:hover { color: #b4534a; border-color: #e7c6c0; background: #fdf8f7; }
QPushButton#resetButton:pressed { background: #f9eeec; }
QFrame#statCard {
    background: #ffffff; border: 1px solid #e7ecea; border-radius: 15px;
}
QFrame#statCardAccent {
    background: #e8f6f1; border: 1px solid #cfe9e0; border-radius: 15px;
}
QLabel#statCaption { color: #7a8c86; font-size: 12px; font-weight: 500; }
QLabel#statValue { color: #183a32; font-size: 23px; font-weight: 750; }
QFrame#toolbar {
    background: #ffffff; border: 1px solid #e4ebe8; border-radius: 14px;
}
QLabel#controlLabel { color: #657a73; font-size: 12px; font-weight: 550; }
/* One pill holding both devices, so the pair reads as a single switch and the
   chosen half looks lifted out of the groove it sits in. */
QFrame#segment {
    background: #eef3f1; border: 1px solid #dfe8e4; border-radius: 12px;
}
QPushButton#segmentButton {
    color: #5f7770; background: transparent; border: none; border-radius: 9px;
    padding: 6px 17px; font-size: 12px; font-weight: 650; letter-spacing: 0.6px;
}
QPushButton#segmentButton:hover { color: #167d6c; }
QPushButton#segmentButton:checked {
    color: #12665a; background: #ffffff; border: 1px solid #d4e3de;
}
QComboBox {
    color: #28483f; background: #f5f8f7; border: 1px solid #dce6e2;
    border-radius: 9px; padding: 7px 12px; min-height: 20px;
}
QComboBox:hover { border-color: #87c8b9; background: #f8fbfa; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    color: #28483f; background: #ffffff; border: 1px solid #d9e4e0;
    selection-background-color: #dcf1ea; selection-color: #174d42; outline: 0;
}
QFrame#keyboardPanel {
    background: #ffffff; border: 1px solid #e3eae7; border-radius: 17px;
}
QScrollArea#keyboardScroll { background: #ffffff; border: none; }
QScrollArea#keyboardScroll > QWidget > QWidget { background: #ffffff; }
QScrollBar:horizontal, QScrollBar:vertical { background: transparent; border: none; }
QScrollBar:horizontal { height: 9px; }
QScrollBar:vertical { width: 9px; }
QScrollBar::handle:horizontal, QScrollBar::handle:vertical { background: #cbd8d4; border-radius: 4px; min-width: 30px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
QLabel#statusLive { color: #159078; font-size: 12px; font-weight: 650; }
/* The gallery: the same white cards as the monitor, so walking from one page
   to the other never feels like leaving the app. */
QFrame#wallPanel {
    background: #ffffff; border: 1px solid #e3eae7; border-radius: 17px;
}
QScrollArea#wallScroll { background: transparent; border: none; }
QScrollArea#wallScroll > QWidget > QWidget { background: transparent; }
QLabel#wallCount { color: #93a49f; font-size: 12px; font-weight: 500; }
QFrame#exhibitCard {
    background: #ffffff; border: 1px solid #e7ecea; border-radius: 15px;
}
QLabel#exhibitKey { color: #7a8c86; font-size: 12px; font-weight: 600; letter-spacing: 0.5px; }
QLabel#exhibitValue { color: #183a32; font-size: 13px; font-weight: 650; }
QLabel#exhibitTitle { color: #17352f; font-size: 14px; font-weight: 700; letter-spacing: 0.8px; }
QPlainTextEdit#jsonView {
    color: #2c4f47; background: #f8fbfa; border: 1px solid #e6edea;
    border-radius: 11px; padding: 9px;
    selection-background-color: #cdeee4; selection-color: #124b41;
}
QMessageBox { background: #ffffff; }
QMessageBox QLabel { color: #24443c; font-size: 13px; }
QMessageBox QPushButton {
    color: #2c4f47; background: #ffffff; border: 1px solid #dce6e2;
    border-radius: 9px; padding: 8px 18px; font-weight: 600; min-width: 96px;
}
QMessageBox QPushButton:hover { color: #167d6c; border-color: #8fc9bb; background: #f6fbf9; }
QMessageBox QPushButton:pressed { background: #edf6f3; }
QMessageBox QPushButton#dangerButton {
    color: #ffffff; background: #c0574c; border-color: #b34c42;
}
QMessageBox QPushButton#dangerButton:hover { background: #ac4c42; border-color: #9e453c; }
QMessageBox QPushButton#dangerButton:pressed { background: #9e453c; }
QMenu { color: #29473f; background: #ffffff; border: 1px solid #dce5e2; padding: 6px; }
QMenu::item { padding: 7px 28px 7px 12px; border-radius: 5px; }
QMenu::item:selected { background: #e4f4ef; color: #167d6c; }
QToolTip { color: #29473f; background: #ffffff; border: 1px solid #cfddd8; padding: 5px; }
"""
