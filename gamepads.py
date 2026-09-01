from __future__ import annotations

"""Geometry for the controller view.

Everything here is measured in pad units, the unit ``pad_reference`` traces
the picture into: 1.0 is 162 pixels of the reference, x runs right and y runs
down, and the origin sits at the top left corner of the silhouette.

The shell, the shoulder, the trigger paddles and the grip panel on them are
point rings copied out of ``pad_reference`` untouched. Everything standing on
the face is built here from the measurements in the same module -- a circle, a
leaning bar, a cross, a stick of three circles -- because those are the shapes
the picture actually draws, and describing them by their dimensions is what
lets a model that is not the reference one move a control without needing the
picture re-traced for it.

A model is that shell plus the controls standing on it. The four models are
the four pads in the reference picture -- an Xbox pad, a DualSense, a Switch
Pro and a plain wired XInput pad -- and they share the shell: what one of them
changes, in a view drawn straight at the face, is which name is on which
button and where the hands go, and nothing else this view can show.
"""

import math
from dataclasses import dataclass, replace

import pad_reference as REF


# The reference is looked at straight on: no part of the pad is drawn with a
# side wall anywhere in it, so nothing here is extruded and all of the depth
# is carried by the shading instead.
STICK_TRAVEL = 0.17      # how far a cap slides at full deflection, in units


@dataclass(frozen=True)
class PadCallout:
    """Where a control writes its count, and how the line reaches it.

    The reference picture leaves the four readout bars carrying their own
    numbers and hangs every other count off its control on a leader, in the
    nearest piece of bare shell. ``side`` is which way the chip lies, ``gap``
    how far its near end stands off the control, and ``drop`` how far it is
    carried across that -- lifted above the line for the top of the face
    diamond, dropped below it for the bottom. ``elbow`` bends the leader
    square instead of curving it, which is what View and Menu are given.
    """

    side: str                                  # right | left | above | below
    gap: float
    drop: float = 0.0
    elbow: bool = False


@dataclass(frozen=True)
class PadElement:
    """One control standing on the face plate.

    ``callout`` is where its count is written, for the controls the picture
    leaves bare -- the four readout bars carry theirs on the bar itself.
    ``outline`` is the footprint: the ring the control occupies on the shell,
    used for hit rectangles and for the checks that keep two of them from
    sharing any ground. ``rings`` carries the extra circles a stick needs --
    its well, its knurled flange and its cap -- which are not concentric and
    so cannot be derived from the footprint.
    """

    element_id: str
    label: str
    x: float                                   # centre
    y: float
    width: float
    height: float
    kind: str                                  # pill | face | small | cross | arm | stick
    outline: tuple[tuple[float, float], ...]
    counted: bool = True
    shows_count: bool = False                  # the four readout bars, in the bar
    glyph: str = ""                            # view | menu | up | down | left | right
    axis: str = ""                             # left | right, for sticks
    tilt: float = 0.0                          # degrees, for a leaning bar
    rings: tuple[tuple[float, float, float, float], ...] = ()
    callout: PadCallout | None = None          # where its count is written

    def moved(self, dx: float, dy: float) -> "PadElement":
        return replace(
            self,
            x=self.x + dx,
            y=self.y + dy,
            outline=tuple((px + dx, py + dy) for px, py in self.outline),
            rings=tuple((cx + dx, cy + dy, rx, ry) for cx, cy, rx, ry in self.rings),
        )


@dataclass(frozen=True)
class PadLight:
    """A lamp the real controller actually has.

    Only lighting the shipping product carries is drawn: the ring round the
    Xbox button, the strips beside a DualSense touch pad, the four player
    slots on a Switch Pro. A pad with no lamps -- the plain wired one -- stays
    dark rather than borrowing the keyboard's backlight.
    """

    light_id: str
    outline: tuple[tuple[float, float], ...]
    colour: str                # rgb (follows the wave) | a fixed hex tone
    reach: float = 0.10        # how far the bloom spreads, in pad units
    lit: bool = True           # a dark slot still shows, it just does not glow

    @property
    def animated(self) -> bool:
        return self.colour == "rgb"

    def moved(self, dx: float, dy: float) -> "PadLight":
        return replace(self, outline=tuple((x + dx, y + dy) for x, y in self.outline))


