"""
Bambu Lab H2S G-code auto-repeat-print processing module
============================================

This module parses .gcode files produced by Bambu Studio and splits them
into the following 5 sections.

    1. HEADER_BLOCK   : `; HEADER_BLOCK_START` ~ `; HEADER_BLOCK_END`
    2. CONFIG_BLOCK   : `; CONFIG_BLOCK_START` ~ `; CONFIG_BLOCK_END`
    3. START_GCODE    : homing, bed levelling, preheat, purge (everything up to the first layer)
    4. BODY           : the actual per-layer print G-code
    5. END_GCODE      : cooling, parking, steppers OFF

The composite output then chains [BODY × N + cool / eject / reheat] in a repeating pattern,
producing a single combined G-code that auto-repeats multiple models in one slicing run.


H2S spec notes:
    - Build volume : 256 × 256 × 250 mm
    - Motion       : CoreXY (X/Y head motion, Z bed motion)
    - Hotend max   : 350°C
    - Chamber heat : PTC + circulation fan, controlled via M141 / M191
    - Fan indices  : P1 = part cooling, P2 = aux, P3 = chamber exhaust
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ============================================================
# Constants (Bambu Lab H2S defaults)
# ============================================================

H2S_BED_X = 340          # mm — H2S build volume X
H2S_BED_Y = 320          # mm — H2S build volume Y
H2S_BED_Z_MAX = 340      # mm — H2S build volume Z
H2S_HOTEND_MAX = 350     # °C
H2S_CHAMBER_MAX = 60     # °C (safety upper bound)
H2S_HEAD_RAIL_LIMIT = 42 # mm — H2S head rail bottom + chamber outlet clearance (max safe print height)
                         # Prints taller than this risk physical collision with the head / chamber during the eject sweep


# ============================================================
# G-code output comments (English only — policy)
# ============================================================
# G-code output uses English comments only so any developer can read the output.
# UI text (separate i18n system) remains bilingual for end users.

COMMENTS = {
    # Block headers
    'init_seq':       '[INIT] Initial start sequence — homing/leveling/preheat (once)',
    'shutdown_seq':   '[SHUTDOWN] All prints done — termination sequence',
    'cooling_block':  '[COOLING] Lower bed temperature for part release + fans full',
    'eject_block':    '[EJECT] 4-step Z descent + Y sweep to push part off bed front',
    'reheat_block':   '[REHEAT] Heat nozzle/bed/chamber for next print',
    'reset_block':    '[RESET] G28 re-home + garbage can purge',
    'flushing_block': '[PURGE + CLEAN] Reuse Bambu standard block',
    'parking_block':  'Eject complete, parking head at bed center',
    'm73_block':      '[M73 Progress Recalculation]',

    # Inline comments
    'motion_clear':     'Drain motion queue',
    'absolute_coords':  'Absolute coordinates',
    'relative_coords':  'Relative coordinates',
    'nozzle_off':       'Nozzle heater OFF immediately',
    'bed_target':       'Bed target temp (induce release)',
    'chamber_off':      'Chamber heater OFF',
    'fans_section':     'Fan control (H2S multi-fan)',
    'park_center':      'Park head above bed center',
    'park_z':           'Move Z to safe height',
    'park_xy':          'Move head to bed center',
    'wait_cool':        'Wait for bed to cool to target',
    'wait_chamber':     'Wait for chamber to cool',
    'sound_init':       'Sound mode init',
    'sound_play':       'Play',
    'sound_wait':       'Wait for playback to complete',
    'sound_motor_on':   'Steppers ON',
    'sound_stabilize':  '1s stabilize',
    'rest':             'rest',
    'eject_y_back':     'Move to back of bed (Z held)',
    'eject_z_safe':     'Lift Z to safe travel',
    'eject_x_center':   '(bed center)',
    'eject_y_center':   '(bed center) — safe for G28 XY',
    'pause_resume':     'Bambu pause (await user resume)',
    'rehome':           'Re-home',
    'farmloop_label':   'Update overall progress',
    'm73_removed':      '[BambuLoop M73 removed]',
    'next_print_count': 'Next print #',
    'print_count':      'Print #',

    # Header metadata
    'header_title':  'BambuLoop — Bambu Lab H2S Auto-Repeat Print G-code',
    'generated_at':  'Generated at',
    'total_prints':  'Total prints',
    'cooling_temp':  'Cooling bed temp',
    'eject_method':  'Eject method',
    'sound_event':   'Sound event',
}


def tr(key: str, lang: str = 'en') -> str:
    """Return the English G-code comment for `key`.

    G-code output is intentionally English only (policy) so any developer can
    follow the generated file. The `lang` parameter is accepted for backwards
    compatibility with callers that still pass it.
    """
    return COMMENTS.get(key, key)


# ============================================================
# Data classes
# ============================================================

@dataclass
class GcodeSections:
    """Parsed sections of a Bambu G-code file."""
    header: str = ""
    config: str = ""
    start_gcode: str = ""
    body: str = ""
    end_gcode: str = ""
    nozzle_load_line: str = ""   # 'nozzle load line' block inside start_gcode (purge line on the bed)
                                 # — hard to push out, abandoned in v8
    flushing_block: str = ""     # flushing block inside start_gcode (E45 discharge into the garbage can)
                                 # — reused for re-purge between prints, leaves no residue on the bed


@dataclass
class PrintTemps:
    """Print temperatures + metadata extracted from the G-code header / config block."""
    nozzle_initial: int = 220        # first-layer nozzle temp
    nozzle: int = 220                # regular-layer nozzle temp
    bed_initial: int = 55            # first-layer bed temp
    bed: int = 55                    # regular-layer bed temp
    chamber: int = 0                 # chamber target temp (0 = disabled)
    filament_type: str = "PLA"
    max_z_height: float = 0.0        # print max Z height (mm) — extracted from HEADER_BLOCK
    nozzle_diameter: float = 0.0     # nozzle diameter (0.2 / 0.4 / 0.6 / 0.8 mm)
    nozzle_flow_type: str = ""       # flow type: "Standard" | "High Flow" | ""
    nozzle_hrc: str = ""             # hardness / material: "Stainless Steel" | "Hardened Steel" | "Tungsten Carbide" | ""


@dataclass
class JobConfig:
    """Print-job configuration for a single G-code file."""
    filename: str
    count: int = 1
    sections: GcodeSections = field(default_factory=GcodeSections)
    temps: PrintTemps = field(default_factory=PrintTemps)


@dataclass
class AutomationSettings:
    """Automation-sequence settings (sourced from the UI)."""

    # ----- Cooling settings -----
    cooling_bed_temp: int = 35       # cool the bed to this temp to allow the part to release
    cooling_chamber_temp: int = 0    # cool the chamber to this temp (0 = do not wait)
    cooling_retries: int = 5        # number of M190 R retries (works around Marlin slope timeout)
    part_fan_enabled: bool = True    # whether to use the P1 part-cooling fan
    part_fan_speed: int = 255        # M106 P1 (part cooling)
    aux_fan_enabled: bool = True     # whether to use the P2 auxiliary fan
    aux_fan_speed: int = 255         # M106 P2 (aux fan)
    chamber_fan_enabled: bool = True # whether to use the P3 chamber exhaust fan
    chamber_fan_speed: int = 255     # M106 P3 (chamber exhaust)
    cooling_park_z_min: int = 20     # minimum bed-drop height during cooling (actual = max(this, print_height + clearance))
    park_z_clearance: int = 10       # extra clearance above the print (mm)

    # ----- Eject (push-off) settings -----
    eject_method: str = "edge_to_center"   # 'sweep' | 'multi_sweep' | 'zigzag' | 'edge_to_center' | 'edge_to_center_bottom' | 'bottom_only' | 'none'
    eject_z_offset: float = 0.4         # final (lowest) sweep Z (mm)
    eject_z_start_offset: float = 10.0  # parking-Z clearance above the print (mm) — height during XY parking
    eject_descent_steps: int = 4        # Z sweep step count: from print top → eject_z_offset
    eject_speed: int = 9000             # sweep travel speed (mm/min)
    # Air sweep during cooling (optional) — traverse above the bed at parking-Z, fanning across the print
    cooling_sweep_enabled: bool = False  # default OFF (opt-in)
    cooling_sweep_passes: int = 5        # number of back-and-forth passes
    cooling_sweep_speed: int = 9000      # cooling-sweep speed (mm/min)
    eject_passes: int = 11              # X-axis pass count (= Y sweep count)
                                         # rule of thumb: bed_X (340) / nozzle outlet (~50mm) ≈ 7 to cover the entire bed
    back_overhang_mm: int = 15          # how far past the bed back (mm) — keeps the head outside the bed area
                                        # y_back = bed_size_y + back_overhang_mm (enters the nozzle-cleaner zone)
    front_overhang_mm: int = 5          # how far past the bed front (mm) — guarantees the part drops off
                                        # y_front = 0 - front_overhang_mm (just past the bed front edge)
    bed_size_x: int = H2S_BED_X
    bed_size_y: int = H2S_BED_Y

    # ----- Safety / verification settings -----
    pause_after_eject: bool = False     # pause after eject (user verifies via Handy camera then resumes)
    nozzle_clean_between: bool = True   # clean the nozzle via G150.1 after reheat

    # ----- Reheat / reset settings -----
    rehome_xy_between: bool = True      # re-home X/Y between prints
    rehome_z_between: bool = False      # re-home Z (slow, only when needed)
    purge_between: bool = True          # flush after reheat
    purge_length_mm: float = 30.0       # fallback purge length (legacy)

    # ----- M73 progress recalculation -----
    # Estimated POST_PRINT duration per cycle (minutes). 0 = auto-estimate (estimate_post_print_seconds)
    post_print_override_min: int = 0

    # ----- Locale -----
    lang: str = 'ko'                    # G-code comment language ('ko' | 'en')

    # ----- Per-event sound presets (M1006) -----
    # Each event maps to a key in PRESET_PATTERNS or custom_melodies. "" = silence (or keep factory).
    sound_print_start: str = ""             # very first print start ("" = keep Bambu factory start sound)
    sound_print_done: str = "do_re_mi"      # after one print finishes (just before cooling)
    sound_cool_done: str = "cavalry_short"  # cooling complete (just before eject)
    sound_sweep_done: str = "victory"       # sweep complete (just before reheat)
    sound_restart: str = "bambu_default_start"  # restart cue (end of reset / just before the next BODY)
    sound_print_end: str = ""               # after the final print ("" = keep Bambu factory end sound)

    # User-defined custom melodies — {"<name>": [[midi, dur], ...], ...}
    custom_melodies: dict = field(default_factory=dict)


# ============================================================
# G-code parser
# ============================================================

class BambuGcodeParser:
    """Split a Bambu Studio G-code into 5 logical sections."""

    # Markers that indicate the first-layer start (varies between Bambu Studio versions)
    LAYER_MARKERS = [
        re.compile(r";\s*LAYER_CHANGE"),
        re.compile(r";\s*layer\s*num/total_layer_count\s*:\s*1/"),
        re.compile(r";\s*CHANGE_LAYER"),
        re.compile(r";\s*Z_HEIGHT\s*:\s*0\."),    # first-layer Z
    ]

    # Markers that indicate the start of the end G-code
    END_MARKERS = [
        "; filament end gcode",
        "; machine_end_gcode",
        "; FEATURE: Custom",      # end gcode is often tagged as a Custom feature
    ]

    def __init__(self, content: str, filename: str = "unknown.gcode"):
        self.content = content
        self.filename = filename
        self.lines = content.split("\n")
        self.sections = GcodeSections()
        self.temps = PrintTemps()
        self._parse()

    # --------------------------------------------------------
    # Main parsing routine
    # --------------------------------------------------------

    def _parse(self) -> None:
        # 1) Locate HEADER / CONFIG blocks
        header_start = header_end = -1
        config_start = config_end = -1

        for i, line in enumerate(self.lines):
            s = line.strip()
            if s == "; HEADER_BLOCK_START":
                header_start = i
            elif s == "; HEADER_BLOCK_END":
                header_end = i
            elif s == "; CONFIG_BLOCK_START":
                config_start = i
            elif s == "; CONFIG_BLOCK_END":
                config_end = i

        # 2) First-layer start = end of START_GCODE
        search_from = (config_end + 1) if config_end >= 0 else 0
        first_layer = self._find_first_layer(search_from)

        # 3) End-of-body = start of END_GCODE
        end_start = self._find_end_gcode(first_layer)

        # 4) Extract sections
        if header_start >= 0 and header_end >= 0:
            self.sections.header = "\n".join(self.lines[header_start:header_end + 1])

        if config_start >= 0 and config_end >= 0:
            self.sections.config = "\n".join(self.lines[config_start:config_end + 1])

        # START_GCODE: from (CONFIG_BLOCK end + 1) to (first_layer - 1)
        if config_end >= 0 and first_layer > config_end:
            self.sections.start_gcode = "\n".join(self.lines[config_end + 1:first_layer])

        # BODY: first_layer ~ end_start - 1
        if first_layer >= 0 and end_start > first_layer:
            self.sections.body = "\n".join(self.lines[first_layer:end_start])

        # END_GCODE: from end_start to the end of the file
        if end_start >= 0:
            self.sections.end_gcode = "\n".join(self.lines[end_start:])

        # 5) Extract temperature info
        self.temps = self._extract_temps()

        # 6) Extract the Bambu standard purge routine (nozzle load line block)
        # The region between ";===== nozzle load line =====" and ";===== noozle load line end ====="
        # inside start_gcode (Bambu typo: "noozle" retained verbatim). Reused for re-purge between prints.
        self.sections.nozzle_load_line = self._extract_nozzle_load_line()

        # 7) Extract the Bambu flushing block (the main purge mechanism since v8)
        # The region after ";===== auto extrude cali end =====" up to
        # ";===== wipe right/left nozzle =====" inside start_gcode.
        # This region contains the Bambu flushing command — E45 for 0.6mm nozzle, E60 for 0.8mm.
        # Filament is discharged into the garbage can, leaving nothing on the bed.
        self.sections.flushing_block = self._extract_flushing_block()

    def _extract_flushing_block(self) -> str:
        """Extract the flushing block (E45/E60 garbage-can discharge) from start_gcode.

        Bambu H2S start_gcode layout:
            ;===== auto extrude cali end =========================
               M106 P1 S0
               M400 S2
               M109 S245           ← reach nozzle temperature
               M83                  ← relative extrusion
               G1 E45 F498.898     ★ flushing (E45 — or E60 for 0.8mm nozzle)
               G1 E-3 F1800        ← retract
               M400 P500           ← 500ms dwell
               G150.2              ← auxiliary wipe motion
               G150.1              ← nozzle wipe (clean)
            ;===== wipe right nozzle start =====

        Returns:
            Block contents. Motion lines around the markers (G91 / G1 Y-16 / G90 etc.) are excluded.
            Returns an empty string if no block is found.
        """
        if not self.sections.start_gcode:
            return ""

        sg = self.sections.start_gcode

        # Start marker — end of `auto extrude cali` (the flushing block begins right after)
        start_marker = "===== auto extrude cali end"
        s_idx = sg.find(start_marker)
        if s_idx == -1:
            return ""
        # Start from the end of the start-marker line
        nl = sg.find("\n", s_idx)
        if nl == -1:
            return ""
        block_start = nl + 1

        # End marker — start of the wipe right/left nozzle block
        end_markers = [
            "===== wipe right nozzle start",
            "===== wipe left nozzle",
            "===== wipe ",
        ]
        block_end = -1
        for m in end_markers:
            idx = sg.find(m, block_start)
            if idx != -1:
                block_end = sg.rfind("\n", 0, idx)
                break

        if block_end == -1 or block_end <= block_start:
            return ""

        block = sg[block_start:block_end].strip("\n")

        # Sanity check: the block must contain an E extrusion to qualify as a flushing block
        # (without E, it is probably the TPU branch with only G150 — handled separately)
        if "E45" not in block and "E60" not in block and " E" not in block:
            return ""

        return block

    def _extract_nozzle_load_line(self) -> str:
        """Extract the 'nozzle load line' block from start_gcode.

        Bambu H2S start_gcode layout:
            ;===== nozzle load line ===============================
              G1 X270 Y-0.5 F60000
              G28.14 R0
              G1 Z0.8 F1200
              G1 X250 F60000
              M109 S245
              G1 E5 F374
              G1 X290 E20 F374   ← actual purge line
              G3 Z0.4 I1.217 J0 P1 F60000
            ;===== noozle load line end ===========================

        Returns:
            Block contents (markers excluded). Empty string if not found.
        """
        if not self.sections.start_gcode:
            return ""

        sg = self.sections.start_gcode
        # Accept both the Bambu typo "noozle" and the standard "nozzle" spelling
        start_markers = [
            "===== nozzle load line =",
            "===== noozle load line =",
        ]
        end_markers = [
            "===== noozle load line end =",
            "===== nozzle load line end =",
        ]

        start_idx = -1
        for m in start_markers:
            idx = sg.find(m)
            if idx != -1:
                start_idx = sg.find("\n", idx)
                if start_idx != -1:
                    start_idx += 1
                break

        if start_idx == -1:
            return ""

        end_idx = -1
        for m in end_markers:
            idx = sg.find(m, start_idx)
            if idx != -1:
                # Up to the start of the line containing the end marker
                end_idx = sg.rfind("\n", 0, idx)
                break

        if end_idx == -1 or end_idx <= start_idx:
            return ""

        block = sg[start_idx:end_idx].strip("\n")
        return block

    def _find_first_layer(self, search_from: int) -> int:
        """Find the first-layer start line."""
        for i in range(search_from, len(self.lines)):
            line = self.lines[i]
            for pat in self.LAYER_MARKERS:
                if pat.search(line):
                    return i

        # If no marker is found, fall back to the first extrusion after M109 (nozzle heat-up)
        after_heat = False
        for i in range(search_from, len(self.lines)):
            s = self.lines[i].strip()
            if s.startswith("M109"):
                after_heat = True
                continue
            if after_heat and s.startswith(("G1", "G0")) and " E" in s:
                # Treat the first move-with-extrusion as the first-layer start
                return i
        return search_from

    def _find_end_gcode(self, body_start: int) -> int:
        """Find the END_GCODE start line."""
        # 1) Explicit markers take priority
        for i in range(len(self.lines) - 1, body_start, -1):
            s = self.lines[i].strip().lower()
            for marker in self.END_MARKERS:
                if marker.lower() in s:
                    return i

        # 2) If no marker, look around the second-to-last M104 S0
        for i in range(len(self.lines) - 1, body_start, -1):
            s = self.lines[i].strip()
            if re.match(r"M104\s+S0\b", s) or re.match(r"M104\s+T\d+\s+S0\b", s):
                # Shutdown sequence starts here
                return i

        # 3) Still not found → fall back to end of file
        return len(self.lines)

    def _extract_temps(self) -> PrintTemps:
        """Extract temperature values from CONFIG_BLOCK comments."""
        cfg = {}
        for line in self.sections.config.split("\n"):
            if "=" not in line:
                continue
            stripped = line.lstrip(";").strip()
            if "=" not in stripped:
                continue
            key, _, val = stripped.partition("=")
            cfg[key.strip()] = val.strip()

        def _int(key: str, default: int) -> int:
            try:
                # Multi-extruder value (e.g. "220,220") — use only the first one
                return int(str(cfg.get(key, default)).split(",")[0].strip() or default)
            except (ValueError, AttributeError):
                return default

        # The bed-temp key depends on curr_bed_type
        bed_type = cfg.get("curr_bed_type", "Textured PEI Plate")
        if "Textured" in bed_type:
            bed_key = "textured_plate_temp"
            bed_init_key = "textured_plate_temp_initial_layer"
        elif "Cool" in bed_type:
            bed_key = "cool_plate_temp"
            bed_init_key = "cool_plate_temp_initial_layer"
        elif "Engineer" in bed_type:
            bed_key = "eng_plate_temp"
            bed_init_key = "eng_plate_temp_initial_layer"
        elif "Supertack" in bed_type:
            bed_key = "supertack_plate_temp"
            bed_init_key = "supertack_plate_temp_initial_layer"
        else:
            bed_key = "hot_plate_temp"
            bed_init_key = "hot_plate_temp_initial_layer"

        # max_z_height lives in HEADER_BLOCK as "; key: value" (CONFIG uses "key = value")
        max_z = 0.0
        for line in self.sections.header.split("\n"):
            m = re.match(r";\s*max_z_height\s*:\s*([\d.]+)", line, re.IGNORECASE)
            if m:
                try:
                    max_z = float(m.group(1))
                except ValueError:
                    pass
                break

        def _float(key: str, default: float) -> float:
            try:
                return float(str(cfg.get(key, default)).split(",")[0].strip() or default)
            except (ValueError, AttributeError):
                return default

        # Extract the nozzle flow type (Standard / High Flow)
        # Priority 1: extruder_nozzle_stats — the nozzle actually used for slicing (e.g. "High Flow#1")
        # Priority 2: filament_extruder_variant — per-filament nozzle variant (e.g. "Direct Drive High Flow")
        # Priority 3: default_nozzle_volume_type — profile default (may differ from actual use; fallback only)
        flow_type = ""
        ens = str(cfg.get("extruder_nozzle_stats", "")).strip().strip('"')
        fev = str(cfg.get("filament_extruder_variant", "")).strip().strip('"').split(';')[0].strip().strip('"')
        nvt = cfg.get("default_nozzle_volume_type", "").strip()

        # Check the most reliable source first
        for source in [ens, fev, nvt]:
            if not source:
                continue
            sl = source.lower()
            if "high flow" in sl or sl.startswith("hf") or "#hf" in sl:
                flow_type = "High Flow"
                break
            elif "standard" in sl:
                flow_type = "Standard"
                break

        # Extract the nozzle hardness / material (HRC) — Stainless Steel / Hardened Steel / Tungsten Carbide etc.
        # Keyword normalisation map (lowercase / snake_case → display label)
        hrc_normalize = [
            ("tungsten", "Tungsten Carbide"),
            ("hardened", "Hardened Steel"),
            ("stainless", "Stainless Steel"),
            ("steel",     "Hardened Steel"),  # standalone "steel" → typically hardened
        ]
        hrc = ""
        # Combine every candidate source for keyword matching (raw values are NOT displayed)
        sources = [
            cfg.get("nozzle_hrc", ""),
            cfg.get("nozzle_type", ""),
            cfg.get("filament_settings_id", ""),
            cfg.get("inherits_group", ""),
            cfg.get("default_filament_profile", ""),
            cfg.get("printer_settings_id", ""),
        ]
        hint = " ".join(str(s) for s in sources).lower()
        for kw, label in hrc_normalize:
            if kw in hint:
                hrc = label
                break

        return PrintTemps(
            nozzle_initial=_int("nozzle_temperature_initial_layer", 220),
            nozzle=_int("nozzle_temperature", 220),
            bed_initial=_int(bed_init_key, _int("hot_plate_temp_initial_layer", 55)),
            bed=_int(bed_key, _int("hot_plate_temp", 55)),
            chamber=_int("chamber_temperatures", 0),
            filament_type=str(cfg.get("filament_type", "PLA")).split(";")[0].strip(),
            max_z_height=max_z,
            nozzle_diameter=_float("nozzle_diameter", 0.0),
            nozzle_flow_type=flow_type,
            nozzle_hrc=hrc,
        )

    # --------------------------------------------------------
    # Public info accessor
    # --------------------------------------------------------

    def get_info(self) -> dict:
        """Summary info for UI display."""
        return {
            "filename": self.filename,
            "filament_type": self.temps.filament_type,
            "nozzle_temp": self.temps.nozzle_initial,
            "nozzle_diameter": self.temps.nozzle_diameter,
            "nozzle_flow_type": self.temps.nozzle_flow_type,
            "nozzle_hrc": self.temps.nozzle_hrc,
            "bed_temp": self.temps.bed_initial,
            "chamber_temp": self.temps.chamber,
            "max_z_height": self.temps.max_z_height,
            "header_lines": len(self.sections.header.split("\n")),
            "body_lines": len(self.sections.body.split("\n")),
            "has_start_gcode": bool(self.sections.start_gcode.strip()),
            "has_end_gcode": bool(self.sections.end_gcode.strip()),
        }


# ============================================================
# Sequence generators — cooling, eject, reheat, reset
# ============================================================

def generate_cooling_sequence(s: AutomationSettings, max_z_height: float = 0.0,
                               *, skip_wait: bool = False,
                               start_bed_temp: int = 0) -> str:
    """Build the post-print cooling sequence G-code.

    Args:
        s: automation settings
        max_z_height: max Z height (mm) of the print that just finished.
        skip_wait: if True, skip all wait commands (for fast dry-run verification).
        start_bed_temp: estimated bed temperature at print end (°C). 0 = use heuristic.
    """
    cx, cy = s.bed_size_x // 2, s.bed_size_y // 2

    # Dynamic parking-Z: max(user_minimum, print_height + clearance), clamped to the H2S Z limit
    park_z_dynamic = max(s.cooling_park_z_min, int(max_z_height) + s.park_z_clearance)
    park_z = min(park_z_dynamic, H2S_BED_Z_MAX - 5)
    park_z_note = (
        f"print height {max_z_height:.1f}mm + clearance {s.park_z_clearance}mm"
        if int(max_z_height) + s.park_z_clearance > s.cooling_park_z_min
        else f"user minimum {s.cooling_park_z_min}mm applied (print {max_z_height:.1f}mm)"
    )

    # Per-fan commands: configured speed if enabled, explicit S0 if disabled (avoid lingering state)
    p1_speed = s.part_fan_speed if s.part_fan_enabled else 0
    p2_speed = s.aux_fan_speed if s.aux_fan_enabled else 0
    p3_speed = s.chamber_fan_speed if s.chamber_fan_enabled else 0
    p1_label = f"S{p1_speed}" + ("" if s.part_fan_enabled else " [OFF]")
    p2_label = f"S{p2_speed}" + ("" if s.aux_fan_enabled else " [OFF]")
    p3_label = f"S{p3_speed}" + ("" if s.chamber_fan_enabled else " [OFF]")

    lines = [
        "; ==========================================================",
        f"; {tr('cooling_block', s.lang)}",
        f";   - parking Z (dyn): {park_z}mm  ({park_z_note})",
        "; ==========================================================",
        "M400                              ; drain motion queue",
        "G90                               ; absolute coordinates",
        "M104 S0                           ; nozzle heater OFF immediately",
        "M140 S0                           ; bed heater fully OFF (natural cooling + fans for fast drop)",
        f"M141 S{s.cooling_chamber_temp}                          ; chamber heater OFF (target {s.cooling_chamber_temp}°C)",
        "",
        "; ----- fan control (H2S multi-fan) -----",
        f"M106 P1 S{p1_speed}                       ; P1 part-cooling fan {p1_label}",
        f"M106 P2 S{p2_speed}                       ; P2 auxiliary fan {p2_label}",
        f"M106 P3 S{p3_speed}                       ; P3 chamber exhaust fan {p3_label}",
        "",
        "; ----- park head above bed centre (safe clearance above the print) -----",
        f"G1 Z{park_z} F1200                       ; lower bed to safe height (= {park_z - int(max_z_height)}mm above the print)",
        f"G1 X{cx} Y{cy} F9000                  ; move head to bed centre",
        "",
        f"; ----- wait until bed cools to {s.cooling_bed_temp}°C or below -----",
    ]

    if skip_wait:
        lines.append(f"; [DRY-RUN] cooling wait skipped (target {s.cooling_bed_temp}°C)")
        lines.append("G4 P3000                          ; short 3s dwell instead (fans visible)")
    else:
        # ============================================================
        # Cooling wait — repeated M190 R calls at the target temperature
        # ============================================================
        # Problem (per Marlin PR #17877 measurements):
        #   M190 R<temp> times out as "cannot cool further" if the slope drops below
        #   MIN_COOLING_SLOPE_DEG_BED (1.5°C / 60s). With default settings, releases around ~42°C.
        #
        # Workaround: call M190 R with the same target multiple times.
        #   - Each call resets the slope timer
        #   - 1st call: fast cool from high temp, times out near 42°C
        #   - 2nd~Nth call: each iteration nudges the temperature down another 1~2°C
        #   - With enough retries (10~15), the bed converges close to the target
        # 
        # In the high-temp band (>45°C), slope tolerance is wide so this is not slower than a stepped scheme.
        # In the low-temp band (near 40°C), repeated calls reach lower temps than a stepped scheme.
        # ============================================================
        NUM_RETRIES = max(1, min(30, s.cooling_retries))  # 1~30 clamp

        lines += [
            f"; cooling: bed heater OFF + M190 R{s.cooling_bed_temp} called {NUM_RETRIES} times",
            f";   each call resets the Marlin slope timeout, gradually reaching lower temperatures",
            f";   (with default MIN_COOLING_SLOPE_DEG_BED, a single call only reaches ~42°C)",
        ]
        for i in range(1, NUM_RETRIES + 1):
            lines.append(
                f"M190 R{s.cooling_bed_temp}                          "
                f"; [cooling {i}/{NUM_RETRIES}] reset slope timer → keep cooling"
            )

        if s.cooling_chamber_temp > 0:
            lines.append(f"M191 R{s.cooling_chamber_temp}                          ; wait for chamber to reach {s.cooling_chamber_temp}°C or below")

    lines.append("")
    return "\n".join(lines)


def generate_eject_sequence(s: AutomationSettings, max_z_height: float = 0.0) -> str:
    """Build the eject (push-off) sequence G-code — stepped descent + orthogonal moves.

    Safety design:
        1) Stepped Z descent: avoids gantry collision if a stuck print lifts off
            Z start = print_height + eject_z_start_offset
            Z end   = eject_z_offset
            Z steps = eject_descent_steps (evenly spaced)

        2) Orthogonal moves (no diagonals): when moving to the next X pass
            (current X, Y_front) → (current X, Y_back) → (next X, Y_back)
            Diagonal moves risk colliding with leftover parts on the bed → always L-shaped.

        3) Start/end outside the bed area: if the head is over the bed during Z descent
            it could press down on a part. Therefore:
            - Y_back = bed_size_y + back_overhang (past the bed back edge, near the nozzle cleaner)
              With the head outside the bed, Z descent cannot touch any print
            - Y_front = -front_overhang (past the bed front edge)
              The sweep continues past the front edge so parts drop off the bed
    """
    if s.eject_method == "none":
        return "; ----- eject sequence disabled -----\n"

    cx = s.bed_size_x // 2
    # Push head outside the bed area first — prevents Z descent from pressing a print
    y_back = s.bed_size_y + s.back_overhang_mm    # past bed back + overhang (nozzle cleaner area)
    y_front = -s.front_overhang_mm                # past bed front - overhang (guarantees part drop)

    # Compute stepped-descent Z levels — v27 revision:
    #   Previously: z_start = print_height + 8mm clearance → first sweep ran in air above the print
    #   Now: park XY at parking Z (print_height + 10mm), then drop Z down to the print top
    #         and sweep down to the final Z offset in N steps. The first sweep actually grips the print.
    #   eject_z_start_offset is now only used as the parking-Z clearance (defaults to max(10, offset)).
    parking_z_above = max(10.0, s.eject_z_start_offset)  # parking clearance above the print
    z_parking = min(max_z_height + parking_z_above, H2S_BED_Z_MAX - 5)

    # Sweep start = top of the print (descend from here toward the bed)
    # When no print is present (max_z_height=0) start from at least 5mm
    z_sweep_start = max(max_z_height, 5.0)
    z_sweep_start = min(z_sweep_start, H2S_BED_Z_MAX - 5)
    z_end = s.eject_z_offset
    steps = max(1, s.eject_descent_steps)

    # bottom_only mode: no Z descent, just repeat sweeps at the final offset
    # For short objects (~20mm or less), multi-step descent wastes the first sweep in air above the part.
    # This mode repeats at the final Z from the start, concentrating the eject force.
    if s.eject_method == "bottom_only" or s.eject_method == "edge_to_center_bottom":
        # Z fixed — sweep repeatedly at the final offset only
        z_levels = [z_end] * steps
    elif steps == 1:
        z_levels = [z_end]
    else:
        z_levels = [
            round(z_sweep_start - (z_sweep_start - z_end) * i / (steps - 1), 2)
            for i in range(steps)
        ]

    z_safe_travel = round(z_parking, 1)   # inter-layer safe travel height = parking Z

    # Compute X positions — even split so passes cover edge-to-edge
    # Earlier versions clustered passes near the centre, missing the bed edges.
    # Fixed: 3mm edge margin so we sweep close to both ends of the bed
    x_edge_margin = 3
    if s.eject_method == "sweep":
        x_positions = [cx]
    elif s.eject_method in ("multi_sweep", "bottom_only", "edge_to_center", "edge_to_center_bottom"):
        if s.eject_passes == 1:
            x_positions = [cx]
        else:
            x_min = x_edge_margin
            x_max = s.bed_size_x - x_edge_margin
            # First build an evenly spaced X-coordinate list (left → right)
            x_linear = [
                int(round(x_min + (x_max - x_min) * i / (s.eject_passes - 1)))
                for i in range(s.eject_passes)
            ]
            # edge_to_center mode: reorder edges → centre alternating
            # e.g. [3, 59, 115, 171, 227, 283, 337]
            #  → [3, 337, 59, 283, 115, 227, 171]
            if s.eject_method in ("edge_to_center", "edge_to_center_bottom"):
                x_positions = []
                n = len(x_linear)
                left = 0
                right = n - 1
                while left <= right:
                    x_positions.append(x_linear[left])
                    if left != right:
                        x_positions.append(x_linear[right])
                    left += 1
                    right -= 1
            else:
                x_positions = x_linear
    elif s.eject_method == "zigzag":
        x_positions = None
    else:
        x_positions = [cx]

    # Total sweep count (for the meta header)
    if s.eject_method == "zigzag":
        total_sweeps = steps * s.eject_passes
    elif s.eject_method == "sweep":
        total_sweeps = steps
    else:
        total_sweeps = steps * len(x_positions)

    # Z-range expression for the meta comment
    if s.eject_method in ("bottom_only", "edge_to_center_bottom"):
        z_range_desc = f"{z_end}mm fixed ({steps} repeat sweep(s))"
    else:
        z_range_desc = f"{z_sweep_start:.1f}mm (print top) → {z_end}mm ({steps} step(s))"

    lines = [
        "; ==========================================================",
        "; [eject sequence] stepped descent + orthogonal moves — safe part removal",
        f";   - method       : {s.eject_method}",
        f";   - X pass count : {s.eject_passes if s.eject_method != 'sweep' else 1} (= Y sweep count)",
        f";   - X coverage   : {x_edge_margin}mm ~ {s.bed_size_x - x_edge_margin}mm (almost edge-to-edge)",
        f";   - print height : {max_z_height:.1f}mm (auto-extracted from G-code header)",
        f";   - parking Z    : {z_parking:.1f}mm (print + {parking_z_above:.0f}mm)",
        f";   - sweep Z range: {z_range_desc}",
        f";   - Y back start : Y={y_back}mm (= bed {s.bed_size_y} + back overhang {s.back_overhang_mm}mm)",
        f";                    ★ outside the bed, so Z descent cannot collide with prints",
        f";   - Y front end  : Y={y_front}mm (= bed front - {s.front_overhang_mm}mm) ★ parts drop off",
        f";   - sweep speed  : {s.eject_speed} mm/min",
        f";   - total sweeps : {total_sweeps}",
        "; ==========================================================",
        "",
        "; [entry order] (1) Z parking → (2) XY parking → (3) drop Z to print top → (4) begin sweep",
        "G90                                ; absolute coordinates",
        f"G1 Z{z_parking:.1f} F1200                       ; (1) Z parking ({max_z_height:.1f}mm + {parking_z_above:.0f}mm clearance)",
    ]

    # Entry: move Y off the bed first, then align X (kept safe at parking-Z height)
    first_x = x_positions[0] if x_positions else cx
    lines += [
        f"G1 Y{y_back} F9000                  ; (2) Y={y_back} (off the bed, toward the nozzle cleaner)",
        f"G1 X{first_x} F9000                  ; (3) X={first_x} alignment (parking Z held)",
        f"G1 Z{z_sweep_start:.1f} F1200                      ; (4) Z down to print top = first sweep start",
    ]

    # Run the full X pattern on each Z level — within a layer, Z is fixed
    for layer_idx, z in enumerate(z_levels):
        layer_label = f"descent step {layer_idx + 1}/{steps}  Z={z}mm"
        gap_to_print = z - max_z_height
        if gap_to_print > 1.0:
            note = f"engage {gap_to_print:.1f}mm above the print (light initial press)"
        elif gap_to_print > -1.0:
            note = "print shoulder height — side scraping"
        elif z > 3.0:
            note = "mid-height cleanup (assumes print already detached)"
        else:
            note = "just above bed surface — final residue scraping"

        # Layer transition: before lowering Z, always return Y to y_back (off the bed)
        # ★ Risk mitigation: change Z only after Y is past the bed (never cross over a print)
        if layer_idx > 0:
            lines += [
                "",
                f"; [layer transition — safe order] prev layer ended at (X, Y=-{-y_front}, Z=prev),",
                f";                     first return Y={y_back} (off bed) → change Z → move X",
                f"G1 Y{y_back} F9000                  ; (1) Y={y_back} return off-bed (Z held at prev layer Z)",
                f"G1 Z{z_levels[layer_idx - 1]} F600                    ; (current Z held — sanity)" if False else f"G1 Z{z} F600                        ; (2) once Y is off-bed, change to new layer Z",
            ]
            # (G1 Z is already in the header block below — but we moved it here. Remove the one below.)
            lines += [
                f"; ---------- [{layer_label}] {note} ----------",
            ]
        else:
            lines += [
                "",
                f"; ---------- [{layer_label}] {note} ----------",
                f"G1 Z{z} F600                        ; descend to first-layer Z (already at y_back, safe)",
            ]

        if s.eject_method == "zigzag":
            # Zigzag: main sweep is diagonal (intentional), inter-sweep moves are orthogonal
            # Within a layer Z is fixed (held at Z=z), only X/Y move
            for i in range(s.eject_passes):
                x_a = int(round(x_edge_margin + (s.bed_size_x - 2*x_edge_margin) * i / s.eject_passes))
                x_b = int(round(x_edge_margin + (s.bed_size_x - 2*x_edge_margin) * (i + 1) / s.eject_passes))
                if i % 2 == 0:
                    ystart, yend = y_back, y_front
                else:
                    ystart, yend = y_front, y_back
                if i == 0 and layer_idx == 0:
                    # First zigzag: already at (first_x, y_back) and Z is descended
                    # x_a may differ from first_x, just align
                    lines.append(f"G1 X{x_a} F9000                     ; align X for first zigzag")
                else:
                    # Move only on Y to reach the next start (Z fixed)
                    lines.append(f"G1 Y{ystart} F9000                  ; move Y to {ystart} (Z fixed)")
                    lines.append(f"G1 X{x_a} F9000                     ; move X to {x_a} (Z fixed)")
                lines.append(f"G1 X{x_b} Y{yend} F{s.eject_speed}     ; zigzag main sweep {i + 1}/{s.eject_passes}")
        else:
            # sweep / multi_sweep: vertical back → front sweep at every X position
            # Within a layer Z is fixed — move only X/Y to the next pass
            for i, x in enumerate(x_positions):
                if i == 0 and layer_idx == 0:
                    # Very first iteration: already at (first_x, y_back, z)
                    pass
                elif i == 0:
                    # Just after a layer transition: Y is already at y_back (returned in header block), Z is the new layer Z
                    # → just move X to the first pass
                    lines.append(f"G1 X{x} F9000                       ; first X={x} of new layer (Y held off-bed)")
                else:
                    # Next X pass within the same layer (Z fixed)
                    lines.append(f"G1 Y{y_back} F9000                  ; return Y off-bed (Z fixed)")
                    lines.append(f"G1 X{x} F9000                       ; move to X={x} (Z fixed)")
                lines.append(f"G1 Y{y_front} F{s.eject_speed}              ; off-bed → off-bed main sweep ({i + 1}/{len(x_positions)}) @ X={x}")

    # Final parking — move to bed centre (so the next G28 XY does not slam X into an end stop)
    # Move Y to y_back first (currently at y_front = off-bed front, safe traversal)
    # → After Y reaches off-bed, raise Z
    # → Centre X/Y on the bed (avoids hitting the left/right limit switches during homing)
    park_x = s.bed_size_x // 2
    park_y = s.bed_size_y // 2
    lines += [
        "",
        f"; ----- {tr('parking_block', s.lang)} -----",
        "; [safe order] from last sweep end (X=last, Y=y_front, Z=z_end) → bed centre",
        f";   currently at Y=-5 (off-bed front), so moving Y to y_back first keeps the path off-bed",
        f";   (even with low Z, we are outside the bed so no print can collide)",
        ";   ★ Park at bed centre: prevents the X axis from slamming into the limit switches",
        ";     during the next G28 XY homing",
        f"G1 Y{y_back} F9000                  ; (1) Y={y_back} back of bed (Z held, motion stays off-bed)",
        f"G1 Z{z_safe_travel} F1200           ; (2) Y is now off-bed → raise Z to safe travel",
        f"G1 X{park_x} F9000                  ; (3) X={park_x} (bed centre)",
        f"G1 Y{park_y} F9000                  ; (4) Y={park_y} (bed centre) — safe for G28 XY",
        "",
    ]
    return "\n".join(lines)


def generate_reheat_sequence(temps: PrintTemps, s: AutomationSettings,
                              *, skip_wait: bool = False) -> str:
    """Reheat sequence for the next print.

    Args:
        temps: target temperatures for the next print
        s: automation settings
        skip_wait: if True, skip M190/M191/M109 wait commands (for fast dry-run)
    """
    lines = [
        "; ==========================================================",
        "; [reheat sequence] heat back up for the next print",
        f";   - nozzle target: {temps.nozzle_initial}°C ({temps.filament_type})",
        f";   - bed target   : {temps.bed_initial}°C",
    ]
    if temps.chamber > 0:
        lines.append(f";   - chamber target: {temps.chamber}°C")
    lines += [
        "; ==========================================================",
        "M400                              ; wait for previous motion to finish",
    ]

    lines.append(f"M140 S{temps.bed_initial}                          ; start heating bed (non-blocking)")
    if temps.chamber > 0:
        lines.append(f"M141 S{temps.chamber}                          ; start heating chamber (non-blocking)")
    lines.append(f"M104 S{temps.nozzle_initial}                         ; start heating nozzle (non-blocking)")

    lines += [
        "",
        "; ----- fans OFF to speed up heating -----",
        "M106 P1 S0                        ; part cooling OFF",
        "M106 P2 S0                        ; aux fan OFF",
        "M106 P3 S0                        ; chamber exhaust OFF",
        "",
        "; ----- wait for targets (slowest first) -----",
    ]

    if skip_wait:
        lines.append(f"; [DRY-RUN] M190 S{temps.bed_initial} skipped")
        if temps.chamber > 0:
            lines.append(f"; [DRY-RUN] M191 S{temps.chamber} skipped")
        lines.append(f"; [DRY-RUN] M109 S{temps.nozzle_initial} skipped")
        lines.append("G4 P3000                          ; short 3s dwell instead")
    else:
        lines.append(f"M190 S{temps.bed_initial}                          ; wait for bed to reach target")
        if temps.chamber > 0:
            lines.append(f"M191 S{temps.chamber}                          ; wait for chamber to reach target")
        lines.append(f"M109 S{temps.nozzle_initial}                         ; wait for nozzle to reach target")

    lines += [
        "",
        "; (nozzle clean G150.1 runs after XY homing in the reset sequence — needs exact coords)",
        "",
    ]
    return "\n".join(lines)


def generate_reset_sequence(s: AutomationSettings, temps: PrintTemps,
                             *, flushing_block: str = "",
                             nozzle_load_line: str = "") -> str:
    """Reset position / extruder state, flush, and clean before the next print.

    v8+ order:
        1) G28 XY (re-home)
        2) G150.3 (move to garbage-can position)
        3) Execute the flushing block (E45 discharge + embedded G150.2 + G150.1 — extracted from the source file)
        4) Leave the garbage can (G1 Y-16)
        5) Begin printing immediately

    The legacy 'nozzle load line' purge drew a 30-40mm line on the bed,
    which had to be ejected later — but the line was too small for the sweep to remove.
    v8 replaced this with flushing (garbage-can discharge) — no residue on the bed.

    Args:
        flushing_block: flushing block extracted from the source .gcode (E45 discharge + wipe). Preferred.
        nozzle_load_line: (legacy, v7 compatibility) not used even when no flushing block was found.
            Falls back to a minimal manual flush instead.
    """
    lines = [
        "; ==========================================================",
        "; [reset sequence] re-home coordinates + flushing + cleaning",
        "; ==========================================================",
        "G90                               ; absolute coordinates",
        "M83                               ; extruder relative mode (Bambu standard)",
        "G92 E0                            ; reset extruder counter",
    ]

    if s.rehome_xy_between or s.rehome_z_between:
        axes = ""
        if s.rehome_xy_between:
            axes += "X Y "
        if s.rehome_z_between:
            axes += "Z "
        lines.append(f"G28 {axes.strip()}                         ; re-home")

    # Flushing + cleaning (v8: discharge E45 into the garbage can, no line drawn on the bed)
    if s.purge_between and flushing_block.strip():
        # Strip M73 P/R from the flushing block — it gets reused every BambuLoop cycle, so
        # leaving the original absolute values (e.g. M73 P0 R53) would reset the overall progress
        flushing_clean = re.sub(
            r"^(M73 P\d+ R\d+.*)$",
            r"; [BambuLoop M73 removed] \1",
            flushing_block, flags=re.MULTILINE
        )
        lines += [
            "",
            "; ==========================================================",
            "; [flushing + cleaning] reuse Bambu standard block",
            ";   → discharge E45 (or E60) into the garbage can, then G150.1 wipe (embedded in block)",
            ";   → no purge line drawn on the bed, so the next eject sweep is unobstructed",
            ";   → M73 commands inside the flushing block were stripped to keep progress monotonic",
            "; ==========================================================",
            "M400                              ; drain motion queue",
            "M106 P1 S0                        ; part cooling fan OFF (stable flushing)",
            "G150.3 F18000                     ; ▶ Bambu: move to garbage can",
            "",
            "; ----- Bambu flushing block START (slicer-tuned per filament) -----",
            flushing_clean,
            "; ----- Bambu flushing block END (includes G150.1 wipe) -----",
            "",
            "G91                               ; relative coordinates",
            "G1 Y-16 F12000                    ; leave the garbage can",
            "G90                               ; back to absolute coordinates",
            "",
        ]

        # Prime nozzle tip + extrude baseline (replicates Bambu's first-print "nozzle load line")
        # 
        # v30: a simple E restore + G150.1 wipe was not enough to fix first-layer extrusion lag.
        # We now replicate what Bambu itself does at first-print start:
        #   → just outside the bed front edge (Y=-0.5), draw a 40mm baseline
        #     from X=250 to X=290 to stabilise flow and protect first-layer quality.
        #
        # Mirrors the trajectory of the original ";===== nozzle load line =====" block in Bambu start_gcode.
        # Because the line is drawn off the build plate, it is removed by the next eject sweep.
        import re as _re
        retract_match = _re.search(r"G1\s+E-([\d.]+)\s+F\d+", flushing_block)
        retract_mm = float(retract_match.group(1)) if retract_match else 3.0

        lines += [
            "; ----- nozzle load line (v30: replicates Bambu's first-print action) -----",
            ";   draw a 40mm baseline at Y=-0.5 (off the bed front), X250 → X290",
            ";   stabilise flow + prevent first-layer extrusion lag.",
            ";   line lives outside the bed, so the next eject sweep removes it naturally.",
            f";   (compensates for the {retract_mm}mm retraction left by flushing)",
            "",
            "G29.2 S1                          ; Z compensation ON",
            "G90                               ; absolute coordinates",
            "M83                               ; relative extrusion",
            "G1 Z5 F1200                       ; lift Z to safe height (avoid bed contact)",
            "G1 X270 Y-0.5 F60000              ; ▶ approach the off-bed front entry point (Y=-0.5)",
            "G28.14 R0                         ; Z position calibration",
            "G29.2 S0                          ; temporarily disable Z compensation",
            "G91                               ; relative coordinates",
            "G1 Z0.8 F1200                     ; Z=0.8mm (nozzle-load-line height)",
            "G90                               ; absolute coordinates",
            "G1 X250 F60000                    ; ▶ line start at X=250",
            "M400 P50                          ; 50ms dwell",
            "M400 S3                           ; 3s stabilise",
            f"M109 S{temps.nozzle_initial}                          ; re-verify nozzle temperature",
            "M83                               ; relative extrusion",
            f"G1 E{retract_mm:.1f} F240                     ; restore the {retract_mm}mm retraction (nozzle-tip priming)",
            "G1 E5 F498.898                    ; 5mm pre-extrusion",
            "G1 X290 E20 F498.898              ; ▶ X250 → X290, 40mm baseline (E20 extrusion)",
            "G91                               ; relative coordinates",
            "G3 Z0.4 I1.217 J0 P1 F60000       ; curved lift at line end (snap filament)",
            "G90                               ; absolute coordinates",
            "M83                               ; relative extrusion",
            "G29.2 S1                          ; Z compensation ON",
            "M400                              ; wait for load line to finish",
            "",
        ]
        # The conditional chain continues below — keep the elif chain.
    elif s.purge_between:
        # Fallback: no flushing block found (non-Bambu slicer, etc.)
        # Minimal manual flush + optional G150.1
        lines += [
            "",
            "; ----- Fallback manual flushing (no Bambu block available) -----",
            "; ⚠ E value is not tuned per-slicer — using a conservative 20mm extrusion",
            "M400",
            "M106 P1 S0                        ; part cooling OFF",
            "G150.3 F18000                     ; move to garbage can (if H2S supports it)",
            "M83                               ; relative extrusion",
            "G1 E20 F240                       ; 20mm discharge (conservative)",
            "G1 E-3 F1800                      ; retract",
            "M400 P500",
        ]
        if s.nozzle_clean_between:
            lines += [
                "G150.1 F18000                     ; nozzle wipe",
            ]
        lines += [
            "G91",
            "G1 Y-16 F12000                    ; leave",
            "G90",
            "",
        ]
    elif s.nozzle_clean_between:
        # Cleaning only, no flushing (rare branch)
        lines += [
            "",
            "; ----- nozzle cleaning only (flushing disabled) -----",
            "M400",
            "G91", "G1 E-0.4 F1800", "G90",
            "G150.1 F18000                     ; nozzle wipe",
            "G91", "G1 E-0.6 F1800", "G90",
            "",
        ]

    lines.append("")
    return "\n".join(lines)


# ============================================================
# Combined G-code builder
# ============================================================

def build_combined_gcode(jobs: list[JobConfig], settings: AutomationSettings) -> str:
    """Combine multiple G-code jobs into a single auto-repeat-print file.

    Structure:
        [HEADER]
        [CONFIG]
        [Automation metadata comment]
        [START_GCODE — taken once from the first job]

        ┌─ Print #1 (Job A 1/N)
        │   [BODY]
        │   [cooling] [eject] [reheat] [reset]
        ├─ Print #2 (Job A 2/N)
        │   [BODY]
        │   [cooling] [eject] [reheat] [reset]
        ...
        └─ Print #M (Job B K/M, final)
            [BODY]

        [END_GCODE — taken once from the last job]
    """
    if not jobs:
        raise ValueError("at least one print job is required.")

    first_job = jobs[0]
    last_job = jobs[-1]
    total_copies = sum(j.count for j in jobs)

    out: list[str] = []

    # ---------- 1) header + config (taken from the first job) ----------
    # Rewrite the header's 'total estimated time' to the total BambuLoop time
    body_time_for_header = (parse_estimated_time_seconds(first_job.sections.header) or
                              parse_estimated_time_seconds(first_job.sections.body) or 0)
    post_for_header = (settings.post_print_override_min * 60
                        if settings.post_print_override_min > 0
                        else estimate_post_print_seconds(settings, first_job.temps.max_z_height))
    total_estimated_sec = (body_time_for_header * total_copies
                            + post_for_header * max(0, total_copies - 1))

    header_text = first_job.sections.header or ""
    if header_text and total_estimated_sec > 0:
        # 'total estimated time: 54m 8s' → replaced with the recomputed value
        h = total_estimated_sec // 3600
        m = (total_estimated_sec % 3600) // 60
        s = total_estimated_sec % 60
        new_time_str = (f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s")
        header_text = re.sub(
            r"(;\s*total estimated time:\s*)[\dhms\s]+",
            r"\g<1>" + new_time_str + f"  ; BambuLoop x{total_copies} (post~{post_for_header//60}m each)",
            header_text, count=1, flags=re.IGNORECASE
        )
        # Also update model printing time (informational)
        if "model printing time" in header_text:
            mp_total = body_time_for_header * total_copies
            mp_h, mp_m, mp_s = mp_total // 3600, (mp_total % 3600) // 60, mp_total % 60
            mp_str = (f"{mp_h}h {mp_m}m {mp_s}s" if mp_h > 0 else f"{mp_m}m {mp_s}s")
            header_text = re.sub(
                r"(;\s*model printing time:\s*)[\dhms\s]+(;)",
                r"\g<1>" + mp_str + r"\g<2>",
                header_text, count=1, flags=re.IGNORECASE
            )

    # Also update total layer number cumulatively (so the printer UI shows current/total correctly)
    if header_text:
        _layers_per_body = count_layers_in_body(first_job.sections.body)
        if _layers_per_body > 0:
            _total_all = _layers_per_body * total_copies
            header_text = re.sub(
                r"(;\s*total layer number:\s*)\d+",
                r"\g<1>" + str(_total_all),
                header_text, count=1, flags=re.IGNORECASE
            )

    if header_text:
        out.append(header_text)
        out.append("")
    if first_job.sections.config:
        out.append(first_job.sections.config)
        out.append("")

    # ---------- 2) Automation meta comment ----------
    out += [
        "; ##########################################################",
        "; #                                                        #",
        "; #   BambuLoop — Bambu Lab H2S auto-repeat-print G-code   #",
        "; #                                                        #",
        "; ##########################################################",
        f"; generated      : {datetime.now().isoformat(timespec='seconds')}",
        f"; job types      : {len(jobs)} model(s)",
        f"; total prints   : {total_copies}",
        ";",
        "; --- print job list ---",
    ]
    for idx, job in enumerate(jobs, start=1):
        out.append(
            f"; {idx:>2}. {job.filename:<40s}  × {job.count}  "
            f"(nozzle {job.temps.nozzle_initial}°C / bed {job.temps.bed_initial}°C / "
            f"{job.temps.filament_type} / height {job.temps.max_z_height:.1f}mm)"
        )
    out += [
        ";",
        "; --- automation settings ---",
        f"; cooling bed temp     : {settings.cooling_bed_temp}°C",
        f"; cooling chamber temp : {settings.cooling_chamber_temp}°C (0 = no wait)",
        f"; fans (P1/P2/P3)      : {'ON' if settings.part_fan_enabled else 'OFF'}/{settings.part_fan_speed}, "
        f"{'ON' if settings.aux_fan_enabled else 'OFF'}/{settings.aux_fan_speed}, "
        f"{'ON' if settings.chamber_fan_enabled else 'OFF'}/{settings.chamber_fan_speed}",
        f"; parking Z (min)      : {settings.cooling_park_z_min}mm + {settings.park_z_clearance}mm above print",
        f"; eject method         : {settings.eject_method} (X passes {settings.eject_passes})",
        f"; eject Z steps        : {settings.eject_descent_steps} step(s), descending to {settings.eject_z_offset}mm",
        f"; eject Z start clr    : {settings.eject_z_start_offset}mm above print",
        f"; eject speed          : {settings.eject_speed} mm/min",
        f"; rehome               : XY={settings.rehome_xy_between}, Z={settings.rehome_z_between}",
        f"; purge                : {settings.purge_between} ({settings.purge_length_mm} mm)",
        "; ##########################################################",
        "",
    ]

    # ---------- 3) START_GCODE (executed once, taken from the first job) ----------
    # Time info for M73 recalculation (applied to both start_gcode and body)
    body_time_sec = (parse_estimated_time_seconds(first_job.sections.header) or
                     parse_estimated_time_seconds(first_job.sections.body) or 0)
    if body_time_sec == 0:
        full_text = first_job.sections.start_gcode + "\n" + first_job.sections.body
        body_time_sec = parse_estimated_time_seconds(full_text) or 0
    post_print_sec = (settings.post_print_override_min * 60
                       if settings.post_print_override_min > 0
                       else estimate_post_print_seconds(settings, first_job.temps.max_z_height))

    start_gcode_processed = first_job.sections.start_gcode

    # Rewrite M73 progress — M73 inside start_gcode is treated as the start of body #1
    # (start_gcode = first print's heat/homing phase = beginning of body_idx=1)
    if body_time_sec > 0:
        start_gcode_processed = rewrite_m73_in_body(
            start_gcode_processed, body_idx=1, total_bodies=total_copies,
            body_time_sec=body_time_sec, post_print_sec=post_print_sec
        )

    if settings.sound_print_start:
        # User chose a start sound → replace the Bambu factory start-sound block
        custom_start_sound = generate_sound_event(
            settings.sound_print_start,
            label=f"initial print start [{settings.sound_print_start}]",
            include_motor_init=True,  # include M17 + M400 S1 (mirrors the Bambu block layout)
            custom_melodies=settings.custom_melodies,
        )
        if custom_start_sound:
            start_gcode_processed = replace_bambu_sound_block(
                start_gcode_processed, "start", custom_start_sound
            )

    out += [
        "; ----------------------------------------------------------",
        f"; {tr('init_seq', settings.lang)}",
        f";   start sound: {settings.sound_print_start or '(Bambu factory retained)'}",
        "; ----------------------------------------------------------",
        # M73 inside start_gcode is rewritten to match the start of body #1
        rewrite_m73_in_body(start_gcode_processed, 1, total_copies, body_time_sec, post_print_sec)
            if body_time_sec > 0 else start_gcode_processed,
        "",
    ]

    # ---------- 4) Body repetition ----------

    out += [
        "; ----------------------------------------------------------",
        "; [M73 progress recalc]",
        f";   original body est. : {body_time_sec}s ({body_time_sec//60}min {body_time_sec%60}s)",
        f";   POST_PRINT est.    : {post_print_sec}s ({post_print_sec//60}min {post_print_sec%60}s)",
        f";   total prints       : {total_copies}",
        f";   ★ overall BambuLoop: {body_time_sec * total_copies + post_print_sec * max(0, total_copies-1)}s "
        f"({(body_time_sec * total_copies + post_print_sec * max(0, total_copies-1))//60}min)",
        "; ----------------------------------------------------------",
        "",
    ]

    print_idx = 0
    for job_idx, job in enumerate(jobs):
        for copy_idx in range(1, job.count + 1):
            print_idx += 1
            is_last_print = (print_idx == total_copies)

            out += [
                "",
                "; ##########################################################",
                f"; ## Print #{print_idx}/{total_copies}  —  {job.filename}  ({copy_idx}/{job.count})",
                "; ##########################################################",
                "",
            ]

            # Insert body — rewrite M73 P/R and accumulate M73 L so the Bambu UI updates correctly
            # If each body went 1..N independently, the Bambu firmware would reject the decrease and the UI would freeze.
            # → Pass the cumulative value so the UI keeps updating.
            layers_per_body = count_layers_in_body(job.sections.body)
            body_layer_offset = (print_idx - 1) * layers_per_body
            body_with_m73 = rewrite_m73_in_body(
                job.sections.body, print_idx, total_copies,
                body_time_sec, post_print_sec,
                layer_offset=body_layer_offset,
            )
            out.append(body_with_m73)

            if not is_last_print:
                # Determine the next print's temperatures + flushing block (same job → self, otherwise next job)
                if copy_idx < job.count:
                    next_temps = job.temps
                    next_flushing = job.sections.flushing_block
                else:
                    next_job = jobs[job_idx + 1]
                    next_temps = next_job.temps
                    next_flushing = next_job.sections.flushing_block

                # Use the just-finished print's height for dynamic Z computation
                completed_max_z = job.temps.max_z_height

                # ── Event sound: print finished (just before cooling) ──
                sound_print_done = generate_sound_event(settings.sound_print_done, label=f"print finished [{settings.sound_print_done}]", custom_melodies=settings.custom_melodies, lang=settings.lang)

                out += [
                    "",
                    "; ----------------------------------------------------------",
                    f"; [POST-PRINT #{print_idx}] preparing next print",
                    f";   completed print height : {completed_max_z:.1f}mm (used for dynamic Z compute)",
                    f";   next print flushing    : {'Bambu standard block' if next_flushing else 'manual fallback'}",
                    "; ----------------------------------------------------------",
                    "",
                ]
                if sound_print_done:
                    out.append(sound_print_done)

                # M73 progress: cooling start
                m73_cool = make_post_print_m73_marks(print_idx, total_copies,
                                                       body_time_sec, post_print_sec, "cool")
                if m73_cool: out.append(m73_cool)

                out.append(generate_cooling_sequence(
                    settings, completed_max_z,
                    start_bed_temp=job.temps.bed_initial,
                ))

                # ── Event sound: cooling complete (just before eject) ──
                sound_cool = generate_sound_event(settings.sound_cool_done, label=f"cooling complete [{settings.sound_cool_done}]", custom_melodies=settings.custom_melodies, lang=settings.lang)
                if sound_cool:
                    out.append(sound_cool)

                # M73 progress: eject start
                m73_eject = make_post_print_m73_marks(print_idx, total_copies,
                                                       body_time_sec, post_print_sec, "eject")
                if m73_eject: out.append(m73_eject)

                out.append(generate_eject_sequence(settings, completed_max_z))

                # ── Event sound: sweep complete (just before reheat) ──
                sound_sweep = generate_sound_event(settings.sound_sweep_done, label=f"sweep complete [{settings.sound_sweep_done}]", custom_melodies=settings.custom_melodies, lang=settings.lang)
                if sound_sweep:
                    out.append(sound_sweep)

                # Pause after eject — user inspects the bed via the Handy app camera
                if settings.pause_after_eject:
                    out += [
                        "; ==========================================================",
                        "; [pause] post-eject inspection — verify the bed via the Bambu Handy camera, then resume",
                        ";   (H2S cannot trigger AI inspection from G-code, so manual verification is required)",
                        ";   to resume, press 'Resume' in Handy/Studio or on the printer screen",
                        "; ==========================================================",
                        "M400 U1                           ; ▶ Bambu pause (waits for user resume)",
                        "",
                    ]

                # M73 progress: reheat start
                m73_reheat = make_post_print_m73_marks(print_idx, total_copies,
                                                        body_time_sec, post_print_sec, "reheat")
                if m73_reheat: out.append(m73_reheat)

                out.append(generate_reheat_sequence(next_temps, settings))

                # M73 progress: reset start
                m73_reset = make_post_print_m73_marks(print_idx, total_copies,
                                                       body_time_sec, post_print_sec, "reset")
                if m73_reset: out.append(m73_reset)

                out.append(generate_reset_sequence(settings, next_temps, flushing_block=next_flushing))

                # ── Event sound: restart (just before next BODY) ──
                sound_restart = generate_sound_event(settings.sound_restart, label=f"print restart [{settings.sound_restart}]", custom_melodies=settings.custom_melodies, lang=settings.lang)
                if sound_restart:
                    out.append(sound_restart)
            else:
                # ── Final print: cool + eject sweep, then end_gcode terminates the file ──
                # AMS unload + parking are handled by the user's slicer end_gcode.
                completed_max_z = job.temps.max_z_height

                # Event sound: print finished (just before cooling)
                sound_print_done = generate_sound_event(settings.sound_print_done, label=f"print finished [{settings.sound_print_done}]", custom_melodies=settings.custom_melodies, lang=settings.lang)

                out += [
                    "",
                    "; ----------------------------------------------------------",
                    f"; [POST-PRINT #{print_idx} = final] cool + eject, then enter shutdown sequence",
                    f";   completed print height: {completed_max_z:.1f}mm",
                    f";   AMS unload / parking / chamber+bed OFF are handled by end_gcode",
                    "; ----------------------------------------------------------",
                    "",
                ]
                if sound_print_done:
                    out.append(sound_print_done)

                # M73 progress: cooling start
                m73_cool = make_post_print_m73_marks(print_idx, total_copies,
                                                       body_time_sec, post_print_sec, "cool")
                if m73_cool: out.append(m73_cool)

                out.append(generate_cooling_sequence(
                    settings, completed_max_z,
                    start_bed_temp=job.temps.bed_initial,
                ))

                # Event sound: cooling complete (just before eject)
                sound_cool = generate_sound_event(settings.sound_cool_done, label=f"cooling complete [{settings.sound_cool_done}]", custom_melodies=settings.custom_melodies, lang=settings.lang)
                if sound_cool:
                    out.append(sound_cool)

                # M73 progress: eject start
                m73_eject = make_post_print_m73_marks(print_idx, total_copies,
                                                       body_time_sec, post_print_sec, "eject")
                if m73_eject: out.append(m73_eject)

                out.append(generate_eject_sequence(settings, completed_max_z))

                # Event sound: sweep complete
                sound_sweep = generate_sound_event(settings.sound_sweep_done, label=f"sweep complete [{settings.sound_sweep_done}]", custom_melodies=settings.custom_melodies, lang=settings.lang)
                if sound_sweep:
                    out.append(sound_sweep)
                # Skip reheat/restart — no next print
                # The trailing end_gcode handles chamber/bed/fan OFF + AMS unload + parking + end sound

    # ---------- 5) END_GCODE (taken once from the last job) ----------
    end_gcode_processed = last_job.sections.end_gcode
    if settings.sound_print_end:
        custom_end_sound = generate_sound_event(
            settings.sound_print_end,
            label=f"all prints finished [{settings.sound_print_end}]",
            include_motor_init=True,
            custom_melodies=settings.custom_melodies,
        )
        if custom_end_sound:
            end_gcode_processed = replace_bambu_sound_block(
                end_gcode_processed, "finish", custom_end_sound
            )

    out += [
        "",
        "; ----------------------------------------------------------",
        f"; {tr('shutdown_seq', settings.lang)}",
        f";   end sound: {settings.sound_print_end or '(Bambu factory retained)'}",
        "; ----------------------------------------------------------",
        end_gcode_processed,
    ]

    return "\n".join(out)


# ============================================================
# Dry-run builder
# ============================================================

def build_dry_run_gcode(
    settings: AutomationSettings,
    simulated_print_height: float = 40.0,
    simulated_nozzle_temp: int = 220,
    simulated_bed_temp: int = 55,
    sample_parser: Optional["BambuGcodeParser"] = None,
    *,
    include_cooling: bool = True,
    wait_for_cooling: bool = True,
    include_eject: bool = True,
    include_reheat: bool = True,
    wait_for_reheat: bool = True,
    include_reset: bool = True,
    minimal_start: bool = False,
    skip_ams_load: bool = False,
    cycles: int = 1,
) -> str:
    """Build a dry-run G-code that exercises the automation sequences without real printing.

    Args:
        minimal_start: if True, skip the full Bambu Studio start sequence (levelling, flow cal,
                       resonance) and use a lightweight start sequence with homing + heat only.
                       Useful for quickly observing only the sweep behaviour.

    ...(other args follow the same shape)
    """
    out = []

    # 1) header / config
    if sample_parser is not None and sample_parser.sections.header:
        out += [
            sample_parser.sections.header,
            "",
            sample_parser.sections.config,
            "",
        ]
    else:
        out += [
            "; HEADER_BLOCK_START",
            "; BambuStudio (Dry-run, auto-generated)",
            "; total layer number: 0",
            f"; max_z_height: {simulated_print_height:.2f}",
            "; HEADER_BLOCK_END",
            "",
            "; CONFIG_BLOCK_START",
            "; nozzle_diameter = 0.4",
            "; printer_model = Bambu Lab H2S",
            "; printable_area = 0x0,340x0,340x320,0x320",
            "; printable_height = 340",
            "; gcode_flavor = marlin",
            "; use_relative_e_distances = 1",
            "; CONFIG_BLOCK_END",
            "",
        ]

    # 2) Automation meta + phase toggles
    out += [
        "; ##########################################################",
        "; #                                                        #",
        "; #   BambuLoop — DRY-RUN G-code (sequence verification only)   #",
        "; #                                                        #",
        "; ##########################################################",
        f"; generated         : {datetime.now().isoformat(timespec='seconds')}",
        f"; simulated print height : {simulated_print_height} mm",
        f"; simulated nozzle temp  : {simulated_nozzle_temp}°C",
        f"; simulated bed temp     : {simulated_bed_temp}°C",
        ";",
        "; --- included sequence phases ---",
        f"; [{'⚡' if minimal_start else '✓'}] start sequence       " +
        ("(minimal — homing + heat only, full calibration skipped)" if minimal_start else "(full Bambu start sequence)"),
        f"; [{'✓' if include_cooling else 'X'}] cooling sequence     " +
        (f"(wait: {'yes' if wait_for_cooling else 'no'})" if include_cooling else "(skipped)"),
        f"; [{'✓' if include_eject else 'X'}] eject (sweep) sequence" +
        ("(primary thing being verified)" if include_eject else "(skipped)"),
        f"; [{'✓' if include_reheat else 'X'}] reheat sequence      " +
        (f"(wait: {'yes' if wait_for_reheat else 'no'})" if include_reheat else "(skipped)"),
        f"; [{'✓' if include_reset else 'X'}] reset (re-home/purge)" +
        ("" if include_reset else "(skipped)"),
        ";",
        "; ⚠ This file does NOT print anything for real.",
        "; ⚠ It only verifies the automation sequences (cooling/eject/reheat).",
        "; ⚠ Run with the door open or with an empty bed.",
        "; ##########################################################",
        "",
    ]

    # 3) Start G-code — apply minimal_start + skip_ams_load filters
    start_removed_blocks: list[str] = []

    def _process_start_gcode(sg: str) -> str:
        """Apply minimal_start and skip_ams_load filters to the uploaded start_gcode."""
        processed = sg
        if minimal_start:
            processed, removed = strip_calibration_blocks(processed)
            start_removed_blocks.extend(removed)
        if skip_ams_load:
            processed, removed = strip_ams_load_blocks(processed)
            start_removed_blocks.extend(removed)
        return processed

    if (minimal_start or skip_ams_load) and sample_parser is not None and sample_parser.sections.start_gcode:
        processed_sg = _process_start_gcode(sample_parser.sections.start_gcode)
        flags = []
        if minimal_start:
            flags.append("MINIMAL START (calibration skipped)")
        if skip_ams_load:
            flags.append("SKIP AMS LOAD (filament load skipped)")
        out += [
            "; ============================================================",
            f"; [start sequence] filters applied: {', '.join(flags)}",
            f";   removed blocks: {', '.join(start_removed_blocks) if start_removed_blocks else '(individual lines only)'}",
            "; ============================================================",
            processed_sg,
            "",
        ]
    elif minimal_start or skip_ams_load:
        # No uploaded file — use the minimal start sequence
        out += [
            "; ============================================================",
            "; [start sequence] no uploaded file — basic homing + heat only",
            "; ============================================================",
            "M17",
            "M211 X0 Y0 Z0",
            "G90",
            "M83",
            f"M140 S{simulated_bed_temp}",
            f"M104 S{simulated_nozzle_temp}",
            "G28                               ; home all axes (including Z)",
        ]
        if wait_for_reheat:
            out += [
                f"M190 S{simulated_bed_temp}",
                f"M109 S{simulated_nozzle_temp}",
            ]
        else:
            out += ["G4 P3000"]
        out.append("")
    elif sample_parser is not None and sample_parser.sections.start_gcode:
        out += [
            "; ----- start sequence (uploaded file verbatim — full Bambu calibration) -----",
            sample_parser.sections.start_gcode,
            "",
        ]
    else:
        out += [
            "; ----- minimal start sequence (no upload, auto-generated) -----",
            "M73 P0 R0",
            "G90", "M83", "G28",
            f"M140 S{simulated_bed_temp}",
            f"M104 S{simulated_nozzle_temp}",
            f"M190 S{simulated_bed_temp}",
            f"M109 S{simulated_nozzle_temp}",
            "",
        ]

    # 4) Simulated print + automation sequences — repeat over n cycles
    cx = settings.bed_size_x // 2
    cy = settings.bed_size_y // 2
    total_cycles = max(1, min(int(cycles), 10))

    # The heat target may have been set high for flushing — fake_temps controls the next cycle
    fake_temps = PrintTemps(
        nozzle_initial=simulated_nozzle_temp,
        nozzle=simulated_nozzle_temp,
        bed_initial=simulated_bed_temp,
        bed=simulated_bed_temp,
        chamber=0,
        filament_type="DRY-RUN",
        max_z_height=simulated_print_height,
    )

    out += [
        "; ##########################################################",
        f"; ## [DRY-RUN] starting {total_cycles}-cycle loop",
        ";                 each cycle = [fake body] → [cool] → [eject] → [reheat] → [reset]",
        "; ##########################################################",
        "",
    ]

    # Flushing block from the uploaded file (not used when skip_ams_load=True)
    flushing = ""
    if sample_parser is not None and not skip_ams_load:
        flushing = sample_parser.sections.flushing_block

    for cycle_idx in range(1, total_cycles + 1):
        is_last_cycle = cycle_idx == total_cycles

        # 4a) Fake body
        out += [
            "",
            f"; ========== cycle {cycle_idx}/{total_cycles} ==========",
            generate_fake_body_gcode(cycle_idx, total_cycles),
        ]

        # 4b) Event sound: print finished
        sound_done = generate_sound_event(settings.sound_print_done, label=f"cycle {cycle_idx} print finished [{settings.sound_print_done}]", custom_melodies=settings.custom_melodies, lang=settings.lang)
        if sound_done:
            out.append(sound_done)

        # 4c) Cooling
        if include_cooling:
            out.append(generate_cooling_sequence(
                settings, simulated_print_height, skip_wait=not wait_for_cooling))
        else:
            out += ["; ----- cooling sequence skipped -----", "M104 S0", ""]

        # 4d) Event sound: cooling complete
        sound_cool = generate_sound_event(settings.sound_cool_done, label=f"cycle {cycle_idx} cooling complete [{settings.sound_cool_done}]", custom_melodies=settings.custom_melodies, lang=settings.lang)
        if sound_cool:
            out.append(sound_cool)

        # 4e) Eject (sweep) — can be skipped on the last cycle since there is nothing left to verify
        if include_eject:
            out.append(generate_eject_sequence(settings, simulated_print_height))
        else:
            out += ["; ----- eject sequence skipped -----", ""]

        # 4f) Event sound: sweep complete
        sound_sweep = generate_sound_event(settings.sound_sweep_done, label=f"cycle {cycle_idx} sweep complete [{settings.sound_sweep_done}]", custom_melodies=settings.custom_melodies, lang=settings.lang)
        if sound_sweep:
            out.append(sound_sweep)

        # Pause after eject
        if settings.pause_after_eject and include_eject:
            out += ["; pause for inspection", "M400 U1", ""]

        # No reheat/reset needed on the final cycle (it ends right after)
        if not is_last_cycle:
            # 4g) Reheat
            if include_reheat:
                out.append(generate_reheat_sequence(
                    fake_temps, settings, skip_wait=not wait_for_reheat))
            else:
                out += ["; ----- reheat sequence skipped -----", ""]

            # 4h) Reset (flushing + cleaning)
            if include_reset:
                out.append(generate_reset_sequence(settings, fake_temps, flushing_block=flushing))
            else:
                out += ["; ----- reset sequence skipped -----", ""]

            # 4i) Event sound: restart
            sound_restart = generate_sound_event(settings.sound_restart, label=f"cycle {cycle_idx + 1} start [{settings.sound_restart}]", custom_melodies=settings.custom_melodies, lang=settings.lang)
            if sound_restart:
                out.append(sound_restart)

    # 5) Shutdown sequence
    # skip_ams_load=True → simplified shutdown; otherwise keep the Bambu end sound
    out += [
        "",
        "; ##########################################################",
        "; ## [DRY-RUN] all cycles complete",
        "; ##########################################################",
    ]

    # A simple finish sound in place of the victory sound in Bambu's original end_gcode
    if skip_ams_load or sample_parser is None:
        # Simplified shutdown
        out += [
            "M104 S0                           ; nozzle OFF",
            "M140 S0                           ; bed OFF",
            "M141 S0                           ; chamber OFF",
            "M106 P1 S0", "M106 P2 S0", "M106 P3 S0",
            "G1 Z200 F1200                     ; lower bed",
            f"G1 X10 Y{settings.bed_size_y - 10} F9000  ; park at the left rear",
            "",
            generate_sound_event("victory", label="all prints finished (simplified shutdown)"),
            "",
            "M84                               ; steppers OFF",
            "; --- DRY-RUN complete ---",
        ]
    else:
        # Use the uploaded file's full end_gcode (preserves Bambu's original end sound)
        out += [
            "; [full shutdown sequence] reusing uploaded end_gcode (includes original Bambu end sound)",
            sample_parser.sections.end_gcode if sample_parser else "",
            "; --- DRY-RUN complete ---",
        ]

    return "\n".join(out)


# ============================================================
# .3mf repackaging (compatible with Bambu Studio / Handy upload)
# ============================================================

def repackage_3mf(
    source_3mf_path: str,
    combined_gcode: str,
    output_3mf_path: str,
    plate_name: str = "plate_1",
    unify_all_plates: bool = True,
) -> dict:
    """Build a new .3mf by replacing plate_N.gcode in the original .3mf with combined_gcode.

    v9+ behaviour (unify_all_plates=True):
        For .3mf files with multiple plates, **every plate is replaced with the same combined G-code**.
        Whichever plate the user selects in Bambu Studio, BambuLoop runs identically.
        Filament IDs are set to the union across all plates (supports multi-filament projects).

    Args:
        source_3mf_path: the uploaded original .3mf
        combined_gcode: the combined G-code to inject
        output_3mf_path: output .3mf path
        plate_name: base plate (source for bbox/thumbnail, defaults to plate_1)
        unify_all_plates: when True, every plate_N.* is unified with plate 1's metadata

    Returns:
        dict with md5, plate_targets, filament_ids_union, entries_copied
    """
    import zipfile, hashlib, json, re

    new_md5 = hashlib.md5(combined_gcode.encode("utf-8")).hexdigest().upper()
    combined_bytes = combined_gcode.encode("utf-8")

    # 1) Scan source — collect plate numbers and json contents
    plate_nums = []
    plate_jsons: dict[int, dict] = {}
    plate_pattern = re.compile(r"^Metadata/plate_(\d+)\.(gcode|json|png)$")
    small_png_pattern = re.compile(r"^Metadata/plate_(\d+)_small\.png$")
    thumb_png_patterns = [re.compile(r"^Metadata/top_(\d+)\.png$"),
                           re.compile(r"^Metadata/pick_(\d+)\.png$"),
                           re.compile(r"^Metadata/plate_no_light_(\d+)\.png$")]

    with zipfile.ZipFile(source_3mf_path, "r") as src:
        for name in src.namelist():
            m = plate_pattern.match(name)
            if m:
                num = int(m.group(1))
                if num not in plate_nums:
                    plate_nums.append(num)
                if m.group(2) == "json":
                    try:
                        with src.open(name) as f:
                            plate_jsons[num] = json.loads(f.read())
                    except Exception:
                        pass
        plate_nums.sort()

    # 2) Compute the union of filament_ids across all plates
    all_filament_ids: set[int] = set()
    for num, pj in plate_jsons.items():
        for fid in pj.get("filament_ids", []):
            all_filament_ids.add(int(fid))
    filament_ids_union = sorted(all_filament_ids)

    # 3) Base plate json (source of bbox etc.)
    base_plate_num = int(plate_name.replace("plate_", "")) if plate_name.startswith("plate_") else 1
    base_json = plate_jsons.get(base_plate_num, plate_jsons.get(1, {}))

    # 4) Build the unified json (filament_ids = union, everything else from base_json)
    unified_json = dict(base_json) if base_json else {}
    unified_json["filament_ids"] = filament_ids_union if filament_ids_union else [0]

    # 5) Write the new .3mf
    source_md5 = None
    entries_copied = 0
    plate_targets: list[str] = []

    with zipfile.ZipFile(source_3mf_path, "r") as src, \
         zipfile.ZipFile(output_3mf_path, "w", zipfile.ZIP_DEFLATED) as dst:

        # Record the MD5 of the source base plate
        try:
            with src.open(f"Metadata/plate_{base_plate_num}.gcode.md5") as f:
                source_md5 = f.read().decode("utf-8").strip()
        except KeyError:
            source_md5 = None

        # Cache the original thumbnail bytes (base plate's)
        thumbnail_cache: dict[str, bytes] = {}
        if unify_all_plates:
            for tmpl in [f"Metadata/plate_{base_plate_num}.png",
                         f"Metadata/plate_{base_plate_num}_small.png",
                         f"Metadata/top_{base_plate_num}.png",
                         f"Metadata/pick_{base_plate_num}.png",
                         f"Metadata/plate_no_light_{base_plate_num}.png"]:
                try:
                    with src.open(tmpl) as f:
                        thumbnail_cache[tmpl] = f.read()
                except KeyError:
                    pass

        for entry in src.infolist():
            name = entry.filename

            # plate_N.gcode → replaced with the combined G-code (every plate)
            pm = plate_pattern.match(name)
            if pm and pm.group(2) == "gcode":
                dst.writestr(name, combined_bytes)
                plate_targets.append(name)
                entries_copied += 1
                continue

            # plate_N.gcode.md5 → recomputed (every plate)
            if name.endswith(".gcode.md5") and "/plate_" in name:
                dst.writestr(name, new_md5)
                entries_copied += 1
                continue

            # plate_N.json → unified json when unify_all_plates is set (identical for every plate)
            # (this logic was verified to keep multi-plate timelapse working up to v26)
            if pm and pm.group(2) == "json" and unify_all_plates:
                dst.writestr(name, json.dumps(unified_json, separators=(",", ":")))
                entries_copied += 1
                continue

            # plate_N thumbnails → unified with the base plate thumbnail when unify_all_plates is set
            if unify_all_plates:
                replaced = False
                for tmpl_pattern in [plate_pattern, small_png_pattern] + thumb_png_patterns:
                    m = tmpl_pattern.match(name) if hasattr(tmpl_pattern, 'match') else None
                    if m:
                        # Replace another plate's thumbnail with the base plate's
                        # Determine the base path
                        if name.endswith(".png"):
                            if "_small.png" in name:
                                src_name = f"Metadata/plate_{base_plate_num}_small.png"
                            elif "plate_no_light_" in name:
                                src_name = f"Metadata/plate_no_light_{base_plate_num}.png"
                            elif name.startswith("Metadata/top_"):
                                src_name = f"Metadata/top_{base_plate_num}.png"
                            elif name.startswith("Metadata/pick_"):
                                src_name = f"Metadata/pick_{base_plate_num}.png"
                            elif name.startswith("Metadata/plate_") and "_small" not in name:
                                src_name = f"Metadata/plate_{base_plate_num}.png"
                            else:
                                src_name = None
                            if src_name and src_name in thumbnail_cache:
                                dst.writestr(name, thumbnail_cache[src_name])
                                entries_copied += 1
                                replaced = True
                                break
                if replaced:
                    continue

            # All other entries are copied verbatim
            with src.open(entry) as f:
                dst.writestr(entry, f.read())
            entries_copied += 1

        # Add an md5 entry if the base plate did not have one
        if source_md5 is None and plate_targets:
            first_plate = plate_targets[0].replace(".gcode", ".gcode.md5")
            dst.writestr(first_plate, new_md5)
            entries_copied += 1

    return {
        "source_md5": source_md5,
        "new_md5": new_md5,
        "plate_target": plate_name,
        "plate_targets": plate_targets,
        "filament_ids_union": filament_ids_union,
        "total_plates": len(plate_nums),
        "entries_copied": entries_copied,
        "new_gcode_bytes": len(combined_bytes),
        "unified": unify_all_plates,
    }


# ============================================================
# Dry-run start_gcode filter — strip leveling / flow cal / resonance / filament priming
# Z homing and AMS load are preserved
# ============================================================

def strip_calibration_blocks(start_gcode: str) -> tuple[str, list[str]]:
    """Strip blocks from a Bambu H2S start_gcode that are safe to skip during a dry-run.

    Kept:
        - G28 (all-axis homing — Z homing included, required)
        - M140 / M104 / M141 / M190 / M109 / M191 (heat / wait)
        - T0 / M620 / M621 (AMS load/unload — required for AMS recognition after .3mf repackaging)
        - Fan control, soft endstop release, and other basic setup

    Removed:
        - Auto-levelling (G29, G29.xx blocks)
        - Flow calibration (M983.3 extrude cali, auto extrude cali blocks)
        - Resonance calibration (M970.x, M974 — mech mode sweep blocks)
        - Filament priming (nozzle load line, the E20 extrusion onto the bed)
        - Bed-type detection / foreign-object detection (M972.xx)
        - Nozzle wipe (wipe right/left nozzle blocks — repeated G150 calls)

    Returns:
        (filtered_start_gcode, removed_blocks_list)
    """
    import re

    # Bambu H2S start_gcode uses "; ===== xxx start =====" ~ "; ===== xxx end =====" markers
    # Each (start, end) marker pair removes the entire block (start line through end line)
    block_markers = [
        ("detection",            "===== detection start =====",         "===== detection end ====="),
        ("auto extrude cali",    "===== auto extrude cali start =====", "===== auto extrude cali end ====="),
        ("bed leveling",         "===== bed leveling ====",             "===== bed leveling end ===="),
        ("mech mode sweep",      "===== mech mode sweep start =====",   "===== mech mode sweep end ====="),
        ("wipe nozzle",          "===== wipe right nozzle start =====", "===== wipe left nozzle end ====="),
        ("nozzle load line",     "===== nozzle load line ====",         "===== noozle load line end ===="),
    ]

    # Strip stray calibration lines that live outside any block
    line_skip_patterns = [
        re.compile(r"^\s*M970\.\d+\b"),              # resonance parameter measurement
        re.compile(r"^\s*M970\b"),
        re.compile(r"^\s*M974\b"),                   # resonance measurement run
        re.compile(r"^\s*M975\b"),                   # input shaping on/off
        re.compile(r"^\s*M982\.2\b"),                # cog noise reduction
        re.compile(r"^\s*M983\.[134]\b"),            # flow / deformation cal
        re.compile(r"^\s*G29\.\d+\b"),               # auto-leveling sub-steps
        re.compile(r"^\s*G29\b"),                    # auto-leveling
        re.compile(r"^\s*G28\.14\d*\b"),             # pre-extrude Z calibration
        re.compile(r"^\s*M1002\s+judge_flag\s+g29"),
        re.compile(r"^\s*M1002\s+judge_flag\s+extrude_cali"),
        re.compile(r"^\s*M1002\s+judge_flag\s+build_plate_detect"),
        re.compile(r"^\s*M972\b"),                   # bed / foreign-object detection
        re.compile(r"^\s*M1028\b"),                  # detection-related
        re.compile(r"^\s*M562\b"),                   # detection-related
        re.compile(r"^\s*M1009\b"),                  # detection anti-collision
        re.compile(r"^\s*M620\.6\b"),                # AMS air-print detect (post-priming)
        re.compile(r"^\s*M1015\.[34]\b"),            # air / TPU detection
        re.compile(r"^\s*M1026\b"),                  # detection
        re.compile(r"^\s*M500\b"),                   # save settings
    ]

    lines = start_gcode.split("\n")
    output: list[str] = []
    removed: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect block start
        matched = None
        for name, start_marker, end_marker in block_markers:
            if start_marker in line:
                matched = (name, end_marker)
                break

        if matched:
            name, end_marker = matched
            output.append(f"; [MINIMAL START] block '{name}' skipped (user option — dry-run)")
            removed.append(name)
            j = i + 1
            while j < len(lines) and end_marker not in lines[j]:
                j += 1
            i = j + 1   # also skip the end_marker line
            continue

        # Individual line filter
        skip = False
        for pat in line_skip_patterns:
            if pat.match(line):
                skip = True
                output.append(f"; [MINIMAL] skipped: {line.strip()}")
                break
        if not skip:
            output.append(line)
        i += 1

    return "\n".join(output), removed


# ============================================================
# Sound alerts (M1006) — Bambu stepper-motor tones
# ============================================================
# Bambu's M1006 produces tones by PWM-vibrating the stepper motors.
# Verified empirically (on H2S):
#   - A value (G-code encoding) = musical MIDI - 23
#     verified: A53 (G-code) → E5 (MIDI 76) — compared by ear with a piano
#   - Audible range: musical MIDI 60~90 (C4 ~ F#6, about 2.5 octaves)
#   - L=99 is the Bambu standard volume (matches the factory start sound)
#   - B=10 ≈ 0.1s (measured)
#   - Sequence: M17 → M400 S1 → M1006 S1 → notes → M1006 W
#
# Presets are written in musical MIDI (easier to read).
# generate_sound_event() applies the -23 offset automatically when emitting G-code.
#
# MIDI reference:
#   C4=60 (middle C), D4=62, E4=64, F4=65, G4=67, A4=69, B4=71
#   C5=72, D5=74, E5=76, F5=77, G5=79, A5=81, B5=83
#   C6=84, D6=86, E6=88, F6=89, F#6=90 (upper limit)

PITCH_OFFSET = 23   # G-code A value = musical MIDI - 23
VOL = 99            # Bambu standard volume
MIN_DUR = 10        # B=10 ≈ 0.1s

# Preset format: notes = [(musical_MIDI, B duration), ...]
# A single tone is sent on all 3 channels for a fuller sound (Bambu default style)
# A rest is (0, dur) — all channels muted

PRESET_PATTERNS: dict[str, dict] = {

    # ────────── 🔬 Verification (2) ──────────
    "bambu_default_start": {
        "desc": {"ko": "Bambu 기본 시작음 (E5-G5-C6 x2)", "en": "Bambu default start (E5-G5-C6 x2)"},
        "notes": [(76, 10), (79, 10), (84, 10),
                  (76, 10), (79, 10), (84, 20)],
    },
    "do_re_mi": {
        "desc": {"ko": "도-레-미-파-솔-라-시-도 (8음, 약 1초)", "en": "Do-Re-Mi-Fa-Sol-La-Ti-Do (8 notes, ~1s)"},
        "notes": [(72, 12), (74, 12), (76, 12), (77, 12),
                  (79, 12), (81, 12), (83, 12), (84, 20)],
    },

    # ────────── 🔔 Notifications (7) ──────────
    "beep_single":  {"desc": {"ko": "C5 단음 (0.2초)", "en": "C5 single beep (0.2s)"},       "notes": [(72, 20)]},
    "beep_double":  {"desc": {"ko": "C5 두 번 (0.5초)", "en": "C5 two beeps (0.5s)"},      "notes": [(72, 15), (0, 10), (72, 20)]},
    "beep_triple":  {"desc": {"ko": "C5 세 번 (0.7초)", "en": "C5 triple beep (0.7s)"},      "notes": [(72, 12), (0, 8), (72, 12), (0, 8), (72, 20)]},
    "chime_high":   {"desc": {"ko": "C6 차임 (0.5초)", "en": "C6 high chime (0.5s)"},       "notes": [(84, 20), (0, 10), (84, 25)]},
    "chime_low":    {"desc": {"ko": "C4 차임 (0.5초)", "en": "C4 low chime (0.5s)"},       "notes": [(60, 20), (0, 10), (60, 25)]},
    "knock":        {"desc": {"ko": "G4 노크 (0.4초)", "en": "G4 knock (0.4s)"},       "notes": [(67, 15), (0, 10), (67, 20)]},
    "ping_sharp":   {"desc": {"ko": "D6 핑 (0.2초)", "en": "D6 sharp ping (0.2s)"},         "notes": [(86, 20)]},

    # ────────── ⬆️ Ascending (5) ──────────
    "ascend_major":     {"desc": {"ko": "C5-E5-G5 상승 (0.4초)", "en": "C5-E5-G5 ascending (0.4s)"},      "notes": [(72, 12), (76, 12), (79, 20)]},
    "ascend_minor":     {"desc": {"ko": "A4-C5-E5 단조 상승 (0.4초)", "en": "A4-C5-E5 minor ascending (0.4s)"}, "notes": [(69, 12), (72, 12), (76, 20)]},
    "ascend_fifth":     {"desc": {"ko": "C5-G5 5도 (0.3초)", "en": "C5-G5 fifth (0.3s)"},          "notes": [(72, 12), (79, 20)]},
    "ascend_octave":    {"desc": {"ko": "C5-C6 옥타브 (0.3초)", "en": "C5-C6 octave (0.3s)"},       "notes": [(72, 12), (84, 20)]},
    "ascend_chromatic": {"desc": {"ko": "C5-D5-E5 짧은 상승 (0.4초)", "en": "C5-D5-E5 short ascending (0.4s)"}, "notes": [(72, 12), (74, 12), (76, 20)]},

    # ────────── ⬇️ Descending (4) ──────────
    "descend_major":     {"desc": {"ko": "G5-E5-C5 하강 (0.4초)", "en": "G5-E5-C5 descending (0.4s)"}, "notes": [(79, 12), (76, 12), (72, 20)]},
    "descend_fifth":     {"desc": {"ko": "G5-C5 5도 하강 (0.3초)", "en": "G5-C5 fifth descending (0.3s)"}, "notes": [(79, 12), (72, 20)]},
    "descend_chromatic": {"desc": {"ko": "E5-D5-C5 짧은 하강 (0.4초)", "en": "E5-D5-C5 short descending (0.4s)"}, "notes": [(76, 12), (74, 12), (72, 20)]},
    "sigh":              {"desc": {"ko": "E5-D5 한숨 (0.3초)", "en": "E5-D5 sigh (0.3s)"}, "notes": [(76, 12), (74, 20)]},

    # ────────── 🎺 Fanfares (9) ──────────
    "fanfare_short":   {"desc": {"ko": "C5-E5-G5-C6 팡파레 (0.5초)", "en": "C5-E5-G5-C6 fanfare (0.5s)"}, "notes": [(72, 10), (76, 10), (79, 10), (84, 20)]},
    "fanfare_trumpet": {"desc": {"ko": "G4×3-C5 트럼펫 (0.6초)", "en": "G4×3-C5 trumpet fanfare (0.6s)"}, "notes": [(67, 10), (0, 5), (67, 10), (0, 5), (67, 10), (72, 20)]},
    "victory":         {"desc": {"ko": "C5-E5-G5-C6 승리 (0.5초)", "en": "C5-E5-G5-C6 victory (0.5s)"}, "notes": [(72, 10), (76, 10), (79, 12), (84, 20)]},
    "ta_da":           {"desc": {"ko": "G5-C6 짠! (0.4초)", "en": "G5-C6 ta-da! (0.4s)"}, "notes": [(79, 15), (84, 25)]},
    "royal":           {"desc": {"ko": "C5-G5-C6 왕실 (E6 제거, 0.4초)", "en": "C5-G5-C6 royal (E6 removed, 0.4s)"}, "notes": [(72, 10), (79, 12), (84, 20)]},
    "cavalry_short":   {"desc": {"ko": "G4-C5-E5-G5 기병 (0.5초)", "en": "G4-C5-E5-G5 cavalry call (0.5s)"}, "notes": [(67, 10), (72, 10), (76, 12), (79, 20)]},
    "triumph":         {"desc": {"ko": "C5-E5-C5-G5-C6 승전 (0.6초)", "en": "C5-E5-C5-G5-C6 triumph (0.6s)"}, "notes": [(72, 10), (76, 10), (72, 10), (79, 12), (84, 20)]},
    "wedding":         {"desc": {"ko": "G4-C5-E5-G5 웨딩 (0.5초)", "en": "G4-C5-E5-G5 wedding intro (0.5s)"}, "notes": [(67, 10), (72, 10), (76, 12), (79, 20)]},
    "sunrise":         {"desc": {"ko": "C5-E5-G5-B5-C6 일출 (0.6초)", "en": "C5-E5-G5-B5-C6 sunrise (0.6s)"}, "notes": [(72, 10), (76, 10), (79, 10), (83, 12), (84, 20)]},

    # ────────── 🎵 Melodies (10) ──────────
    "mario_coin":      {"desc": {"ko": "B5-D6 코인 (0.3초)", "en": "B5-D6 coin (0.3s)"}, "notes": [(83, 10), (86, 20)]},
    "door_chime":      {"desc": {"ko": "E5-C5-G4-C5 초인종 (0.7초)", "en": "E5-C5-G4-C5 doorbell (0.7s)"}, "notes": [(76, 15), (72, 15), (67, 15), (72, 25)]},
    "nokia_bit":       {"desc": {"ko": "E5-D5-C5-D5 노키아풍 (0.5초)", "en": "E5-D5-C5-D5 Nokia-like (0.5s)"}, "notes": [(76, 12), (74, 12), (72, 12), (74, 18)]},
    "windows_startup": {"desc": {"ko": "C5-E5-G5 부드러운 시작 (0.5초)", "en": "C5-E5-G5 soft startup (0.5s)"}, "notes": [(72, 15), (76, 15), (79, 25)]},
    "mac_startup":     {"desc": {"ko": "C4-G4-C5-E5-G5-C6 Mac풍 (0.7초)", "en": "C4-G4-C5-E5-G5-C6 Mac-like (0.7s)"}, "notes": [(60, 12), (67, 12), (72, 12), (76, 12), (79, 12), (84, 20)]},
    "zelda_item":      {"desc": {"ko": "C5-E5-G5-C6 아이템 획득 (0.5초)", "en": "C5-E5-G5-C6 item get (0.5s)"}, "notes": [(72, 10), (76, 10), (79, 10), (84, 20)]},
    "pokemon_heal":    {"desc": {"ko": "G4-C5-E5 회복 (0.4초)", "en": "G4-C5-E5 heal (0.4s)"}, "notes": [(67, 12), (72, 12), (76, 20)]},
    "level_up":        {"desc": {"ko": "C5-E5-G5-B5-C6 레벨업 (0.6초)", "en": "C5-E5-G5-B5-C6 level up (0.6s)"}, "notes": [(72, 10), (76, 10), (79, 10), (83, 10), (84, 20)]},
    "morse_v":         {"desc": {"ko": "C5 ···— 모스 V (0.7초)", "en": "C5 ···— Morse V (0.7s)"}, "notes": [(72, 8), (0, 6), (72, 8), (0, 6), (72, 8), (0, 6), (72, 25)]},
    "tetris_line":     {"desc": {"ko": "E5-B4-C5-D5 테트리스풍 (0.6초)", "en": "E5-B4-C5-D5 Tetris-like (0.6s)"}, "notes": [(76, 15), (71, 15), (72, 15), (74, 20)]},

    # ────────── 🎼 Moods (11) ──────────
    "question":   {"desc": {"ko": "C5-G5 의문형 (0.4초)", "en": "C5-G5 questioning rise (0.4s)"}, "notes": [(72, 15), (79, 25)]},
    "gentle":     {"desc": {"ko": "E5-G5 부드러움 (0.4초)", "en": "E5-G5 gentle (0.4s)"}, "notes": [(76, 15), (79, 25)]},
    "melancholy": {"desc": {"ko": "A4-G4-E4 우울 (0.6초)", "en": "A4-G4-E4 melancholy (0.6s)"}, "notes": [(69, 15), (67, 15), (64, 30)]},
    "mysterious": {"desc": {"ko": "D5-F5-A5 신비 D단조 (0.5초)", "en": "D5-F5-A5 mysterious D minor (0.5s)"}, "notes": [(74, 15), (77, 15), (81, 25)]},
    "calm":       {"desc": {"ko": "G4-B4-D5 평온 G장조 (0.5초)", "en": "G4-B4-D5 calm G major (0.5s)"}, "notes": [(67, 15), (71, 15), (74, 25)]},
    "playful":    {"desc": {"ko": "C5-E5-C5-G5 장난 (0.5초)", "en": "C5-E5-C5-G5 playful (0.5s)"}, "notes": [(72, 10), (76, 10), (72, 10), (79, 20)]},
    "dreamy":     {"desc": {"ko": "C5-F5-A5 꿈꾸는 듯 Fmaj (0.5초)", "en": "C5-F5-A5 dreamy F major (0.5s)"}, "notes": [(72, 15), (77, 15), (81, 25)]},
    "heroic":     {"desc": {"ko": "C5-G5-C6 영웅 (0.6초)", "en": "C5-G5-C6 heroic (0.6s)"}, "notes": [(72, 15), (79, 15), (84, 30)]},
    "tense":      {"desc": {"ko": "C5-C#5 트릴 긴장 (0.5초)", "en": "C5-C#5 trill tension (0.5s)"}, "notes": [(72, 10), (73, 10), (72, 10), (73, 20)]},
    "warm":       {"desc": {"ko": "F4-A4-C5 따뜻함 Fmaj (0.5초)", "en": "F4-A4-C5 warm F major (0.5s)"}, "notes": [(65, 15), (69, 15), (72, 25)]},
    "serene":     {"desc": {"ko": "D5-A5 고요함 5도 (0.5초)", "en": "D5-A5 serene fifth (0.5s)"}, "notes": [(74, 20), (81, 30)]},

    # ────────── 🎨 Custom (13) ──────────
    "lg_appliance_jingle": {
        "desc": {"ko": "LG 가전 종료 멜로디 (약 8.5초)", "en": "LG appliance end jingle (~8.5s)"},
        "notes": [(79, 35), (0, 10), (84, 20), (83, 20), (81, 20), (79, 30), (0, 20),
                  (76, 30), (0, 30), (77, 20), (79, 20), (81, 20), (74, 20), (76, 20),
                  (77, 20), (76, 30), (0, 25), (79, 35), (0, 30), (79, 35), (0, 10),
                  (84, 20), (83, 20), (81, 20), (79, 30), (0, 20), (84, 30), (0, 30),
                  (84, 20), (86, 20), (84, 20), (83, 20), (81, 20), (83, 20), (84, 60)],
    },
    "tetris_theme": {
        "desc": {"ko": "테트리스 메인 테마 (Korobeiniki, 약 12초)", "en": "Tetris main theme (Korobeiniki, ~12s)"},
        "notes": [(71, 20), (0, 20), (71, 20), (72, 20), (74, 20), (0, 20), (72, 20),
                  (71, 20), (69, 20), (0, 20), (69, 20), (72, 20), (76, 20), (0, 20),
                  (74, 20), (72, 20), (71, 20), (0, 20), (71, 20), (72, 20), (74, 20),
                  (0, 20), (76, 20), (0, 20), (72, 20), (0, 20), (69, 20), (0, 20),
                  (69, 20), (0, 20), (0, 20), (0, 20), (74, 20), (0, 20), (74, 20),
                  (77, 20), (81, 20), (0, 20), (79, 20), (77, 20), (76, 20), (0, 20),
                  (72, 20), (74, 20), (76, 20), (77, 10), (76, 10), (74, 20), (72, 20),
                  (71, 20), (0, 20), (71, 20), (72, 20), (74, 20), (0, 20), (76, 20),
                  (0, 20), (72, 20), (0, 20), (69, 20), (0, 20), (69, 20)],
    },
    "still_alive": {
        "desc": {"ko": "Portal 'Still Alive' 멜로디 (긴 곡)", "en": "Portal 'Still Alive' melody (long)"},
        "notes": [(79, 30), (78, 30), (76, 30), (76, 30), (78, 30), (0, 80), (0, 80),
                  (0, 80), (74, 30), (79, 30), (78, 30), (76, 30), (76, 30), (0, 30),
                  (0, 30), (0, 10), (78, 30), (74, 30), (0, 30), (0, 30), (76, 30),
                  (69, 30), (0, 60), (0, 60), (0, 60), (69, 30), (0, 30), (0, 30),
                  (76, 30), (0, 30), (78, 30), (79, 30), (0, 30), (76, 30), (0, 30),
                  (0, 30), (73, 30), (0, 30), (74, 30), (76, 30), (0, 30), (69, 30),
                  (0, 30), (69, 40), (0, 20), (78, 30), (0, 80), (0, 80), (0, 80),
                  (79, 30), (78, 30), (76, 30), (76, 30), (78, 30), (0, 80), (0, 80),
                  (0, 80), (74, 30), (79, 30), (78, 30), (76, 30), (76, 30), (0, 30),
                  (0, 30), (0, 10), (78, 30), (74, 30), (0, 30), (0, 30), (76, 30),
                  (69, 30), (0, 60), (0, 60), (0, 60), (69, 30), (0, 30), (0, 30),
                  (76, 30), (0, 30), (78, 30), (79, 30), (0, 30), (76, 30), (0, 30),
                  (0, 30), (73, 30), (0, 30), (74, 30), (76, 30), (0, 30), (69, 30),
                  (74, 30), (76, 30), (77, 30), (76, 30), (74, 30), (72, 30), (0, 30),
                  (0, 30), (69, 30), (70, 30), (72, 30), (0, 30), (77, 30), (0, 30),
                  (76, 30), (74, 30), (74, 30), (72, 30), (74, 30), (72, 30), (72, 30),
                  (69, 30), (72, 30), (0, 30), (69, 30), (70, 30), (72, 30), (0, 30),
                  (77, 30), (0, 30), (79, 30), (77, 30), (76, 30), (74, 30), (74, 30),
                  (76, 30), (77, 30), (0, 30), (77, 30), (0, 30), (79, 30), (81, 30),
                  (82, 30), (82, 30), (81, 30), (79, 30), (79, 30), (0, 30), (77, 30),
                  (79, 30), (81, 30), (81, 30), (79, 30), (77, 30), (77, 30), (0, 30),
                  (74, 30), (72, 30), (74, 30), (77, 30), (77, 30), (76, 30), (0, 30),
                  (76, 30), (78, 30), (78, 30)],
    },
    "trumpet_signal":     {"desc": {"ko": "G5-A5-B5 트럼펫 신호 (약 2초)", "en": "G5-A5-B5 trumpet signal (~2s)"}, "notes": [(79, 30), (79, 10), (79, 30), (0, 10), (81, 20), (79, 20), (81, 20), (83, 30), (83, 10), (83, 30)]},
    "done_ascend":        {"desc": {"ko": "C5-E5-G5-C6 짧은 완료 (약 0.9초)", "en": "C5-E5-G5-C6 short completion (~0.9s)"}, "notes": [(76, 10), (72, 10), (76, 10), (79, 10), (84, 20), (84, 10), (84, 20)]},
    "done_scale_jump":    {"desc": {"ko": "F5-G5-A5 → C5-C6 완료 (약 1.1초)", "en": "F5-G5-A5 → C5-C6 completion (~1.1s)"}, "notes": [(77, 10), (79, 10), (81, 10), (77, 10), (79, 10), (81, 10), (76, 20), (0, 10), (84, 20)]},
    "done_chord_slow":    {"desc": {"ko": "C5-E5-G5-C6 느린 완료 (약 1초)", "en": "C5-E5-G5-C6 slow completion (~1s)"}, "notes": [(76, 20), (72, 20), (76, 20), (79, 20), (84, 20)]},
    "done_arpeggio_burst": {"desc": {"ko": "G5-A5-B5-D6-C6 느림→빠름 완료 (약 2초)", "en": "G5-A5-B5-D6-C6 slow→fast completion (~2s)"}, "notes": [(79, 25), (81, 25), (83, 25), (86, 25), (84, 25), (79, 10), (81, 10), (83, 10), (84, 10), (79, 10), (81, 10), (83, 10), (84, 10)]},
    "warning_chromatic":  {"desc": {"ko": "E5-Eb5-D5 반음 반복 경고 (약 1.5초)", "en": "E5-Eb5-D5 chromatic warning loop (~1.5s)"}, "notes": [(76, 10), (75, 10), (74, 10), (76, 10), (75, 10), (74, 10), (76, 10), (75, 10), (74, 10), (76, 10), (75, 10), (74, 10), (76, 10), (75, 10), (74, 15)]},
    "done_double_ascend": {"desc": {"ko": "C5-E5-G5-C6 + 빠른 반복 (약 1.6초)", "en": "C5-E5-G5-C6 + quick repeat (~1.6s)"}, "notes": [(76, 20), (72, 20), (76, 20), (79, 20), (84, 20), (72, 10), (76, 10), (79, 10), (84, 15)]},
    "done_major7":        {"desc": {"ko": "G5-A5-B5-D6-C6 메이저7 완료 (약 1.1초)", "en": "G5-A5-B5-D6-C6 major-7 completion (~1.1s)"}, "notes": [(79, 20), (81, 20), (83, 20), (86, 20), (84, 30)]},
    "alarm_alternate":    {"desc": {"ko": "D6-A5 교대 경보음 (약 6초)", "en": "D6-A5 alternating alarm (~6s)"}, "notes": [(86, 20), (81, 20), (0, 20), (86, 20), (81, 20), (0, 20), (86, 20), (81, 20), (0, 20), (86, 20), (81, 20), (0, 20), (86, 20), (81, 25), (0, 20), (86, 20), (81, 20), (0, 20), (86, 20), (81, 20), (0, 20), (86, 20), (81, 20), (0, 20), (86, 20), (81, 20), (0, 20), (86, 20), (81, 20)]},
    "trumpet_finish":     {"desc": {"ko": "G5-A5-B5 트럼펫 피날레 (약 1.7초)", "en": "G5-A5-B5 trumpet finale (~1.7s)"}, "notes": [(79, 15), (0, 10), (79, 10), (79, 20), (0, 20), (81, 20), (79, 20), (81, 20), (83, 15), (0, 10), (83, 10), (83, 20)]},
}


def _to_gcode_note(musical_midi: int) -> int:
    """Convert musical MIDI to a Bambu G-code A value (apply the -23 offset)."""
    if musical_midi == 0:
        return 0
    return max(0, musical_midi - PITCH_OFFSET)


def generate_sound_event(preset_name: str, *, label: str = "",
                          include_motor_init: bool = True,
                          custom_melodies: dict = None,
                          lang: str = "ko") -> str:
    """Build an M1006 command sequence (Bambu stepper-motor tones).

    Musical MIDI values from the preset are automatically converted to G-code A values (-23 offset).

    Args:
        preset_name: a key in PRESET_PATTERNS or in custom_melodies
        label: G-code comment label
        include_motor_init: when True, emit M17 + M400 S1 (motor ON + stabilize)
        custom_melodies: user-defined melodies dict {"<name>": [[midi, dur], ...]}
            If preset_name is not in PRESET_PATTERNS, it is looked up here

    Returns:
        G-code string. Empty string if the preset is not found anywhere.
    """
    notes = None
    desc = ""
    is_custom = False

    if preset_name in PRESET_PATTERNS:
        preset = PRESET_PATTERNS[preset_name]
        notes = preset["notes"]
        raw_desc = preset.get("desc", "")
        # desc may be a {ko, en} dict or a plain str (legacy compat).
        # G-code output is English-only by policy, so prefer the English entry.
        if isinstance(raw_desc, dict):
            desc = raw_desc.get("en") or raw_desc.get("ko", "")
        else:
            desc = raw_desc
    elif custom_melodies and preset_name in custom_melodies:
        notes = custom_melodies[preset_name]
        desc = "(Custom melody)"
        is_custom = True

    if not notes:
        return ""

    lines = [
        f"; [SOUND] {label or preset_name} — {desc}",
    ]

    if include_motor_init:
        lines += [
            "M17                               ; steppers ON",
            "M400 S1                           ; 1s stabilize",
        ]

    lines.append("M1006 S1                          ; sound mode init")

    for musical_note, dur in notes:
        d = max(MIN_DUR, dur) if musical_note != 0 else dur
        if musical_note == 0:
            # rest: emit all 3 channels (same channel layout as tone output)
            # Avoid the bug where motor C keeps playing the previous tone if its channel is omitted
            lines.append(f"M1006 A0 B{d} L0 C0 D{d} M0 E0 F{d} N0   ; rest")
        else:
            gcode_note = _to_gcode_note(musical_note)
            lines.append(
                f"M1006 A{gcode_note} B{d} L{VOL} C{gcode_note} D{d} M{VOL} E{gcode_note} F{d} N{VOL}"
            )

    lines.append("M1006 W                           ; play")
    return "\n".join(lines)


def generate_sound_catalog_gcode(mode: str = "all",
                                   custom_melodies: dict = None,
                                   lang: str = "ko") -> str:
    """Build a sound-preset catalog G-code.

    Args:
        mode: "all" (every preset + customs), "builtin" (built-ins only), "custom" (customs only)
        custom_melodies: {"<name>": [[midi, dur], ...], ...}
        lang: 'ko' | 'en' — accepted for API compatibility; G-code output is always English
    """
    custom_melodies = custom_melodies or {}

    # Determine the items to play
    items: list[tuple[str, dict, bool]] = []  # (name, preset_dict, is_custom)
    if mode in ("all", "builtin"):
        for name, preset in PRESET_PATTERNS.items():
            items.append((name, preset, False))
    if mode in ("all", "custom"):
        custom_desc = "Custom melody"
        for name, notes in custom_melodies.items():
            items.append((name, {"desc": custom_desc, "notes": notes}, True))

    if not items:
        empty_msg = "; (No presets to play)\n"
        return empty_msg

    # Catalog labels (G-code comments → English only)
    title       = "BambuLoop — Sound Preset Catalog"
    mode_lbl    = f"Mode: {mode} ({len(items)} items)"
    interval    = "2-second pause between presets"
    settings_lbl = (f"Volume L={VOL}, min duration B={MIN_DUR} (~0.1s), MIDI offset -{PITCH_OFFSET}"
                    if lang == "en"
                    else f"Settings: volume L={VOL}, min duration B={MIN_DUR} (≈0.1s), MIDI offset -{PITCH_OFFSET}")
    motor_on    = "Steppers ON"
    stab        = "2s stabilize"
    wait_play   = "Wait for playback"
    pause_lbl   = "2s pause"
    motor_off   = "Steppers OFF"
    end_lbl     = "=== Catalog End ==="

    out = [
        "; ============================================================",
        f"; {title}",
        f";   {mode_lbl}",
        f";   {interval}",
        f";   {settings_lbl}",
        "; ============================================================",
        "",
        f"M17                               ; {motor_on}",
        f"M400 S2                           ; {stab}",
        "",
    ]

    for i, (name, preset, is_custom) in enumerate(items, 1):
        marker = "★" if is_custom else "  "
        out += [
            f"; ============ {marker} {i}/{len(items)}: {name} ============",
            f"M73 P{int(i * 100 / len(items))} R{max(0, (len(items) - i) * 3 // 60)}",
            generate_sound_event(name,
                                  label=f"{i}/{len(items)}: {name}",
                                  include_motor_init=False,
                                  custom_melodies=custom_melodies,
                                  lang=lang),
            f"M400                              ; {wait_play}",
            f"G4 P2000                          ; {pause_lbl}",
            "",
        ]

    out += [
        "M400",
        "M73 P100 R0",
        f"M18                               ; {motor_off}",
        f"; {end_lbl}",
    ]
    return "\n".join(out)


def generate_fake_body_gcode(cycle_num: int, total_cycles: int) -> str:
    """Fake body for a multi-cycle dry-run — mimics print timing and motion without extruding."""
    return "\n".join([
        "; ============================================================",
        f"; [fake BODY {cycle_num}/{total_cycles}] XY motion + dwell in place of a real print",
        ";   purpose: visual 'printing' feedback between cycles during a dry-run",
        ";   approx duration: 10 seconds",
        "; ============================================================",
        "G90",
        "G1 Z5 F600                        ; Z=5mm safe height",
        "G1 X170 Y160 F12000               ; bed centre",
        "G4 P3000                          ; 3s dwell (mimics first layer)",
        "G1 X100 Y100 F12000               ; diagonal",
        "G4 P2000",
        "G1 X220 Y220 F12000               ; opposite diagonal",
        "G4 P2000",
        "G1 X170 Y160 F12000               ; back to centre",
        "G4 P2000",
        "",
    ])



def replace_bambu_sound_block(gcode: str, sound_type: str, custom_gcode: str) -> str:
    """Swap a factory Bambu sound block with a user-defined sound.

    Args:
        gcode: source G-code (start_gcode or end_gcode)
        sound_type: "start" (start sound) or "finish" (end sound)
        custom_gcode: replacement sound G-code (M17 + ...)

    Bambu factory block format:
        ;=====printer start sound ===================
        M17
        M400 S1
        M1006 S1
        ...M1006 commands...
        M1006 W
        ;=====printer start sound ===================
    """
    import re
    # Start / end markers (identical format on both sides)
    marker_kw = "start" if sound_type == "start" else "finish"

    pattern = re.compile(
        rf";=+\s*printer\s+{marker_kw}\s+sound\s*=+\s*\n"  # start marker (\s+ matches one or more spaces)
        r".*?"                                              # any commands in between
        rf";=+\s*printer\s+{marker_kw}\s+sound\s*=+\s*\n", # end marker (same form)
        re.DOTALL | re.IGNORECASE
    )

    if not pattern.search(gcode):
        # No factory block found — return the source as-is
        return gcode

    replacement = (
        f";===== [BambuLoop replacement] printer {marker_kw} sound =====\n"
        f"{custom_gcode}\n"
        f";===== [BambuLoop replacement end] =====\n"
    )
    return pattern.sub(replacement, gcode, count=1)


# ============================================================
# M73 progress recalculation — based on the cumulative BambuLoop time
# ============================================================

_TIME_RE = re.compile(
    r";\s*total estimated time:\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?",
    re.IGNORECASE
)
_M73_RE = re.compile(r"M73 P(\d+) R(\d+)")
_M73_L_RE = re.compile(r"M73 L(\d+)")


def count_layers_in_body(body: str) -> int:
    """Return the largest M73 L<n> value found in the body."""
    layers = [int(m.group(1)) for m in _M73_L_RE.finditer(body)]
    return max(layers) if layers else 0


def parse_estimated_time_seconds(gcode: str) -> Optional[int]:
    """Parse the 'total estimated time' from the G-code header into seconds.

    Bambu format: '; model printing time: 48m 51s; total estimated time: 54m 8s'
    Returns the value as an int (seconds), or None if not found.
    """
    m = _TIME_RE.search(gcode[:5000])  # search the header only
    if not m:
        return None
    h = int(m.group(1) or 0)
    mn = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mn * 60 + s


def estimate_post_print_seconds(s: "AutomationSettings",
                                 max_z_height: float = 40.0) -> int:
    """Estimate one POST_PRINT sequence duration in seconds.

    Per-phase heuristics:
        cooling: nozzle temp delta / 5°C·s + bed-target wait
        eject:   sweep_passes × z_steps × average_pass_time
        reheat:  reach next-print temps (roughly nozzle 60s + bed 2-3min)
        reset:   G28 + flushing ≈ 90s
    """
    # Cooling (nozzle OFF + bed → cooling_bed_temp)
    cool_sec = 60 + max(0, (60 - s.cooling_bed_temp)) * 6  # time for the bed to cool

    # Eject: Y bidirectional distance / speed × pass count × z steps
    y_dist_mm = (s.bed_size_y + s.back_overhang_mm + s.front_overhang_mm) * 2
    feed = max(1000, s.eject_speed)  # mm/min
    sweep_per_pass_sec = (y_dist_mm / feed) * 60
    eject_sec = int(sweep_per_pass_sec * s.eject_passes * s.eject_descent_steps + 30)

    # Reheat (heat for the next print — wait for nozzle and bed targets)
    reheat_sec = 180  # ~3 min, conservative

    # Reset (G28 + flushing + cleaning)
    reset_sec = 90 if s.purge_between else 60

    return cool_sec + eject_sec + reheat_sec + reset_sec


def rewrite_m73_in_body(body: str, body_idx: int, total_bodies: int,
                          body_time_sec: int, post_print_sec: int,
                          layer_offset: int = 0, total_layers_all: int = 0) -> str:
    """Rewrite every M73 P/R/L command in the body to use the overall BambuLoop progress.

    Args:
        body: print body G-code string
        body_idx: current body index (1-indexed, 1..total_bodies)
        total_bodies: total number of prints
        body_time_sec: estimated duration of one body (seconds)
        post_print_sec: one POST_PRINT duration (seconds)
        layer_offset: layers accumulated before this body (added to M73 L values)
        total_layers_all: total layer count across every print (0 if unknown; shown explicitly on the printer UI)

    Returns:
        The body string with M73 lines rewritten.
    """
    if total_bodies < 1 or body_time_sec <= 0:
        # No timing info — still apply the layer offset
        if layer_offset > 0:
            def repl_l_only(m: re.Match) -> str:
                original_l = int(m.group(1))
                return f"M73 L{original_l + layer_offset}"
            return _M73_L_RE.sub(repl_l_only, body)
        return body

    total_sec = body_time_sec * total_bodies + post_print_sec * max(0, total_bodies - 1)
    body_start_sec = (body_idx - 1) * (body_time_sec + post_print_sec)

    def repl_pr(m: re.Match) -> str:
        original_p = int(m.group(1))
        elapsed_in_body = (original_p / 100.0) * body_time_sec
        global_elapsed = body_start_sec + elapsed_in_body
        new_p = max(0, min(100, int(round(global_elapsed / total_sec * 100))))
        new_r = max(0, int(round((total_sec - global_elapsed) / 60)))
        return f"M73 P{new_p} R{new_r}"

    def repl_l(m: re.Match) -> str:
        original_l = int(m.group(1))
        return f"M73 L{original_l + layer_offset}"

    body = _M73_RE.sub(repl_pr, body)
    body = _M73_L_RE.sub(repl_l, body)
    return body


def make_post_print_m73_marks(body_idx: int, total_bodies: int,
                                body_time_sec: int, post_print_sec: int,
                                phase: str, next_total_layers: int = 0) -> str:
    """Insert a single M73 command at the start of a POST_PRINT phase.

    Args:
        phase: "cool" | "eject" | "reheat" | "reset"
        next_total_layers: total layer count of the next body (used in the reset phase for M991 reset)

    Approximate time share per phase:
        cool=20%, eject=15%, reheat=50%, reset=15%
    """
    if total_bodies < 1 or body_time_sec <= 0:
        return ""

    phase_offsets = {
        "cool":   0.0,
        "eject":  0.20,
        "reheat": 0.35,
        "reset":  0.85,
    }
    offset = phase_offsets.get(phase, 0.0)

    total_sec = body_time_sec * total_bodies + post_print_sec * max(0, total_bodies - 1)
    body_end_sec = body_idx * body_time_sec + (body_idx - 1) * post_print_sec
    phase_sec = body_end_sec + offset * post_print_sec

    p = max(0, min(100, int(round(phase_sec / total_sec * 100))))
    r = max(0, int(round((total_sec - phase_sec) / 60)))

    lines = [f"M73 P{p} R{r}                        ; [BambuLoop {phase}] overall progress update"]

    # v28: the 'M73 L0' in the reset phase was removed.
    # Bambu firmware interpreted 'M73 L0' as a print-session reset and stopped timelapse recording.
    # Instead, the next body's 'M73 L1' resumes the layer count from 1 naturally (timelapse stays alive).

    return "\n".join(lines)
