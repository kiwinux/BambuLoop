"""Job-storage regressions shared by the browser worker and local HTTP API."""
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from job_service import JobFiles, JobError

GCODE = ("; HEADER_BLOCK_START\n; max_z_height: 2\n; total layer number: 1\n; HEADER_BLOCK_END\n"
         "; CONFIG_BLOCK_START\n; CONFIG_BLOCK_END\nG28\n; CHANGE_LAYER\nM73 L1\nG1 X10 Y10\n"
         "; filament end gcode\nM84\n")


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.inputs, self.outputs = self.path / "in", self.path / "out"
        self.inputs.mkdir()
        self.outputs.mkdir()
        self.store = JobFiles(self.inputs, self.outputs)

    def load_archive(self, original="same.gcode.3mf"):
        key = self.store.stage(original)
        with ZipFile(self.inputs / key, "w") as archive:
            archive.writestr("Metadata/plate_2.gcode", GCODE)
            archive.writestr("metadata/PLATE_10.GCODE", GCODE)
            archive.writestr("Extras/plate_preview.gcode.md5", "source")
        return self.store.import_staged(original, key)["files"]

    def test_same_name_and_shared_archive_lifetime(self):
        first, second = self.load_archive(), self.load_archive()
        self.assertNotEqual(first[0]["source_3mf_stored"], second[0]["source_3mf_stored"])
        self.store.delete_upload(first[0])
        self.assertTrue((self.inputs / first[1]["source_3mf_stored"]).is_file())
        self.store.delete_upload(first[1])
        self.assertFalse((self.inputs / first[1]["source_3mf_stored"]).exists())
        self.assertTrue((self.inputs / second[0]["source_3mf_stored"]).is_file())

    def test_workspace_limit_rolls_back_only_current_file(self):
        self.store.byte_budget = len(GCODE.encode()) + 10
        old = self.store.stage("existing.gcode")
        (self.inputs / old).write_bytes(GCODE.encode())
        self.store.import_staged("existing.gcode", old)
        incoming = self.store.stage("other.gcode")
        (self.inputs / incoming).write_text(GCODE, encoding="utf-8")
        with self.assertRaises(JobError) as caught:
            self.store.import_staged("other.gcode", incoming)
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(list(self.inputs.iterdir()), [self.inputs / old])

    def test_oversize_multi_plate_result_falls_back_to_gcode(self):
        jobs = self.load_archive()
        payload = {"jobs":jobs, "settings":{"eject_method":"none"}}
        first = self.store.generate(payload)
        size = (self.outputs / first["filename"]).stat().st_size
        self.store.byte_budget = size + 100
        result = self.store.generate(payload)
        self.assertIn("repack_error", result)
        self.assertNotIn("filename_3mf", result)
        self.assertTrue((self.outputs / result["filename"]).is_file())

    def test_budget_includes_replicated_thumbnail_and_new_checksums(self):
        jobs = self.load_archive()
        key = jobs[0]["source_3mf_stored"]
        with ZipFile(self.inputs / key, "a") as z:
            z.writestr("Metadata/plate_2.png", b"p" * 4096)
            z.writestr("Metadata/plate_10.png", b"q")
        req = {"jobs": jobs, "settings": {"eject_method": "none"}}
        first = self.store.generate(req)
        with ZipFile(self.outputs / first["filename_3mf"]) as z:
            expected = sum(entry.file_size for entry in z.infolist())
        self.store.byte_budget = expected - 1
        self.assertIn("repack_error", self.store.generate(req))
        self.store.byte_budget = expected
        self.assertIn("filename_3mf", self.store.generate(req))

    def test_invalid_archive_restores_storage(self):
        for entries in [("3D/model.xml",), ("Metadata/plate_1.gcode", "metadata/PLATE_01.GCODE")]:
            key = self.store.stage("bad.3mf")
            with ZipFile(self.inputs / key, "w") as archive:
                for name in entries:
                    archive.writestr(name, GCODE)
            with self.assertRaises(JobError):
                self.store.import_staged("bad.3mf", key)
            self.assertFalse(any(self.inputs.iterdir()))

    def test_conflicts_keep_distinct_hardware_and_temperature_rules(self):
        def plate(name, diameter, temp):
            key = self.store.stage(name)
            content = GCODE.replace("; CONFIG_BLOCK_END", f"; nozzle_diameter = {diameter}\n; nozzle_temperature = {temp}\n; CONFIG_BLOCK_END")
            (self.inputs/key).write_text(content,encoding="utf-8")
            return self.store.import_staged(name,key)["files"][0]
        first = plate("a.gcode",0.4,200)
        temp = plate("b.gcode",0.4,230)
        hardware = plate("c.gcode",0.6,200)
        with self.assertRaises(JobError) as warning:
            self.store.generate({"jobs":[first,temp]})
        self.assertEqual(warning.exception.payload["error"], "incompatible_jobs")
        self.assertIn("filename", self.store.generate({"jobs":[first,temp],"force_compatibility":True}))
        with self.assertRaises(JobError) as blocked:
            self.store.generate({"jobs":[first,hardware],"force_compatibility":True})
        self.assertEqual(blocked.exception.status,409)