@dataclass(frozen=True)
class PadLayout:
    layout_id: str
    name: str
    elements: tuple[PadElement, ...]
    outline: tuple[tuple[float, float], ...]          # the shell
    width: float
    height: float
    shoulder: tuple[tuple[float, float], ...] = ()    # paddles and the trim
    paddles: tuple[tuple[tuple[float, float], ...], ...] = ()
    panels: tuple[tuple[tuple[float, float], ...], ...] = ()
    hexagon: tuple[tuple[float, float], ...] = ()
    led: tuple[float, float] | None = None            # the pairing pinhole
    lights: tuple[PadLight, ...] = ()
    # The lead of a wired pad, as the rings it is drawn from. It rises into
    # the notch between the two shoulder horns, which is empty on every model,
    # so carrying one costs the pad no height and none of them change size.
    cable: tuple[tuple[tuple[float, float], ...], ...] = ()

    @property
    def keys(self) -> tuple[PadElement, ...]:
        """Alias so shared canvas code can treat a pad like a board."""
        return self.elements

    def labels(self) -> dict[str, str]:
        """What this model calls each button it counts, for the summary cards."""
        return {
            element.element_id: element.label
            for element in self.elements
            if element.counted
        }


# --- ring builders ---------------------------------------------------------


def _signed_area(points) -> float:
    total = 0.0
    for index, (x, y) in enumerate(points):
        nx, ny = points[(index + 1) % len(points)]
        total += x * ny - nx * y
    return total


def _clockwise(points) -> tuple[tuple[float, float], ...]:
    return tuple(points if _signed_area(points) >= 0.0 else list(reversed(points)))


def _ellipse(cx: float, cy: float, rx: float, ry: float, steps: int = 48):
    return _clockwise([
        (
            cx + rx * math.cos(2.0 * math.pi * index / steps),
            cy + ry * math.sin(2.0 * math.pi * index / steps),
        )
        for index in range(steps)
    ])


def _arc(cx: float, cy: float, radius: float, start: float, sweep: float, steps: int = 7):
    return [
        (
            cx + radius * math.cos(math.radians(start + sweep * step / steps)),
            cy + radius * math.sin(math.radians(start + sweep * step / steps)),
        )
        for step in range(steps + 1)
    ]


def _stadium(cx: float, cy: float, width: float, height: float, tilt: float = 0.0):
    """A bar with fully round ends, leaning by ``tilt`` degrees.

    The four readout bars follow the curve of the shell edge above them, so
    each one leans a few degrees; drawing them level is the single thing that
    reads as wrong fastest when the pad is put beside the picture.
    """
    radius = height * 0.5
    reach = width * 0.5 - radius
    points = _arc(reach, 0.0, radius, -90.0, 180.0, 12) + _arc(-reach, 0.0, radius, 90.0, 180.0, 12)
    angle = math.radians(tilt)
    cos, sin = math.cos(angle), math.sin(angle)
    return _clockwise([
        (cx + x * cos - y * sin, cy + x * sin + y * cos) for x, y in points
    ])


def _rounded(cx: float, cy: float, width: float, height: float, radius: float, steps: int = 8):
    radius = max(0.0, min(radius, width * 0.5, height * 0.5))
    left, right = cx - width * 0.5, cx + width * 0.5
    top, bottom = cy - height * 0.5, cy + height * 0.5
    points: list[tuple[float, float]] = []
    for ox, oy, start in (
        (right - radius, top + radius, -90.0),
        (right - radius, bottom - radius, 0.0),
        (left + radius, bottom - radius, 90.0),
        (left + radius, top + radius, 180.0),
    ):
        points += _arc(ox, oy, radius, start, 90.0, steps)
    return _clockwise(points)


