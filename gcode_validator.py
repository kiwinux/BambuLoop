#!/usr/bin/env python3
"""
Bambu Lab H2S G-code safe-zone validator
========================================

Reads a 3MF (zip) or raw .gcode file, simulates every toolhead move, and
reports commands that leave the printer's printable area in a way that could
cause physical damage.

Supported G-code:
    G0/G1   - Linear move
    G2/G3   - Arc move (CW/CCW), both I/J and R forms
    G28     - Homing
    G90/G91 - Absolute / relative positioning mode
    G92     - Set current position (no motion)
    G21     - mm units (parsed for completeness)
    M82/M83 - Extruder absolute / relative (parsed for E-axis tracking only;
              irrelevant to safety but tokenised)

Ordinary moves use the printable bounds. Only recognised H2S purge paths
can use the front-edge purge margin. Eject sweeps have their own checked Y
envelope. Unrecognised out-of-area movement is reported as hard.

Usage:
    python gcode_validator.py <input.3mf | input.gcode>
    python gcode_validator.py input.3mf --margin 5 --json report.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from gcode_processor import sliced_plates
from validation_paths import classify_paths


# ──────────────────────────────────────────────────────────────────────────────
# 1. Printer specs (Bambu Lab H2S defaults; overridden by the header when present)
# ──────────────────────────────────────────────────────────────────────────────
H2S_DEFAULT_PRINTABLE = {
    "x_min": 0.0, "x_max": 340.0,
    "y_min": 0.0, "y_max": 320.0,
    "z_min": 0.0, "z_max": 340.0,
}


# ──────────────────────────────────────────────────────────────────────────────
# 2. Data model
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Bounds:
    """Axis-aligned (min, max) box."""
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float

    def expanded(self, margin: float) -> "Bounds":
        return Bounds(
            self.x_min - margin, self.x_max + margin,
            self.y_min - margin, self.y_max + margin,
            self.z_min - margin, self.z_max + margin,
        )

    def violates(self, x: float, y: float, z: float) -> list[str]:
        v = []
        if x < self.x_min: v.append(f"X={x:.3f} < {self.x_min}")
        if x > self.x_max: v.append(f"X={x:.3f} > {self.x_max}")
        if y < self.y_min: v.append(f"Y={y:.3f} < {self.y_min}")
        if y > self.y_max: v.append(f"Y={y:.3f} > {self.y_max}")
        if z < self.z_min: v.append(f"Z={z:.3f} < {self.z_min}")
        if z > self.z_max: v.append(f"Z={z:.3f} > {self.z_max}")
        return v


@dataclass
class Violation:
    line_no: int
    command: str
    kind: str               # "soft" or "hard"
    axes: list[str]         # violated axes / reasons
    point: tuple[float, float, float]   # checked coordinate (move endpoint or arc extremum)
    note: str = ""          # extra description (e.g. "G3 arc extremum")


@dataclass
class Report:
    source: str
    printable: Bounds
    physical:  Bounds
    total_lines: int = 0
    total_moves: int = 0
    moves_g0g1: int = 0
    moves_arc:  int = 0
    bbox_min: tuple[float, float, float] = (math.inf,  math.inf,  math.inf)
    bbox_max: tuple[float, float, float] = (-math.inf, -math.inf, -math.inf)
    soft_violations: list[Violation] = field(default_factory=list)
    hard_violations: list[Violation] = field(default_factory=list)
    soft_count: int = 0
    hard_count: int = 0
    skipped_moves: int = 0

    def update_bbox(self, x: float, y: float, z: float) -> None:
        self.bbox_min = (min(self.bbox_min[0], x),
                         min(self.bbox_min[1], y),
                         min(self.bbox_min[2], z))
        self.bbox_max = (max(self.bbox_max[0], x),
                         max(self.bbox_max[1], y),
                         max(self.bbox_max[2], z))


# ──────────────────────────────────────────────────────────────────────────────
# 3. Input handling: .3mf (zip) or raw .gcode
# ──────────────────────────────────────────────────────────────────────────────
def first_plate(names) -> Optional[str]:
    plates = sliced_plates(names)
    return plates[0][1] if plates else None


def load_gcode(path: Path) -> tuple[str, str]:
    """Read the file and return (gcode text, display path)."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            # Bambu 3mf uses the Metadata/plate_*.gcode layout
            target = first_plate(zf.namelist())
            if target is None:
                raise ValueError(f"{path}: no sliced plate inside the 3MF.")
            data = zf.read(target).decode("utf-8", errors="replace")
            return data, f"{path.name}!{target}"
    return path.read_text(encoding="utf-8", errors="replace"), str(path)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Auto-extract the printable area from the header
