"""Quick smoke test for the parser and the combined-G-code builder."""

import sys
sys.path.insert(0, '/home/claude/bambuloop_v40')

from gcode_processor import (
    BambuGcodeParser, AutomationSettings, JobConfig,
    build_combined_gcode,
)

# Minimal Bambu-style G-code that mirrors the real output structure.
SAMPLE_GCODE = """; HEADER_BLOCK_START
; BambuStudio 02.00.01.50
; model printing time: 21s
; total estimated time: 6m 39s
; total layer number: 3
; HEADER_BLOCK_END

; CONFIG_BLOCK_START
; nozzle_temperature_initial_layer = 220
; nozzle_temperature = 220
; hot_plate_temp = 55
; hot_plate_temp_initial_layer = 55
; textured_plate_temp = 55
; textured_plate_temp_initial_layer = 55
; chamber_temperatures = 0
; curr_bed_type = Textured PEI Plate
; filament_type = PLA
; CONFIG_BLOCK_END

M73 P0 R5
M201 X20000 Y20000
G90
M83
G28
G29
M104 S220
M140 S55
M190 S55
M109 S220
G1 X10 Y10 Z0.3 F3000
G1 X100 Y10 E15 F1500
G92 E0

; LAYER_CHANGE
; Z_HEIGHT: 0.2
G1 X50 Y50 Z0.2 F3000
G1 X150 Y50 E5 F1200
G1 X150 Y150 E5
G1 X50 Y150 E5
G1 X50 Y50 E5

; LAYER_CHANGE
; Z_HEIGHT: 0.4
G1 Z0.4 F600
G1 X50 Y50 E2
G1 X150 Y50 E5

; filament end gcode
M104 S0
M140 S0
M106 S0
G1 X128 Y250 F6000
G1 Z100 F600
M84
"""


def main():
    print("=" * 60)
    print("[1] Parser check")
    print("=" * 60)
    parser = BambuGcodeParser(SAMPLE_GCODE, "test_cube.gcode")
    info = parser.get_info()
    print(f"Filename       : {info['filename']}")
    print(f"Filament       : {info['filament_type']}")
    print(f"Nozzle temp    : {info['nozzle_temp']}°C")
    print(f"Bed temp       : {info['bed_temp']}°C")
    print(f"Chamber temp   : {info['chamber_temp']}°C")
    print(f"Header lines   : {info['header_lines']}")
    print(f"Body lines     : {info['body_lines']}")
    print(f"START present  : {info['has_start_gcode']}")
    print(f"END present    : {info['has_end_gcode']}")
    print()

    print("--- HEADER (first 3 lines) ---")
    print("\n".join(parser.sections.header.split("\n")[:3]))
    print("...")
    print()
    print("--- START_GCODE (first 5 lines) ---")
    print("\n".join(parser.sections.start_gcode.split("\n")[:5]))
    print("...")
    print()
    print("--- BODY (first 4 lines) ---")
    print("\n".join(parser.sections.body.split("\n")[:4]))
    print("...")
    print()
    print("--- END_GCODE ---")
    print(parser.sections.end_gcode)
    print()

    print("=" * 60)
    print("[2] Combined-build check (Model A x 2)")
    print("=" * 60)
    job = JobConfig(
        filename="test_cube.gcode",
        count=2,
        sections=parser.sections,
        temps=parser.temps,
    )
    settings = AutomationSettings(
        cooling_bed_temp=35,
        eject_method="multi_sweep",
        eject_passes=3,
    )
    combined = build_combined_gcode([job], settings)
    print(f"Combined line count: {len(combined.split(chr(10)))}")
    print()
    print("--- Automation metadata (first 30 lines) ---")
    for line in combined.split("\n")[:30]:
        print(line)
    print()
    print("--- Sequence search after first print ---")
    lines = combined.split("\n")
    for i, line in enumerate(lines):
        if "[POST-PRINT #1]" in line:
            for l in lines[i:i+30]:
                print(l)
            break

    print()
    print("=" * 60)
    print("[3] Multi-model combined-build check (A x 2 + B x 1)")
    print("=" * 60)
    job_b = JobConfig(
        filename="test_cone.gcode",
        count=1,
        sections=parser.sections,
        temps=parser.temps,
    )
    combined2 = build_combined_gcode([job, job_b], settings)
    print(f"Combined line count: {len(combined2.split(chr(10)))}")
    headers = [l for l in combined2.split("\n") if l.startswith("; ## Print")]
    print("--- Print headers ---")
    for h in headers:
        print(h)


if __name__ == "__main__":
    main()