def _cross_ring(cx: float, cy: float, width: float, height: float,
                bar_x: float, bar_y: float, radius: float):
    """The D-pad silhouette: one moulded cross with every corner filleted."""
    half_w, half_h = width * 0.5, height * 0.5
    bar_hw, bar_hh = bar_x * 0.5, bar_y * 0.5
    # Outer corners are rounded off; the four inner armpits are filleted the
    # other way, and far more generously, which is what stops the cross
    # reading as four tiles glued at the corners.
    inner = radius * 1.5
    points: list[tuple[float, float]] = []
    points += _arc(cx + bar_hw - radius, cy - half_h + radius, radius, -90.0, 90.0)
    points += _arc(cx + bar_hw + inner, cy - bar_hh - inner, inner, 180.0, -90.0)
    points += _arc(cx + half_w - radius, cy - bar_hh + radius, radius, -90.0, 90.0)
    points += _arc(cx + half_w - radius, cy + bar_hh - radius, radius, 0.0, 90.0)
    points += _arc(cx + bar_hw + inner, cy + bar_hh + inner, inner, -90.0, -90.0)
    points += _arc(cx + bar_hw - radius, cy + half_h - radius, radius, 0.0, 90.0)
    points += _arc(cx - bar_hw + radius, cy + half_h - radius, radius, 90.0, 90.0)
    points += _arc(cx - bar_hw - inner, cy + bar_hh + inner, inner, 0.0, -90.0)
    points += _arc(cx - half_w + radius, cy + bar_hh - radius, radius, 90.0, 90.0)
    points += _arc(cx - half_w + radius, cy - bar_hh + radius, radius, 180.0, 90.0)
    points += _arc(cx - bar_hw - inner, cy - bar_hh - inner, inner, 90.0, -90.0)
    points += _arc(cx - bar_hw + radius, cy - half_h + radius, radius, 180.0, 90.0)
    return _clockwise(points)


def _fillet(before, corner, after, radius: float, steps: int = 6):
    """Round one corner off with a quadratic bend through it."""
    points = []
    ends = []
    for other in (before, after):
        dx, dy = other[0] - corner[0], other[1] - corner[1]
        span = math.hypot(dx, dy) or 1.0
        share = min(0.45, radius / span)
        ends.append((corner[0] + dx * share, corner[1] + dy * share))
    entry, exit_point = ends
    for step in range(steps + 1):
        t = step / steps
        inverse = 1.0 - t
        points.append((
            inverse * inverse * entry[0] + 2 * inverse * t * corner[0] + t * t * exit_point[0],
            inverse * inverse * entry[1] + 2 * inverse * t * corner[1] + t * t * exit_point[1],
        ))
    return points


def _hexagon():
    """The panel scored into the shell around the guide button.

    Six corners, each filleted, mirrored about the shell's own centre line.
    Its top side is the lower edge of the shoulder trim and is drawn by the
    trim itself, so what comes back is an open polyline that starts at the
    top left corner and finishes at the top right one -- the five sides that
    the picture actually scores into the shell, and no more.
    """
    top_left = REF.HEX_TOP_LEFT
    top_right = (2 * REF.AXIS - top_left[0], top_left[1])
    left = REF.HEX_LEFT
    right = (2 * REF.AXIS - left[0], left[1])
    bottom_left = REF.HEX_BOTTOM_LEFT
    bottom_right = (2 * REF.AXIS - bottom_left[0], bottom_left[1])
    walk = (top_right, top_left, left, bottom_left, bottom_right, right, top_right, top_left)
    points: list[tuple[float, float]] = []
    for index in range(1, len(walk) - 1):
        points += _fillet(walk[index - 1], walk[index], walk[index + 1], REF.HEX_R)
    return tuple(points)


