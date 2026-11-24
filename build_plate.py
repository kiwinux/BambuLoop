"""Bambu Studio build-surface provenance and H2S build-plate detection."""

from __future__ import annotations

import json
import re
from typing import NamedTuple
from xml.etree import ElementTree as ET


# Bambu Studio's BedType names and the identifiers used in its sliced plate JSON.
BED_NAMES = {
    "cool_plate": "Cool Plate",
    "eng_plate": "Engineering Plate",
    "hot_plate": "High Temp Plate",
    "textured_plate": "Textured PEI Plate",
    "supertack_plate": "Supertack Plate",
}
_BED_IDS = {name.casefold(): key for key, name in BED_NAMES.items()}


def surface_name(value) -> str:
    value = value.strip() if isinstance(value, str) else ""
    if not value or not value.isprintable():
        return ""
    if value.casefold() in ("default", "default plate"):
        return ""
    key = value.casefold()
    return BED_NAMES.get(_BED_IDS.get(key, key), value)


def surface_id(name: str) -> str:
    return _BED_IDS.get(surface_name(name).casefold(), "")


def sliced_surface(lines):
    """Read the slice's own configuration before the executable toolpath."""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(";") or line.upper() in ("; CONFIG_BLOCK_END", "; EXECUTABLE_BLOCK_START", "; LAYER_CHANGE", "; CHANGE_LAYER"):
            break
        match = re.fullmatch(r";[ \t]*curr_bed_type[ \t]*=[ \t]*(.*)", line, re.I)
        if match:
            return match[1].strip()
    return ""


class Surface(NamedTuple):
    config_name: str
    wire_id: str


class ArchiveSurfaces:
    """Read the specific sliced bed, per-plate override and project default once."""
    def __init__(self, archive):
        names = {n.casefold(): n for n in archive.namelist()}
        self.metadata = {}
        self.project_path = names.get("metadata/project_settings.config")
        self.model_path = names.get("metadata/model_settings.config")
        self.project = None
        self.model = None
        self.nodes = {}
        for name in archive.namelist():
            match = re.fullmatch(r"Metadata/plate_(\d+)\.json", name, re.I)
            if match:
                self.metadata[int(match[1])] = self._json(archive, name) or {}
        if self.project_path:
            self.project = self._json(archive, self.project_path)
        if self.model_path:
            try:
                parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
                self.model = ET.fromstring(archive.read(self.model_path), parser=parser)
            except (ET.ParseError, ValueError):
                return
            for node in self.model.findall("./{*}plate"):
                field = node.find("{*}metadata[@key='plater_id']")
                if field is not None and field.get("value", "").isdigit():
                    self.nodes[int(field.get("value"))] = node

    @staticmethod
    def _json(archive, name):
        try:
            value = json.loads(archive.read(name))
            return value if isinstance(value, dict) else None
        except (ValueError, UnicodeError):
            return None

    def selected(self, number: int, sliced_name: str = "") -> Surface:
        node = self.nodes.get(number)
        field = node.find("{*}metadata[@key='bed_type']") if node is not None else None
        original = self.metadata.get(number, {}).get("bed_type")
        wire = original.strip() if surface_name(original) else ""
        # A future wire ID may have no known Studio enum. Keep its original
        # JSON spelling and only write a config name supplied by the source.
        config = (BED_NAMES.get(surface_id(wire), "")
                  or surface_name(field.get("value") if field is not None else None)
                  or surface_name(sliced_name))
        if not wire and not config:
            config = surface_name((self.project or {}).get("curr_bed_type"))
        return Surface(config, wire or surface_id(config))

    def package_settings(self, numbers, surface: Surface):
        """The output slots all contain the first job. Match their Studio overrides."""
        replacements = {}
        selected = surface.config_name
        if self.project is not None:
            project = self.project.copy()
            if selected:
                project["curr_bed_type"] = selected
            elif surface.wire_id:
                project.pop("curr_bed_type", None)
            if project != self.project:
                replacements[self.project_path] = json.dumps(project, ensure_ascii=False).encode()
        changed = False
        for number in numbers:
            node = self.nodes.get(number)
            if node is None:
                continue
            field = node.find("{*}metadata[@key='bed_type']")
            if not selected:
                if field is not None:
                    node.remove(field)
                    changed = True
                continue
            if field is None:
                # Missing means inherit the project default.
                if self.project is not None:
                    continue
                field = ET.SubElement(node, node.find("{*}metadata[@key='plater_id']").tag, key="bed_type")
            if field.get("value") != selected:
                field.set("value", selected)
                changed = True
        if changed:
            replacements[self.model_path] = ET.tostring(self.model, encoding="utf-8", xml_declaration=True)
        return replacements


