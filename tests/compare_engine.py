"""Optional native parity check for the real browser smoke test."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from job_service import JobFiles


def comparable(contents):
    return re.sub(rb"(?m)^(; generated\s*: )[^\r\n]+", rb"\1<timestamp>", contents)


def compare(case):
    downloaded = Path(case["result"]).resolve()
    assert downloaded.is_relative_to((ROOT / ".dev-notes").resolve())
    source = Path(case["source"])
    with tempfile.TemporaryDirectory(dir=downloaded.parent) as directory:
        store = JobFiles(directory, directory)
        name = store.stage(source.name)
        shutil.copyfile(source, Path(directory, name))
        plates = {info["source_plate_name"]: info for info in store.import_staged(source.name, name)["files"]}
        payload = case["payload"]
        for job in payload["jobs"]:
            plate = plates[job["source_plate_name"]]
            job.update(stored_name=plate["stored_name"], source_3mf_stored=name)
        result = store.generate(payload)
        with ZipFile(Path(directory, result["filename_3mf"])) as native, ZipFile(downloaded) as browser:
            assert sorted(native.namelist()) == sorted(browser.namelist())
            checksums = {(n + ".md5").casefold(): n for n in native.namelist() if n.lower().endswith(".gcode")}
            for member in native.namelist():
                a, b = native.read(member), browser.read(member)
                if member.casefold() in checksums:
                    gcode = checksums[member.casefold()]
                    assert a == hashlib.md5(native.read(gcode)).hexdigest().upper().encode()
                    assert b == hashlib.md5(browser.read(gcode)).hexdigest().upper().encode()
                elif member.lower().endswith(".gcode"):
                    assert comparable(a) == comparable(b), member
                else:
                    assert a == b, member
        print(f"Native parity: all {len(plates)} plates and metadata match ({result['lines']:,} G-code lines).")


if __name__ == "__main__":
    compare(json.load(sys.stdin))
