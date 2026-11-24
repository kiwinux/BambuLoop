"""File-backed job operations shared by the local API and the browser worker."""

from __future__ import annotations

import math
from pathlib import Path
import re
import secrets
import shutil
import time
import zipfile

from gcode_processor import (
    ArchiveSizeLimit, AutomationSettings, BambuGcodeParser, EjectClearanceError, H2S_HEAD_RAIL_LIMIT,
    JobConfig, PRESET_PATTERNS, build_combined_gcode, build_dry_run_gcode,
    generate_sound_catalog_gcode, generate_sound_event, repackage_3mf, sliced_plates,
)
from build_plate import ArchiveSurfaces, PlateCheckFormatError, has_plate_check
from gcode_validator import first_plate, parse_warning_margin, validate_gcode_text
from i18n_helper import t_dict

INPUT_LIMIT = 200 * 1024 * 1024
EXTENSIONS = {".gcode", ".gco", ".g", ".3mf"}


class JobError(ValueError):
    def __init__(self, payload, status=400):
        super().__init__(str(payload.get("error", "")))
        self.payload = payload
        self.status = status


def field_error(key, status=400, **values):
    return JobError({"error": t_dict(key, **values)}, status)


def _margin(value):
    try:
        return parse_warning_margin(value)
    except ValueError:
        raise field_error("error.invalid_warning_margin") from None


def _clearance_error(error):
    height, settings, limit = error.height, error.settings, H2S_HEAD_RAIL_LIMIT
    key = "error.z_collision." + error.reason
    details = {"print_height": height, "limit": limit}
    values = {"print_height": f"{height:.1f}", "z_limit": limit}
    if error.reason == "unknown_height":
        values["filename"] = error.filename
    elif error.reason == "bottom_mode":
        details["current_method"] = settings.eject_method
        values["z_offset"] = settings.eject_z_offset
    else:
        steps = max(1, settings.eject_descent_steps)
        drop = height / max(1, steps - 1)
        recommended = math.ceil(height / limit) + 1
        details.update(current_steps=steps, step_drop=round(drop, 1), recommended_steps=recommended)
        values.update(steps=steps, step_drop=f"{drop:.1f}", recommended=recommended)
    return JobError(dict(error="z_collision_" + error.reason, title=t_dict(key + ".title"),
                         message=t_dict(key + ".message", **values), **details), 409)


def parse_settings(settings_data):
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

    return AutomationSettings(
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
        verify_build_plate=_b("verify_build_plate", True),
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


def _file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or name in (".", "..") or any(c in name for c in "/\\:\0"):
        raise field_error("error.file_not_found", 404, filename=name or "")
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise field_error("error.file_not_found", 404, filename=name)
    return path


def _output_name(prefix, extension=".gcode"):
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(5)}{extension}"


def _plate_check_result(text, requested):
    if has_plate_check(text):
        return "once"
    return "absent" if requested else "off"


def _report(text, name, margin):
    try:
        report = validate_gcode_text(text, margin=margin, source_name=name)
        for kind in ("expected_moves", "soft_violations", "hard_violations"):
            report[kind] = report[kind][:20]
        return report
    except (ValueError, ArithmeticError) as error:
        return {"error": str(error)}


def _compatible(jobs, force):
    first = jobs[0]
    warnings = []
    for job in jobs[1:]:
        base, other = first.temps, job.temps
        hardware_mismatch = (
            base.nozzle_diameter and other.nozzle_diameter and abs(base.nozzle_diameter - other.nozzle_diameter) > 0.001
            or base.nozzle_flow_type and other.nozzle_flow_type and base.nozzle_flow_type != other.nozzle_flow_type
            or base.nozzle_hrc and other.nozzle_hrc and base.nozzle_hrc != other.nozzle_hrc
        )
        if hardware_mismatch:
            raise field_error("error.hardware_mismatch", 409, filename=job.filename, first_filename=first.filename)
        if force:
            continue
        names = dict(filename=job.filename, first_filename=first.filename)
        if abs(base.nozzle - other.nozzle) > 10:
            warnings.append(t_dict("compat.warning.nozzle_temp_diff", **names, temp=other.nozzle,
                                   first_temp=base.nozzle, diff=abs(base.nozzle - other.nozzle)))
        if abs(base.bed - other.bed) > 5:
            warnings.append(t_dict("compat.warning.bed_temp_diff", **names, temp=other.bed, first_temp=base.bed))
        if base.filament_type and other.filament_type and base.filament_type != other.filament_type:
            warnings.append(t_dict("compat.warning.filament_type_diff", **names,
                                   filament_type=other.filament_type, first_filament_type=base.filament_type))
    if warnings:
        raise JobError(dict(error="incompatible_jobs", title=t_dict("compat.warning.title"),
                            message=t_dict("compat.warning.main_message"), warnings=warnings,
                            first_job=dict(filename=first.filename, nozzle=first.temps.nozzle,
                                           bed=first.temps.bed, filament_type=first.temps.filament_type),
                            hint=t_dict("compat.warning.hint")), 409)