# ──────────────────────────────────────────────────────────────────────────────
_AREA_RE   = re.compile(r"^;\s*printable_area\s*=\s*(.+)$",   re.M)
_HEIGHT_RE = re.compile(r"^;\s*printable_height\s*=\s*([\d.]+)", re.M)

def parse_header_bounds(gcode: str) -> Optional[Bounds]:
    """Convert the gcode header's `printable_area` / `printable_height` comments into Bounds."""
    m_area   = _AREA_RE.search(gcode)
    m_height = _HEIGHT_RE.search(gcode)
    if not (m_area and m_height):
        return None
    # e.g. "0x0,340x0,340x320,0x320"  →  X[0,340], Y[0,320]
    pts = []
    for token in m_area.group(1).split(","):
        token = token.strip()
        try:
            sx, sy = token.split("x")
            pts.append((float(sx), float(sy)))
        except ValueError:
            return None
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return Bounds(
        x_min=min(xs), x_max=max(xs),
        y_min=min(ys), y_max=max(ys),
        z_min=0.0,    z_max=float(m_height.group(1)),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 5. G-code line tokeniser
# ──────────────────────────────────────────────────────────────────────────────
_COMMAND_RE = re.compile(r"^(?:N\d+\s*)?([GMT])0*(\d+(?:\.\d+)?)(.*)$", re.I)
_TOKEN_RE = re.compile(r"([A-Za-z])([+-]?(?:\d+(?:\.\d*)?|\.\d+))")

def parse_line(raw: str) -> Optional[tuple[str, dict[str, float], str]]:
    """
    Parse a single line into (cmd, params, comment).
    Returns None if the line is not a G/M/T command.
    """
    # Split off the comment (anything before ';' is the command)
    code, _, comment = raw.partition(";")
    code = code.strip()
    if not code:
        return None
    match = _COMMAND_RE.match(code)
    if not match:
        return None
    head_u = match[1].upper() + match[2]
    body = match[3].split("*", 1)[0]
    params = {letter.upper(): float(num) for letter, num in _TOKEN_RE.findall(body)}
    if head_u == "G28":
        for axis in re.findall(r"[XYZ]", body.upper()):
            params.setdefault(axis, 0.0)
    return head_u, params, comment.strip()


# ──────────────────────────────────────────────────────────────────────────────
# 6. Bounding box of an arc path
# ──────────────────────────────────────────────────────────────────────────────
def arc_bbox(x0: float, y0: float, x1: float, y1: float,
             cx: float, cy: float, ccw: bool
             ) -> tuple[float, float, float, float]:
    """
    Return the (x_min, x_max, y_min, y_max) of the area swept by the XY-plane
    arc. The endpoints are always included; we also add any of the four
    cardinal extrema (at distance `r` in each compass direction) that the arc
    actually crosses.
    """
    r = math.hypot(x0 - cx, y0 - cy)
    a0 = math.atan2(y0 - cy, x0 - cx) % (2 * math.pi)
    a1 = math.atan2(y1 - cy, x1 - cx) % (2 * math.pi)

    # Angular sweep [a0 → a1] (direction-aware)
    if ccw:
        sweep = (a1 - a0) % (2 * math.pi)
    else:
        sweep = (a0 - a1) % (2 * math.pi)
    if sweep == 0:                       # treat as a full circle
        sweep = 2 * math.pi

    # Check whether each of the 4 cardinal angles falls inside the arc
    extremes_x = [x0, x1]
    extremes_y = [y0, y1]
    cardinals = {0.0: (cx + r, cy),
                 math.pi / 2: (cx, cy + r),
                 math.pi: (cx - r, cy),
                 3 * math.pi / 2: (cx, cy - r)}
    for ang, (px, py) in cardinals.items():
        # Is `ang` reachable from a0 within `sweep` (respecting direction)?
        if ccw:
            delta = (ang - a0) % (2 * math.pi)
        else:
            delta = (a0 - ang) % (2 * math.pi)
        if delta <= sweep + 1e-9:
            extremes_x.append(px)
            extremes_y.append(py)
    return min(extremes_x), max(extremes_x), min(extremes_y), max(extremes_y)


# ──────────────────────────────────────────────────────────────────────────────
# 7. The simulator
# ──────────────────────────────────────────────────────────────────────────────
class GcodeSimulator:
    def __init__(self, printable: Bounds, physical: Bounds,
                 max_violations: int = 200, path_limits=None, duplicate_exits=()):
        self.printable = printable
        self.physical  = physical
        self.report    = Report(source="", printable=printable, physical=physical)
        self.max_violations = max_violations
        self.path_limits = path_limits or {}
        self.duplicate_exits = duplicate_exits

        # Modal state
        self.absolute = True          # G90 is the default
        self.x = self.y = self.z = 0.0
        self.located_axes: set[str] = set()
        self.work_offsets: dict[str, Optional[float]] = dict.fromkeys("XYZ", 0.0)
        self.unit_scale = 1.0
        self.arc_plane = "G17"

        # A warning and a hard violation on the same side are different transitions.
        self._oob: dict[str, str] = {}

    # ── Violation check (per-axis [min, max] interval) ─────────────────────
    def _check_extents(self,
                       x_lo: float, x_hi: float,
                       y_lo: float, y_hi: float,
                       z_lo: float, z_hi: float,
                       line_no: int, command: str, note: str = "", *, incomplete: bool = False) -> None:
        """
        Take the [min, max] interval swept by a single command and check it.
        G0/G1 only checks the endpoint (so lo == hi); G2/G3 passes the arc's
        bounding box.

        Six slots (X<, X>, Y<, Y>, Z<, Z>) are tracked so that we only report
        when newly entering a violation, and we clear the slot when motion
        returns inside the bounds (so a later violation in the same slot can
        be reported again).
        """
        if incomplete or len(self.located_axes) < 3:
            self.report.skipped_moves += 1
        if len(self.located_axes) == 3:
            self.report.update_bbox(x_lo, y_lo, z_lo)
            self.report.update_bbox(x_hi, y_hi, z_hi)

        allowed = self.path_limits.get(line_no)
        if allowed and (self.unit_scale != 1 or self.arc_plane != "G17"
                        or any(offset != 0 for offset in self.work_offsets.values())
                        or (allowed.held_y is not None and (not self.absolute or self.y != allowed.held_y))):
            allowed = None
        p = self.printable
        y_min, y_max = (allowed.low, allowed.high) if allowed else (p.y_min, p.y_max)
        intervals = (("X", x_lo, x_hi, p.x_min, p.x_max, p.x_min, p.x_max),
                     ("Y", y_lo, y_hi, p.y_min, p.y_max, y_min, y_max),
                     ("Z", z_lo, z_hi, p.z_min, p.z_max, p.z_min, p.z_max))
        changes = {"soft": [], "hard": []}
        for axis, low, high, p_min, p_max, limit_min, limit_max in intervals:
            if axis not in self.located_axes:
                continue
            for direction, value, outside, beyond, limit, edge in (
                ("<", low, low < p_min, low < limit_min, limit_min, p_min),
                (">", high, high > p_max, high > limit_max, limit_max, p_max),
            ):
                slot = axis + direction
                severity = "hard" if beyond else "soft" if outside else ""
                if severity != self._oob.get(slot, ""):
                    self._oob[slot] = severity
                    if severity:
                        boundary = limit if beyond else edge
                        changes[severity].append(f"{axis}={value:.3f} {direction} {boundary}")

        # The G150 macro endpoint is firmware-specific. Two relative exits exceed
        # the one 16 mm retreat even when the estimated endpoint is on the bed.
        if line_no in self.duplicate_exits:
            changes["hard"].append("ΔY=−32 mm (2 × −16 mm)" if self.unit_scale == 1 else "2 × G1 Y-16")
            note = "H2S purge-bin exit"
        context = ", ".join(filter(None, [allowed.operation if allowed else "", note]))
        for kind, axes in changes.items():
            if not axes:
                continue
            if kind == "hard":
                self.report.hard_count += 1
                details = self.report.hard_violations
            else:
                self.report.soft_count += 1
                details = self.report.soft_violations
            if len(details) < self.max_violations:
                details.append(Violation(line_no, command, kind, axes, (x_hi, y_hi, z_hi), context))

    # ── Per-line dispatch ───────────────────────────────────────────────────
    def feed(self, line_no: int, raw: str) -> None:
        parsed = parse_line(raw)
        if not parsed:
            return
        cmd, p, _ = parsed
        if cmd in ("G20", "G21"):
            self.unit_scale = 25.4 if cmd == "G20" else 1.0
            return
        if cmd in ("G17", "G18", "G19"):
            self.arc_plane = cmd
            return
        if self.unit_scale != 1.0:
            for axis in p.keys() & {"X", "Y", "Z", "I", "J", "K", "R"}:
                p[axis] *= self.unit_scale

        # Mode changes ────────────────────────────────────────
        if cmd == "G90":
            self.absolute = True
            return
        if cmd == "G91":
            self.absolute = False
            return
        if cmd == "G92":
            # Relabelling a position neither moves nor locates the carriage.
            for axis in p.keys() & {"X", "Y", "Z"}:
                position = getattr(self, axis.lower())
                self.work_offsets[axis] = position - p[axis] if axis in self.located_axes else None
            return
        if cmd == "G28":
            # Homing. If specific X/Y/Z keys are given, home only those axes;
            # otherwise home all axes. The exact post-home position is firmware
            # dependent, so we conservatively assume 0 (origin). Subsequent
            # absolute G1 moves will resync the simulator naturally.
            axes = [a for a in ("X", "Y", "Z") if a in p] or ["X", "Y", "Z"]
            if "X" in axes: self.x = 0.0
            if "Y" in axes: self.y = 0.0
            if "Z" in axes: self.z = 0.0
            self.located_axes.update(axes)
            for axis in axes:
                self.work_offsets[axis] = 0.0
                self._oob.pop(axis + "<", None)
                self._oob.pop(axis + ">", None)
            return

        # Movement commands ──────────────────────────────────────
        if cmd in ("G0", "G1"):
            if not ("X" in p or "Y" in p or "Z" in p):
                return
            self.report.moves_g0g1 += 1
            self.report.total_moves += 1
            incomplete = len(self.located_axes) < 3
            if self.absolute:
                self.located_axes.update(a for a in p.keys() & {"X", "Y", "Z"} if self.work_offsets[a] is not None)
            nx, ny, nz = self._next_xyz(p)
            # Linear move: only check the endpoint (the start point was
            # already checked by the previous command).
            self._check_extents(nx, nx, ny, ny, nz, nz,
                                line_no, raw.strip(), incomplete=incomplete)
            self.x, self.y, self.z = nx, ny, nz
            return

        if cmd in ("G2", "G3"):
            self.report.moves_arc += 1
            self.report.total_moves += 1
            nx, ny, nz = self._next_xyz(p)

            xy_known = self.arc_plane == "G17" and {"X", "Y"}.issubset(self.located_axes)
            incomplete = len(self.located_axes) < 3
            if self.absolute:
                self.located_axes.update(a for a in p.keys() & {"X", "Y", "Z"} if self.work_offsets[a] is not None)
            ccw = cmd == "G3"
            center = None
            if xy_known and ("I" in p or "J" in p):
                center = self.x + p.get("I", 0.0), self.y + p.get("J", 0.0)
            elif xy_known and "R" in p:
                dx, dy = nx - self.x, ny - self.y
                chord = math.hypot(dx, dy)
                radius = p["R"]
                if 0 < chord <= 2 * abs(radius):
                    offset = math.sqrt(max(0.0, radius * radius - chord * chord / 4)) / chord
                    if ccw != (radius > 0):
                        offset = -offset
                    center = (self.x + nx) / 2 - dy * offset, (self.y + ny) / 2 + dx * offset
            if center is None:
                self._check_extents(nx, nx, ny, ny, nz, nz, line_no, raw.strip(),
                                    note="Unresolved arc", incomplete=True)
            else:
                cx, cy = center
                xmn, xmx, ymn, ymx = arc_bbox(self.x, self.y, nx, ny, cx, cy, ccw)
                if p.get("P", 1) > 1:
                    radius = math.hypot(self.x - cx, self.y - cy)
                    xmn, xmx, ymn, ymx = cx - radius, cx + radius, cy - radius, cy + radius
                self._check_extents(xmn, xmx, ymn, ymx, min(self.z, nz), max(self.z, nz),
                                    line_no, raw.strip(), note="G2/G3 arc", incomplete=incomplete)
            self.x, self.y, self.z = nx, ny, nz
            return

    def _next_xyz(self, p: dict[str, float]) -> tuple[float, float, float]:
        coordinates = []
        for axis, position in zip("XYZ", (self.x, self.y, self.z)):
            if axis in p:
                base = self.work_offsets[axis] if self.absolute else position
                if base is not None:
                    position = base + p[axis]
            coordinates.append(position)
        return tuple(coordinates)


# ──────────────────────────────────────────────────────────────────────────────
# 8. Entry points
# ──────────────────────────────────────────────────────────────────────────────
def _simulate(text: str, source: str, margin: float, max_violations: int):
    if not math.isfinite(margin) or margin < 0:
        raise ValueError("Purge margin must be finite and non-negative.")
    supplied = parse_header_bounds(text)
    machine = Bounds(**H2S_DEFAULT_PRINTABLE)
    bounds = machine
    if supplied is not None:
        bounds = Bounds(max(supplied.x_min, machine.x_min), min(supplied.x_max, machine.x_max),
                        max(supplied.y_min, machine.y_min), min(supplied.y_max, machine.y_max),
                        max(supplied.z_min, machine.z_min), min(supplied.z_max, machine.z_max))
        if not (bounds.x_min < bounds.x_max and bounds.y_min < bounds.y_max and bounds.z_min < bounds.z_max):
            raise ValueError("The printable area does not intersect the H2S build volume.")
    lines = text.splitlines()
    limits, duplicate_exits = classify_paths(lines, bounds, margin)
    y_min = min((v.low for v in limits.values()), default=bounds.y_min)
    y_max = max((v.high for v in limits.values()), default=bounds.y_max)
    envelope = Bounds(bounds.x_min, bounds.x_max, min(y_min, bounds.y_min),
                      max(y_max, bounds.y_max), bounds.z_min, bounds.z_max)
    sim = GcodeSimulator(bounds, envelope, max_violations, limits, duplicate_exits)
    for i, line in enumerate(lines, 1):
        sim.feed(i, line)
    sim.report.source = source
    sim.report.total_lines = len(lines)
    return sim.report, supplied is not None


def run(path: Path, margin: float, max_viol: int) -> Report:
    gcode, source = load_gcode(path)
    report, from_header = _simulate(gcode, source, margin, max_viol)
    report._header_note = "(from header)" if from_header else "(H2S defaults)"
    return report


def format_report(r: Report) -> str:
    note = getattr(r, "_header_note", "")
    out: list[str] = []
    out.append("=" * 72)
    out.append(f"Bambu Lab H2S G-code validation report")
    out.append("=" * 72)
    out.append(f"File          : {r.source}")
    out.append(f"Lines         : {r.total_lines:,}")
    out.append(f"Move commands : {r.total_moves:,} "
               f"(G0/G1 {r.moves_g0g1:,} · G2/G3 {r.moves_arc:,})")
    out.append("")
    out.append(f"[Printable area] {note}")
    out.append(f"  X: {r.printable.x_min:7.2f} ~ {r.printable.x_max:7.2f} mm")
    out.append(f"  Y: {r.printable.y_min:7.2f} ~ {r.printable.y_max:7.2f} mm")
    out.append(f"  Z: {r.printable.z_min:7.2f} ~ {r.printable.z_max:7.2f} mm")
    out.append("")
    out.append(f"[Envelope of checked paths] (allowances apply only to recognised moves)")
    out.append(f"  X: {r.physical.x_min:7.2f} ~ {r.physical.x_max:7.2f} mm")
    out.append(f"  Y: {r.physical.y_min:7.2f} ~ {r.physical.y_max:7.2f} mm")
    out.append(f"  Z: {r.physical.z_min:7.2f} ~ {r.physical.z_max:7.2f} mm")
    out.append("")
    if r.total_moves and r.bbox_min[0] != math.inf:
        out.append(f"[Actual motion bounding box]")
        out.append(f"  X: {r.bbox_min[0]:7.3f} ~ {r.bbox_max[0]:7.3f} mm")
        out.append(f"  Y: {r.bbox_min[1]:7.3f} ~ {r.bbox_max[1]:7.3f} mm")
        out.append(f"  Z: {r.bbox_min[2]:7.3f} ~ {r.bbox_max[2]:7.3f} mm")
        out.append("")

    # ── Violation report ─────────────────────────────────────────
    out.append(f"[Hard violations] (collision risk): {r.hard_count} item(s)")
    for v in r.hard_violations[:20]:
        out.append(f"  L{v.line_no:>6}  {v.command[:60]:60}  ⛔ "
                   + ", ".join(v.axes)
                   + (f"  ({v.note})" if v.note else ""))
    if len(r.hard_violations) > 20:
        out.append(f"  ... (+{len(r.hard_violations) - 20} more)")
    out.append("")

    out.append(f"[Soft violations] (recognised off-bed paths): "
               f"{r.soft_count} item(s)")
    for v in r.soft_violations[:20]:
        out.append(f"  L{v.line_no:>6}  {v.command[:60]:60}  ⚠️  "
                   + ", ".join(v.axes)
                   + (f"  ({v.note})" if v.note else ""))
    if len(r.soft_violations) > 20:
        out.append(f"  ... (+{len(r.soft_violations) - 20} more)")
    out.append("")

    # ── Overall verdict ───────────────────────────────────────────
    if r.hard_count:
        verdict = "🛑 Unsafe: at least one move is outside its permitted path."
    elif r.skipped_moves or not r.total_moves:
        verdict = f"Unverified: {r.skipped_moves} incomplete moves or no motion."
    elif r.soft_count:
        verdict = "Recognised calibration, purge or eject moves outside the printable area."
    else:
        verdict = "Checked moves stay inside the printable area."
    out.append(verdict)
    out.append("=" * 72)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Bambu Lab H2S G-code safe-zone validator")
    ap.add_argument("input", type=Path,
                    help="Input .3mf or .gcode file")
    ap.add_argument("--margin", type=float, default=20.0,
                    help="Front-edge margin for recognised H2S purge paths [mm], default 20.")
    ap.add_argument("--max-violations", type=int, default=200,
                    help="Maximum number of violations to retain (default 200)")
    ap.add_argument("--json", type=Path, default=None,
                    help="Path to write the structured result as JSON")
    args = ap.parse_args(argv)

    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 2

    report = run(args.input, args.margin, args.max_violations)
    print(format_report(report))

    if args.json:
        # dataclass → dict
        d = asdict(report)
        args.json.write_text(json.dumps(d, indent=2, ensure_ascii=False))
        print(f"\nJSON saved: {args.json}")

    # Exit code: 1 if any hard violation, 0 otherwise
    if report.hard_count:
        return 1
    return 2 if report.skipped_moves or not report.total_moves else 0


if __name__ == "__main__":
    sys.exit(main())


# ──────────────────────────────────────────────────────────────────────────────
# Helper for BambuLoop integration — returns a Flask-friendly dict
# ──────────────────────────────────────────────────────────────────────────────
def validate_gcode_text(gcode_text: str, margin: float = 20.0,
                         max_violations: int = 200,
                         source_name: str = "(in-memory)") -> dict:
    """Validate a G-code text and return the result as a dict.

    Args:
        gcode_text: G-code string to validate
        margin: Front-edge Y margin for recognised H2S purge moves (mm)
        max_violations: Maximum number of violations to retain
        source_name: Source label used in the report

    Returns:
        {
            'verdict': 'safe' | 'soft_only' | 'unsafe' | 'unverified',
            'verdict_label': {'ko': '...', 'en': '...'},  # i18n label for UI
            'printable': {x_min, x_max, y_min, y_max, z_min, z_max},
            'physical': {...},
            'bbox_min': [x, y, z] or None,
            'bbox_max': [x, y, z] or None,
            'total_lines': int,
            'total_moves': int,
            'moves_g0g1': int,
            'moves_arc': int,
            'soft_count': int,
            'hard_count': int,
            'soft_violations': [{line_no, command, axes, point, note}, ...] (capped at max_violations)
            'hard_violations': [{line_no, command, axes, point, note}, ...]
            'header_note': {'ko': '...', 'en': '...'}  # i18n source of the bounds
        }
    """
    from i18n_helper import t_dict
    r, from_header = _simulate(gcode_text, source_name, margin, max_violations)
    bounds, physical = r.printable, r.physical
    header_note = t_dict("validator.header.auto_detected" if from_header else "validator.header.no_header")

    # Verdict
    if r.hard_count:
        verdict = 'unsafe'
        verdict_label = t_dict("validator.verdict.unsafe")
    elif r.skipped_moves or not r.total_moves:
        verdict = 'unverified'
        verdict_label = t_dict("validator.verdict.unverified")
    elif r.soft_count:
        verdict = 'soft_only'
        verdict_label = t_dict("validator.verdict.soft_only")
    else:
        verdict = 'safe'
        verdict_label = t_dict("validator.verdict.safe")

    def _b(b: Bounds) -> dict:
        return {'x_min': b.x_min, 'x_max': b.x_max,
                'y_min': b.y_min, 'y_max': b.y_max,
                'z_min': b.z_min, 'z_max': b.z_max}

    def _v(viol: Violation) -> dict:
        return {'line_no': viol.line_no, 'command': viol.command[:120],
                'axes': viol.axes, 'point': list(viol.point), 'note': viol.note}

    bbox_min = list(r.bbox_min) if r.bbox_min[0] != math.inf else None
    bbox_max = list(r.bbox_max) if r.bbox_max[0] != -math.inf else None

    return {
        'verdict': verdict,
        'verdict_label': verdict_label,
        'header_note': header_note,
        'margin_mm': margin,
        'skipped_moves': r.skipped_moves,
        'source': source_name,
        'printable': _b(bounds),
        'physical': _b(physical),
        'bbox_min': bbox_min,
        'bbox_max': bbox_max,
        'total_lines': r.total_lines,
        'total_moves': r.total_moves,
        'moves_g0g1': r.moves_g0g1,
        'moves_arc': r.moves_arc,
        'soft_count': r.soft_count,
        'hard_count': r.hard_count,
        'soft_violations': [_v(v) for v in r.soft_violations],
        'hard_violations': [_v(v) for v in r.hard_violations],
    }
