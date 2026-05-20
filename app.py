"""
BambuLoop — Flask web application
=================================

Endpoints:
    GET  /                  : Main UI
    POST /api/upload        : Upload G-code / 3MF files (multipart, multi-file)
                              → parses each file and returns metadata
    POST /api/generate      : Build a combined G-code from a job list + settings
                              → returns the output filename for download
    GET  /api/download/<f>  : Download a generated file
    POST /api/dry_run       : Build a dry-run G-code (automation sequences only)
    POST /api/validate      : Run safety validation on a G-code text or file
    GET  /api/sound_presets : List available sound presets for the UI preview
    POST /api/sound_catalog : Build a sound-preset catalog G-code
    POST /api/delete_upload : Remove a single uploaded file
    POST /api/reset         : Empty the upload and output directories

Run:
    python app.py
    → http://localhost:5000
"""

from __future__ import annotations

import os
import re
import time
import shutil
import secrets
import zipfile
from pathlib import Path

from flask import (
    Flask, render_template, request, jsonify, send_from_directory, abort,
)
from werkzeug.utils import secure_filename

from gcode_processor import (
    BambuGcodeParser, JobConfig, AutomationSettings,
    build_combined_gcode, build_dry_run_gcode,
    PRESET_PATTERNS, generate_sound_catalog_gcode, generate_sound_event,
)
from gcode_validator import validate_gcode_text
from i18n_helper import t_dict


# ============================================================
# App configuration
# ============================================================

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024   # 200MB upload cap
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)
app.config["OUTPUT_FOLDER"] = str(OUTPUT_DIR)

ALLOWED_EXT = {".gcode", ".gco", ".g", ".3mf"}
PLATE_PATTERN = re.compile(r"Metadata/plate_(\d+)\.gcode$", re.IGNORECASE)


# ============================================================
# Utilities
# ============================================================

def _allowed(filename: str) -> bool:
    return any(filename.lower().endswith(ext) for ext in ALLOWED_EXT)


def _safe_unique_filename(original: str) -> str:
    """Return a collision-safe filename built from `secure_filename` + a random token."""
    safe = secure_filename(original) or "file.gcode"
    token = secrets.token_hex(4)
    name, _, ext = safe.rpartition(".")
    return f"{name}__{token}.{ext}" if name else f"{safe}__{token}"


def _extract_3mf_plates(archive_path: Path, base_name: str) -> list[tuple[str, str, bytes, str]]:
    """Extract every `plate_N.gcode` entry from a .3mf archive.

    Returns:
        list of (display_name, stored_name, content_bytes, plate_name).
        `plate_name` is the original entry name inside the .3mf
        (e.g. "plate_1", "plate_2"). It tells the repackager which plate
        of the source .3mf to replace when rebuilding the archive.
    """
    out: list[tuple[str, str, bytes, str]] = []
    # Strip the .3mf / .gcode.3mf extension from `base_name`
    bn = base_name
    for ext in (".gcode.3mf", ".3mf"):
        if bn.lower().endswith(ext):
            bn = bn[: -len(ext)]
            break

    try:
        with zipfile.ZipFile(archive_path) as zf:
            members = sorted(
                [(int(m.group(1)), name)
                 for name in zf.namelist()
                 if (m := PLATE_PATTERN.match(name))],
                key=lambda x: x[0],
            )
            for plate_num, member in members:
                with zf.open(member) as gf:
                    content = gf.read()
                # Plate entry name inside the .3mf: "plate_1", "plate_2", ...
                plate_name = f"plate_{plate_num}"
                # If there's only one plate, drop the suffix from the display name
                if len(members) == 1:
                    display = f"{bn}.gcode"
                else:
                    display = f"{bn}__{plate_name}.gcode"
                stored = _safe_unique_filename(display)
                out.append((display, stored, content, plate_name))
    except zipfile.BadZipFile as e:
        raise ValueError(t_dict("error.3mf_corrupted", error_message=str(e))["en"])
    return out