_FLAG = re.compile(r"M1002\s+JUDGE_FLAG\s+BUILD_PLATE_DETECT_FLAG\Z")
_OPEN = re.compile(r"M622(?=\s|[JS]\d|$)")
_CLOSE = re.compile(r"M623(?=\s|$)")
_PLATE_OP = re.compile(r"^M972(?=\s|[A-Z][+-]?\d).*?S(19|31|34)(?:\.0+)?(?=[A-Z\s]|$)")
_ACTION = re.compile(r"M1002\s+GCODE_CLAIM_ACTION\s*:\s*(11|73)\Z")
_HINT = re.compile(r"^[ \t]*(?:N\d+[ \t]*)?(?:M1002[ \t]+judge_flag[ \t]+build_plate_detect_flag\b|M972(?=[ \tA-Z])[^;\r\n]*?S(?:19|34)(?=[\sA-Z.;]|$))", re.I | re.M)


_ACTIVE_DETECT = re.compile(r"^[ \t]*(?:N\d+[ \t]*)?M972(?=[ \tA-Z])[^;\r\n]*?S(?:19|34)(?:\.0+)?(?=[ \tA-Z;\r\n*]|$)", re.I | re.M)


class PlateCheckFormatError(ValueError):
    """A named plate-check conditional cannot be edited without changing its neighbours."""


def _command(line):
    code = line.partition(";")[0].strip().upper()
    if code.startswith("N"):
        code = re.sub(r"^N\d+\s*", "", code)
    return code.partition("*")[0].strip()


def _next_code(lines, i):
    while i < len(lines) and not _command(lines[i]):
        i += 1
    return i


def _branch_end(lines, start):
    depth = 1
    for i in range(start + 1, len(lines)):
        if re.match(r"^\s*;\s*(?:=+\s*detection end\b|(?:MACHINE_START_GCODE_END|CHANGE_LAYER|LAYER_CHANGE)\b)", lines[i], re.I):
            break
        code = _command(lines[i])
        if _OPEN.match(code):
            depth += 1
        elif _CLOSE.match(code):
            depth -= 1
            if depth == 0:
                return i + 1
    raise PlateCheckFormatError("Unclosed build-plate check (M622/M623).")


def _plate_instruction(code):
    op = _PLATE_OP.match(code)
    if op:
        return "camera" if op[1] == "31" else op[1]
    return "label" if _ACTION.fullmatch(code) else ""


def _bare_group(lines, begin, stop=None, *, camera_lead=False):
    """Return only instructions belonging to one identification/alignment routine."""
    targets, pending = [], []
    last = begin
    identified = False
    for i in range(begin, len(lines) if stop is None else stop):
        code = _command(lines[i])
        if not code or code.split()[0] in ("M400", "M73"):
            continue
        kind = _plate_instruction(code)
        if kind == "label":
            if identified and _ACTION.fullmatch(code)[1] == "11":
                break
            pending.append((i, "19" if _ACTION.fullmatch(code)[1] == "11" else "34"))
        elif kind == "camera" and (identified or camera_lead):
            # The standalone camera test is also used for other operations.
            # Only associate it with this check when followed by plate alignment.
            pending.append((i, "34"))
        elif kind in ("19", "34"):
            if kind == "19" and identified:
                break
            targets.extend(n for n, stage in pending if stage == kind)
            pending.clear()
            targets.append(i)
            last = i + 1
            if kind == "34":
                break
            identified = True
        else:
            break
    return last, targets