class JobFiles:
    def __init__(self, uploads, outputs, *, byte_budget=None):
        self.uploads = Path(uploads)
        self.outputs = Path(outputs)
        self.byte_budget = byte_budget

    def stage(self, original):
        ext = Path(original).suffix.lower()
        if ext not in EXTENSIONS:
            raise field_error("error.unsupported_extension")
        return secrets.token_hex(12) + ext

    def _budget(self, nbytes):
        if self.byte_budget is not None and nbytes > self.byte_budget:
            raise field_error("error.browser_size", 413, mib=self.byte_budget // 1024**2)

    def check_input_capacity(self, incoming=0):
        if self.byte_budget is None:
            return 0
        held = sum(p.stat().st_size for p in self.uploads.iterdir() if p.is_file())
        self._budget(held + incoming)
        return held

    def _plate_info(self, path, display, surfaces=None, plate_number=None):
        text = path.read_text(encoding="utf-8", errors="ignore")
        info = BambuGcodeParser(text, display, surfaces=surfaces, plate_number=plate_number).get_info()
        info.update(stored_name=path.name, original_name=display, size_kb=round(path.stat().st_size / 1024, 1))
        return info

    def import_staged(self, original, stored):
        path = _file(self.uploads, stored)
        produced = []
        files, errors = [], []
        try:
            held = self.check_input_capacity()
            if path.suffix.lower() != ".3mf":
                info = self._plate_info(path, original)
                info["from_3mf"] = None
                return {"files": [info], "errors": []}
            with zipfile.ZipFile(path) as archive:
                members = sliced_plates(archive.namelist())
                if not members:
                    raise field_error("error.no_gcode_in_3mf")
                self._budget(sum(i.file_size for i in archive.infolist()))
                surfaces = ArchiveSurfaces(archive)
                base = re.sub(r"(?:\.gcode)?\.3mf$", "", original, flags=re.I)
                self._budget(held + sum(archive.getinfo(entry).file_size for _, entry in members))
                for number, entry in members:
                    plate = f"plate_{number}"
                    member_path = self.uploads / f"{path.stem}__{plate}.gcode"
                    display = (base if len(members) == 1 else f"{base}__{plate}") + ".gcode"
                    produced.append(member_path)
                    with archive.open(entry) as src, member_path.open("wb") as out:
                        shutil.copyfileobj(src, out)
                    try:
                        info = self._plate_info(member_path, display, surfaces, number)
                    except ValueError as error:
                        errors.append({"filename": display, "message": t_dict("error.parse_failed",
                                       error_type=type(error).__name__, error_message=str(error))})
                        member_path.unlink(missing_ok=True)
                        continue
                    info.update(from_3mf=original, source_3mf_stored=stored, source_plate_name=plate)
                    files.append(info)
            if not files:
                path.unlink(missing_ok=True)
            return {"files": files, "errors": errors}
        except Exception as error:
            for member in produced:
                member.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            if isinstance(error, JobError):
                raise
            key = "error.3mf_extract_failed" if path.suffix == ".3mf" else "error.parse_failed"
            raise field_error(key, error_type=type(error).__name__, error_message=str(error)) from error

    def delete_upload(self, data):
        name = data.get("stored_name")
        if not name:
            raise field_error("error.delete.stored_name_required")
        try:
            path = _file(self.uploads, name)
        except JobError:
            return {"ok": True, "note": "already gone"}
        path.unlink(missing_ok=True)
        plate = re.fullmatch(r"([0-9a-f]{24})__plate_\d+\.gcode", name)
        if plate and not any(self.uploads.glob(plate[1] + "__plate_*.gcode")):
            (self.uploads / (plate[1] + ".3mf")).unlink(missing_ok=True)
        return {"ok": True}

    def _write_gcode(self, prefix, text, margin=None):
        encoded = text.encode("utf-8")
        self._budget(len(encoded))
        name = _output_name(prefix)
        path = self.outputs / name
        try:
            path.write_bytes(encoded)
        except OSError:
            path.unlink(missing_ok=True)
            raise
        result = dict(filename=name, size_kb=round(path.stat().st_size / 1024, 1), lines=text.count("\n") + 1)
        if margin is not None:
            result["safety"] = _report(text, name, margin)
        return result

    def _parse_stored(self, path, display, hints, cache):
        # New imports encode the source archive and numeric plate in the stored name.
        # Old API callers can still supply the original source fields.
        handle = re.fullmatch(r"([0-9a-f]{24})__plate_(\d+)\.gcode", path.name, re.I)
        if handle:
            archive_name, number = handle[1] + ".3mf", int(handle[2])
        else:
            archive_name = hints.get("source_3mf_stored")
            hint = re.fullmatch(r"plate_(\d+)", hints.get("source_plate_name") or "", re.I)
            legacy = re.search(r"__plate_(\d+)__[0-9a-f]{8}\.gcode$", path.name, re.I)
            number = int((legacy or hint)[1]) if legacy or hint else None
        surfaces = None
        if archive_name:
            if archive_name not in cache:
                try:
                    original = _file(self.uploads, archive_name)
                except JobError:
                    cache[archive_name] = None
                else:
                    with zipfile.ZipFile(original) as archive:
                        cache[archive_name] = ArchiveSurfaces(archive), dict(sliced_plates(archive.namelist()))
            record = cache[archive_name]
            if record is not None:
                surfaces, plates = record
                if not handle and len(plates) == 1:
                    number = next(iter(plates))
                if number not in plates:
                    raise field_error("error.source_plate_unknown", filename=display)
        parser = BambuGcodeParser(path.read_text(encoding="utf-8", errors="ignore"), display,
                                  surfaces=surfaces, plate_number=number)
        return parser, archive_name, number

    def generate(self, data):
        margin = _margin(data.get("safety_margin_mm", 0))
        requested = data.get("jobs") or []
        if not requested:
            raise field_error("error.no_jobs")
        jobs, estimated = [], 0
        archive_cache = {}
        first_source = (None, None)
        for item in requested:
            stored = item.get("stored_name")
            if not stored:
                raise field_error("error.missing_stored_name")
            try:
                path = _file(self.uploads, stored)
            except JobError:
                raise field_error("error.upload_file_not_found", 404, filename=stored)
            count = max(1, int(item.get("count", 1)))
            estimated += path.stat().st_size * count
            self._budget(estimated)
            display = item.get("original_name") or stored
            parsed, original, number = self._parse_stored(path, display, item, archive_cache)
            if not jobs:
                first_source = original, number
            jobs.append(JobConfig(display, count, parsed.sections, parsed.temps))
        _compatible(jobs, data.get("force_compatibility", False))
        settings = parse_settings(data.get("settings") or {})
        try:
            combined = build_combined_gcode(jobs, settings)
        except EjectClearanceError as error:
            raise _clearance_error(error) from error
        except PlateCheckFormatError as error:
            raise field_error("error.plate_check_format") from error
        result = self._write_gcode("bambuloop", combined, margin)
        result.update(total_copies=sum(j.count for j in jobs), job_count=len(jobs),
                      bed_type=jobs[0].temps.bed_type,
                      plate_check=_plate_check_result(combined, settings.verify_build_plate))
        if not data.get("want_3mf", True):
            return result
        archive_name, number = first_source
        if not archive_name:
            result["repack_note"] = t_dict("info.repack.gcode_only")
            return result
        try:
            original = _file(self.uploads, archive_name)
        except JobError:
            result["repack_error"] = t_dict("warning.repack.source_3mf_not_found", filename=archive_name)
            return result
        target = self.outputs / (result["filename"] + ".3mf")
        plate = f"plate_{number}"
        try:
            info = repackage_3mf(original, combined, target, plate_name=plate,
                                 max_uncompressed_bytes=self.byte_budget)
            result.update(filename_3mf=target.name, size_kb_3mf=round(target.stat().st_size / 1024, 1),
                          md5_new=info["new_md5"], md5_source=info["source_md5"], plate_target=plate)
        except Exception as error:
            target.unlink(missing_ok=True)
            if isinstance(error, ArchiveSizeLimit):
                result["repack_error"] = t_dict("error.repack_size", mib=self.byte_budget // 1024**2)
            else:
                result["repack_error"] = t_dict("error.repack_failed", error_message=str(error))
        return result

    def dry_run(self, data):
        margin = _margin(data.get("safety_margin_mm", 0))
        settings = parse_settings(data.get("settings") or {})
        phases = data.get("phases") or {}
        opts = {key: bool(phases.get(key, default)) for key, default in (
            ("include_cooling", True), ("wait_for_cooling", True), ("include_eject", True),
            ("include_reheat", True), ("wait_for_reheat", True), ("include_reset", True),
            ("minimal_start", False), ("skip_ams_load", False))}
        sample_name = data.get("sample_stored_name")
        value = data.get("simulated_print_height", 40.0)
        if value is None and opts["include_eject"] and settings.eject_method != "none":
            raise _clearance_error(EjectClearanceError("unknown_height", 0, settings, sample_name or "—"))
        try:
            height = float(value) if value is not None else 0.0
            if not math.isfinite(height) or height < 0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise field_error("error.invalid_print_height")
        sample = None
        if sample_name:
            path = _file(self.uploads, sample_name)
            sample, _, _ = self._parse_stored(path, sample_name, data, {})
        try:
            text = build_dry_run_gcode(settings, height, int(data.get("simulated_nozzle_temp", 220)),
                                       int(data.get("simulated_bed_temp", 55)), sample,
                                       cycles=max(1, min(10, int(phases.get("cycles", 1)))), **opts)
        except EjectClearanceError as error:
            raise _clearance_error(error) from error
        except PlateCheckFormatError as error:
            raise field_error("error.plate_check_format") from error
        result = self._write_gcode("DRYRUN", text, margin)
        result.update(used_sample_start=sample is not None, bed_type=sample.temps.bed_type if sample else "",
                      plate_check=_plate_check_result(text, settings.verify_build_plate))
        return result

    def validate(self, data):
        margin = _margin(data.get("margin_mm", 0))
        filename = data.get("filename")
        text, source = data.get("gcode_text"), "(in-memory)"
        if filename:
            try:
                target = _file(self.outputs, filename)
            except JobError:
                target = _file(self.uploads, filename)
            source = filename
            if target.suffix.lower() == ".3mf":
                try:
                    with zipfile.ZipFile(target) as archive:
                        requested = data.get("plate_name")
                        if requested:
                            plate = re.fullmatch(r"plate_(\d+)", requested, re.I)
                            member = dict(sliced_plates(archive.namelist())).get(int(plate[1])) if plate else None
                            if member is None:
                                raise field_error("error.source_plate_unknown", filename=filename)
                        else:
                            member = first_plate(archive.namelist())
                        if member is None:
                            raise field_error("error.no_gcode_inside_3mf")
                        self._budget(archive.getinfo(member).file_size)
                        text = archive.read(member).decode("utf-8", errors="replace")
                        source = f"{filename}!{member}"
                except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
                    if isinstance(error, JobError):
                        raise
                    raise field_error("error.3mf_read_failed", error_type=type(error).__name__, error_message=str(error)) from error
            else:
                text = target.read_text(encoding="utf-8", errors="replace")
        if not text:
            raise field_error("error.filename_or_text_required")
        return validate_gcode_text(text, margin, int(data.get("max_violations", 200)), source)

    def sound_presets(self, data):
        presets = [dict(key=key, desc=value.get("desc", ""), notes=value.get("notes", []))
                   for key, value in PRESET_PATTERNS.items()]
        return dict(presets=presets, count=len(presets))

    def sound_catalog(self, data):
        mode = data.get("mode", "all")
        if mode not in ("all", "builtin", "custom"):
            raise ValueError("Unknown catalog mode")
        custom = data.get("custom_melodies") or {}
        preset, notes, lang = data.get("single_preset"), data.get("single_notes"), data.get("lang", "ko")
        if notes or preset:
            key = "__preview__" if notes else preset
            translations = t_dict("sound.preview.adhoc_title" if notes else "sound.preview.preset_title")
            labels = t_dict("sound.preview.label")
            event = generate_sound_event(key, label=labels.get(lang, labels["en"]), include_motor_init=False,
                                         custom_melodies={key: notes} if notes else custom, lang=lang)
            text = "\n".join(["; " + translations.get(lang, translations["en"]), "M17", "M400 S2", event, "M400", "M18"])
            result, count = self._write_gcode("preview", text), 1
        else:
            text = generate_sound_catalog_gcode(mode=mode, custom_melodies=custom, lang=lang)
            count = (len(custom) if mode != "builtin" else 0) + (len(PRESET_PATTERNS) if mode != "custom" else 0)
            result = self._write_gcode("sound_catalog_" + mode, text)
        result.update(item_count=count, mode=mode)
        return result


OPERATIONS = ("generate", "dry_run", "validate", "sound_presets", "sound_catalog", "delete_upload")


def dispatch(store, action, data):
    """Return a status and JSON payload for either transport."""
    if action not in OPERATIONS:
        return 404, {"error": "Unknown operation"}
    try:
        if not isinstance(data, dict):
            raise ValueError("Expected an object")
        return 200, getattr(store, action)(data)
    except JobError as error:
        return error.status, error.payload
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        return 400, {"error": str(error)}
