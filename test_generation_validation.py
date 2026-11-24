"""Regression tests for file generation and offline validation. No device I/O."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import app as web
from gcode_processor import (
    AutomationSettings, BambuGcodeParser, EjectClearanceError, JobConfig,
    build_combined_gcode, build_dry_run_gcode,
)
from gcode_validator import run, validate_gcode_text


def source(layers=1, height=5, notes=""):
    return "\n".join([
        "; HEADER_BLOCK_START", f"; max_z_height: {height}", f"; total layer number: {layers}",
        "; HEADER_BLOCK_END", "; CONFIG_BLOCK_START", "; printer_model = Bambu Lab H2S",
        "; CONFIG_BLOCK_END", "G28", "; CHANGE_LAYER", notes,
        *(f"M73 L{i}" for i in range(1, layers + 1)), "; filament end gcode", "M84",
    ])


def job(layers, copies=1, height=5):
    parser = BambuGcodeParser(source(layers, height, "; M73 L99"))
    return JobConfig(f"{layers}.gcode", copies, parser.sections, parser.temps)


class GenerationTests(unittest.TestCase):
    def test_mixed_copies_keep_monotonic_layers(self):
        for jobs in ([job(3), job(1)], [job(1, 2), job(3, 2)], [job(3, 2)]):
            with self.subTest(jobs=[j.filename for j in jobs]):
                result = build_combined_gcode(jobs, AutomationSettings())
                numbers = [int(s.split("L")[1]) for s in result.splitlines() if s.startswith("M73 L")]
                total = sum(int(j.filename.split(".")[0]) * j.count for j in jobs)
                self.assertEqual(numbers, list(range(1, total + 1)))
                self.assertIn(f"; total layer number: {total}\n", result)
                self.assertEqual(result.count("; M73 L99"), sum(j.count for j in jobs))
                final = result.split("= final]")[-1]
                self.assertEqual(sum(s.startswith("M190 R35 ") for s in final.splitlines()), 5)
                self.assertLess(final.index("[eject sequence]"), final.index("M84"))

    def test_missing_layer_commands_use_header(self):
        first = job(3)
        first.sections.body = "; CHANGE_LAYER\n; M73 L99\nG1 X10"
        result = build_combined_gcode([first, job(1)], AutomationSettings())
        self.assertIn("; total layer number: 4\n", result)
        self.assertIn("\nM73 L4\n", result)

    def test_time_and_layer_header_fields_keep_their_lines(self):
        item = job(3, 2)
        item.sections.header = item.sections.header.replace(
            "; total layer number:", "; model printing time: 21s\n; total estimated time: 6m 39s\n; total layer number:")
        text = build_combined_gcode([item], AutomationSettings())
        header = text.split("; HEADER_BLOCK_END")[0]
        self.assertEqual(header.count("total layer number:"), 1)
        self.assertIn("\n; total estimated time:", header)
        self.assertIn("\n; total layer number: 6\n", header)

    def test_partial_layer_commands_and_missing_header_total(self):
        first = job(3)
        first.sections.header = "; HEADER_BLOCK_START\n; HEADER_BLOCK_END"
        first.sections.body = "; CHANGE_LAYER\nM73 L1\n; CHANGE_LAYER\n; CHANGE_LAYER"
        text = build_combined_gcode([first, job(1)], AutomationSettings())
        self.assertIn("; total layer number: 4\n; HEADER_BLOCK_END", text)
        self.assertIn("\nM73 L4\n", text)

    def test_unknown_height_in_a_mixed_job(self):
        unknown = job(1, height=0)
        with self.assertRaises(EjectClearanceError) as failure:
            build_combined_gcode([job(1), unknown], AutomationSettings())
        self.assertEqual(failure.exception.reason, "unknown_height")
        text = build_combined_gcode([unknown], AutomationSettings(eject_method="none"))
        self.assertIn("eject sequence disabled", text)
        legacy = BambuGcodeParser(source(height=0).replace("; max_z_height: 0", "")
                                  .replace("M73 L1", "; Z_HEIGHT: 43.5\nM73 L1"))
        self.assertEqual(legacy.temps.max_z_height, 43.5)

    def test_reset_keeps_exactly_one_bin_exit_and_the_wipes(self):
        from gcode_processor import PrintTemps, generate_reset_sequence
        base = "M83\nG1 E45 F600\nG1 E-3 F1800\nG150.2\nG150.1"
        mode = AutomationSettings()
        for tail in ("", "\nG91\nM73 P1 R4\nG1 Y-16 F12000 ; move away\nG90\nM400",
                     "\ng91\ng01 y-16.0 f12000\n; EOF", "\nG91\nG1 F12000 Y-16\nG90",
                     "\nG91\nM400\nG1 Y-16 F12000\nG92 E0\nM400\nG90\nG92 E0"):
            with self.subTest(tail=tail):
                gcode = generate_reset_sequence(mode, PrintTemps(), flushing_block=base + tail)
                code = [line.partition(";")[0].strip().upper() for line in gcode.splitlines()]
                self.assertEqual(sum("Y-16" in line for line in code), 1)
                self.assertEqual(code.count("G150.2"), 1)
                self.assertEqual(code.count("G150.1"), 1)
                self.assertIn("G1 X270 Y-0.5 F60000", code)
        # An absolute Y position, a comment, and a retreat before another wipe are distinct cases.
        for tail in ("\n; G91 G1 Y-16 G90", "\nG90\nG1 Y-16 F12000", "\nG91\nG1 Y-16\nG90\nG150.3"):
            gcode = generate_reset_sequence(mode, PrintTemps(), flushing_block=base + tail)
            self.assertIn("; leave the garbage can", gcode)

    def test_clearance_boundaries(self):
        for method, height, steps, blocked in (
            ("bottom_only", 41.99, 4, False), ("edge_to_center_bottom", 42, 4, True),
            ("edge_to_center", 84, 3, False), ("multi_sweep", 84.01, 3, True),
        ):
            settings = AutomationSettings(eject_method=method, eject_descent_steps=steps)
            builders = (lambda: build_combined_gcode([job(1, height=height)], settings),
                        lambda: build_dry_run_gcode(settings, simulated_print_height=height))
            for build in builders:
                with self.subTest(method=method, height=height):
                    if blocked:
                        with self.assertRaises(EjectClearanceError):
                            build()
                    else:
                        self.assertIn("[eject sequence]", build())
        self.assertNotIn("[eject sequence]", build_dry_run_gcode(
            AutomationSettings(eject_method="bottom_only"), 50, include_eject=False))


START = ";===== machine: H2S =====================\nG28\nG90\n"
EXIT = "G150.3\nM83\nG1 E20 F240\nG150.1\nG91\nG1 Y-16 F12000\nG90\n"
PRIME = """;===== nozzle load line ===============================
G29.2 S1
G90
M83
G1 Z5 F1200
G1 X270 Y-0.5 F60000
G28.14 R0
G29.2 S0
G91
G1 Z0.8 F1200
G90
G1 X250 F60000
M109 S220
M83
G1 E5 F240
G1 X290 E20 F374
G91
G3 Z0.4 I1.217 J0 P1 F60000
G90
M83
G29.2 S1
;===== noozle load line end ===========================
"""


class ValidationTests(unittest.TestCase):
    def test_purge_geometry_and_section(self):
        for path in (PRIME, EXIT):
            with self.subTest(path=path[:30]):
                self.assertEqual(validate_gcode_text(START + path)["verdict"], "expected_only")
                self.assertEqual(validate_gcode_text(START + path, 0)["verdict"], "expected_only")
                placed_in_model = validate_gcode_text(START + "; CHANGE_LAYER\n" + path)
                self.assertEqual(placed_in_model["expected_count"], 0)
                self.assertEqual(placed_in_model["verdict"], "soft_only" if path == PRIME else "unsafe")
        self.assertEqual(validate_gcode_text(START + PRIME.replace("X290 E20", "X310 E20"))["verdict"], "unsafe")
        self.assertEqual(validate_gcode_text(START + "; purge\nG1 Y-1")["verdict"], "unsafe")
        self.assertEqual(validate_gcode_text(START + "G1 X345\nG1 Z-1")["hard_count"], 2)

    def test_expected_paths_and_duplicate_exit_are_independent_of_warning_margin(self):
        job = START + EXIT + PRIME + "; CHANGE_LAYER\nG1 Y20\nG1 Y-0.5\nG1 Y-60"
        duplicate = START + EXIT + "G91\nG1 Y-16 F12000\nG90"
        for margin in (0, 0.25, 1, 10, 16, 20, 50):
            with self.subTest(margin=margin):
                r = validate_gcode_text(job, margin)
                self.assertEqual((r["expected_count"], r["soft_count"], r["hard_count"]), (1, 1, 1))
                self.assertEqual(r["physical"]["y_min"], -16)
                self.assertEqual(r["soft_violations"][0]["command"], "G1 Y-0.5")
                self.assertEqual(r["hard_violations"][0]["command"], "G1 Y-60")
                d = validate_gcode_text(duplicate, margin)
                self.assertEqual(d["hard_count"], 1)
                self.assertIn("2 ×", d["hard_violations"][0]["axes"][-1])
        for altered in (PRIME.replace("G1 X250 F60000", "G1 X250 F60000Y-1"),
                        PRIME.replace("G1 E5 F240", "G1 E5Y-1 F240")):
            self.assertEqual(validate_gcode_text(START + altered, 0)["verdict"], "unsafe")

    def test_purge_exit_with_stationary_commands(self):
        routine = "G150.1\nG91\nM400\nG01 Y-16.0 F12000\nG92 E0\nM400\nG90"
        self.assertEqual(validate_gcode_text(START + routine)["verdict"], "expected_only")
        self.assertEqual(validate_gcode_text(START + routine, 0)["verdict"], "expected_only")

    def test_pre_extrusion_calibration_only_at_first_start(self):
        approach = "G1 X270 Y-0.5 F60000"
        block = ("G390.1 Z\nG90\nM73 P0 R286\nG1 Z5 F1200\n" + approach + "\nG28.140 S0\n"
                 "M141 S0\nM104 S245\nM1002 gcode_claim_action : 3\nG90\nG1 Z5 F1200\nG1 X187 Y160 F20000\n")
        self.assertEqual(validate_gcode_text(START + block)["verdict"], "expected_only")
        self.assertEqual(validate_gcode_text(START + "; CHANGE_LAYER\n" + block)["verdict"], "soft_only")
        for suffix in (block + block,
                       block.replace("G28.140 S0", "G28.14 R0"), block.replace("X270", "X260"),
                       block.replace("G390.1 Z", "G28"), block.replace("G1 X187", "G1 X180"),
                       "G390.1 Z\nG1 X20\n" + block, block.split("M141")[0]):
            with self.subTest(suffix=suffix):
                self.assertGreater(validate_gcode_text(START + suffix)["hard_count"], 0)
        self.assertEqual(validate_gcode_text(START + block, 0)["verdict"], "expected_only")

    def test_bin_to_load_lift_requires_one_uninterrupted_exit(self):
        lift = "G1 Z5 F1200"
        self.assertEqual(validate_gcode_text(START + EXIT + "M400\n" + PRIME)["verdict"], "expected_only")
        for prefix in (EXIT + "G150.3\n", EXIT + "G91\nG90\n", "G1 Y-16\n",
                       "G1 Y1\n" + EXIT, EXIT + "G91\nG1 Y-16 F12000\nG90\n"):
            with self.subTest(prefix=prefix):
                r = validate_gcode_text(START + prefix + PRIME)
                self.assertEqual(r["verdict"], "unsafe")
        altered = PRIME.replace(lift, "G1 Z4 F1200")
        self.assertEqual(validate_gcode_text(START + EXIT + altered)["verdict"], "unsafe")
        self.assertEqual(validate_gcode_text(START + EXIT + PRIME, 0)["verdict"], "expected_only")

    def test_load_to_first_layer_allows_only_the_expected_z_move(self):
        layer = "; CHANGE_LAYER\n; layer num/total_layer_count: 1/81\nM73 L82\nM106 S0\n"
        entry = "G1 Z.4 F60000"
        def check(tail, margin=20):
            return validate_gcode_text(START + PRIME + tail, margin)
        for move in (entry, "G1 Z.4 F30000", "g1 z0.400 f27500.5 ; profile travel speed"):
            with self.subTest(move=move):
                r = check(layer + move)
                self.assertEqual((r["verdict"], r["soft_count"], r["hard_count"]), ("expected_only", 0, 0))
                self.assertEqual(check(layer + move, 0)["verdict"], "expected_only")
        for move in ("G1 Z.4 F0", "G1 Z.4 F-1", "G1 Z.4 F30000Y-2", "G1 Z.4 F30000 E1",
                     "G1 Z.4 F30000 Y-0.5", "G1 Z.4 F30.0.0", "G1 Z.4 F" + "9" * 310):
            with self.subTest(move=move):
                self.assertEqual(check(layer + move)["verdict"], "soft_only")
        self.assertEqual(check(layer + "G1 Z.4 F30000\nG1 X30 Y20\nG1 Y-0.5")["soft_count"], 1)
        self.assertEqual(check(entry)["verdict"], "unsafe")  # unexpected move during startup
        for tail in (layer.replace("1/81", "2/81") + entry, layer + entry + "\n" + entry,
                     layer + "G1 Z.5 F60000", layer + "G1 X290 Z.4 F60000", "G91\n" + layer + entry,
                     "G150.1\n" + layer + entry, layer + "G1 E1 F1200\n" + entry,
                     layer + entry + "\nG1 X30 Y20\nG1 Y-0.5"):
            with self.subTest(tail=tail):
                self.assertEqual(check(tail)["verdict"], "soft_only")
        self.assertIn("Z=-1.000 < 0.0", check(layer + "G1 Z-1")["hard_violations"][0]["axes"])

    def test_expected_warning_and_risk_have_separate_counters_and_details(self):
        text = START + PRIME + "; CHANGE_LAYER\nG1 Y30\nG1 Y-0.5\nG1 Y-0.6\nG1 Y-17\nG1 Y-0.4"
        r = validate_gcode_text(text)
        self.assertEqual((r["expected_count"], r["soft_count"], r["hard_count"]), (1, 2, 1))
        self.assertEqual(r["expected_moves"][0]["note"], "H2S nozzle load line")
        self.assertEqual([v["command"] for v in r["soft_violations"]], ["G1 Y-0.5", "G1 Y-0.4"])
        self.assertEqual(r["hard_violations"][0]["command"], "G1 Y-17")
        capped = validate_gcode_text(text, max_violations=0)
        for count, details in (("expected_count", "expected_moves"), ("soft_count", "soft_violations"),
                               ("hard_count", "hard_violations")):
            self.assertEqual(capped[count], r[count])
            self.assertEqual(capped[details], [])

    def test_one_severity_per_move_with_default_warning_margin(self):
        body = START + "; CHANGE_LAYER\n"
        for move, verdict in (("G1 Y-5", "soft_only"), ("G1 Y335", "soft_only"),
                              ("G1 Y-5.01", "unsafe"), ("G1 Y335.01", "unsafe"),
                              ("G1 X341 Y-0.5", "unsafe"), ("G1 Y-0.5 Z-0.1", "unsafe")):
            with self.subTest(move=move):
                r = validate_gcode_text(body + move)
                self.assertEqual(r["verdict"], verdict)
                self.assertEqual(r["expected_count"] + r["soft_count"] + r["hard_count"], 1)
        narrow = "; printable_area = 0x0,200x0,200x190,0x190\n; printable_height = 100\n"
        self.assertEqual(validate_gcode_text(narrow + body + "G1 X201")["verdict"], "soft_only")
        self.assertEqual(validate_gcode_text(narrow + body + "G1 Z341")["verdict"], "unsafe")

    def test_warning_margin_boundary_and_exclusions(self):
        body = START + "; CHANGE_LAYER\n"
        for move in ("G1 X342", "G1 X-2", "G1 Y-7", "G1 Y337", "G1 Z342"):
            with self.subTest(move=move):
                for margin, verdict in [(0, "unsafe"), (1.99, "unsafe"), (2, "soft_only")]:
                    r = validate_gcode_text(body + move, margin)
                    self.assertEqual(r["verdict"], verdict)
                    self.assertEqual(r["expected_count"], 0)
        for text in (body + "G1 Z-0.1", body + "G1 X342 Z-0.1", START + "G1 X342",
                     START + "G1 Y-17", START + EXIT + "G91\nG1 Y-16 F12000\nG90"):
            self.assertEqual(validate_gcode_text(text, 50)["verdict"], "unsafe")
        r = validate_gcode_text(body + "G1 X342", 2)
        self.assertEqual(r["warning_bounds"], dict(x_min=-2, x_max=342, y_min=-7, y_max=337, z_min=0, z_max=342))
        for margin in (-1, 50.01, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                validate_gcode_text(body, margin)

    def test_source_and_generated_machine_end_use_service_limits(self):
        for marker in ("; MACHINE_END_GCODE_START", "; [SHUTDOWN]", "; machine_end_gcode", "; filament end gcode"):
            with self.subTest(marker=marker):
                text = START + "; CHANGE_LAYER\nG1 Y-0.5\n" + marker + "\nG1 Y-0.5"
                r = validate_gcode_text(text)
                self.assertEqual((r["expected_count"], r["soft_count"], r["hard_count"]), (0, 1, 1))

    def test_in_model_filament_change_keeps_ordinary_warning_range(self):
        job = START + "; CHANGE_LAYER\n; filament end gcode\n; filament start gcode\nG1 X342"
        self.assertEqual(validate_gcode_text(job, 2)["verdict"], "soft_only")

    def test_warning_escalates_and_rearms(self):
        text = START + EXIT + "G1 Y-17\nG1 Y-18\nG1 Y10\nG1 Y-17"
        r = validate_gcode_text(text)
        self.assertEqual((r["expected_count"], r["hard_count"], r["verdict"]), (1, 2, "unsafe"))
        capped = validate_gcode_text(text, max_violations=0)
        self.assertEqual(capped["hard_count"], 2)
        self.assertEqual(capped["hard_violations"], [])
        self.assertEqual(capped["verdict"], "unsafe")

    def test_default_sweeps_are_checked_without_purge_margin(self):
        for method in ("multi_sweep", "edge_to_center", "edge_to_center_bottom", "bottom_only", "zigzag", "sweep"):
            with self.subTest(method=method):
                settings = AutomationSettings(eject_method=method, eject_passes=3, eject_descent_steps=2)
                text = build_dry_run_gcode(settings, 10, include_reset=False)
                r = validate_gcode_text(text, 0)
                self.assertEqual(r["hard_count"], 0)
                self.assertGreater(r["expected_count"], 0)
                self.assertTrue(all("eject sweep" in v["note"] for v in r["expected_moves"]))
                tampered = text.replace("G1 Y335 F9000", "G1 Y334 F9000", 1)
                self.assertEqual(validate_gcode_text(tampered)["verdict"], "unsafe")

    def test_sweep_cannot_declare_its_own_machine_limit(self):
        settings = AutomationSettings(back_overhang_mm=25)
        text = build_dry_run_gcode(settings, 10, include_reset=False)
        self.assertEqual(validate_gcode_text(text, 50)["verdict"], "unsafe")
        self.assertEqual(validate_gcode_text(START + "G1 Y335", 50)["verdict"], "unsafe")

    def test_legacy_korean_sweep_replays_actual_movements(self):
        text = """; #   BambuLoop — Bambu Lab H2S 자동 반복 인쇄 G-code   #
