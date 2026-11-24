"""Refresh or check the small project-owned assets in the standalone Pages folder."""

import argparse
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gcode_processor import PRESET_PATTERNS

SOURCES = ("build_plate.py", "gcode_processor.py", "gcode_validator.py", "validation_paths.py",
           "i18n_helper.py", "job_service.py", "browser_bridge.py")


def artifacts():
    stream = io.BytesIO()
    sources = [ROOT / p for p in SOURCES] + sorted((ROOT / "i18n").glob("*.json"))
    with ZipFile(stream, "w") as archive:
        for path in sources:
            entry = ZipInfo(path.relative_to(ROOT).as_posix(), (2020, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, path.read_text(encoding="utf-8").encode("utf-8"))
    presets = [dict(key=key, desc=p.get("desc", ""), notes=p.get("notes", []))
               for key, p in PRESET_PATTERNS.items()]
    return {"assets/engine.zip": stream.getvalue(),
            "assets/presets.json": (json.dumps(presets, ensure_ascii=False, separators=(",", ":")) + "\n").encode(),
            "LICENSE.txt": (ROOT / "LICENSE").read_text(encoding="utf-8").encode(),
            ".nojekyll": b""}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    for name, data in artifacts().items():
        path = ROOT / "docs" / name
        if path.is_file() and path.read_bytes() == data:
            continue
        if check:
            raise SystemExit(f"Rebuild the Pages asset: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print("Pages engine and presets are current.")


if __name__ == "__main__":
    main()
