"""The gallery: every archived run, printed and filled into an album.

A reset files two things next to each other -- a picture of the board as it
stood and the counts behind it as JSON. Before, the only way to see either was
to open the folder. This page prints the pictures instead and fills them in
the order they were taken: the first run ever filed sits in the top left, the
next goes beside it, and each row wraps onto the one below. Every run is
mounted the same way -- cut mat, deep foot, the day and the size of the run
written on the board under the picture -- and the rest of the counts are a
click away. The keyboard and the pad each get their own wall, because a run
only ever belongs to one of them.

Nothing here writes to the archive except the delete button, and that asks
first.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from i18n import Wording, tr
from render import compact_number
from storage import (
    GAMEPAD_DEVICE,
    KEYBOARD_DEVICE,
    current_snapshot_folders,
    ensure_snapshot_dir,
    remove_snapshot,
)


# The wall's palette is the console's, one shade softer: a frame has to sit on
# the page without competing with the picture inside it.
INK = QColor("#183a32")
MUTED = QColor("#7a8c86")
FAINT = QColor("#a3b3ae")
MINT = QColor("#1FA58E")
MAT = QColor("#f6faf9")
MAT_EDGE = QColor("#e8efec")
FRAME_EDGE = QColor("#dfe8e4")
FRAME_EDGE_HOVER = QColor("#8fc9bb")
# The board a print is mounted on. Not flat white: it warms by a shade towards
# the foot, which is the difference between a card and a piece of paper.
BOARD_HEAD = QColor("#ffffff")
BOARD_FOOT = QColor("#f4f8f7")
# The lip of the cut mat, as the shade it throws inwards over the picture's
# own edge. Three hairlines of ink, fading: enough for the picture to sit in
# the mount rather than on top of it, not enough to read as a border.
BEVEL_SHADE = (26, 13, 6)

# One run on the wall is a print in a mount: the picture behind a cut mat, the
# board around it, and the day it was filed written on the board underneath.
# The foot is the deep margin, the way a photograph is actually mounted -- it
# gives the label somewhere to sit that is not on top of the picture, and it
# is what stops a wall of prints reading as a grid of plain white tiles.
PRINT_BORDER = 13
PRINT_FOOT = 34
PRINT_RADIUS = 12
MAT_RADIUS = 6
GRID_GAP = 18
WALL_MARGIN = 22
LINE_BREAK = chr(10)

# How wide one print asks to be. A row takes as many as the wall is wide
# enough for and then shares the leftover evenly between them, so a print
# lands near this width and the grid stays flush down both edges. A board is a
# wide picture and a pad an almost square one, which is why they ask for
# different widths: three boards, or four pads, across a window of the usual
# size.
TARGET_PRINT = {KEYBOARD_DEVICE: 390, GAMEPAD_DEVICE: 280}
# ...and never much wider than it asked for, or a narrow window would answer
# by blowing two prints up to fill it.
WIDEST_PRINT = 1.15
# The shape every print on a wall is cut to, before there is one to measure.
DEFAULT_RATIO = {KEYBOARD_DEVICE: 2.24, GAMEPAD_DEVICE: 1.15}
RATIO_RANGE = (0.85, 2.95)


def default_print_size(device: str) -> QSize:
    """The size a print is cut to before the wall has been measured."""
    width = TARGET_PRINT.get(device, 380)
    return QSize(width, max(90, round(width / DEFAULT_RATIO.get(device, 2.0))))


def open_folder(folder: Path) -> None:
    """Open a folder in the file manager."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def reveal(path: Path) -> None:
    """Open the folder a file is in, with the file itself picked out.

    Explorer selects a file only when it is asked for by name, which no URL
    can do, so this is the one place the gallery shells out. Anything that
    goes wrong falls back to opening the folder -- which is all this used to
    do, and is never worse than nothing.
    """
    if sys.platform == "win32":
        try:
            # One command line rather than an argument list: /select, and the
            # path are a single token to Explorer, and a path with a space in
            # it has to reach it still quoted.
            subprocess.run(
                f'explorer /select,"{path}"',
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
        except OSError:
            pass
    open_folder(path.parent)


def text_font(size: int, weight: QFont.Weight, spacing: float = 0.0) -> QFont:
    font = QFont()
    font.setFamilies(["Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI"])
    font.setPixelSize(size)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def mono_font(size: int) -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setFamilies(["Cascadia Mono", "Consolas", font.family()])
    font.setPixelSize(size)
    return font


def _moment(value: Any) -> datetime | None:
    """An ISO stamp -- or a bare date -- as a naive local datetime.

    Snapshots written on a machine with one offset can be read on the same
    machine with another (a laptop that flew), so the two ends of a run are
    compared with their offsets dropped rather than half-applied.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _stamp(value: datetime | None, day_only: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:%Y-%m-%d}" if day_only else f"{value:%Y-%m-%d  %H:%M}"


def _span(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None or end < start:
        return "—"
    minutes = int((end - start).total_seconds() // 60)
    if minutes < 1:
        return tr("under a minute")
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    parts: list[str] = []
    if days:
        parts.append(tr("{days} d").format(days=days))
    if hours:
        parts.append(tr("{hours} h").format(hours=hours))
    if mins and not days:
        parts.append(tr("{minutes} m").format(minutes=mins))
    return "  ".join(parts)


@dataclass
class Snapshot:
    """One archived run: the file pair on disk and the few fields we show."""

    json_path: Path
    image_path: Path | None
    device: str
    archived_at: datetime | None
    started_at: datetime | None
    start_is_day_only: bool
    first_day: str | None
    last_day: str | None
    total: int
    distinct: int
    layout_name: str
    ranking: list[tuple[str, int]]
    text: str
    number: int = 0
    # The picture's width over its height. The wall cuts every print on it to
    # one shape, and that shape is measured from the pictures themselves --
    # a 60% board is not the same picture as a full one.
    ratio: float = 0.0

    @classmethod
    def read(cls, path: Path) -> "Snapshot | None":
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or data.get("kind") != "reset_snapshot":
            return None

        device = str(data.get("device") or KEYBOARD_DEVICE)
        if device not in (KEYBOARD_DEVICE, GAMEPAD_DEVICE):
            device = KEYBOARD_DEVICE
        covers = data.get("covers") if isinstance(data.get("covers"), dict) else {}
        first_day = covers.get("first_day")
        last_day = covers.get("last_day")

        started = _moment(data.get("started_at"))
        day_only = False
        if started is None:
            # Archives filed before the start was recorded still know which day
            # they opened on; dating them by that beats leaving the label blank.
            started = _moment(first_day)
            day_only = started is not None

        ranking: list[tuple[str, int]] = []
        for entry in data.get("ranking") or []:
            if isinstance(entry, dict) and isinstance(entry.get("count"), int):
                ranking.append((str(entry.get("label") or entry.get("key") or "?"), entry["count"]))
        image = path.with_suffix(".png")
        has_picture = image.exists()
        return cls(
            json_path=path,
            image_path=image if has_picture else None,
            device=device,
            archived_at=_moment(data.get("archived_at")),
            started_at=started,
            start_is_day_only=day_only,
            first_day=str(first_day) if first_day else None,
            last_day=str(last_day) if last_day else None,
            total=int(data.get("total_keystrokes") or 0),
            distinct=int(data.get("distinct_keys") or len(data.get("keys") or {})),
            layout_name=str(data.get("layout_name") or ""),
            ranking=ranking,
            text=text,
            number=0,
            ratio=picture_ratio(image) if has_picture else 0.0,
        )

    @property
    def noun(self) -> str:
        return "presses" if self.device == GAMEPAD_DEVICE else "keystrokes"

    @property
    def unit(self) -> str:
        return "buttons" if self.device == GAMEPAD_DEVICE else "keys"

    @property
    def counted(self) -> str:
        """How much this run counted, in the words its device is counted in."""
        pad = self.device == GAMEPAD_DEVICE
        return tr("{total} presses" if pad else "{total} keystrokes").format(
            total=f"{self.total:,}"
        )

    @property
    def spread(self) -> str:
        """How many separate keys or buttons that was spread across."""
        pad = self.device == GAMEPAD_DEVICE
        return tr("{count} buttons" if pad else "{count} keys").format(count=self.distinct)

    @property
    def title(self) -> str:
        return _stamp(self.archived_at) if self.archived_at else self.json_path.stem

    @property
    def date_text(self) -> str:
        """The day this run was filed -- the only thing the wall says about it."""
        moment = self.archived_at or self.started_at
        if moment is not None:
            return f"{moment:%Y-%m-%d}"
        return self.last_day or self.first_day or "--"


def read_snapshots() -> dict[str, list[Snapshot]]:
    """Every readable archive, per device, oldest first and numbered to match.

    The wall is filled the way an album is: the first run ever filed takes the
    top left corner, the next one goes to its right, and each new one lands
    after the last. Reading them newest first put every new picture in the
    corner and shuffled all the others along behind it, so the wall never
    looked the same twice.
    """
    walls: dict[str, list[Snapshot]] = {KEYBOARD_DEVICE: [], GAMEPAD_DEVICE: []}
    seen: set[str] = set()
    for path in archive_files():
        # A run is its file name. The device folders are read before the
        # archive folder around them, so a copy that could not be moved down
        # into its folder is not hung a second time beside the one that was.
        if path.name.casefold() in seen:
            continue
        seen.add(path.name.casefold())
        snapshot = Snapshot.read(path)
        if snapshot is not None:
            walls[snapshot.device].append(snapshot)
    for wall in walls.values():
        # Undated files sort last so a missing stamp never claims No. 1.
        wall.sort(key=lambda item: (item.archived_at or datetime.min, item.json_path.name))
        for index, snapshot in enumerate(wall, start=1):
            snapshot.number = index
    return walls


def picture_ratio(path: Path) -> float:
    """A picture's width over its height, from its header alone."""
    size = QImageReader(str(path)).size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        return size.width() / size.height()
    return 0.0


def archive_files() -> list[Path]:
    """Every archived run in the folder in use, each device's folder first."""
    found: list[Path] = []
    for folder in current_snapshot_folders():
        try:
            found += sorted(folder.glob("*.json"))
        except OSError:
            continue
    return found


def archive_mark() -> tuple[int, int]:
    """A cheap stamp of the archive folder: how many runs, and changed when.

    The wall is rebuilt only when something moved, and something moved has
    to include a file that arrived without this window filing it -- a run
    adopted from an older folder at startup, or one dropped in by hand.
    Without that the wall could sit on an answer it cached before the
    pictures were there.
    """
    filed = archive_files()
    try:
        return len(filed), max((path.stat().st_mtime_ns for path in filed), default=0)
    except OSError:
        return 0, 0


def load_thumbnail(path: Path, box: QSize) -> QPixmap | None:
    """Decode the picture straight to thumbnail size, not full size then down."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        reader.setScaledSize(size.scaled(box, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        return None
    return QPixmap.fromImage(image)


def paint_board(painter: QPainter, body: QRectF, radius: float, edge: QColor) -> None:
    """The board a print is mounted on, painted before anything sits on it."""
    board = QLinearGradient(body.topLeft(), body.bottomLeft())
    board.setColorAt(0.0, BOARD_HEAD)
    board.setColorAt(1.0, BOARD_FOOT)
    painter.setBrush(QBrush(board))
    painter.setPen(QPen(edge, 1))
    painter.drawRoundedRect(body, radius, radius)


def paint_bevel(painter: QPainter, window: QRectF, radius: float) -> None:
    """The lip of the cut mat, over whatever was fitted into the window.

    Painted last, and only ever inwards: the picture is dropped into the
    opening square, and these three fading hairlines are what give the mat a
    thickness for it to sit behind.
    """
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for step, alpha in enumerate(BEVEL_SHADE):
        shade = QColor(INK)
        shade.setAlpha(alpha)
        painter.setPen(QPen(shade, 1))
        painter.drawRoundedRect(
            window.adjusted(step, step, -step, -step), radius - step, radius - step
        )


def fit_inside(painter: QPainter, window: QRectF, radius: float) -> None:
    """Clip to the mat's opening, so a picture cannot spill past its corners."""
    corners = QPainterPath()
    corners.addRoundedRect(window, radius, radius)
    painter.setClipPath(corners)


class FlowLayout(QLayout):
    """Prints fill a row from the left and wrap onto the next, like words.

    Flush left rather than centred: a half-empty last row floating in the
    middle of the wall breaks the column the eye follows down the left
    edge, and an album is read down its left edge.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = 22) -> None:
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self._space = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        rows: list[list[QWidgetItem]] = [[]]
        used = 0
        for item in self._items:
            width = item.sizeHint().width()
            needed = width if not rows[-1] else used + self._space + width
            if rows[-1] and needed > area.width():
                rows.append([])
                needed = width
            rows[-1].append(item)
            used = needed
        top = area.y()
        for row in rows:
            if not row:
                continue
            height = max(item.sizeHint().height() for item in row)
            left = area.x()
            if apply:
                for item in row:
                    hint = item.sizeHint()
                    item.setGeometry(QRect(QPoint(left, top), hint))
                    left += hint.width() + self._space
            top += height + self._space
        if rows and rows[-1]:
            top -= self._space
        return top - area.y() + margins.top() + margins.bottom()


class FrameCard(QFrame):
    """One run on the wall, mounted: the picture, the mat, and the label."""

    clicked = Signal(object)

    def __init__(
        self,
        snapshot: Snapshot,
        print_size: QSize | None = None,
        fresh: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.snapshot = snapshot
        self.fresh = fresh
        self._thumb: QPixmap | None = None
        self._decoded = QSize(0, 0)
        self.is_loaded = False
        self._hover = False
        self._print = QSize(0, 0)
        self.set_print_size(print_size or default_print_size(snapshot.device))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip(
            f"{snapshot.date_text}  ·  {snapshot.counted}\n"
            + tr("Click for the counts behind this picture")
        )

    def set_print_size(self, size: QSize) -> None:
        """Cut this print to the size the wall has room for."""
        size = QSize(max(120, size.width()), max(80, size.height()))
        if size == self._print:
            return
        self._print = size
        self.setFixedSize(
            size.width() + PRINT_BORDER * 2, size.height() + PRINT_BORDER + PRINT_FOOT
        )
        if self._thumb is not None and (
            self._decoded.width() < size.width() or self._decoded.height() < size.height()
        ):
            # The print outgrew the pixels it was decoded with. Decoding again
            # is cheap; blowing the old ones up shows.
            self._thumb = None
            self.is_loaded = False
        self.update()

    def load(self) -> None:
        """Decode this print's picture. The wall calls it a few prints a tick."""
        if self.is_loaded:
            return
        self.is_loaded = True
        if self.snapshot.image_path is not None:
            # Decoded at twice the print, so a HiDPI screen has pixels to spare.
            box = QSize(self._print.width() * 2, self._print.height() * 2)
            self._thumb = load_thumbnail(self.snapshot.image_path, box)
            if self._thumb is not None:
                self._decoded = self._thumb.size()
                # The ratio maps those extra pixels back down to the print.
                self._thumb.setDevicePixelRatio(
                    max(
                        1.0,
                        self._thumb.width() / self._print.width(),
                        self._thumb.height() / self._print.height(),
                    )
                )
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        spot = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(spot):
            self.clicked.emit(self.snapshot)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # A lifted print throws a slightly longer shadow; both are painted as
        # stacked translucent rectangles, the way the console's cards are.
        lift = 3 if self._hover else 0
        body = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1).translated(0, -lift)
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(6):
            grow = (6.0 + lift * 2) * (1.0 - step / 6)
            shade = QColor(42, 66, 58)
            shade.setAlpha(6 if self._hover else 4)
            painter.setBrush(shade)
            painter.drawRoundedRect(
                body.adjusted(-grow, -grow + 3 + lift, grow, grow + 3 + lift),
                PRINT_RADIUS + grow,
                PRINT_RADIUS + grow,
            )

        paint_board(painter, body, PRINT_RADIUS, FRAME_EDGE_HOVER if self._hover else FRAME_EDGE)

        # The mat, cut deeper at the foot than at the head, so the picture sits
        # above the middle of the board and the label has a margin of its own.
        window = body.adjusted(PRINT_BORDER, PRINT_BORDER, -PRINT_BORDER, -PRINT_FOOT)
        painter.setBrush(MAT)
        painter.setPen(QPen(MAT_EDGE, 1))
        painter.drawRoundedRect(window, MAT_RADIUS, MAT_RADIUS)

        if self._thumb is None:
            painter.setPen(FAINT)
            painter.setFont(text_font(12, QFont.Weight.Medium))
            painter.drawText(
                window,
                Qt.AlignmentFlag.AlignCenter,
                tr("loading...") if not self.is_loaded else tr("picture missing"),
            )
            self._print_label(painter, body)
            return

        # The picture keeps its own shape inside the mat, so a board filed in
        # one layout never comes out stretched into the shape of another, and
        # it is clipped to the opening rather than laid over it.
        ratio = self._thumb.devicePixelRatio() or 1.0
        picture = QRectF(0, 0, self._thumb.width() / ratio, self._thumb.height() / ratio)
        picture.moveCenter(window.center())
        painter.save()
        fit_inside(painter, window, MAT_RADIUS)
        painter.drawPixmap(picture.topLeft(), self._thumb)
        painter.restore()
        paint_bevel(painter, window, MAT_RADIUS)
        self._print_label(painter, body)

    def _print_label(self, painter: QPainter, body: QRectF) -> None:
        """What the board says under the picture: the day, and how much of it.

        Two short things on one line, the way a print is labelled under the
        mount rather than across the picture: the day it was filed on the
        left, the size of the run on the right. Everything else about it --
        which number it is, which keys carried it -- is one click away, and
        repeating that under every print only made the grid noisy.
        """
        foot = QRectF(
            body.left() + PRINT_BORDER + 1,
            body.bottom() - PRINT_FOOT,
            body.width() - (PRINT_BORDER + 1) * 2,
            PRINT_FOOT,
        )
        middle = Qt.AlignmentFlag.AlignVCenter
        painter.setFont(text_font(11, QFont.Weight.DemiBold, 0.8))
        painter.setPen(INK if self._hover else MUTED)
        painter.drawText(
            foot, Qt.AlignmentFlag.AlignLeft | middle, self.snapshot.date_text
        )
        painter.setFont(text_font(11, QFont.Weight.Medium, 0.4))
        painter.setPen(MINT if self._hover else FAINT)
        painter.drawText(
            foot, Qt.AlignmentFlag.AlignRight | middle, compact_number(self.snapshot.total)
        )