# ============================================================
# Routes
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload + parse G-code files.

    .gcode / .gco / .g  → stored as-is
    .3mf                → every internal Metadata/plate_N.gcode is extracted
    """
    files = request.files.getlist("gcode_files")
    if not files:
        return jsonify({"error": t_dict("error.no_file")}), 400

    results = []
    errors = []

    for f in files:
        if not f or not f.filename:
            continue
        if not _allowed(f.filename):
            errors.append({
                "filename": f.filename,
                "message": t_dict("error.unsupported_extension"),
            })
            continue

        is_3mf = f.filename.lower().endswith(".3mf")

        if is_3mf:
            # .3mf is saved temporarily first, then plates are extracted
            tmp_name = _safe_unique_filename(f.filename)
            tmp_path = UPLOAD_DIR / tmp_name
            f.save(tmp_path)

            try:
                plates = _extract_3mf_plates(tmp_path, f.filename)
                if not plates:
                    errors.append({
                        "filename": f.filename,
                        "message": t_dict("error.no_gcode_in_3mf"),
                    })
                    tmp_path.unlink(missing_ok=True)
                    continue

                for display, stored, content, plate_name in plates:
                    plate_path = UPLOAD_DIR / stored
                    plate_path.write_bytes(content)
                    try:
                        text = content.decode("utf-8", errors="ignore")
                        parser = BambuGcodeParser(text, display)
                        info = parser.get_info()
                        info["stored_name"] = stored
                        info["original_name"] = display
                        info["size_kb"] = round(plate_path.stat().st_size / 1024, 1)
                        info["from_3mf"] = f.filename
                        info["source_3mf_stored"] = tmp_name        # keep the original .3mf for repackaging
                        info["source_plate_name"] = plate_name       # plate entry name inside the .3mf (repackage target)
                        results.append(info)
                    except Exception as e:
                        errors.append({
                            "filename": display,
                            "message": t_dict(
                                "error.parse_failed",
                                error_type=type(e).__name__,
                                error_message=str(e),
                            ),
                        })
                        plate_path.unlink(missing_ok=True)

                # The original .3mf is kept on disk for repackaging (do NOT delete)
            except Exception as e:
                errors.append({
                    "filename": f.filename,
                    "message": t_dict(
                        "error.3mf_extract_failed",
                        error_type=type(e).__name__,
                        error_message=str(e),
                    ),
                })
                tmp_path.unlink(missing_ok=True)
            continue

        # Plain .gcode / .gco / .g
        stored_name = _safe_unique_filename(f.filename)
        path = UPLOAD_DIR / stored_name
        f.save(path)

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as gf:
                content = gf.read()
            parser = BambuGcodeParser(content, f.filename)
            info = parser.get_info()
            info["stored_name"] = stored_name
            info["original_name"] = f.filename
            info["size_kb"] = round(path.stat().st_size / 1024, 1)
            info["from_3mf"] = None
            results.append(info)
        except Exception as e:
            errors.append({
                "filename": f.filename,
                "message": t_dict(
                    "error.parse_failed",
                    error_type=type(e).__name__,
                    error_message=str(e),
                ),
            })
            try:
                path.unlink()
            except OSError:
                pass

    return jsonify({"files": results, "errors": errors})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Build a combined G-code from a job list and settings."""
    data = request.get_json(silent=True) or {}
    jobs_data = data.get("jobs", [])
    settings_data = data.get("settings", {})

    if not jobs_data:
        return jsonify({"error": t_dict("error.no_jobs")}), 400

    # Build the job list
    jobs: list[JobConfig] = []
    for j in jobs_data:
        stored = j.get("stored_name")
        count = max(1, int(j.get("count", 1)))
        if not stored:
            return jsonify({"error": t_dict("error.missing_stored_name")}), 400

        path = UPLOAD_DIR / stored
        if not path.is_file():
            return jsonify({"error": t_dict("error.upload_file_not_found", filename=stored)}), 404

        with open(path, "r", encoding="utf-8", errors="ignore") as gf:
            content = gf.read()
        parser = BambuGcodeParser(content, j.get("original_name", stored))
        jobs.append(JobConfig(
            filename=j.get("original_name", stored),
            count=count,
            sections=parser.sections,
            temps=parser.temps,
        ))

    # ── Multi-job compatibility check ──────────────────────────────────────
    # The first job's START_GCODE / header / config is applied to every
    # subsequent job, so mismatched nozzle diameter / bed temp / filament
    # type will cause a print failure. The caller can override the check
    # by passing `force_compatibility=true`.
    force_compat = bool(data.get("force_compatibility", False))
    if len(jobs) > 1 and not force_compat:
        first = jobs[0]
        warnings = []
        for j in jobs[1:]:
            t1, t2 = first.temps, j.temps
            # Nozzle temp difference greater than ±10°C
            if abs(t1.nozzle - t2.nozzle) > 10:
                warnings.append(t_dict(
                    "compat.warning.nozzle_temp_diff",
                    filename=j.filename,
                    temp=t2.nozzle,
                    first_filename=first.filename,
                    first_temp=t1.nozzle,
                    diff=abs(t1.nozzle - t2.nozzle),
                ))
            # Bed temp difference greater than ±5°C
            if abs(t1.bed - t2.bed) > 5:
                warnings.append(t_dict(
                    "compat.warning.bed_temp_diff",
                    filename=j.filename,
                    temp=t2.bed,
                    first_temp=t1.bed,
                ))
            # Filament type mismatch
            if t1.filament_type and t2.filament_type and t1.filament_type != t2.filament_type:
                warnings.append(t_dict(
                    "compat.warning.filament_type_diff",
                    filename=j.filename,
                    filament_type=t2.filament_type,
                    first_filament_type=t1.filament_type,
                ))
        if warnings:
            return jsonify({
                "error": "incompatible_jobs",                       # machine code (stable English ID)
                "title":   t_dict("compat.warning.title"),
                "message": t_dict("compat.warning.main_message"),
                "warnings": warnings,
                "first_job": {
                    "filename": first.filename,
                    "nozzle": first.temps.nozzle,
                    "bed": first.temps.bed,
                    "filament_type": first.temps.filament_type,
                },
                "hint": t_dict("compat.warning.hint"),
            }), 409   # 409 Conflict

    # Build the settings object (safe casting)
    def _i(k: str, d: int) -> int:
        try:
            return int(settings_data.get(k, d))
        except (TypeError, ValueError):
            return d

    def _f(k: str, d: float) -> float:
        try:
            return float(settings_data.get(k, d))
        except (TypeError, ValueError):
            return d

    def _b(k: str, d: bool) -> bool:
        v = settings_data.get(k, d)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return bool(v)

    settings = AutomationSettings(
        cooling_bed_temp=min(40, max(0, _i("cooling_bed_temp", 35))),
        cooling_retries=max(1, min(30, _i("cooling_retries", 5))),
        cooling_chamber_temp=_i("cooling_chamber_temp", 0),
        part_fan_enabled=_b("part_fan_enabled", True),
        part_fan_speed=_i("part_fan_speed", 255),
        aux_fan_enabled=_b("aux_fan_enabled", True),
        aux_fan_speed=_i("aux_fan_speed", 255),
        chamber_fan_enabled=_b("chamber_fan_enabled", True),
        chamber_fan_speed=_i("chamber_fan_speed", 255),
        cooling_park_z_min=_i("cooling_park_z_min", 80),
        park_z_clearance=_i("park_z_clearance", 10),
        eject_method=str(settings_data.get("eject_method", "edge_to_center")),
        eject_z_offset=_f("eject_z_offset", 0.4),
        eject_z_start_offset=_f("eject_z_start_offset", 8.0),
        eject_descent_steps=_i("eject_descent_steps", 4),
        eject_speed=_i("eject_speed", 9000),
        eject_passes=_i("eject_passes", 11),
        back_overhang_mm=_i("back_overhang_mm", 15),
        front_overhang_mm=_i("front_overhang_mm", 5),
        bed_size_x=_i("bed_size_x", 340),
        bed_size_y=_i("bed_size_y", 320),
        pause_after_eject=_b("pause_after_eject", False),
        nozzle_clean_between=_b("nozzle_clean_between", True),
        rehome_xy_between=_b("rehome_xy_between", True),
        rehome_z_between=_b("rehome_z_between", False),
        purge_between=_b("purge_between", True),
        purge_length_mm=_f("purge_length_mm", 30.0),
        post_print_override_min=_i("post_print_override_min", 0),
        lang=str(settings_data.get("lang", "ko")),
        sound_print_start=str(settings_data.get("sound_print_start", "")),
        sound_print_done=str(settings_data.get("sound_print_done", "chime_high")),
        sound_cool_done=str(settings_data.get("sound_cool_done", "chime_low")),
        sound_sweep_done=str(settings_data.get("sound_sweep_done", "ascend_fifth")),
        sound_restart=str(settings_data.get("sound_restart", "ascend_minor")),
        sound_print_end=str(settings_data.get("sound_print_end", "")),
        custom_melodies=settings_data.get("custom_melodies", {}) or {},
    )

    # ── Z collision check (H2S head rail + chamber outlet clearance = 42mm) ──
    from gcode_processor import H2S_HEAD_RAIL_LIMIT
    Z_LIMIT = H2S_HEAD_RAIL_LIMIT  # 42mm
    method = settings.eject_method
    steps = max(1, settings.eject_descent_steps)
    # Use the tallest print across every job (different models may be mixed)
    max_print_h = max((float(j.temps.max_z_height or 0) for j in jobs), default=0.0)

    if method != "none" and max_print_h > 0:
        # Case A: bottom-fixed mode + print taller than the limit
        if method in ("bottom_only", "edge_to_center_bottom") and max_print_h >= Z_LIMIT:
            return jsonify({
                "error": "z_collision_bottom_mode",                  # machine code
                "title":   t_dict("error.z_collision.bottom_mode.title"),
                "message": t_dict("error.z_collision.bottom_mode.message",
                                   print_height=f"{max_print_h:.1f}",
                                   z_limit=Z_LIMIT,
                                   z_offset=settings.eject_z_offset),
                "print_height": max_print_h,
                "limit": Z_LIMIT,
                "current_method": method,
            }), 409

        # Case B: Z multi-step descent mode + per-step drop exceeds the limit
        if method in ("multi_sweep", "edge_to_center", "zigzag", "sweep") and max_print_h >= Z_LIMIT:
            # Per-step drop = print_height / max(1, steps - 1)
            # steps == 1 means "one drop from the top straight to the bottom" — dangerous
            divisor = max(1, steps - 1)
            step_drop = max_print_h / divisor
            if step_drop > Z_LIMIT:
                # Recommended step count so that each step drops ≤42mm:
                # max_print_h / (recommended - 1) <= 42  →  recommended >= max_print_h/42 + 1
                import math
                recommended = max(2, int(math.ceil(max_print_h / Z_LIMIT)) + 1)
                return jsonify({
                    "error": "z_collision_step_drop",                # machine code
                    "title":   t_dict("error.z_collision.step_drop.title"),
                    "message": t_dict("error.z_collision.step_drop.message",
                                       print_height=f"{max_print_h:.1f}",
                                       steps=steps,
                                       step_drop=f"{step_drop:.1f}",
                                       z_limit=Z_LIMIT,
                                       recommended=recommended),
                    "print_height": max_print_h,
                    "limit": Z_LIMIT,
                    "current_steps": steps,
                    "step_drop": round(step_drop, 1),
                    "recommended_steps": recommended,
                    "current_method": method,
                }), 409

    try:
        combined = build_combined_gcode(jobs, settings)
    except Exception as e:
        return jsonify({"error": t_dict(
            "error.gcode_generate_failed",
            error_type=type(e).__name__,
            error_message=str(e),
        )}), 500

    # Output filename pattern: bambuloop_YYYYMMDD_HHMMSS_<token>.gcode
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    token = secrets.token_hex(3)
    out_name = f"bambuloop_{timestamp}_{token}.gcode"
    out_path = OUTPUT_DIR / out_name
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(combined)

    total_copies = sum(j.count for j in jobs)
    response = {
        "filename": out_name,
        "size_kb": round(out_path.stat().st_size / 1024, 1),
        "lines": len(combined.split("\n")),
        "total_copies": total_copies,
        "job_count": len(jobs),
    }

    # .3mf repackaging — runs when the first job came from a .3mf and the
    # caller requested want_3mf=True. The result is upload-compatible with
    # Bambu Studio / Handy and preserves the AMS filament assignment.
    want_3mf = bool(data.get("want_3mf", True))    # default True — auto-generate .3mf if source is one
    first_job = jobs_data[0] if jobs_data else {}
    source_3mf_stored = first_job.get("source_3mf_stored")

    if want_3mf and source_3mf_stored:
        source_3mf_path = UPLOAD_DIR / secure_filename(source_3mf_stored)
        if source_3mf_path.is_file():
            from gcode_processor import repackage_3mf
            # Which plate of the original .3mf to replace — taken from the first job
            source_plate_name = first_job.get("source_plate_name", "plate_1")
            out_3mf_name = f"bambuloop_{timestamp}_{token}.gcode.3mf"
            out_3mf_path = OUTPUT_DIR / out_3mf_name
            try:
                repack_info = repackage_3mf(
                    source_3mf_path=str(source_3mf_path),
                    combined_gcode=combined,
                    output_3mf_path=str(out_3mf_path),
                    plate_name=source_plate_name,
                )
                response["filename_3mf"] = out_3mf_name
                response["size_kb_3mf"] = round(out_3mf_path.stat().st_size / 1024, 1)
                response["md5_new"] = repack_info["new_md5"]
                response["md5_source"] = repack_info["source_md5"]
                response["plate_target"] = source_plate_name
            except Exception as e:
                response["repack_error"] = f"{type(e).__name__}: {e}"
        else:
            response["repack_error"] = t_dict(
                "warning.repack.source_3mf_not_found",
                filename=source_3mf_stored,
            )
    elif want_3mf and not source_3mf_stored:
        response["repack_note"] = t_dict("info.repack.gcode_only")

    # Safety validation (margin from settings, default 20mm)
    safety_margin = float(data.get("safety_margin_mm", 20.0))
    try:
        validation = validate_gcode_text(combined, margin=safety_margin,
                                          source_name=out_name)
        # Only the key fields go into the response (full violation list via /api/validate)
        response["safety"] = {
            "verdict": validation["verdict"],
            "verdict_label": validation["verdict_label"],
            "header_note": validation["header_note"],
            "margin_mm": validation["margin_mm"],
            "printable": validation["printable"],
            "physical": validation["physical"],
            "bbox_min": validation["bbox_min"],
            "bbox_max": validation["bbox_max"],
            "total_moves": validation["total_moves"],
            "moves_g0g1": validation["moves_g0g1"],
            "moves_arc": validation["moves_arc"],
            "soft_count": validation["soft_count"],
            "hard_count": validation["hard_count"],
            "soft_violations": validation["soft_violations"][:20],
            "hard_violations": validation["hard_violations"][:20],
        }
    except Exception as e:
        response["safety"] = {"error": f"{type(e).__name__}: {e}"}

    return jsonify(response)


