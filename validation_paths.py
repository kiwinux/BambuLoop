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
    held_y: float | None = None  # Prior Y required for a Z-only transition


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


def _calibration_moves(lines, start):
    """First pre-extrusion Z calibration and its return toward the bed."""
    commands = ((n, " ".join(words)) for n, words in _commands(lines, start, min(start + 40, len(lines)))
                if words[0] != "M73")
    approach = None
    for expected in ("G90", "G1 Z5 F1200", "G1 X270 Y-0.5 F60000", "G28.140 S0"):
        n, command = next(commands, (None, ""))
        if command != expected:
            return ()
        if expected.startswith("G1 X"):
            approach = n

    # Studio reasserts Z5 at the calibration point before returning to the bed.
    for _, command in commands:
        if re.fullmatch(r"M(?:104|141) S\d+(?:\.\d+)?", command) or command == "M1002 GCODE_CLAIM_ACTION : 3":
            continue
        if command == "G90":
            lift, z_command = next(commands, (None, ""))
            _, xy_command = next(commands, (None, ""))
            if z_command == "G1 Z5 F1200" and xy_command == "G1 X187 Y160 F20000":
                return approach, lift
        break
    return ()


def _lift_after_bin_exit(lines, exit_line, load_moves):
    """Only bridge a recognised retreat directly into the load line's first Z5."""
    if exit_line is None or exit_line >= load_moves[0]:
        return None
    for n, words in _commands(lines, exit_line, load_moves[-1]):
        command = " ".join(words)
        if command in {"G90", "G29.2 S1"} or stationary_purge_command(command):
            continue
        if n in load_moves and command == "G1 Z5 F1200":
            return n
        break
    return None


# Stationary slicer setup and restart sounds between the prime and the first layer.
_LAYER_SETUP = {"M73", "M104", "M106", "M204", "M400", "M981", "M991", "M993",
                "M1006", "M1015.3", "M1015.4", "M620.6"}


def _first_layer_z(lines, prime_end):
    first_layer = False
    for index in range(prime_end, len(lines)):
        line = lines[index].strip()
        if line.startswith(";"):
            if line.startswith(_POST + _SWEEP + _RESET + ("; [SHUTDOWN]",)):
                return None
            if match := re.match(r"^;\s*layer num/total_layer_count\s*:\s*(\d+)/\d+\b", line, re.I):
                if first_layer or match[1] != "1":
                    return None
                first_layer = True
            elif first_layer and (line.startswith(_BODY) or _LAYER_MARKER.match(line)):
                return None
            continue
        command = line.partition(";")[0].strip().upper()
        if not command:
            continue
        words = command.split()
        if first_layer and words in (["G1", "Z.4", "F60000"], ["G1", "Z0.4", "F60000"]):
            return index + 1
        if command in {"M17", "M83", "G90", "G21", "G29.2 S1", "G29.99", "M211 Z1"} or words[0] in _LAYER_SETUP:
            continue
        if not first_layer and words in (["G1", "E-.4", "F1800"], ["G1", "E-0.4", "F1800"]):
            continue
        return None
    return None


def _bin_exits(lines, start):
    """Locate the closed relative exit and detect a second retreat before other motion."""
    # Another wipe is checked at its own line. Stop at the first unrelated
    # command or section, so comments and waits cannot hide a repeated retreat.
    commands = ((n, " ".join(words)) for n, words in _commands(lines, start, len(lines))
                if not stationary_purge_command(" ".join(words)))
    _, mode = next(commands, (None, ""))
    if mode != "G91":
        return None, None
    first, move = next(commands, (None, ""))
    if not is_purge_retreat(move):
        return None, None
    n, command = next(commands, (None, ""))
    closed_exit = first if command == "G90" else None
    relative = True
    while command in {"G90", "G91"}:
        relative = command == "G91"
        n, command = next(commands, (None, ""))
    duplicate = n if relative and is_purge_retreat(command) else None
    return closed_exit, duplicate


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


def classify_paths(lines, printable, margin):
    """Authorise individual motions, never a whole comment-delimited section."""
    prime = YRange(max(printable.y_min - margin, -1.717), printable.y_max, "H2S nozzle load line")
    retreat = YRange(max(printable.y_min - margin, -16.0), printable.y_max, "H2S purge-bin exit")
    front = max(printable.y_min - margin, -0.5)
    allowances = {}
    duplicate_exits = set()
    calibration_seen = False
    last_bin_exit = None
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
                moves = _load_line_moves(lines, index + 1)
                if moves:
                    allowances.update(dict.fromkeys(moves, prime))
                    lift = _lift_after_bin_exit(lines, last_bin_exit, moves)
                    if lift is not None:
                        allowances[lift] = YRange(retreat.low, retreat.high, "H2S purge-bin exit to load line", -16.0)
                    layer_z = _first_layer_z(lines, moves[-1])
                    if layer_z is not None:
                        allowances[layer_z] = YRange(front, prime.high, "H2S load line to first layer", -0.5)
        elif phase == "start" and not calibration_seen and line.partition(";")[0].upper().split() == ["G390.1", "Z"]:
            calibration_seen = True
            moves = _calibration_moves(lines, index + 1)
            allowances.update(dict.fromkeys(moves, YRange(front, prime.high, "H2S pre-extrusion calibration")))
        elif phase in ("start", "reset") and line.upper().startswith(("G150.1", "G150.2", "G150.3")):
            if line.partition(";")[0].split()[0].upper() not in {"G150.1", "G150.2", "G150.3"}:
                continue
            exit_line, duplicate = _bin_exits(lines, index + 1)
            if exit_line is not None:
                last_bin_exit = exit_line
                allowances[exit_line] = retreat
            if duplicate is not None:
                duplicate_exits.add(duplicate)
    return allowances, duplicate_exits


def known_y_ranges(lines, printable, margin):
    """Return the per-line allowances without the independent duplicate-exit checks."""
    return classify_paths(lines, printable, margin)[0]