class EmptyWall(QWidget):
    """What an empty room says, in an empty frame."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Held in English and put into words as they are painted, so the
        # notice follows the language switch without being rebuilt.
        self.lines = ("Nothing is hanging here yet", "")
        self.setMinimumHeight(300)

    def set_device(self, device: str) -> None:
        pad = device == GAMEPAD_DEVICE
        self.lines = (
            "The pad wall is empty" if pad else "The keyboard wall is empty",
            "RESET files the current run as a picture. It is hung here.",
        )
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(0, 0, 268, 152)
        frame.moveCenter(self.rect().center() + QPoint(0, -22))
        pen = QPen(QColor("#d7e3df"), 1.4)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([5, 5])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(frame, 13, 13)
        painter.setPen(QColor("#b9c8c3"))
        painter.setFont(text_font(19, QFont.Weight.Medium))
        painter.drawText(frame, Qt.AlignmentFlag.AlignCenter, "( ˘ ᵕ ˘ )")
        painter.setFont(text_font(14, QFont.Weight.DemiBold))
        painter.setPen(MUTED)
        painter.drawText(
            QRect(0, int(frame.bottom()) + 20, self.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            tr(self.lines[0]),
        )
        painter.setFont(text_font(12, QFont.Weight.Medium))
        painter.setPen(FAINT)
        painter.drawText(
            QRect(0, int(frame.bottom()) + 42, self.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            tr(self.lines[1]),
        )


class Wall(QWidget):
    """The prints themselves, wrapped left to right, growing tall enough to scroll.

    The empty-room notice is a child rather than another item in the flow, so
    an empty wall stays exactly as tall as the view instead of scrolling.
    """

    # A new width means every print on the wall has to be re-cut before the
    # wall can say how tall it now is, and only the page knows how to cut
    # them, so it is told first and asked for the height afterwards.
    resized = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.flow = FlowLayout(self, spacing=GRID_GAP)
        self.flow.setContentsMargins(WALL_MARGIN, WALL_MARGIN + 4, WALL_MARGIN, WALL_MARGIN + 4)
        self.empty = EmptyWall(self)
        self.empty.hide()
        # Whether the notice is the thing on show. Not the same question as
        # whether it is on screen: the page is filled in before it is brought
        # to the front, so for the whole of that stretch the notice is what
        # the wall is showing and isVisible() still answers False.
        self.showing_empty = False

    def show_empty(self, device: str) -> None:
        self.showing_empty = True
        self.empty.set_device(device)
        self.empty.setGeometry(self.rect())
        self.empty.show()
        self.setMinimumHeight(0)

    def hide_empty(self) -> None:
        self.showing_empty = False
        self.empty.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # The notice is stretched over the wall whether or not it is on screen
        # yet. Switching to the gallery resizes the wall from whatever size it
        # was built at up to the width of the card, and that resize arrives
        # while the page is still behind the monitor -- so gating this on
        # isVisible() left the notice at its build size, parked in the top
        # left corner of an otherwise blank card.
        self.empty.setGeometry(self.rect())
        self.resized.emit()
        if self.showing_empty:
            self.setMinimumHeight(0)
        else:
            self.setMinimumHeight(self.flow.heightForWidth(self.width()))


class RankingStrip(QWidget):
    """The busiest few keys of a run, as a short bar chart."""

    ROWS = 7

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[tuple[str, int]] = []
        self.setMinimumHeight(self.ROWS * 24 + 8)

    def set_rows(self, rows: list[tuple[str, int]]) -> None:
        self.rows = rows[: self.ROWS]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self.rows:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = max(1, self.rows[0][1])
        label_w, count_w, gap = 86, 62, 14
        for index, (label, count) in enumerate(self.rows):
            y = index * 24
            painter.setFont(text_font(12, QFont.Weight.DemiBold))
            painter.setPen(INK)
            painter.drawText(
                QRect(0, y, label_w - 12, 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            track = QRectF(label_w, y + 6, max(10, self.width() - label_w - count_w - gap), 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#eef4f2"))
            painter.drawRoundedRect(track, 4, 4)
            fill = QRectF(track)
            fill.setWidth(max(4.0, track.width() * count / top))
            tint = QColor(MINT)
            tint.setAlpha(235 - index * 22)
            painter.setBrush(tint)
            painter.drawRoundedRect(fill, 4, 4)
            painter.setFont(text_font(12, QFont.Weight.Medium))
            painter.setPen(MUTED)
            painter.drawText(
                QRect(self.width() - count_w, y, count_w, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{count:,}",
            )


class FramedPicture(QWidget):
    """The exhibit itself, matted and fitted to whatever room it is given."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.picture: QPixmap | None = None
        self.note = "picture missing"
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_picture(self, path: Path | None) -> None:
        self.picture = None
        if path is not None:
            picture = QPixmap(str(path))
            if not picture.isNull():
                self.picture = picture
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        paint_board(painter, frame, 15, FRAME_EDGE)
        mat = frame.adjusted(14, 14, -14, -14)
        painter.setBrush(MAT)
        painter.setPen(QPen(MAT_EDGE, 1))
        painter.drawRoundedRect(mat, 9, 9)
        if self.picture is None:
            painter.setPen(FAINT)
            painter.setFont(text_font(13, QFont.Weight.Medium))
            painter.drawText(mat, Qt.AlignmentFlag.AlignCenter, tr(self.note))
            return
        opening = mat.adjusted(10, 10, -10, -10)
        size = self.picture.size()
        scale = min(opening.width() / size.width(), opening.height() / size.height(), 1.0)
        spot = QRectF(0, 0, size.width() * scale, size.height() * scale)
        spot.moveCenter(mat.center())
        painter.drawPixmap(spot, self.picture, QRectF(self.picture.rect()))
        paint_bevel(painter, mat, 9)


