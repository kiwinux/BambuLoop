"""Recognise the H2S paths that intentionally leave the printable area."""

from __future__ import annotations

import re
from typing import NamedTuple

from gcode_processor import AutomationSettings, check_eject_clearance, generate_eject_sequence, is_purge_retreat, stationary_purge_command


# BambuLoop's reference H2S sweep reaches these Y endpoints. Wider settings
# have no verified sweep envelope in this project.
SWEEP_FRONT = -5.0
SWEEP_BACK = 335.0


class YRange(NamedTuple):
    low: float
    high: float
    operation: str


_BODY = ("; MACHINE_START_GCODE_END", "; ## Print #", "; ## 인쇄 #", "; CHANGE_LAYER",
         "; LAYER_CHANGE", "; Z_HEIGHT:", "; layer num/total_layer_count",
         "; [SHUTDOWN]", "; ## [DRY-RUN] all cycles complete")
_POST = ("; [POST-PRINT #", "; ========== cycle ", "; ========== 사이클 ")
_SWEEP = ("; [eject sequence]", "; [분리 시퀀스]")
_RESET = ("; [reset sequence]", "; [리셋 시퀀스]")


_LAYER_MARKER = re.compile(r"^;\s*(?:CHANGE_LAYER\b|LAYER_CHANGE\b|Z_HEIGHT\s*:|layer\s*num/total_layer_count\s*:|MACHINE_START_GCODE_END\b)", re.I)


def _commands(lines, start, stop):
    """Yield executable words and their one-based line numbers."""
    for index in range(start, stop):
        raw = lines[index].lstrip()
        if raw.startswith(_BODY + _POST + _SWEEP + _RESET) or _LAYER_MARKER.match(raw):
            return
        words = raw.partition(";")[0].upper().split()
        if words:
            yield index + 1, words


# Spatial commands in the H2S nozzle load line, including coordinate mode
# changes. Temperature, dwell and extrusion-only commands vary by filament.
_LOAD_LINE = (
    "G90", "G1 Z5", "G1 X270 Y-0.5", "G28.14 R0", "G91", "G1 Z0.8",
    "G90", "G1 X250", "G1 X290 E20", "G91", "G3 Z0.4 I1.217 J0 P1", "G90",
)
_LOAD_AUX = {"M83", "M109", "M400", "M500", "G29.2", "M73"}
_LOAD_MARKER = re.compile(r"^;\s*=+\s*noo?z+le load line\s*=+", re.I)


def _load_line_moves(lines, start):
    moves = []
    position = 0
    for line_no, words in _commands(lines, start, min(start + 96, len(lines))):
        op = words[0]
        args = [word for word in words[1:] if not word.startswith("F")]
        if op in _LOAD_AUX or (op == "G1" and args and all(w.startswith("E") for w in args)):
            if op == "G1":
                moves.append(line_no)
            continue
        if " ".join([op, *args]) != _LOAD_LINE[position]:
            return ()
        moves.append(line_no)
        position += 1
        if position == len(_LOAD_LINE):
            return moves
    return ()


def _bin_exit(lines, start):
    """One relative Y retreat after the H2S flushing/wipe routine."""
    commands = _commands(lines, start, min(start + 40, len(lines)))
    for _, words in commands:
        op = words[0]
        if op in {"G150.1", "G150.2"} or stationary_purge_command(" ".join(words)):
            continue
        if words == ["G91"]:
            for line_no, move in commands:
                if stationary_purge_command(" ".join(move)):
                    continue
                if is_purge_retreat(" ".join(move)):
                    for _, end in commands:
                        if not stationary_purge_command(" ".join(end)):
                            return line_no if end == ["G90"] else None
                break
        break
    return None


_LEGACY_FIELDS = {
    "방식": "method", "X 패스 수": "X pass count", "X 커버 범위": "X coverage",
    "인쇄물 높이": "print height", "파킹 Z": "parking Z", "스윕 Z 범위": "sweep Z range",
    "Y 후방 시작점": "Y back start", "Y 전방 종료점": "Y front end", "스윕 속도": "sweep speed",
}


