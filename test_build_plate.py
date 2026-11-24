"""Offline regressions for the original build surface and its one-time check."""

import hashlib
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from build_plate import PlateCheckFormatError, filter_plate_checks
from gcode_processor import AutomationSettings, BambuGcodeParser, JobConfig, build_combined_gcode, build_dry_run_gcode
from job_service import JobFiles


def check(label):
    return "\n".join((
        "M1002 judge_flag build_plate_detect_flag", "M622 S1",
        "; source routine " + label, "    M972 S19 P0 C0 ; heatbed detection",
        "    M972 S31 P0 T5000 ; toolhead camera", "    M972 S34 P0 T5000 ; plate offset", "M623",
    ))


def sliced(label, *, initial=True, repeated=False, declared="High Temp Plate"):
    block = check(label)
    enabled = (block + "\n" + block) if initial else "; source contains no plate check"
    return "\n".join((
        "; HEADER_BLOCK_START", "; max_z_height: 4", "; total layer number: 1", "; HEADER_BLOCK_END",
        "; CONFIG_BLOCK_START", "; printer_model = Bambu Lab H2S", "; curr_bed_type = " + declared,
        "; hot_plate_temp = 70", "; hot_plate_temp_initial_layer = 72",
        "; textured_plate_temp = 50", "; textured_plate_temp_initial_layer = 52",
        "; supertack_plate_temp = 40", "; supertack_plate_temp_initial_layer = 42",
        "; CONFIG_BLOCK_END", "G28", "M972 S41 P0 T5000 ; trash can",
        ";===== detection start =====", "M104 S0", "M562 P1 E0 B1", "M1028 S1",
        enabled, "M1028 S0", "M562 P1 E1 B1", "M17 D", "G3811 Z145 ; bed obstacle",
        ";===== detection end =====", "G29", "M140 S72",
        "; CHANGE_LAYER", "; Z_HEIGHT: 4", "M73 L1", "G1 X10 Y10 Z4",
        block if repeated else "", "; filament end gcode", block if repeated else "", "M84"))


def active(text):
    return [code for raw in text.splitlines() if (code := raw.partition(";")[0].strip())]