def callout_box(element: PadElement, width: float,
                height: float) -> tuple[float, float, float, float] | None:
    """Where a control's chip stands, in pad units, at the size it needs.

    The chip is laid out here rather than on the canvas because where it
    lands is a fact about the pad -- which piece of shell beside a control is
    bare -- and the canvas only has to draw it. How wide it needs to be is
    the canvas's business, since that is a question about a font, so it comes
    in as an argument.
    """
    mark = element.callout
    if mark is None:
        return None
    if mark.side in ("left", "right"):
        sign = 1.0 if mark.side == "right" else -1.0
        near = element.x + sign * (element.width * 0.5 + mark.gap)
        return (near if sign > 0 else near - width,
                element.y + mark.drop - height * 0.5, width, height)
    sign = 1.0 if mark.side == "below" else -1.0
    near = element.y + sign * (element.height * 0.5 + mark.gap)
    return (element.x + mark.drop - width * 0.5,
            near if sign > 0 else near - height, width, height)


def _mirror(point):
    return (2 * REF.AXIS - point[0], point[1])


# --- where the counts hang -------------------------------------------------

# The face diamond, in the order the picture numbers it: up, right, down,
# left. Three of them have bare shell straight out from the diamond and take
# it; the inboard one has Menu in the way, so its count drops under the row
# those two buttons make and comes back on a bent line.
FACE_CALLOUTS = (
    PadCallout("right", 0.32, -0.24),
    PadCallout("right", 0.13),
    PadCallout("right", 0.42, 0.10),
    PadCallout("left", 0.45, 0.45),
)

# The D-pad: each limb writes its count straight out of its own end.
CROSS_CALLOUTS = {
    "DPAD_UP": PadCallout("above", 0.07),
    "DPAD_DOWN": PadCallout("below", 0.05),
    "DPAD_LEFT": PadCallout("left", 0.14),
    "DPAD_RIGHT": PadCallout("right", 0.14),
}

# View and Menu sit in the middle of the shell with the hexagon above them and
# a stick either side, so their counts go up into the corner of that gap on a
# square leader rather than straight out into something.
SMALL_CALLOUTS = (
    PadCallout("left", 0.40, -0.50, elbow=True),
    PadCallout("right", 0.40, -0.50, elbow=True),
)

# A Switch Pro stands its Home button in the bare shell every other pad
# leaves under Menu, which is where the inboard face writes its count -- so on
# that pad alone the count goes up over the row above instead of down under it.
SWITCH_FACE_CALLOUTS = FACE_CALLOUTS[:3] + (PadCallout("left", 0.45, -0.45),)

STICK_CALLOUTS = (PadCallout("left", 0.16), PadCallout("right", 0.16))


# --- element builders ------------------------------------------------------


def _face(element_id: str, label: str, centre, glyph: str = "",
          diameter: float = REF.FACE_D, callout: PadCallout | None = None,
          counted: bool = True) -> PadElement:
    cx, cy = centre
    radius = diameter * 0.5
    return PadElement(
        element_id, label, cx, cy, diameter, diameter, "face",
        _ellipse(cx, cy, radius, radius), counted=counted,
        glyph=glyph or label, callout=callout,
    )


def _guide() -> PadElement:
    """The Xbox button: a lit ring with the moulded sphere sunk inside it."""
    cx, cy = REF.GUIDE
    radius = REF.GUIDE_RING_R
    return PadElement(
        "GUIDE", "Guide", cx, cy, radius * 2, radius * 2, "guide",
        _ellipse(cx, cy, radius, radius),
    )


def _small(element_id: str, label: str, glyph: str, centre,
           callout: PadCallout | None = None) -> PadElement:
    cx, cy = centre
    return PadElement(
        element_id, label, cx, cy, REF.SMALL_W, REF.SMALL_H, "small",
        _rounded(cx, cy, REF.SMALL_W, REF.SMALL_H, REF.SMALL_R), glyph=glyph,
        callout=callout,
    )


def _bar(element_id: str, label: str, centre, width: float, tilt: float) -> PadElement:
    cx, cy = centre
    return PadElement(
        element_id, label, cx, cy, width, REF.LT_H, "pill",
        _stadium(cx, cy, width, REF.LT_H, tilt), shows_count=True, tilt=tilt,
    )