class LabelRow(QWidget):
    """One line of the wall label: a caption on the left, its value on the right."""

    def __init__(self, caption: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.caption = QLabel(caption)
        self.caption.setObjectName("exhibitKey")
        self.value = QLabel("—")
        self.value.setObjectName("exhibitValue")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.caption, 0)
        row.addStretch(1)
        row.addWidget(self.value, 0)

    def set_value(self, text: str, tip: str = "") -> None:
        self.value.setText(text)
        self.value.setToolTip(tip or text)


class DetailPage(QWidget):
    """One exhibit, close up: the picture, its label, and the file behind it."""

    back_requested = Signal()
    deleted = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.snapshot: Snapshot | None = None
        self.wording = Wording()

        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(12)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        back = QPushButton()
        back.setObjectName("ghostButton")
        back.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.wording.label(back, "←  WALL", "Back to the wall")
        back.clicked.connect(self.back_requested.emit)
        bar.addWidget(back)
        self.heading = QLabel("—")
        self.heading.setObjectName("exhibitTitle")
        bar.addWidget(self.heading)
        bar.addStretch(1)
        for text, tip, slot in (
            ("COPY JSON", "Copy the whole file to the clipboard", self._copy_json),
            ("SHOW FILE", "Show this file in Explorer", self._show_file),
            ("REMOVE", "Delete this picture and its counts from disk", self._remove),
        ):
            button = QPushButton()
            button.setObjectName("ghostButton" if text != "REMOVE" else "resetButton")
            button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.wording.label(button, text, tip)
            button.clicked.connect(slot)
            bar.addWidget(button)
        page.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(14)
        self.picture = FramedPicture()
        left.addWidget(self.picture, 1)
        ranking = QFrame()
        ranking.setObjectName("exhibitCard")
        ranking_box = QVBoxLayout(ranking)
        ranking_box.setContentsMargins(20, 16, 20, 16)
        ranking_box.setSpacing(10)
        caption = QLabel()
        caption.setObjectName("exhibitKey")
        self.wording.label(caption, "BUSIEST")
        ranking_box.addWidget(caption)
        self.ranking = RankingStrip()
        ranking_box.addWidget(self.ranking)
        left.addWidget(ranking, 0)
        body.addLayout(left, 5)

        right = QVBoxLayout()
        right.setSpacing(14)
        label = QFrame()
        label.setObjectName("exhibitCard")
        label_box = QVBoxLayout(label)
        label_box.setContentsMargins(20, 16, 20, 18)
        label_box.setSpacing(9)
        title = QLabel()
        title.setObjectName("exhibitKey")
        self.wording.label(title, "EXHIBIT LABEL")
        label_box.addWidget(title)
        self.rows: dict[str, LabelRow] = {}
        for key, caption_text in (
            ("from", "Counted from"),
            ("until", "Counted until"),
            ("span", "Span"),
            ("days", "Dates covered"),
            ("total", "Total"),
            ("distinct", "Distinct"),
            ("device", "Device"),
            ("file", "File"),
        ):
            row = LabelRow()
            self.wording.label(row.caption, caption_text)
            self.rows[key] = row
            label_box.addWidget(row)
        right.addWidget(label, 0)

        json_card = QFrame()
        json_card.setObjectName("exhibitCard")
        json_box = QVBoxLayout(json_card)
        json_box.setContentsMargins(20, 16, 20, 16)
        json_box.setSpacing(10)
        json_title = QLabel("JSON")
        json_title.setObjectName("exhibitKey")
        json_box.addWidget(json_title)
        self.json_view = QPlainTextEdit()
        self.json_view.setObjectName("jsonView")
        self.json_view.setReadOnly(True)
        self.json_view.setFont(mono_font(12))
        self.json_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        json_box.addWidget(self.json_view, 1)
        right.addWidget(json_card, 1)
        body.addLayout(right, 4)
        page.addLayout(body, 1)

    def show_snapshot(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        pad = snapshot.device == GAMEPAD_DEVICE
        self.heading.setText(tr("No. {number}   ·   {title}").format(
            number=f"{snapshot.number:02d}", title=snapshot.title
        ))
        self.picture.note = (
            "the picture of this run is missing" if snapshot.image_path is None else ""
        )
        self.picture.set_picture(snapshot.image_path)
        self.ranking.set_rows(snapshot.ranking)

        start_text = _stamp(snapshot.started_at, snapshot.start_is_day_only)
        if snapshot.start_is_day_only:
            start_text += tr("   (first day)")
        self.rows["from"].set_value(start_text)
        self.rows["until"].set_value(_stamp(snapshot.archived_at))
        self.rows["span"].set_value(_span(snapshot.started_at, snapshot.archived_at))
        days = (
            f"{snapshot.first_day} → {snapshot.last_day}"
            if snapshot.first_day and snapshot.last_day and snapshot.first_day != snapshot.last_day
            else (snapshot.first_day or "—")
        )
        self.rows["days"].set_value(days)
        self.rows["total"].set_value(snapshot.counted)
        self.rows["distinct"].set_value(snapshot.spread)
        # Archives from before the layout was recorded name the device alone
        # rather than repeating it as its own model.
        name = tr("Gamepad") if pad else tr("Keyboard")
        model = tr(snapshot.layout_name)
        self.rows["device"].set_value(f"{name}  ·  {model}" if model else name)
        self.rows["file"].set_value(snapshot.json_path.name, str(snapshot.json_path))
        self.json_view.setPlainText(snapshot.text)
        self.json_view.verticalScrollBar().setValue(0)

    def retranslate(self) -> None:
        """Say the exhibit again, label and all, in the language now in force."""
        self.wording.apply()
        if self.snapshot is not None:
            self.show_snapshot(self.snapshot)

    # -- actions -----------------------------------------------------------

    def _copy_json(self) -> None:
        if self.snapshot is None:
            return
        QGuiApplication.clipboard().setText(self.snapshot.text)

    def _show_file(self) -> None:
        if self.snapshot is None:
            return
        reveal(self.snapshot.json_path)

    def _remove(self) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("Remove exhibit"))
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(tr("Take No. {number} off the wall?").format(
            number=f"{snapshot.number:02d}"
        ))
        box.setInformativeText(tr(
            "{file} and its picture are deleted from disk, from every folder KeyPulse keeps "
            "archives in. This cannot be undone."
        ).format(file=snapshot.json_path.name))
        confirm = box.addButton(tr("Delete"), QMessageBox.ButtonRole.AcceptRole)
        confirm.setObjectName("dangerButton")
        confirm.style().unpolish(confirm)
        confirm.style().polish(confirm)
        cancel = box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() is not confirm:
            return
        # Taking it off the wall has to take it off the disk, in every folder
        # at once: a copy left behind in an older one is adopted back at the
        # next start, and the exhibit the user just deleted comes back.
        beaten = remove_snapshot(snapshot.json_path)
        if beaten:
            failed = QMessageBox(self)
            failed.setWindowTitle(tr("Remove failed"))
            failed.setIcon(QMessageBox.Icon.NoIcon)
            failed.setTextFormat(Qt.TextFormat.PlainText)
            failed.setText(tr("Part of this exhibit could not be deleted."))
            failed.setInformativeText(
                LINE_BREAK.join(f"{path}: {error.strerror or error}" for path, error in beaten)
            )
            failed.addButton(tr("OK"), QMessageBox.ButtonRole.AcceptRole)
            failed.exec()
        self.deleted.emit()