class PlateCheckTests(TestCase):
    def test_default_once_and_optional_skip_across_jobs(self):
        first = BambuGcodeParser(sliced("selected", repeated=True))
        other = BambuGcodeParser(sliced("later", repeated=True))
        inputs = [JobConfig("selected", 3, first.sections, first.temps), JobConfig("later", 2, other.sections, other.temps)]
        for value in (True, False, True):
            result = build_combined_gcode(inputs, AutomationSettings(verify_build_plate=value))
            before, after = result.split("; ## Print #1/", 1)
            for op in ("M1002 judge_flag build_plate_detect_flag", "M972 S19 P0 C0",
                       "M972 S31 P0 T5000", "M972 S34 P0 T5000"):
                self.assertEqual(active(before).count(op), int(value))
                self.assertNotIn(op, active(after))
            self.assertEqual(result.count("; source routine selected"), int(value))
            self.assertNotIn("; source routine later", result)
            for command in ("G28", "G29", "M972 S41 P0 T5000", "G3811 Z145", "M562 P1 E1 B1"):
                self.assertIn(command, active(before))
        self.assertIn(check("selected"), first.sections.start_gcode)

    def test_absent_start_is_never_fabricated_or_borrowed(self):
        first = BambuGcodeParser(sliced("absent", initial=False, repeated=True))
        later = BambuGcodeParser(sliced("later"))
        result = build_combined_gcode([JobConfig("a",2,first.sections,first.temps),
                                      JobConfig("b",1,later.sections,later.temps)], AutomationSettings())
        self.assertNotIn("M972 S19 P0 C0", active(result))
        self.assertNotIn("M972 S19 P0 C0", active(build_dry_run_gcode(AutomationSettings(), cycles=3)))
        plain = BambuGcodeParser("G28\n"+check("plain")+"\n; LAYER_CHANGE\nG1 X10\n; filament end gcode\nM84")
        self.assertIn(check("plain"), plain.sections.start_gcode)

    def test_unrelated_m972_and_other_conditionals_survive(self):
        calibration = "M1002 judge_flag g29_before_print_flag\nM622 J1\nG29\nM623"
        bare = "M972 S19 P0 C0\nM400\nM972 S31 P0 T5000\nM972 S34 P0 T5000"
        text = calibration+"\n"+bare+"\n"+check("second")+"\nM972 S31 P0 T9000\nM972 S190 P0\nM972 S41 P0 T5000"
        enabled = filter_plate_checks(text, True)
        self.assertIn(bare, enabled)
        self.assertNotIn("; source routine second", enabled)
        off = filter_plate_checks(text, False)
        self.assertIn(calibration, off)
        for command in ("M400", "M972 S31 P0 T9000", "M972 S190 P0", "M972 S41 P0 T5000"):
            self.assertIn(command, active(off))
        self.assertNotIn("M972 S19 P0 C0",active(off))
        self.assertNotIn("M972 S34 P0 T5000",active(off))

    def test_nested_conditions_and_malformed_boundary(self):
        mixed = check("custom").replace("M623", "M1002 judge_flag other\nM622 J1\nG28 X\nM623\nM623")
        text = mixed + "\nM622 J0\nM104 S90\nM623\nM972 S41 P0"
        cleaned = filter_plate_checks(text, False)
        self.assertIn("M622 J1\nG28 X\nM623", cleaned)
        self.assertIn("M622 J0\nM104 S90\nM623", cleaned)
        self.assertEqual(active(cleaned).count("M623"), 3)
        self.assertNotIn("M972 S19 P0 C0", active(cleaned))
        with self.assertRaises(PlateCheckFormatError):
            filter_plate_checks(check("bad").removesuffix("M623") + "\nG28\nG29", False)
        comment = "; M1002 judge_flag build_plate_detect_flag\n; M972 S19 P0 C0\nG28"
        self.assertEqual(filter_plate_checks(comment, False), comment)

    def test_preparation_guard_does_not_use_up_the_initial_check(self):
        prep = "M1002 judge_flag build_plate_detect_flag\nM622 S1\nG28 X\nM623"
        source = prep + "\n" + check("real") + "\n" + check("again")
        enabled = filter_plate_checks(source,True)
        self.assertIn(prep, enabled)
        self.assertIn(check("real"),enabled)
        self.assertEqual(active(enabled).count("M972 S34 P0 T5000"), 1)
        self.assertIn(prep,filter_plate_checks(source,False))

    def test_identification_and_alignment_split_across_guards(self):
        def guarded(*ops):
            return "\n".join(("M1002 judge_flag build_plate_detect_flag","M622 S1",*ops,"M623"))
        identify = guarded("M972 S19 P0 C0")
        align = guarded("M972 S31 P0 T5000","M972 S34 P0 T5000")
        seq = identify + "\nM400\n" + align
        text = seq + "\n" + seq
        on = active(filter_plate_checks(text, True))
        off = active(filter_plate_checks(text, False))
        for move in ("M972 S19 P0 C0","M972 S31 P0 T5000","M972 S34 P0 T5000"):
            self.assertEqual(on.count(move), 1)
            self.assertNotIn(move, off)
        alternatives = identify+"\nM622 J0\nM972 S19 P1 C0\nM623"
        self.assertEqual(filter_plate_checks(alternatives,True),alternatives)
        self.assertFalse(active(filter_plate_checks(alternatives,False)))

    def test_duplicate_complete_routines_inside_single_positive_branch(self):
        moves = "M972 S19 P0 C0\nM972 S31 P0 T5000\nM972 S34 P0 T5000"
        text = "M1002 judge_flag build_plate_detect_flag\nM622 S1\n"+moves+"\n"+moves+"\nM623"
        self.assertEqual(filter_plate_checks(text,True).count(moves),1)
        self.assertFalse(active(filter_plate_checks(text,False)))

    def test_camera_after_alignment_and_inside_other_flag_is_preserved(self):
        bare = "M972 S19 P0 C0\nM73 P1 R5\nM972 S31 P0 T5000\nM972 S34 P0 T5000"
        self.assertEqual(filter_plate_checks(bare+"\nM972 S31 P0 T9000", False),
                         "M73 P1 R5\nM972 S31 P0 T9000")
        camera = "M1002 judge_flag other_camera\nM622 J1\nM972 S31 P0 T9000\nM623"
        mixed = check("in guard").replace("M623",camera+"\nM623")
        self.assertIn(camera,filter_plate_checks(mixed,False))
        self.assertNotIn("M972 S31 P0 T5000",active(filter_plate_checks(mixed,False)))
        with self.assertRaises(PlateCheckFormatError):
            filter_plate_checks(check("broken").removesuffix("M623")+";===== detection end =====\nM623", False)

    def test_sampled_dry_run_all_start_filters(self):
        sample = BambuGcodeParser(sliced("dry",repeated=True))
        for want in (False,True):
            for minimal in (False,True):
                for skip_ams in (False,True):
                    with self.subTest(want=want,minimal=minimal,skip_ams=skip_ams):
                        out=build_dry_run_gcode(AutomationSettings(verify_build_plate=want),sample_parser=sample,
                                               cycles=3,minimal_start=minimal,skip_ams_load=skip_ams)
                        first,rest=out.split("; ## [DRY-RUN] starting",1)
                        self.assertEqual(active(first).count("M972 S19 P0 C0"), int(want))
                        self.assertNotIn("M972 S34 P0 T5000",active(rest))
                        if skip_ams:
                            self.assertNotIn("G1 E20 F240", active(rest))
                        if want:
                            self.assertIn(check("dry"), first)
                            self.assertIn("M1028 S1",active(first))
                            self.assertIn("M1028 S0",active(first))


class SurfaceArchiveTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        (base/"in").mkdir()
        (base/"out").mkdir()
        self.store = JobFiles(base/"in",base/"out")

    def load(self, *, selected_json=True, selected_xml=True):
        name="two-beds.gcode.3mf"
        token=self.store.stage(name)
        group="".join(f'<plate><metadata key="plater_id" value="{n}"/>'+
                      (f'<metadata key="bed_type" value="{model}"/>' if n==1 or selected_xml else '')+
                      f'<metadata key="plater_name" value="Keep {n}"/></plate>'
                      for n,model in ((1,"High Temp Plate"),(7,"Textured PEI Plate")))
        with ZipFile(self.store.uploads/token,"w") as z:
            z.writestr("Metadata/project_settings.config",json.dumps({"curr_bed_type":"High Temp Plate","other":"keep"}))
            z.writestr("Metadata/model_settings.config",f"<config>{group}</config>")
            z.writestr("Metadata/plate_1.gcode",sliced("one"))
            z.writestr("Metadata/PLATE_7.GCODE",sliced("seven",repeated=True))
            z.writestr("Metadata/plate_1.json",json.dumps({"bed_type":"hot_plate","filament_ids":[2],"source":1}))
            if selected_json:
                z.writestr("metadata/PLATE_7.JSON",json.dumps({"bed_type":"supertack_plate","filament_ids":[5],"source":7}))
            z.writestr("3D/preserved.bin",b"model")
        return self.store.import_staged(name,token)["files"]

    def test_nonfirst_origin_controls_all_output_slots_even_with_stale_hint(self):
        first,chosen=self.load()
        self.assertEqual((first["bed_type"],chosen["bed_type"],chosen["bed_temp"]),
                         ("High Temp Plate","Supertack Plate",42))
        self.assertTrue(chosen["has_build_plate_check"])
        for enabled in (True,False):
            req={"jobs":[{"stored_name":chosen["stored_name"],"count":3,"source_plate_name":"plate_1"},
                         {"stored_name":first["stored_name"],"count":2}],
                 "settings":{"verify_build_plate":enabled},"force_compatibility":True}
            result=self.store.generate(req)
            self.assertEqual(result["plate_target"],"plate_7")
            with ZipFile(self.store.outputs/result["filename_3mf"]) as z:
                self.assertEqual(z.read("3D/preserved.bin"),b"model")
                self.assertEqual(json.loads(z.read("Metadata/project_settings.config")),
                                 {"curr_bed_type":"Supertack Plate","other":"keep"})
                xml=ET.fromstring(z.read("Metadata/model_settings.config"))
                self.assertEqual([e.attrib["value"] for e in xml.findall("./plate/metadata[@key='bed_type']")],["Supertack Plate"]*2)
                self.assertEqual([e.attrib["value"] for e in xml.findall("./plate/metadata[@key='plater_name']")],["Keep 1","Keep 7"])
                for g,j in (("Metadata/plate_1.gcode","Metadata/plate_1.json"),("Metadata/PLATE_7.GCODE","metadata/PLATE_7.JSON")):
                    code=z.read(g); text=code.decode()
                    self.assertEqual(z.read(g+".md5"),hashlib.md5(code).hexdigest().upper().encode())
                    self.assertEqual(json.loads(z.read(j)),{"bed_type":"supertack_plate","filament_ids":[2,5],"source":7})
                    self.assertIn("; curr_bed_type = Supertack Plate\n",text)
                    self.assertEqual(active(text).count("M972 S19 P0 C0"),int(enabled))
                    self.assertEqual(text.count("; source routine seven"),int(enabled))
                    self.assertNotIn("; source routine one",text)

    def test_missing_selected_json_uses_its_override_not_another_slot(self):
        _,chosen=self.load(selected_json=False)
        self.assertEqual((chosen["bed_type"], chosen["bed_temp"]), ("Textured PEI Plate",52))
        result=self.store.generate({"jobs":[{"stored_name":chosen["stored_name"]}]})
        with ZipFile(self.store.outputs/result["filename_3mf"]) as z:
            self.assertEqual(json.loads(z.read("Metadata/plate_1.json"))["bed_type"],"textured_plate")
            self.assertEqual(json.loads(z.read("Metadata/project_settings.config"))["curr_bed_type"],"Textured PEI Plate")

    def test_legacy_plate_suffix_beats_stale_request_and_name_prefix(self):
        _, chosen = self.load()
        old = self.store.uploads / "design__plate_1__old__plate_7__a123bc45.gcode"
        (self.store.uploads/chosen["stored_name"]).rename(old)
        result = self.store.generate({"jobs":[{"stored_name":old.name, "source_plate_name":"plate_1",
                                               "source_3mf_stored":chosen["source_3mf_stored"]}]})
        self.assertEqual((result["plate_target"],result["bed_type"]), ("plate_7","Supertack Plate"))
        report = self.store.validate({"filename":result["filename_3mf"],"plate_name":"plate_7"})
        self.assertTrue(report["source"].endswith("!Metadata/PLATE_7.GCODE"))

    def test_unspecified_source_clears_stale_sibling_override(self):
        key = self.store.stage("unspecified.3mf")
        xml = '<config><plate><metadata key="plater_id" value="1"/><metadata key="bed_type" value="High Temp Plate"/><metadata key="other" value="keep"/></plate><plate><metadata key="plater_id" value="7"/></plate></config>'
        plain = sliced("unknown").replace("; curr_bed_type = High Temp Plate\n","")
        with ZipFile(self.store.uploads/key,"w") as z:
            z.writestr("Metadata/plate_1.gcode",sliced("one"))
            z.writestr("Metadata/plate_7.gcode",plain)
            z.writestr("Metadata/plate_1.json",'{"bed_type":"hot_plate"}')
            z.writestr("Metadata/model_settings.config",xml)
            z.writestr("Metadata/project_settings.config","{}")
        _,chosen = self.store.import_staged("unspecified.3mf",key)["files"]
        self.assertEqual(chosen["bed_type"],"")
        result = self.store.generate({"jobs":[chosen]})
        with ZipFile(self.store.outputs/result["filename_3mf"]) as z:
            meta=ET.fromstring(z.read("Metadata/model_settings.config"))
            self.assertIsNone(meta.find(".//metadata[@key='bed_type']"))
            self.assertEqual(meta.find(".//metadata[@key='other']").get("value"),"keep")
            self.assertNotIn("bed_type",json.loads(z.read("Metadata/plate_1.json")))
            self.assertEqual(json.loads(z.read("Metadata/project_settings.config")),{})

    def test_repack_fallback_reads_selected_slice_not_the_combined_header(self):
        from gcode_processor import repackage_3mf
        file = self.store.uploads / "source.3mf"
        with ZipFile(file,"w") as z:
            z.writestr("Metadata/plate_1.gcode",sliced("one"))
            z.writestr("Metadata/plate_7.gcode",sliced("seven",declared="Engineering Plate"))
            z.writestr("Metadata/plate_1.json",'{"bed_type":"hot_plate"}')
            z.writestr("Metadata/project_settings.config",'{"curr_bed_type":"High Temp Plate"}')
        output = self.store.outputs / "result.3mf"
        repackage_3mf(file,sliced("arbitrary",declared="Cool Plate"),output,plate_name="plate_7")
        with ZipFile(output) as z:
            self.assertEqual(json.loads(z.read("Metadata/project_settings.config"))["curr_bed_type"],"Engineering Plate")
            self.assertEqual(json.loads(z.read("Metadata/plate_1.json"))["bed_type"],"eng_plate")

    def test_unrecognised_surface_id_is_not_used_as_a_studio_enum(self):
        key = self.store.stage("custom.3mf")
        only = sliced("custom").replace("; curr_bed_type = High Temp Plate\n","")
        with ZipFile(self.store.uploads/key,"w") as z:
            z.writestr("Metadata/plate_7.gcode",only)
            z.writestr("Metadata/plate_7.json",'{"bed_type":"vendor_surface_x"}')
            z.writestr("Metadata/project_settings.config",'{"curr_bed_type":"High Temp Plate","keep":1}')
        [chosen] = self.store.import_staged("custom.3mf",key)["files"]
        self.assertEqual(chosen["bed_type"],"vendor_surface_x")
        result = self.store.generate({"jobs":[chosen]})
        with ZipFile(self.store.outputs/result["filename_3mf"]) as z:
            self.assertEqual(json.loads(z.read("Metadata/plate_7.json"))["bed_type"],"vendor_surface_x")
            self.assertEqual(json.loads(z.read("Metadata/project_settings.config")),{"keep":1})
            self.assertNotIn(b"; curr_bed_type =", z.read("Metadata/plate_7.gcode"))

    def test_plain_unknown_bed_uses_sliced_temperature_without_a_plate_guess(self):
        text = sliced("plain").replace("; curr_bed_type = High Temp Plate\n","")
        p=BambuGcodeParser(text)
        self.assertEqual((p.temps.bed_type,p.temps.bed_initial),("",72))
        p=BambuGcodeParser(text.replace("; CONFIG_BLOCK_END","; curr_bed_type = My coated surface\n; CONFIG_BLOCK_END"))
        self.assertEqual((p.temps.bed_type,p.temps.bed_initial),("My coated surface",72))