def _stick(element_id: str, label: str, axis: str, well, well_r,
           flange, flange_rx, flange_ry, cap, cap_rx, cap_ry,
           at=None, callout: PadCallout | None = None) -> PadElement:
    """One thumbstick: a well, a knurled flange standing in it, and the cap.

    ``at`` moves the whole assembly somewhere else on the shell while keeping
    the three circles the offsets from each other the picture gives them --
    which is the only thing that makes a stick read as pointing at the viewer.
    """
    dx = dy = 0.0
    if at is not None:
        dx, dy = at[0] - well[0], at[1] - well[1]
    cx, cy = well[0] + dx, well[1] + dy
    return PadElement(
        element_id, label, cx, cy, well_r * 2.0, well_r * 2.0, "stick",
        _ellipse(cx, cy, well_r, well_r), glyph="", axis=axis, callout=callout,
        rings=(
            (cx, cy, well_r, well_r),
            (flange[0] + dx, flange[1] + dy, flange_rx, flange_ry),
            (cap[0] + dx, cap[1] + dy, cap_rx, cap_ry),
        ),
    )


def _left_stick(at=None, callout: PadCallout | None = None) -> PadElement:
    return _stick(
        "LS", "LS", "left", REF.LS_WELL, REF.LS_WELL_R,
        REF.LS_FLANGE, REF.LS_FLANGE_RX, REF.LS_FLANGE_RY,
        REF.LS_CAP, REF.LS_CAP_RX, REF.LS_CAP_RY, at,
        callout or STICK_CALLOUTS[0],
    )


def _right_stick(at=None, callout: PadCallout | None = None) -> PadElement:
    return _stick(
        "RS", "RS", "right", REF.RS_WELL, REF.RS_WELL_R,
        REF.RS_FLANGE, REF.RS_FLANGE_RX, REF.RS_FLANGE_RY,
        REF.RS_CAP, REF.RS_CAP_RX, REF.RS_CAP_RY, at,
        callout or STICK_CALLOUTS[1],
    )


def _cross(at=None) -> list[PadElement]:
    """The D-pad: one moulded cross with the four directions inside it.

    The picture draws a single cross, not four tiles with daylight between
    them, so that is what the shell carries. The directions ride along as the
    limbs of it: they are never drawn on their own, the cross paints each limb
    in the colour its own count earns, so a heat map survives a shape that has
    no seams to hang four separate caps on.
    """
    cx, cy = at or REF.DPAD
    ring = _cross_ring(cx, cy, REF.DPAD_W, REF.DPAD_H,
                       REF.DPAD_BAR_X, REF.DPAD_BAR_Y, REF.DPAD_R)
    reach_x, reach_y = REF.DPAD_W * 0.5, REF.DPAD_H * 0.5
    bar_x, bar_y = REF.DPAD_BAR_X * 0.5, REF.DPAD_BAR_Y * 0.5
    limbs = (
        ("DPAD_UP", "Up", "up", cx, cy - (reach_y + bar_y) * 0.5,
         bar_x * 2, reach_y - bar_y),
        ("DPAD_DOWN", "Down", "down", cx, cy + (reach_y + bar_y) * 0.5,
         bar_x * 2, reach_y - bar_y),
        ("DPAD_LEFT", "Left", "left", cx - (reach_x + bar_x) * 0.5, cy,
         reach_x - bar_x, bar_y * 2),
        ("DPAD_RIGHT", "Right", "right", cx + (reach_x + bar_x) * 0.5, cy,
         reach_x - bar_x, bar_y * 2),
    )
    elements = [PadElement("DPAD", "", cx, cy, REF.DPAD_W, REF.DPAD_H,
                           "cross", ring, counted=False)]
    elements += [
        PadElement(element_id, label, ax, ay, w, h, "arm",
                   _rounded(ax, ay, w, h, 0.0), glyph=glyph,
                   callout=CROSS_CALLOUTS[element_id])
        for element_id, label, glyph, ax, ay, w, h in limbs
    ]
    return elements