@app.route("/api/download/<path:filename>")
def api_download(filename: str):
    """Download a generated file."""
    safe = secure_filename(filename)
    target = OUTPUT_DIR / safe
    if not target.is_file():
        abort(404)
    return send_from_directory(
        OUTPUT_DIR, safe,
        as_attachment=True,
        download_name=safe,
        mimetype="text/plain",
    )


@app.route("/api/dry_run", methods=["POST"])
def api_dry_run():
    """Build a dry-run G-code that exercises the automation sequences only.

    Body:
        settings: AutomationSettings (same shape as /api/generate)
        sample_stored_name: (optional) stored_name of an uploaded G-code —
                            if provided, its START_GCODE is reused for realism
        simulated_print_height: virtual print height (mm)
        simulated_nozzle_temp:  simulated nozzle temperature
        simulated_bed_temp:     simulated bed temperature
    """
    data = request.get_json(silent=True) or {}
    settings_data = data.get("settings", {})

    def _i(k: str, d: int) -> int:
        try: return int(settings_data.get(k, d))
        except (TypeError, ValueError): return d
    def _f(k: str, d: float) -> float:
        try: return float(settings_data.get(k, d))
        except (TypeError, ValueError): return d
    def _b(k: str, d: bool) -> bool:
        v = settings_data.get(k, d)
        if isinstance(v, bool): return v
        if isinstance(v, str): return v.lower() in ("true", "1", "yes", "on")
        return bool(v)

    settings = AutomationSettings(
        cooling_bed_temp=min(40, max(0, _i("cooling_bed_temp", 35))),
        cooling_retries=max(1, min(30, _i("cooling_retries", 5))),
        cooling_chamber_temp=_i("cooling_chamber_temp", 0),
        part_fan_enabled=_b("part_fan_enabled", True),
        part_fan_speed=_i("part_fan_speed", 255),
        aux_fan_enabled=_b("aux_fan_enabled", True),
        aux_fan_speed=_i("aux_fan_speed", 255),
        chamber_fan_enabled=_b("chamber_fan_enabled", True),
        chamber_fan_speed=_i("chamber_fan_speed", 255),
        cooling_park_z_min=_i("cooling_park_z_min", 80),
        park_z_clearance=_i("park_z_clearance", 10),
        eject_method=str(settings_data.get("eject_method", "edge_to_center")),
        eject_z_offset=_f("eject_z_offset", 0.4),
        eject_z_start_offset=_f("eject_z_start_offset", 8.0),
        eject_descent_steps=_i("eject_descent_steps", 4),
        eject_speed=_i("eject_speed", 9000),
        eject_passes=_i("eject_passes", 11),
        back_overhang_mm=_i("back_overhang_mm", 15),
        front_overhang_mm=_i("front_overhang_mm", 5),
        bed_size_x=_i("bed_size_x", 340),
        bed_size_y=_i("bed_size_y", 320),
        pause_after_eject=_b("pause_after_eject", False),
        nozzle_clean_between=_b("nozzle_clean_between", True),
        rehome_xy_between=_b("rehome_xy_between", True),
        rehome_z_between=_b("rehome_z_between", False),
        purge_between=_b("purge_between", True),
        purge_length_mm=_f("purge_length_mm", 30.0),
        post_print_override_min=_i("post_print_override_min", 0),
        lang=str(settings_data.get("lang", "ko")),
        sound_print_start=str(settings_data.get("sound_print_start", "")),
        sound_print_done=str(settings_data.get("sound_print_done", "chime_high")),
        sound_cool_done=str(settings_data.get("sound_cool_done", "chime_low")),
        sound_sweep_done=str(settings_data.get("sound_sweep_done", "ascend_fifth")),
        sound_restart=str(settings_data.get("sound_restart", "ascend_minor")),
        sound_print_end=str(settings_data.get("sound_print_end", "")),
        custom_melodies=settings_data.get("custom_melodies", {}) or {},
    )

    sim_height = float(data.get("simulated_print_height", 40.0))
    sim_nozzle = int(data.get("simulated_nozzle_temp", 220))
    sim_bed = int(data.get("simulated_bed_temp", 55))
    sample_stored = data.get("sample_stored_name")

    # Dry-run phase options (all phases included by default)
    phases = data.get("phases", {})
    include_cooling = bool(phases.get("include_cooling", True))
    wait_for_cooling = bool(phases.get("wait_for_cooling", True))
    include_eject = bool(phases.get("include_eject", True))
    include_reheat = bool(phases.get("include_reheat", True))
    wait_for_reheat = bool(phases.get("wait_for_reheat", True))
    include_reset = bool(phases.get("include_reset", True))
    minimal_start = bool(phases.get("minimal_start", False))
    skip_ams_load = bool(phases.get("skip_ams_load", False))
    cycles = max(1, min(int(phases.get("cycles", 1)), 10))

    # Optional: use an uploaded file as the sample (gives a realistic start_gcode)
    sample_parser = None
    if sample_stored:
        sample_path = UPLOAD_DIR / sample_stored
        if sample_path.is_file():
            with open(sample_path, "r", encoding="utf-8", errors="ignore") as gf:
                sample_parser = BambuGcodeParser(gf.read(), sample_stored)

    try:
        gcode = build_dry_run_gcode(
            settings=settings,
            simulated_print_height=sim_height,
            simulated_nozzle_temp=sim_nozzle,
            simulated_bed_temp=sim_bed,
            sample_parser=sample_parser,
            include_cooling=include_cooling,
            wait_for_cooling=wait_for_cooling,
            include_eject=include_eject,
            include_reheat=include_reheat,
            wait_for_reheat=wait_for_reheat,
            include_reset=include_reset,
            minimal_start=minimal_start,
            skip_ams_load=skip_ams_load,
            cycles=cycles,
        )
    except Exception as e:
        return jsonify({"error": t_dict(
            "error.dry_run_generate_failed",
            error_type=type(e).__name__,
            error_message=str(e),
        )}), 500

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    token = secrets.token_hex(3)
    out_name = f"DRYRUN_{timestamp}_{token}.gcode"
    out_path = OUTPUT_DIR / out_name
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(gcode)

    # Safety validation
    safety_margin = float(data.get("safety_margin_mm", 20.0))
    safety_block = None
    try:
        validation = validate_gcode_text(gcode, margin=safety_margin,
                                          source_name=out_name)
        safety_block = {
            "verdict": validation["verdict"],
            "verdict_label": validation["verdict_label"],
            "header_note": validation["header_note"],
            "margin_mm": validation["margin_mm"],
            "printable": validation["printable"],
            "physical": validation["physical"],
            "bbox_min": validation["bbox_min"],
            "bbox_max": validation["bbox_max"],
            "total_moves": validation["total_moves"],
            "moves_g0g1": validation["moves_g0g1"],
            "moves_arc": validation["moves_arc"],
            "soft_count": validation["soft_count"],
            "hard_count": validation["hard_count"],
            "soft_violations": validation["soft_violations"][:20],
            "hard_violations": validation["hard_violations"][:20],
        }
    except Exception as e:
        safety_block = {"error": f"{type(e).__name__}: {e}"}

    return jsonify({
        "filename": out_name,
        "size_kb": round(out_path.stat().st_size / 1024, 1),
        "lines": len(gcode.split("\n")),
        "used_sample_start": sample_parser is not None,
        "safety": safety_block,
    })