class GalleryPage(QWidget):
    """The room: a wall per device, and the exhibit a click opens."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.wording = Wording()
        self.device = KEYBOARD_DEVICE
        self.walls: dict[str, list[Snapshot]] = {KEYBOARD_DEVICE: [], GAMEPAD_DEVICE: []}
        self.cards: list[FrameCard] = []
        self._stale = True
        self._mark = (-1, -1)
        self._fresh: Path | None = None

        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(16)
        page.addWidget(self._build_bar())

        self.stack = QStackedWidget()
        # The window paints this card's shadow for it, the way it does the
        # monitor's, so it is kept where the window can reach it.
        panel = self.panel = QFrame()
        panel.setObjectName("wallPanel")
        panel_box = QVBoxLayout(panel)
        panel_box.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("wallScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.wall = Wall()
        self.wall.resized.connect(self._fit_prints)
        self.scroll.setWidget(self.wall)
        panel_box.addWidget(self.scroll)
        self.stack.addWidget(panel)

        self.detail = DetailPage()
        self.detail.back_requested.connect(self.show_wall)
        self.detail.deleted.connect(self._after_delete)
        self.stack.addWidget(self.detail)
        page.addWidget(self.stack, 1)

        # Thumbnails are decoded a few per tick, so a wall of fifty pictures
        # never freezes the switch onto it.
        self._loader = QTimer(self)
        self._loader.setInterval(16)
        self._loader.timeout.connect(self._load_some)

    # -- construction ------------------------------------------------------

    def _build_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("toolbar")
        bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 12, 18, 12)
        row.setSpacing(12)

        caption = QLabel()
        caption.setObjectName("controlLabel")
        self.wording.label(caption, "WALL")
        row.addWidget(caption, 0, Qt.AlignmentFlag.AlignVCenter)

        segment = QFrame()
        segment.setObjectName("segment")
        inner = QHBoxLayout(segment)
        inner.setContentsMargins(3, 3, 3, 3)
        inner.setSpacing(3)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for device, text, tip in (
            (KEYBOARD_DEVICE, "KEYBOARD", "Runs archived from the keyboard"),
            (GAMEPAD_DEVICE, "GAMEPAD", "Runs archived from the controller"),
        ):
            button = QPushButton()
            button.setObjectName("segmentButton")
            button.setCheckable(True)
            button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.wording.label(button, text, tip)
            button.clicked.connect(lambda _checked, name=device: self.show_device(name))
            self.group.addButton(button)
            self.buttons[device] = button
            inner.addWidget(button)
        self.buttons[KEYBOARD_DEVICE].setChecked(True)
        row.addWidget(segment, 0, Qt.AlignmentFlag.AlignVCenter)

        self.count_label = QLabel("")
        self.count_label.setObjectName("wallCount")
        row.addWidget(self.count_label, 0, Qt.AlignmentFlag.AlignVCenter)

        row.addStretch(1)
        folder = QPushButton()
        folder.setObjectName("ghostButton")
        folder.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.wording.label(folder, "FOLDER", "Open the folder this wall is filed in")
        # The wall on screen and the folder on disk are the same shelf, so the
        # button opens the one belonging to the device being shown. Before the
        # first RESET neither exists yet, and asking Explorer to open a path
        # that is not there does nothing at all.
        folder.clicked.connect(lambda: open_folder(ensure_snapshot_dir(self.device)))
        row.addWidget(folder)
        return bar

    # -- wall --------------------------------------------------------------

    def invalidate(self, fresh: Path | None = None) -> None:
        """A run was filed or removed: rebuild the wall the next time it shows."""
        self._stale = True
        if fresh is not None:
            self._fresh = fresh

    def refresh(self, force: bool = False) -> None:
        mark = archive_mark()
        if not self._stale and not force and mark == self._mark:
            return
        self._stale = False
        self._mark = mark
        self.walls = read_snapshots()
        self._rebuild()

    def show_device(self, device: str) -> None:
        self.device = device
        self.buttons[device].setChecked(True)
        self._rebuild()
        self.show_wall()

    def show_wall(self) -> None:
        self.stack.setCurrentIndex(0)

    def retranslate(self) -> None:
        """Say the room again, in the language now in force.

        The count beside the switch, the notice on an empty wall and the
        tooltip on every print are all written while the wall is being filled,
        so the wall is simply filled again.
        """
        self.wording.apply()
        self.detail.retranslate()
        self._rebuild()

    def show_detail(self, snapshot: Snapshot) -> None:
        self.detail.show_snapshot(snapshot)
        self.stack.setCurrentIndex(1)

    def opened(self, device: str | None = None) -> None:
        """Called when the page comes on screen."""
        self.refresh()
        if device is not None and device != self.device:
            self.show_device(device)
        else:
            self.show_wall()

    def _print_size(self, snapshots: list[Snapshot]) -> QSize:
        """How big one print is on this wall, and so how many fit in a row.

        A row takes as many prints as the wall is wide enough for and then
        shares the leftover evenly between them, so the grid ends flush on
        both edges instead of trailing off. Every print on a wall is cut to
        one shape -- the shape the pictures on it actually are -- so the
        rows line up and a picture is never stretched to fit.
        """
        room = max(260, self.wall.width() - WALL_MARGIN * 2)
        asked = TARGET_PRINT.get(self.device, 380) + PRINT_BORDER * 2
        columns = max(1, int((room + GRID_GAP) // (asked + GRID_GAP)))
        card = min((room - GRID_GAP * (columns - 1)) / columns, asked * WIDEST_PRINT)
        width = max(140, int(card) - PRINT_BORDER * 2)
        shapes = sorted(piece.ratio for piece in snapshots if piece.ratio > 0)
        ratio = shapes[len(shapes) // 2] if shapes else DEFAULT_RATIO.get(self.device, 2.0)
        ratio = min(max(ratio, RATIO_RANGE[0]), RATIO_RANGE[1])
        return QSize(width, max(90, round(width / ratio)))

    def _fit_prints(self) -> None:
        """Re-cut every print on the wall to the width the wall now has."""
        if not self.cards:
            return
        size = self._print_size([card.snapshot for card in self.cards])
        changed = False
        for card in self.cards:
            was = card.size()
            card.set_print_size(size)
            changed = changed or card.size() != was
        if changed:
            self.wall.flow.invalidate()
            # A print that grew wants its picture decoded again, larger.
            if not self._loader.isActive():
                self._loader.start()

    def _show_fresh(self) -> None:
        """Scroll to the run just filed: it is the last print, not the first."""
        card = next((card for card in self.cards if card.fresh), None)
        if card is not None:
            self.scroll.ensureWidgetVisible(card, 0, 40)

    def _rebuild(self) -> None:
        self._loader.stop()
        layout = self.wall.flow
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.cards = []

        snapshots = self.walls.get(self.device, [])
        pieces = len(snapshots)
        self.count_label.setText(
            "" if not pieces
            else tr("{pieces} piece" if pieces == 1 else "{pieces} pieces").format(pieces=pieces)
        )
        if not pieces:
            self.wall.show_empty(self.device)
            return

        self.wall.hide_empty()
        size = self._print_size(snapshots)
        for snapshot in snapshots:
            card = FrameCard(snapshot, size, fresh=snapshot.json_path == self._fresh)
            card.clicked.connect(self.show_detail)
            layout.addWidget(card)
            self.cards.append(card)
        self.wall.setMinimumHeight(layout.heightForWidth(max(1, self.wall.width())))
        self._loader.start()
        if any(card.fresh for card in self.cards):
            # The album is filled oldest first, so the run just filed is at
            # the end of it -- worth scrolling to, once the wall is laid out.
            QTimer.singleShot(0, self._show_fresh)
        else:
            self.scroll.verticalScrollBar().setValue(0)

    def _load_some(self) -> None:
        pending = [card for card in self.cards if not card.is_loaded]
        if not pending:
            self._loader.stop()
            return
        for card in pending[:3]:
            card.load()

    def _after_delete(self) -> None:
        self._fresh = None
        self.refresh(force=True)
        self.show_wall()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.stack.currentIndex() == 1:
            self.show_wall()
            return
        super().keyPressEvent(event)