def _sweep_settings(lines, start):
    # These fields are emitted by both the legacy and current generator.
    fields = {}
    for raw in lines[start:start + 14]:
        if raw.startswith(";   - "):
            key, _, value = raw[6:].partition(":")
            key = key.strip()
            fields[_LEGACY_FIELDS.get(key, key)] = value.strip()
    try:
        method = fields["method"]
        if method not in {"multi_sweep", "edge_to_center", "edge_to_center_bottom",
                          "bottom_only", "sweep", "zigzag"}:
            return None
        passes = int(fields["X pass count"].split()[0])
        z_range = fields["sweep Z range"]
        step_field = re.search(r"\((\d+)(?: (?:step|repeat sweep)\(s\)|단 분할|회 반복 스윕)\)$", z_range)
        if not step_field:
            return None
        steps = int(step_field[1])
        if passes < 1 or steps < 1:
            return None
        end_z = float(z_range.split(" → ")[-1].split("mm")[0])
        height = float(fields["print height"].split("mm")[0])
        clearance = float(fields["parking Z"].split(" + ")[1].split("mm")[0])
        bed_x = int(fields["X coverage"].split(" ~ ")[1].split("mm")[0]) + 3
        back = re.fullmatch(r"Y=(-?\d+)mm \(= (?:bed|베드) (\d+) \+ (?:back overhang|베드밖) (\d+)mm\)",
                            fields["Y back start"])
        front = re.match(r"Y=(-?\d+)mm \(= (?:bed front|베드 앞면) - (\d+)mm\)", fields["Y front end"])
        if not back or not front:
            return None
        bed_y, back_over = int(back[2]), int(back[3])
        front_over = int(front[2])
        if int(back[1]) != bed_y + back_over or int(front[1]) != -front_over:
            return None
        settings = AutomationSettings(eject_method=method, eject_passes=passes,
                                      eject_descent_steps=steps, eject_z_offset=end_z,
                                      eject_z_start_offset=clearance, bed_size_x=bed_x,
                                      bed_size_y=bed_y, back_overhang_mm=back_over,
                                      front_overhang_mm=front_over,
                                      eject_speed=int(fields["sweep speed"].split()[0]))
        return settings, height
    except (KeyError, ValueError, IndexError, TypeError, OverflowError):
        return None


def _match_sweep(lines, start, observed_height):
    parsed = _sweep_settings(lines, start)
    if parsed is None:
        return (), None
    settings, height = parsed
    # Bound replay work by the actual block, including older API-generated
    # files with more steps than the UI offers.
    end = start
    while end < len(lines):
        raw = lines[end].lstrip()
        if raw.startswith(("; [safe order]", "; [안전 순서]", ";   ★ Park", ";   ★ Z")):
            break
        if raw.startswith(_BODY + _POST + _SWEEP + _RESET):
            break
        end += 1
    if settings.eject_descent_steps * settings.eject_passes > end - start:
        return (), None
    try:
        check_eject_clearance(settings, max(height, observed_height))
        # Layer heights can retain precision omitted in older summary comments.
        if observed_height > 0 and round(observed_height, 1) == height:
            height = observed_height
        reference = generate_eject_sequence(settings, height).splitlines()
    except (ValueError, OverflowError):
        return (), None
    expected = _commands(reference, 2, len(reference))
    actual = _commands(lines, start, min(start + len(reference) + 16, len(lines)))
    moves = []
    for _, planned in expected:
        line_no, words = next(actual, (None, None))
        if words != planned:
            return (), None
        moves.append(line_no)
    low = max(-settings.front_overhang_mm, SWEEP_FRONT)
    high = min(settings.bed_size_y + settings.back_overhang_mm, SWEEP_BACK)
    return moves, YRange(low, high, "H2S eject sweep")


def known_y_ranges(lines, printable, margin):
    """Authorise individual motions, never a whole comment-delimited section."""
    prime = YRange(max(printable.y_min - margin, -1.717), printable.y_max, "H2S nozzle load line")
    retreat = YRange(max(printable.y_min - margin, -16.0), printable.y_max, "H2S purge-bin exit")
    allowances = {}
    phase = "unknown"
    generated = False
    observed_height = 0.0
    for index, raw in enumerate(lines):
        line = raw.lstrip()
        if line.startswith(";"):
            if phase in ("start", "unknown") and line.startswith("; #   BambuLoop"):
                generated = True
                phase = "start"
            elif phase == "unknown" and re.match(r"^;\s*=+\s*machine:\s*H2S\b", line, re.I):
                phase = "start"
            elif line.startswith(_BODY) or _LAYER_MARKER.match(line):
                if line.startswith(("; ## Print #", "; ## 인쇄 #")):
                    observed_height = 0.0
                elif value := re.match(r";\s*Z_HEIGHT:\s*(\d+(?:\.\d+)?)", line, re.I):
                    observed_height = max(observed_height, float(value[1]))
                phase = "body"
            elif generated and line.startswith(_POST):
                phase = "post"
            elif phase == "post" and line.startswith(_RESET):
                phase = "reset"
            elif phase == "post" and line.startswith(_SWEEP):
                moves, envelope = _match_sweep(lines, index + 1, observed_height)
                for n in moves:
                    allowances[n] = envelope
            elif phase in ("start", "reset") and (
                _LOAD_MARKER.match(line) or line.startswith(("; ----- nozzle load line (v30:", "; ----- 노즐 로드 라인 (v30:"))
            ):
                for n in _load_line_moves(lines, index + 1):
                    allowances[n] = prime
        elif phase in ("start", "reset") and line.upper().startswith(("G150.1", "G150.2", "G150.3")):
            if line.partition(";")[0].split()[0].upper() not in {"G150.1", "G150.2", "G150.3"}:
                continue
            n = _bin_exit(lines, index + 1)
            if n is not None:
                allowances[n] = retreat
    return allowances