@app.route("/api/validate", methods=["POST"])
def api_validate():
    """Run safety validation on an existing output file or raw G-code text.

    Body:
        filename:        file name inside the output directory (optional)
        gcode_text:      G-code string to validate (optional; lower priority than `filename`)
        margin_mm:       safety margin in mm (default 20)
        max_violations:  maximum violations to report (default 200)
    """
    body = request.get_json(silent=True) or {}
    margin = float(body.get("margin_mm", 20.0))
    max_v = int(body.get("max_violations", 200))
    filename = body.get("filename")
    gcode_text = body.get("gcode_text")

    source_name = "(in-memory)"
    if filename:
        # Look up both .3mf and .gcode in OUTPUT_DIR and UPLOAD_DIR
        candidates = [OUTPUT_DIR / filename, UPLOAD_DIR / filename]
        target = next((p for p in candidates if p.is_file()), None)
        if not target:
            return jsonify({"error": t_dict("error.file_not_found", filename=filename)}), 404
        source_name = filename
        if str(target).endswith(".3mf"):
            # Extract a plate_*.gcode entry from inside the .3mf
            import zipfile
            try:
                with zipfile.ZipFile(target) as zf:
                    cands = sorted([n for n in zf.namelist()
                                    if n.startswith("Metadata/")
                                    and n.endswith(".gcode")
                                    and not n.endswith(".gcode.md5")])
                    if not cands:
                        return jsonify({"error": t_dict("error.no_gcode_inside_3mf")}), 400
                    gcode_text = zf.read(cands[0]).decode("utf-8", errors="replace")
                    source_name = f"{filename}!{cands[0]}"
            except Exception as e:
                return jsonify({"error": t_dict(
                    "error.3mf_read_failed",
                    error_message=str(e),
                )}), 500
        else:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                gcode_text = f.read()

    if not gcode_text:
        return jsonify({"error": t_dict("error.filename_or_text_required")}), 400

    try:
        result = validate_gcode_text(gcode_text, margin=margin,
                                      max_violations=max_v,
                                      source_name=source_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/sound_presets")
def api_sound_presets():
    """List the available sound presets with note data (for UI preview).

    `desc` is forwarded as a {ko, en} dict so the UI can pick by currentLang.
    """
    presets = [
        {"key": name,
         "desc": pattern.get("desc", ""),  # may be a dict or a plain str
         "notes": pattern.get("notes", [])}
        for name, pattern in PRESET_PATTERNS.items()
    ]
    return jsonify({"presets": presets, "count": len(presets)})


@app.route("/api/sound_catalog", methods=["POST"])
def api_sound_catalog():
    """Build a sound-preset catalog G-code.

    Body (JSON):
        mode:            "all" | "builtin" | "custom"  (default "all")
        custom_melodies: {"<name>": [[midi, dur], ...], ...}  (optional)
        single_preset:   "preset_name"  (optional, preview one preset only)
        single_notes:    [[midi, dur], ...]  (optional, ad-hoc melody preview)
    """
    body = request.get_json(silent=True) or {}
    mode = body.get("mode", "all")
    custom_melodies = body.get("custom_melodies", {}) or {}
    single_preset = body.get("single_preset")
    single_notes = body.get("single_notes")
    lang = body.get("lang", "ko")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    token = secrets.token_hex(3)

    # Catalog title (per-language pick from i18n)
    preview_title_dict = t_dict("sound.preview.adhoc_title")
    preset_preview_title_dict = t_dict("sound.preview.preset_title")
    # The catalog G-code is emitted in one language at a time (a single
    # header comment is written, not both KO and EN). Default to KO when the
    # caller does not specify, matching legacy behaviour.
    preview_title = preview_title_dict.get(lang, preview_title_dict.get("en", ""))
    preset_preview_title = preset_preview_title_dict.get(lang, preset_preview_title_dict.get("en", ""))
    preview_label_dict = t_dict("sound.preview.label")
    preview_label = preview_label_dict.get(lang, preview_label_dict.get("en", "Preview"))

    # Single-melody preview mode
    if single_notes:
        out_name = f"preview_{timestamp}_{token}.gcode"
        gcode = "\n".join([
            f"; {preview_title}",
            "M17", "M400 S2",
            generate_sound_event("__preview__",
                                  label=preview_label,
                                  include_motor_init=False,
                                  custom_melodies={"__preview__": single_notes},
                                  lang=lang),
            "M400", "M18",
        ])
        item_count = 1
    elif single_preset:
        out_name = f"preview_{timestamp}_{token}.gcode"
        gcode = "\n".join([
            f"; {preset_preview_title}",
            "M17", "M400 S2",
            generate_sound_event(single_preset, label=preview_label,
                                  include_motor_init=False,
                                  custom_melodies=custom_melodies,
                                  lang=lang),
            "M400", "M18",
        ])
        item_count = 1
    else:
        out_name = f"sound_catalog_{mode}_{timestamp}_{token}.gcode"
        gcode = generate_sound_catalog_gcode(mode=mode, custom_melodies=custom_melodies, lang=lang)
        if mode == "custom":
            item_count = len(custom_melodies)
        elif mode == "builtin":
            item_count = len(PRESET_PATTERNS)
        else:
            item_count = len(PRESET_PATTERNS) + len(custom_melodies)

    out_path = OUTPUT_DIR / out_name
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(gcode)

    return jsonify({
        "filename": out_name,
        "size_kb": round(out_path.stat().st_size / 1024, 1),
        "lines": len(gcode.split("\n")),
        "item_count": item_count,
        "mode": mode,
    })


@app.route("/api/delete_upload", methods=["POST"])
def api_delete_upload():
    """Delete a single uploaded file (used when an upload is rejected)."""
    body = request.get_json(silent=True) or {}
    stored = body.get("stored_name")
    if not stored:
        return jsonify({"error": t_dict("error.delete.stored_name_required")}), 400
    target = UPLOAD_DIR / stored
    if not target.is_file():
        return jsonify({"ok": True, "note": "already gone"})
    try:
        target.unlink()
        # Also remove the original .3mf if it was kept alongside the plates
        for sibling in UPLOAD_DIR.glob(stored.replace(".gcode", "") + "*"):
            if sibling.is_file():
                try: sibling.unlink()
                except OSError: pass
        return jsonify({"ok": True})
    except OSError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Empty both the upload and output directories."""
    for d in (UPLOAD_DIR, OUTPUT_DIR):
        for p in d.iterdir():
            if p.is_file():
                p.unlink()
    return jsonify({"ok": True})


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("BambuLoop — Bambu Lab H2S Auto-Repeat Print Tool")
    print("=" * 60)
    print(f"  Upload dir  : {UPLOAD_DIR}")
    print(f"  Output dir  : {OUTPUT_DIR}")
    print(f"  Server      : http://localhost:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)