G28
; ## 인쇄 #1/1
; Z_HEIGHT: 10
; [POST-PRINT #1] 다음 인쇄 준비 시작
; [분리 시퀀스] 단계적 하강 + 직각 이동
;   - 방식         : sweep
;   - X 패스 수    : 1 (= Y 스윕 횟수)
;   - X 커버 범위  : 3mm ~ 337mm (베드 양끝까지 거의 다)
;   - 인쇄물 높이  : 10.0mm (G-code 헤더에서 자동 추출)
;   - 파킹 Z       : 20.0mm (인쇄물 + 10mm)
;   - 스윕 Z 범위  : 10.0mm (인쇄물 꼭대기) → 0.4mm (1단 분할)
;   - Y 후방 시작점: Y=335mm (= 베드 320 + 베드밖 15mm)
;   - Y 전방 종료점: Y=-5mm (= 베드 앞면 - 5mm)
;   - 스윕 속도    : 9000 mm/min
G90
G1 Z20.0 F1200
G1 Y335 F9000
G1 X170 F9000
G1 Z10.0 F1200
G1 Z0.4 F600
G1 Y-5 F9000
G1 Y335 F9000
G1 Z20.0 F1200
G1 X170 F9000
G1 Y160 F9000"""
        self.assertEqual(validate_gcode_text(text, 0)["verdict"], "expected_only")
        changed = text.replace("G1 X170 F9000", "G1 X160 F9000", 1)
        self.assertEqual(validate_gcode_text(changed)["verdict"], "unsafe")
        self.assertEqual(validate_gcode_text(text.replace("Z_HEIGHT: 10", "Z_HEIGHT: 50"))["verdict"], "unsafe")

    def test_position_reset_keeps_physical_limits(self):
        text = START + "G1 X100 Y10 Z1\nG92 X0\nG01X300Y10"
        self.assertEqual(validate_gcode_text(text)["hard_violations"][0]["point"][0], 400)
        self.assertEqual(validate_gcode_text(START + "G1 X100\nG92 X0\n" + PRIME)["verdict"], "unsafe")
        unknown = "G92 X0 Y0 Z0\nG1 X2 Y3 Z1"
        self.assertEqual(validate_gcode_text(unknown)["verdict"], "unverified")
        self.assertEqual(validate_gcode_text(START + "G20\nG1 X16")["verdict"], "unsafe")
        self.assertEqual(validate_gcode_text(START + ";CHANGE_LAYER\n" + EXIT)["verdict"], "unsafe")

    def test_first_homing_checks_xy_before_z_is_homed(self):
        homing = """;===== machine: H2S =====
;===== first homing start =====
G28 X T300
M1009 Q1 L1
G91
G380 S2 Z30 F1200
G90
G1 X170 Y160 F30000
G28 Z P0 T250
M1009 Q1 L0
;===== first homing end ====="""
        report = validate_gcode_text(homing)
        self.assertEqual((report["verdict"], report["total_moves"], report["skipped_moves"]), ("safe", 1, 0))
        self.assertEqual(report["verdict_label"]["ko"], "✅ 모든 GCODE 이동이 정상 범위입니다")
        self.assertIsNone(report["bbox_min"])  # Never manufacture a Z for the XY move.
        narrow = "; printable_area = 0x0,100x0,100x100,0x100\n; printable_height = 100\n"
        self.assertEqual(validate_gcode_text(narrow + homing)["hard_count"], 1)
        for altered in (homing.replace("G28 Z P0 T250", "M400"), homing.replace("X170", "X169"),
                        homing.replace("G28 X T300", "G28 Y T300"), homing.replace("G90", "G91"),
                        homing.replace("M1009 Q1 L1", "G92 Y0\nM1009 Q1 L1"),
                        homing.replace("G28 X T300", "G28 X T300\nM84 X"),
                        homing.replace(";===== first homing start", "; CHANGE_LAYER\n;===== first homing start")):
            with self.subTest(altered=altered):
                r = validate_gcode_text(altered)
                self.assertEqual((r["verdict"], r["skipped_moves"]), ("unverified", 1))

    def test_success_label_requires_checked_moves(self):
        passed = validate_gcode_text(START + EXIT)
        self.assertEqual((passed["verdict"], passed["verdict_label"]["ko"]),
                         ("expected_only", "✅ 모든 GCODE 이동이 정상 범위입니다"))
        for source, label in (("M400", "검사할 이동이 없습니다"),
                              ("G28 X\nG91\nG1 Y5", "일부 이동의 좌표를 확인할 수 없습니다")):
            r = validate_gcode_text(source)
            self.assertEqual((r["verdict"], r["verdict_label"]["ko"]), ("unverified", label))

    def test_partial_home_and_arcs(self):
        incomplete = validate_gcode_text("G28 X\nG91\nG1 Y5")
        self.assertEqual((incomplete["verdict"], incomplete["skipped_moves"]), ("unverified", 1))
        self.assertEqual(validate_gcode_text(START + "G1 X10 Y0.5 Z1\nG3 X14 Y0.5 R2")["verdict"], "unsafe")
        invalid = validate_gcode_text(START + EXIT + "G1 X20 Y20\nG2 X40 Y20 R1")
        self.assertEqual(invalid["verdict"], "unverified")
        self.assertEqual((invalid["expected_count"], invalid["skipped_moves"]), (1, 1))

    def test_duplicate_retreat_is_an_unrecognised_move(self):
        text = START + EXIT + "G91\nG1 Y-16 F12000\nG90\n"
        r = validate_gcode_text(text)
        self.assertEqual((r["expected_count"], r["hard_count"]), (1, 1))
        self.assertEqual(r["hard_violations"][0]["point"][1], -32)

    def test_duplicate_retreat_even_with_an_on_bed_estimated_position(self):
        for separator in ("", "G90\nM400\nG91\n", "G90\n" + "; wait\n\nM400\n" * 50 + "G91\n"):
            with self.subTest(separator=separator):
                prefix = START + "G1 Y100\n" + EXIT.removesuffix("G90\n")
                r = validate_gcode_text(prefix + separator + "G1 Y-16 F12000\nG90")
                self.assertEqual(r["hard_count"], 1)
                self.assertEqual(r["hard_violations"][0]["point"][1], 68)
                self.assertIn("2 ×", r["hard_violations"][0]["axes"][-1])
        separate = START + "G1 Y100\n" + EXIT + "G1 Y100\n" + EXIT
        self.assertEqual(validate_gcode_text(separate)["hard_count"], 0)

    def test_3mf_cli_and_api_report_same_verdict(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            path = Path(tmp, "plate.gcode.3mf")
            with ZipFile(path, "w") as archive:
                archive.writestr("Metadata/plate_1.gcode", START + EXIT)
            for margin in (0, 20):
                cli = run(path, margin, 20)
                api = validate_gcode_text(START + EXIT, margin)
                self.assertEqual((cli.expected_count, cli.soft_count, cli.hard_count),
                                 (api["expected_count"], api["soft_count"], api["hard_count"]))


class RouteTests(unittest.TestCase):
    def test_generation_dry_run_and_download_recheck(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            store = Path(tmp)
            with patch.object(web, "UPLOAD_DIR", store), patch.object(web, "OUTPUT_DIR", store):
                client = web.app.test_client()
                (store / "source.gcode").write_text(source(height=42), encoding="utf-8")
                settings = {"eject_method": "bottom_only"}
                gen = client.post("/api/generate", json={"settings": settings, "jobs": [
                    {"stored_name": "source.gcode", "count": 1}]})
                dry = client.post("/api/dry_run", json={"settings": settings, "simulated_print_height": 42})
                self.assertEqual((gen.status_code, dry.status_code), (409, 409))
                self.assertEqual(gen.json, dry.json)
                self.assertEqual(gen.json["error"], "z_collision_bottom_mode")
                unknown = client.post("/api/dry_run", json={"settings":settings,"simulated_print_height":None})
                self.assertEqual((unknown.status_code, unknown.json["error"]), (409, "z_collision_unknown_height"))
                invalid = client.post("/api/generate", json={"safety_margin_mm":"NaN"})
                self.assertEqual(invalid.status_code, 400)
                self.assertEqual(sorted(p.name for p in store.iterdir()), ["source.gcode"])
                good = client.post("/api/dry_run", json={"settings": settings, "simulated_print_height": 42,
                                                         "phases":{"include_eject":False}})
                self.assertEqual(good.status_code, 200)
                generated = client.post("/api/generate", json={"settings":{"eject_method":"edge_to_center"},
                    "jobs":[{"stored_name":"source.gcode","count":2}]})
                self.assertEqual(generated.status_code, 200)
                with client.get("/api/download/" + generated.json["filename"]) as download:
                    self.assertIn(b"; total layer number: 2", download.data)
                (store / "purge.gcode").write_text(START + EXIT, encoding="utf-8")
                with ZipFile(store / "multiple.3mf", "w") as archive:
                    archive.writestr("Metadata/plate_10.gcode", START)
                    archive.writestr("Metadata/plate_2.gcode", START + EXIT)
                check = client.post("/api/validate", json={"filename": "multiple.3mf", "margin_mm": 0})
                self.assertEqual(check.json["source"], "multiple.3mf!Metadata/plate_2.gcode")
                self.assertEqual(check.json["verdict"], "expected_only")
                for margin in (0, 1, 20):
                    result = client.post("/api/validate",json={"filename":"purge.gcode","margin_mm":margin})
                    self.assertEqual((result.json["margin_mm"], result.json["verdict"]), (margin, "expected_only"))


if __name__ == "__main__":
    unittest.main()