def _stud(element_id: str, label: str, centre, diameter: float) -> PadElement:
    """A small moulded button with no mark cut into it.

    Turbo, mode, share: things the pads in the picture carry that XInput never
    reports, so they are counted by nothing and read by nothing. They are here
    because they are what tells one pad from another at a glance -- an Xbox
    pad has one of them under its View and Menu pair, a plain wired pad has
    two, and that is the difference the picture actually shows.
    """
    cx, cy = centre
    radius = diameter * 0.5
    return PadElement(
        element_id, label, cx, cy, diameter, diameter, "small",
        _ellipse(cx, cy, radius, radius), counted=False,
    )


def _cable() -> tuple[tuple[tuple[float, float], ...], ...]:
    """The lead of a wired pad: a stalk and the strain relief it comes out of.

    It rises out of the notch between the two shoulder horns -- the one part
    of the picture above the shell that no model has anything in -- so it is
    drawn without the pad growing a millimetre, and the shell is painted over
    its foot afterwards so the two meet rather than butt together.
    """
    lead = _rounded(REF.AXIS, 0.35, 0.230, 0.68, 0.1150)
    collar = _rounded(REF.AXIS, 0.77, 0.360, 0.52, 0.1100)
    return (lead, collar)


def _lamp(light_id: str, cx: float, cy: float, width: float, height: float,
          colour: str, radius: float | None = None, reach: float = 0.10,
          lit: bool = True) -> PadLight:
    if radius is None:
        radius = min(width, height) * 0.5
    return PadLight(light_id, _rounded(cx, cy, width, height, radius), colour, reach, lit)


# --- assembly --------------------------------------------------------------


def _assemble(layout_id: str, name: str, elements: list[PadElement],
              lights: list[PadLight] | None = None,
              led: tuple[float, float] | None = None,
              cable: tuple[tuple[tuple[float, float], ...], ...] = ()) -> PadLayout:
    lights = lights or []
    right_paddle = tuple(_mirror(point) for point in REF.PADDLE)
    right_panel = tuple(_mirror(point) for point in REF.PANEL)
    points = (
        list(REF.BODY) + list(REF.SHOULDER)
        + [point for element in elements for point in element.outline]
        + [point for ring in cable for point in ring]
    )
    dx = -min(x for x, _ in points)
    dy = -min(y for _, y in points)

    def shift(ring):
        return tuple((x + dx, y + dy) for x, y in ring)

    return PadLayout(
        layout_id,
        name,
        tuple(element.moved(dx, dy) for element in elements),
        shift(REF.BODY),
        max(x for x, _ in points) + dx,
        max(y for _, y in points) + dy,
        shift(REF.SHOULDER),
        (shift(REF.PADDLE), shift(right_paddle)),
        (shift(REF.PANEL), shift(right_panel)),
        shift(_hexagon()),
        None if led is None else (led[0] + dx, led[1] + dy),
        tuple(light.moved(dx, dy) for light in lights),
        tuple(shift(ring) for ring in cable),
    )


# --- models ----------------------------------------------------------------

SMALL_LEFT = (REF.AXIS - REF.SMALL_DX, REF.SMALL_Y)
SMALL_RIGHT = (REF.AXIS + REF.SMALL_DX, REF.SMALL_Y)
LT_AT = REF.LT
LB_AT = REF.LB
RT_AT = _mirror(REF.LT)
RB_AT = _mirror(REF.LB)


def _shoulders(labels: tuple[str, str, str, str]) -> list[PadElement]:
    """The four readout bars, in the corners the picture puts them.

    These are the only controls that carry their count inside themselves:
    the picture prints the trigger and bumper counts on the bars, and every
    other button on the pad is given its number on a leader instead.
    """
    left_trigger, right_trigger, left_bumper, right_bumper = labels
    return [
        _bar("LT", left_trigger, LT_AT, REF.LT_W, REF.LT_TILT),
        _bar("RT", right_trigger, RT_AT, REF.LT_W, -REF.LT_TILT),
        _bar("LB", left_bumper, LB_AT, REF.LB_W, REF.LB_TILT),
        _bar("RB", right_bumper, RB_AT, REF.LB_W, -REF.LB_TILT),
    ]


