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

Soft (printable area) and hard (machine) limits are reported separately.
- Soft violation: outside the `printable_area` header (or a user-supplied area).
- Hard violation: outside the physical limit (soft + safety margin)
  → real risk of collision.

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
from typing import Iterator, Optional


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
def load_gcode(path: Path) -> tuple[str, str]:
    """Read the file and return (gcode text, display path)."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            # Bambu 3mf uses the Metadata/plate_*.gcode layout
            candidates = [n for n in zf.namelist()
                          if n.startswith("Metadata/") and n.endswith(".gcode")]
            if not candidates:
                raise ValueError(f"{path}: no .gcode entry found inside the 3MF.")
            # Prefer plate_1
            candidates.sort()
            target = candidates[0]
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
_TOKEN_RE = re.compile(r"([A-Za-z])(-?\d+(?:\.\d+)?)")

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
    head, *rest = code.split(maxsplit=1)
    head_u = head.upper()
    if not head_u or head_u[0] not in ("G", "M", "T"):
        return None
    body = rest[0] if rest else ""
    params = {letter.upper(): float(num) for letter, num in _TOKEN_RE.findall(body)}
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
                 max_violations: int = 200):
        self.printable = printable
        self.physical  = physical
        self.report    = Report(source="", printable=printable, physical=physical)
        self.max_violations = max_violations

        # Modal state
        self.absolute = True          # G90 is the default
        self.x = self.y = self.z = 0.0
        self.homed = False            # unknown before G28

        # Per (axis, direction) "currently violating" flags — report only once
        # per transition into the violating state.
        # Keys: "X<", "X>", "Y<", "Y>", "Z<", "Z>"
        self._oob: dict[str, bool] = {
            "X<": False, "X>": False,
            "Y<": False, "Y>": False,
            "Z<": False, "Z>": False,
        }

    # ── Violation check (per-axis [min, max] interval) ─────────────────────
    def _check_extents(self,
                       x_lo: float, x_hi: float,
                       y_lo: float, y_hi: float,
                       z_lo: float, z_hi: float,
                       line_no: int, command: str, note: str = "") -> None:
        """
        Take the [min, max] interval swept by a single command and check it.
        G0/G1 only checks the endpoint (so lo == hi); G2/G3 passes the arc's
        bounding box.

        Six slots (X<, X>, Y<, Y>, Z<, Z>) are tracked so that we only report
        when newly entering a violation, and we clear the slot when motion
        returns inside the bounds (so a later violation in the same slot can
        be reported again).
        """
        if not self.homed:
            return
        # Update the overall motion bounding box
        self.report.update_bbox(x_lo, y_lo, z_lo)
        self.report.update_bbox(x_hi, y_hi, z_hi)

        axis_specs = [
            ("X", x_lo, x_hi, self.printable.x_min, self.printable.x_max,
                                self.physical.x_min,  self.physical.x_max),
            ("Y", y_lo, y_hi, self.printable.y_min, self.printable.y_max,
                                self.physical.y_min,  self.physical.y_max),
            ("Z", z_lo, z_hi, self.printable.z_min, self.printable.z_max,
                                self.physical.z_min,  self.physical.z_max),
        ]

        new_hard: list[str] = []
        new_soft: list[str] = []

        for name, lo, hi, p_lo, p_hi, h_lo, h_hi in axis_specs:
            # ── Below (<) violation ────────────────────────────
            below_hard = lo < h_lo
            below_soft = lo < p_lo and not below_hard   # if hard fires, soft is absorbed
            slot = f"{name}<"
            if below_hard:
                if not self._oob[slot]:
                    new_hard.append(f"{name}={lo:.3f} < {h_lo}")
                    self._oob[slot] = True
            elif below_soft:
                if not self._oob[slot]:
                    new_soft.append(f"{name}={lo:.3f} < {p_lo}")
                    self._oob[slot] = True
            else:
                self._oob[slot] = False     # returned to safe range

            # ── Above (>) violation ──────────────────────────────
            above_hard = hi > h_hi
            above_soft = hi > p_hi and not above_hard
            slot = f"{name}>"
            if above_hard:
                if not self._oob[slot]:
                    new_hard.append(f"{name}={hi:.3f} > {h_hi}")
                    self._oob[slot] = True
            elif above_soft:
                if not self._oob[slot]:
                    new_soft.append(f"{name}={hi:.3f} > {p_hi}")
                    self._oob[slot] = True
            else:
                self._oob[slot] = False

        # If one command triggers both hard and soft, record them as separate entries
        if new_hard and len(self.report.hard_violations) < self.max_violations:
            self.report.hard_violations.append(
                Violation(line_no, command, "hard", new_hard,
                          (x_hi, y_hi, z_hi), note))
        if new_soft and len(self.report.soft_violations) < self.max_violations:
            self.report.soft_violations.append(
                Violation(line_no, command, "soft", new_soft,
                          (x_hi, y_hi, z_hi), note))

    # ── Per-line dispatch ───────────────────────────────────────────────────
    def feed(self, line_no: int, raw: str) -> None:
        parsed = parse_line(raw)
        if not parsed:
            return
        cmd, p, _ = parsed

        # Mode changes ────────────────────────────────────────
        if cmd == "G90":
            self.absolute = True
            return
        if cmd == "G91":
            self.absolute = False
            return
        if cmd == "G92":
            # Reset current position. No physical motion.
            if "X" in p: self.x = p["X"]
            if "Y" in p: self.y = p["Y"]
            if "Z" in p: self.z = p["Z"]
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
            self.homed = True
            # Homing clears every violation slot
            for k in self._oob:
                self._oob[k] = False
            return

        # Movement commands ──────────────────────────────────────
        if cmd in ("G0", "G1"):
            self.report.moves_g0g1 += 1
            self.report.total_moves += 1
            nx, ny, nz = self._next_xyz(p)
            # Linear move: only check the endpoint (the start point was
            # already checked by the previous command).
            self._check_extents(nx, nx, ny, ny, nz, nz,
                                line_no, raw.strip())
            self.x, self.y, self.z = nx, ny, nz
            return

        if cmd in ("G2", "G3"):
            self.report.moves_arc += 1
            self.report.total_moves += 1
            nx, ny, nz = self._next_xyz(p)

            # Determine the centre (prefer I/J; without them, check the endpoint only)
            if "I" in p or "J" in p:
                cx = self.x + p.get("I", 0.0)
                cy = self.y + p.get("J", 0.0)
                ccw = (cmd == "G3")
                xmn, xmx, ymn, ymx = arc_bbox(self.x, self.y, nx, ny,
                                              cx, cy, ccw)
                # Z may interpolate linearly during G2/G3 (XY arc + Z move)
                z_lo, z_hi = min(self.z, nz), max(self.z, nz)
                self._check_extents(xmn, xmx, ymn, ymx, z_lo, z_hi,
                                    line_no, raw.strip(), note="G2/G3 arc region")
            else:
                # R-form — the centre is ambiguous, so only check the endpoint
                self._check_extents(nx, nx, ny, ny, nz, nz,
                                    line_no, raw.strip(),
                                    note="G2/G3 R-form (mid-arc check skipped)")
            self.x, self.y, self.z = nx, ny, nz
            return

    def _next_xyz(self, p: dict[str, float]) -> tuple[float, float, float]:
        if self.absolute:
            return (p.get("X", self.x), p.get("Y", self.y), p.get("Z", self.z))
        return (self.x + p.get("X", 0.0),
                self.y + p.get("Y", 0.0),
                self.z + p.get("Z", 0.0))


# ──────────────────────────────────────────────────────────────────────────────
# 8. Entry points
# ──────────────────────────────────────────────────────────────────────────────
def run(path: Path, margin: float, max_viol: int) -> Report:
    gcode, source = load_gcode(path)
    bounds = parse_header_bounds(gcode)
    if bounds is None:
        bounds = Bounds(**H2S_DEFAULT_PRINTABLE)
        header_note = "(no header found — using H2S defaults)"
    else:
        header_note = "(auto-detected from header)"

    physical = bounds.expanded(margin)
    sim = GcodeSimulator(printable=bounds, physical=physical,
                         max_violations=max_viol)
    sim.report.source = source

    for i, line in enumerate(gcode.splitlines(), start=1):
        sim.feed(i, line)
    sim.report.total_lines = i
    sim.report._header_note = header_note    # type: ignore[attr-defined]
    return sim.report


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
    out.append(f"[Physical limit] (printable + safety margin)")
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
    out.append(f"[Hard violations] (collision risk): {len(r.hard_violations)} item(s)")
    for v in r.hard_violations[:20]:
        out.append(f"  L{v.line_no:>6}  {v.command[:60]:60}  ⛔ "
                   + ", ".join(v.axes)
                   + (f"  ({v.note})" if v.note else ""))
    if len(r.hard_violations) > 20:
        out.append(f"  ... (+{len(r.hard_violations) - 20} more)")
    out.append("")

    out.append(f"[Soft violations] (outside printable area, typically normal wipe/purge): "
               f"{len(r.soft_violations)} item(s)")
    for v in r.soft_violations[:20]:
        out.append(f"  L{v.line_no:>6}  {v.command[:60]:60}  ⚠️  "
                   + ", ".join(v.axes)
                   + (f"  ({v.note})" if v.note else ""))
    if len(r.soft_violations) > 20:
        out.append(f"  ... (+{len(r.soft_violations) - 20} more)")
    out.append("")

    # ── Overall verdict ───────────────────────────────────────────
    if r.hard_violations:
        verdict = "🛑 Unsafe: at least one move exceeds the physical limit."
    elif r.soft_violations:
        verdict = ("✅ Safe: moves exist outside the printable area but stay within the "
                   "physical limit (likely normal wipe/purge).")
    else:
        verdict = "✅ Safe: every move stays inside the printable area."
    out.append(verdict)
    out.append("=" * 72)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Bambu Lab H2S G-code safe-zone validator")
    ap.add_argument("input", type=Path,
                    help="Input .3mf or .gcode file")
    ap.add_argument("--margin", type=float, default=20.0,
                    help="Safety margin allowed outside the printable area [mm] "
                         "(beyond this is a hard violation). Defaults to 20mm to "
                         "absorb Bambu's normal wipe/purge moves, which can extend "
                         "~16mm past the printable area.")
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
    return 1 if report.hard_violations else 0


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
        margin: Safety margin allowed outside the printable area (mm)
        max_violations: Maximum number of violations to retain
        source_name: Source label used in the report

    Returns:
        {
            'verdict': 'safe' | 'soft_only' | 'unsafe',
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
    bounds = parse_header_bounds(gcode_text)
    if bounds is None:
        bounds = Bounds(**H2S_DEFAULT_PRINTABLE)
        from i18n_helper import t_dict
        header_note = t_dict("validator.header.no_header")
    else:
        from i18n_helper import t_dict
        header_note = t_dict("validator.header.auto_detected")

    physical = bounds.expanded(margin)
    sim = GcodeSimulator(printable=bounds, physical=physical, max_violations=max_violations)
    sim.report.source = source_name

    last_i = 0
    for i, line in enumerate(gcode_text.splitlines(), start=1):
        sim.feed(i, line)
        last_i = i
    sim.report.total_lines = last_i

    r = sim.report

    # Verdict
    if r.hard_violations:
        verdict = 'unsafe'
        verdict_label = t_dict("validator.verdict.unsafe")
    elif r.soft_violations:
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
        'printable': _b(bounds),
        'physical': _b(physical),
        'bbox_min': bbox_min,
        'bbox_max': bbox_max,
        'total_lines': r.total_lines,
        'total_moves': r.total_moves,
        'moves_g0g1': r.moves_g0g1,
        'moves_arc': r.moves_arc,
        'soft_count': len(r.soft_violations),
        'hard_count': len(r.hard_violations),
        'soft_violations': [_v(v) for v in r.soft_violations],
        'hard_violations': [_v(v) for v in r.hard_violations],
    }