def _prune_group(lines, targets, available):
    kinds = {i: _plate_instruction(_command(lines[i])) for i in targets}
    stages = set(kinds.values()) & {"19", "34"}
    keep = stages & available
    available.difference_update(stages)
    removed = set()
    for i, kind in kinds.items():
        if kind == "camera":
            kind = "34"  # adjacent camera and plate alignment
        elif kind == "label":
            kind = "19" if _ACTION.fullmatch(_command(lines[i]))[1] == "11" else "34"
        if kind not in keep:
            removed.add(i)
    return removed


def _branches(lines, opener, stop):
    while opener < stop and _OPEN.match(_command(lines[opener])):
        end = _branch_end(lines, opener)
        if end > stop:
            raise PlateCheckFormatError("Overlapping build-plate conditionals.")
        yield opener, end
        opener = _next_code(lines, end)


def _prune_branches(lines, opener, stop, available, *, outer):
    # J1 and J0 are alternate paths: each can keep the first identification
    # and alignment. Repeated branches with the same sense share a budget.
    initial = available.copy()
    by_sense = {}
    removed = set()
    for left, end in _branches(lines, opener, stop):
        predicate = re.search(r"[SJ]\s*([01])\b", _command(lines[left]))
        sense = predicate[1] if predicate else ""
        budget = by_sense.setdefault(sense, initial.copy())
        branch_removed = set()
        i = left + 1
        while i < end - 1:
            code = _command(lines[i])
            if _OPEN.match(code):
                nested, i = _prune_branches(lines, i, end - 1, budget, outer=False)
                branch_removed.update(nested)
                continue
            kind = _plate_instruction(code)
            if kind in ("19", "34", "label") or (outer and kind == "camera"):
                after, targets = _bare_group(lines, i, end - 1, camera_lead=outer)
                if targets:
                    branch_removed.update(_prune_group(lines, targets, budget))
                    i = after
                    continue
            i += 1
        if branch_removed and not any(_command(lines[n]) and not re.fullmatch(r"M400(?:\s.*)?", _command(lines[n]))
                                      for n in range(left + 1, end - 1) if n not in branch_removed):
            branch_removed.update(range(left, end))
        removed.update(branch_removed)
        available.difference_update(initial - budget)
    return removed, end


def _guard_opener(lines, begin):
    opener = _next_code(lines, begin + 1)
    while opener < len(lines) and _command(lines[opener]).split()[0] in ("M622.1", "M400", "M73"):
        opener = _next_code(lines, opener + 1)
    if opener == len(lines) or not _OPEN.match(_command(lines[opener])):
        raise PlateCheckFormatError("Build-plate flag has no following conditional (M622).")
    return opener


def source_check_end(lines, i):
    code = _command(lines[i])
    if _FLAG.fullmatch(code):
        return max(end for _, end in _branches(lines, _guard_opener(lines, i), len(lines)))
    if _plate_instruction(code) in ("19", "34", "label"):
        end, targets = _bare_group(lines, i)
        return end if targets else None
    return None


def filter_plate_checks(text: str, keep_first: bool) -> str:
    """Keep the first source identification and alignment at their original locations."""
    if not text or not _HINT.search(text):
        return text
    lines = text.splitlines(keepends=True)
    available = {"19", "34"} if keep_first else set()
    removed = set()
    i = 0
    while i < len(lines):
        code = _command(lines[i])
        if _FLAG.fullmatch(code):
            opener = _guard_opener(lines, i)
            dropped, end = _prune_branches(lines, opener, len(lines), available, outer=True)
            if opener in dropped and not any(_command(lines[n]) for n in range(opener, end) if n not in dropped):
                # Preserve independent progress/dwell commands preceding the opener.
                dropped.update(n for n in range(i, opener)
                               if _command(lines[n]).split()[:1] not in (["M400"], ["M73"]))
            removed.update(dropped)
            i = end
            continue
        if _plate_instruction(code) in ("19", "34", "label"):
            end, targets = _bare_group(lines, i)
            if targets:
                removed.update(_prune_group(lines, targets, available))
                i = end
                continue
        i += 1
    return "".join(raw for n, raw in enumerate(lines) if n not in removed) if removed else text


def has_plate_check(text: str) -> bool:
    return bool(_ACTIVE_DETECT.search(text))