def _face_diamond(labels: tuple[str, str, str, str],
                  callouts: tuple[PadCallout, ...] = FACE_CALLOUTS) -> list[PadElement]:
    up, right, down, left = labels
    return [
        _face("FACE_UP", up, REF.FACE_UP, callout=callouts[0]),
        _face("FACE_RIGHT", right, REF.FACE_RIGHT, callout=callouts[1]),
        _face("FACE_DOWN", down, REF.FACE_DOWN, callout=callouts[2]),
        _face("FACE_LEFT", left, REF.FACE_LEFT, callout=callouts[3]),
    ]


def _guide_lamp() -> PadLight:
    """The ring round the guide button: the one lamp an Xbox pad shows."""
    cx, cy = REF.GUIDE
    return _lamp("guide", cx, cy, REF.GUIDE_RING_R * 2, REF.GUIDE_RING_R * 2,
                 "#D9EEFB", reach=0.10)


MINOR_D = 0.40           # a round button that is not one of the four faces

# The four pads in the reference picture, in the order it numbers them. What
# separates them, looked at straight on, is where the hands go and what the
# buttons are called -- so that is all each one sets.

# A DualSense carries its two sticks side by side at the bottom and puts the
# D-pad up where an Xbox pad keeps its left stick. Create and Options ride
# high and outboard, clear of the touch pad between them, and the PS button
# drops to the floor between the two sticks.
PS_SMALL_DX = 1.72
PS_SMALL_Y = 2.25
PS_GUIDE = (REF.AXIS, 4.05)

# The row under View and Menu, measured off the picture against the distance
# from the guide button to the Y key: an Xbox pad puts its share button on the
# centre line here, a wired pad a turbo and a mode button either side of it,
# and a Switch Pro its capture and home pair at the same spread.
MIDDLE_ROW_Y = REF.SMALL_Y + 0.60
STUD_DX = 0.33


def _xbox() -> PadLayout:
    """No. 1 -- the reference picture itself: every shape where it was traced.

    Its own mark in the middle is the share button sitting on the centre line
    below View and Menu, which is the one the wired pad has nothing in.
    """
    elements = _shoulders(("LT", "RT", "LB", "RB"))
    elements += [
        _guide(),
        _small("BACK", "View", "view", SMALL_LEFT, SMALL_CALLOUTS[0]),
        _small("START", "Menu", "menu", SMALL_RIGHT, SMALL_CALLOUTS[1]),
        _stud("SHARE", "Share", (REF.AXIS, MIDDLE_ROW_Y), 0.34),
        _left_stick(),
        _right_stick(),
    ]
    elements += _face_diamond(("Y", "B", "A", "X"))
    elements += _cross()
    # The pinhole under the guide button is a feature of this shell alone,
    # so only the pad it belongs to carries it.
    return _assemble("xbox", "Xbox", elements, [_guide_lamp()], led=REF.LED)


def _playstation() -> PadLayout:
    """No. 2 -- DualSense hands: D-pad up on the left, sticks side by side."""
    elements = _shoulders(("L2", "R2", "L1", "R1"))
    elements += [
        _face("GUIDE", "PS", PS_GUIDE, glyph="PS", diameter=MINOR_D),
        _small("BACK", "Create", "view", (REF.AXIS - PS_SMALL_DX, PS_SMALL_Y),
               PadCallout("above", 0.05, 0.12)),
        _small("START", "Options", "menu", (REF.AXIS + PS_SMALL_DX, PS_SMALL_Y),
               PadCallout("above", 0.05, -0.12)),
        _left_stick(at=_mirror(REF.RS_WELL)),
        _right_stick(),
    ]
    elements += _face_diamond(("△", "○", "✕", "□"))
    elements += _cross(at=REF.LS_WELL)
    # The light bar: a strip either side of where the touch pad would be, and
    # the one lamp on any of these pads a game can change the colour of.
    cx, cy = REF.GUIDE
    lights = [
        _lamp("bar_left", cx - 0.98, cy + 0.02, 0.09, 0.36, "rgb", 0.045, reach=0.11),
        _lamp("bar_right", cx + 0.98, cy + 0.02, 0.09, 0.36, "rgb", 0.045, reach=0.11),
    ]
    return _assemble("ps", "PlayStation", elements, lights)


def _switch_pro() -> PadLayout:
    """No. 3 -- Switch hands: minus and plus up, capture and home below."""
    cx = REF.AXIS
    below = REF.SMALL_Y + 0.62
    elements = _shoulders(("ZL", "ZR", "L", "R"))
    elements += [
        _face("GUIDE", "Home", (cx + 0.30, below), glyph="⌂", diameter=MINOR_D),
        # XInput has no bit for a capture button, so nothing ever reports one
        # and there is no count here to write down.
        _face("CAPTURE", "Capture", (cx - 0.30, below), glyph="◉",
              diameter=MINOR_D, counted=False),
        _small("BACK", "Minus", "minus", SMALL_LEFT, SMALL_CALLOUTS[0]),
        _small("START", "Plus", "plus", SMALL_RIGHT, SMALL_CALLOUTS[1]),
        _left_stick(),
        _right_stick(),
    ]
    elements += _face_diamond(("X", "A", "B", "Y"), SWITCH_FACE_CALLOUTS)
    elements += _cross()
    # Four player slots, and with one controller paired only the first is on.
    lights = [
        _lamp(f"player{index + 1}", cx - 0.33 + index * 0.22, REF.GUIDE[1] - 0.62,
              0.13, 0.08, "#FDFEFF", 0.035, reach=0.06, lit=index == 0)
        for index in range(4)
    ]
    return _assemble("switch", "Switch Pro", elements, lights)


def _wired() -> PadLayout:
    """No. 4 -- the plain wired pad: an XInput controller, Xbox naming.

    Its sticks, its D-pad and its four faces are where an Xbox pad keeps them,
    and that is not an oversight: a pad Windows sees as XInput is an Xbox pad
    as far as anything on this screen goes, which is the whole point of the
    thing. What the picture does show it having instead is a lead out of the
    top, a turbo and a mode button under Back and Start rather than a single
    share button, and neither the lit ring nor the pairing pinhole a
    first-party pad carries -- so those are what it gets.
    """
    elements = _shoulders(("LT", "RT", "LB", "RB"))
    elements += [
        _guide(),
        _small("BACK", "Back", "view", SMALL_LEFT, SMALL_CALLOUTS[0]),
        _small("START", "Start", "menu", SMALL_RIGHT, SMALL_CALLOUTS[1]),
        _stud("TURBO", "Turbo", (REF.AXIS - STUD_DX, MIDDLE_ROW_Y), 0.30),
        _stud("MODE", "Mode", (REF.AXIS + STUD_DX, MIDDLE_ROW_Y), 0.30),
        _left_stick(),
        _right_stick(),
    ]
    elements += _face_diamond(("Y", "B", "A", "X"))
    elements += _cross()
    return _assemble("wired", "Wired", elements, cable=_cable())


MODELS: dict[str, PadLayout] = {
    model.layout_id: model
    for model in (_xbox(), _playstation(), _switch_pro(), _wired())
}

MODEL_ORDER = ("xbox", "ps", "switch", "wired")
DEFAULT_MODEL = "xbox"

# Every button id any model can report, with the Xbox naming as the fallback
# label for summaries taken while another model is on screen.
BUTTON_LABELS: dict[str, str] = {
    element.element_id: element.label
    for model_id in reversed(MODEL_ORDER)
    for element in MODELS[model_id].elements
    if element.counted
}
