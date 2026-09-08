"""Tests for hwdb.upload.femb (issue #137) — fake API client, no live HTTP."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from cets.testutils import make_cets_user
from core.models import COLDATA, FEMB, ColdADC, FembRepair, LArASIC
from hwdb.upload import femb as lib


DEV_PROFILE = {
    "api": "https://example/dev",
    "ui": "https://example/devui",
    "femb_part_types": {"IO-1826": "DFEMB-HD", "IO-1865": "DFEMB-VD"},
}

CONNECTORS = {}
for side in "FB":
    for n in range(1, 5):
        CONNECTORS[f"({side}) LArASIC {n}"] = "DLAR"
        CONNECTORS[f"({side}) ColdADC {n}"] = "DADC"
for n in (1, 2):
    CONNECTORS[f"(F) COLDATA {n}"] = "DCOL"


class FakeApi:
    """In-memory HWDB: enough of FnalDbApiClient for the orchestrator."""

    def __init__(self, connectors=CONNECTORS):
        self.connectors = connectors
        self.items = {}          # part_id -> dict
        self.by_serial = {}      # (type, serial) -> part_id
        self.slots = {}          # femb pid -> {label: pid}
        self.images = {}         # pid -> [names]
        self.enabled = set()
        self.calls = []
        self._n = 0

    def _pid(self, type_id):
        self._n += 1
        return f"{type_id}-{self._n:05d}"

    def seed(self, type_id, serial, status=110, comments=""):
        pid = self._pid(type_id)
        self.items[pid] = {"part_id": pid, "serial_number": serial,
                           "status": {"id": status}, "comments": comments}
        self.by_serial[(type_id, serial)] = pid
        self.enabled.add(pid)
        return pid

    # -- reads
    def get_component_type(self, type_id):
        return {"data": {"connectors": self.connectors}}

    def find_component_by_serial(self, type_id, serial):
        pid = self.by_serial.get((type_id, serial))
        return dict(self.items[pid]) if pid else None

    def get_component(self, pid):
        return {"data": dict(self.items[pid])}

    def get_subcomponents(self, pid):
        return {"data": [{"functional_position": k, "part_id": v}
                         for k, v in self.slots.get(pid, {}).items() if v]}

    def get_images(self, pid):
        return {"data": [{"image_name": n} for n in self.images.get(pid, [])]}

    # -- writes
    def create_component(self, type_id, payload):
        self.calls.append(("create", type_id, payload["serial_number"]))
        pid = self._pid(type_id)
        self.items[pid] = {"part_id": pid, "serial_number": payload["serial_number"],
                           "status": dict(payload["status"]), "comments": payload["comments"],
                           "specifications": payload["specifications"]}
        self.by_serial[(type_id, payload["serial_number"])] = pid
        return {"status": "OK", "part_id": pid}

    def enable_component(self, pid):
        self.calls.append(("enable", pid))
        self.enabled.add(pid)
        self.items[pid]["comments"] = ""      # the documented side effect
        return {"status": "OK"}

    def patch_component(self, pid, payload):
        self.calls.append(("patch", pid, payload))
        item = self.items[pid]
        if "status" in payload:
            item["status"] = dict(payload["status"])
        if "comments" in payload:
            item["comments"] = payload["comments"]
        return {"status": "OK"}

    def patch_subcomponents(self, pid, payload):
        self.calls.append(("subcomponents", pid, payload["subcomponents"]))
        for sub in payload["subcomponents"].values():
            if sub and sub not in self.enabled:
                return {"status": "ERROR", "data": f"Component '{sub}' is not yet available"}
        self.slots[pid] = {k: v for k, v in payload["subcomponents"].items() if v}
        return {"status": "OK"}

    def post_location(self, pid, payload):
        self.calls.append(("location", pid))
        return {"status": "OK"}

    def post_component_image(self, pid, fileobj, filename, comments="", content_type=None):
        self.calls.append(("image", pid, filename, content_type))
        self.images.setdefault(pid, []).append(filename)
        return {"image_id": len(self.images[pid])}


def _femb(version="IO-1865-1L", sn="00002", batch="03192026", chips=True):
    femb = FEMB.objects.create(version=version, serial_number=sn, batch_id=batch)
    if chips:
        for side in "FB":
            for n in range(1, 5):
                LArASIC.objects.create(serial_number=f"011-{side}{n}", femb=femb, femb_pos=f"{side}{n}")
                ColdADC.objects.create(serial_number=f"2422-{side}{n}", femb=femb, femb_pos=f"{side}{n}")
        for n in (1, 2):
            COLDATA.objects.create(serial_number=f"2506-F{n}", femb=femb, femb_pos=f"F{n}")
    return femb


def _run(api, femb, **kw):
    lines, result = [], None
    for item in lib.upload_femb(api, femb, profile=DEV_PROFILE, instance="dev", **kw):
        if isinstance(item, lib.FembResult):
            result = item
        else:
            lines.append(item)
    return "".join(lines), result


class NamingTest(TestCase):
    def test_position_label_matches_hwdb_connector_names(self):
        self.assertEqual(lib.position_label("LArASIC", "F1"), "(F) LArASIC 1")
        self.assertEqual(lib.position_label("ColdADC", "B4"), "(B) ColdADC 4")
        self.assertEqual(lib.position_label("COLDATA", "F2"), "(F) COLDATA 2")

    def test_hwdb_serial_is_the_full_ocr_path(self):
        f = SimpleNamespace(version="IO-1865-1L", serial_number="00002")
        self.assertEqual(lib.hwdb_serial(f), "BNL/FEMB/IO-1865-1L/00002")
        self.assertEqual(lib.femb_dirname(f), "BNL_FEMB_IO_1865_1L_00002")

    def test_femb_part_type_from_version_marker(self):
        self.assertEqual(lib.femb_part_type(DEV_PROFILE, SimpleNamespace(version="IO-1865-1K")), "DFEMB-VD")
        self.assertEqual(lib.femb_part_type(DEV_PROFILE, SimpleNamespace(version="IO-1826-2A")), "DFEMB-HD")
        # OCR zero-for-O misread still resolves (type choice only)
        self.assertEqual(lib.femb_part_type(DEV_PROFILE, SimpleNamespace(version="I0-1865-1K")), "DFEMB-VD")
        with self.assertRaises(lib.UploadError):
            lib.femb_part_type(DEV_PROFILE, SimpleNamespace(version="XX-0000"))

    def test_local_assembly_skips_removed_chips(self):
        femb = _femb()
        repair = FembRepair.objects.create(femb=femb, iteration_number=1,
                                           date=datetime(2026, 3, 31, tzinfo=timezone.utc), operator="lke")
        old = LArASIC.objects.get(serial_number="011-F1")
        old.removed_at_repair = repair
        old.femb_pos = ""
        old.save()
        LArASIC.objects.create(serial_number="011-NEW", femb=femb, femb_pos="F1", installed_at_repair=repair)
        asm = lib.local_assembly(femb)
        self.assertEqual(len(asm), 18)
        self.assertEqual(asm["(F) LArASIC 1"], ("LArASIC", "011-NEW"))
        self.assertEqual(lib.removed_chips(femb), {"011-F1": repair})

    def test_find_photos_walks_assembly_and_repair_dirs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "batch_03192026" / "BNL_FEMB_IO_1865_1L_00002"
            r = root / "batch_03192026_rework" / "BNL_FEMB_IO_1865_1L_00002" / "repair_1"
            d.mkdir(parents=True)
            r.mkdir(parents=True)
            (d / "femb_BNL_FEMB_IO_1865_1L_00002_FRONT.png").write_bytes(b"x")
            (d / "back_chip_0.png").write_bytes(b"x")        # not a FEMB photo
            (r / "femb_BNL_FEMB_IO_1865_1L_00002_BACK.png").write_bytes(b"x")
            f = SimpleNamespace(version="IO-1865-1L", serial_number="00002")
            names = [p.name for p in lib.find_photos(root, f)]
            self.assertEqual(names, ["femb_BNL_FEMB_IO_1865_1L_00002_FRONT.png",
                                     "femb_BNL_FEMB_IO_1865_1L_00002_BACK.png"])
            self.assertEqual(lib.find_photos(None, f), [])


@override_settings(HWDB_COMPONENT_DEFAULTS={"femb": {
    "manufacturer_id": {"prod": 21, "dev": 58},
    "chip_manufacturer_id": {"prod": 15, "dev": 59},
    "institution_id": 128, "country_code": "US", "initial_status_id": 110,
}})
class UploadFembTest(TestCase):
    def test_fresh_femb_creates_everything_and_attaches_18_slots(self):
        femb = _femb()
        api = FakeApi()
        text, res = _run(api, femb)
        self.assertTrue(res.ok, text)
        self.assertTrue(res.created)
        self.assertEqual(res.chips_created, 18)
        self.assertEqual(len(res.attached), 18)
        femb_pid = res.part_id
        self.assertEqual(len(api.slots[femb_pid]), 18)
        # chips were created under the connector-declared types, and enabled
        created_types = {c[1] for c in api.calls if c[0] == "create"}
        self.assertEqual(created_types, {"DLAR", "DADC", "DCOL", "DFEMB-VD"})
        enabled = [c for c in api.calls if c[0] == "enable"]
        self.assertEqual(len(enabled), 18)          # chips only, not the FEMB
        self.assertNotIn(("enable", femb_pid), api.calls)
        # the FEMB specs carry label -> serial
        self.assertEqual(api.items[femb_pid]["specifications"]["DATA"]["(F) LArASIC 1"], "011-F1")

    def test_rerun_is_a_noop(self):
        femb = _femb()
        api = FakeApi()
        _run(api, femb)
        n_calls = len(api.calls)
        text, res = _run(api, femb)
        self.assertTrue(res.ok)
        self.assertFalse(res.changed)
        self.assertIn("slots already match", text)
        writes = [c for c in api.calls[n_calls:] if c[0] in ("create", "enable", "subcomponents", "image")]
        self.assertEqual(writes, [])

    def test_existing_chips_are_reused_not_re_enabled(self):
        femb = _femb()
        api = FakeApi()
        pid = api.seed("DLAR", "011-F1", status=120, comments="passed QC")
        text, res = _run(api, femb)
        self.assertTrue(res.ok, text)
        self.assertEqual(res.chips_created, 17)
        self.assertNotIn(("enable", pid), api.calls)
        self.assertEqual(api.items[pid]["status"]["id"], 120)       # meaningful status kept
        self.assertEqual(api.items[pid]["comments"], "passed QC")
        self.assertEqual(api.slots[res.part_id]["(F) LArASIC 1"], pid)

    def test_placeholder_status_is_bumped_to_110(self):
        femb = _femb()
        api = FakeApi()
        pid = api.seed("DADC", "2422-B2", status=100)
        _run(api, femb)
        self.assertEqual(api.items[pid]["status"]["id"], 110)

    def test_broken_chip_is_refused_and_slot_left_empty(self):
        femb = _femb()
        api = FakeApi()
        api.seed("DLAR", "011-B3", status=180)
        text, res = _run(api, femb)
        self.assertTrue(res.ok)
        self.assertEqual(res.refused, ["(B) LArASIC 3"])
        self.assertNotIn("(B) LArASIC 3", api.slots[res.part_id])
        self.assertIn("marked Broken", text)

    def test_repair_swaps_slot_and_marks_old_chip_broken(self):
        femb = _femb()
        api = FakeApi()
        _run(api, femb)                                     # initial assembly in HWDB
        old_pid = api.by_serial[("DLAR", "011-F1")]
        femb_pid = api.by_serial[("DFEMB-VD", "BNL/FEMB/IO-1865-1L/00002")]

        repair = FembRepair.objects.create(
            femb=femb, iteration_number=1, operator="lke",
            date=datetime(2026, 3, 31, 10, 19, tzinfo=timezone.utc),
            what_was_fixed="replaced larasic chip",
        )
        old = LArASIC.objects.get(serial_number="011-F1")
        old.removed_at_repair = repair
        old.femb_pos = ""
        old.save()
        LArASIC.objects.create(serial_number="009-02394", femb=femb, femb_pos="F1", installed_at_repair=repair)

        text, res = _run(api, femb)
        self.assertTrue(res.ok, text)
        self.assertEqual(res.swapped, ["(F) LArASIC 1"])
        new_pid = api.by_serial[("DLAR", "009-02394")]
        self.assertEqual(api.slots[femb_pid]["(F) LArASIC 1"], new_pid)
        self.assertEqual(api.items[old_pid]["status"]["id"], 180)
        self.assertIn("Removed from FEMB BNL/FEMB/IO-1865-1L/00002 ((F) LArASIC 1) during repair #1",
                      api.items[old_pid]["comments"])
        self.assertIn("Repaired (#1, 2026-03-31, operator lke): replaced larasic chip",
                      api.items[femb_pid]["comments"])
        # the other 17 slots were untouched
        self.assertEqual(len(api.slots[femb_pid]), 18)

    def test_unknown_chip_in_hwdb_slot_is_left_alone(self):
        femb = _femb()
        api = FakeApi()
        femb_pid = api.seed("DFEMB-VD", "BNL/FEMB/IO-1865-1L/00002")
        stranger = api.seed("DLAR", "011-STRANGER")
        api.slots[femb_pid] = {"(F) LArASIC 1": stranger}
        text, res = _run(api, femb)
        self.assertTrue(res.ok, text)
        self.assertEqual(res.refused, ["(F) LArASIC 1"])
        self.assertEqual(api.slots[femb_pid]["(F) LArASIC 1"], stranger)
        self.assertEqual(len(api.slots[femb_pid]), 18)
        self.assertEqual(api.items[stranger]["status"]["id"], 110)   # not marked broken
        self.assertIn("local record may be stale", text)

    def test_photos_uploaded_once_with_png_mime(self):
        import tempfile
        femb = _femb()
        api = FakeApi()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "batch_03192026" / "BNL_FEMB_IO_1865_1L_00002"
            d.mkdir(parents=True)
            (d / "femb_BNL_FEMB_IO_1865_1L_00002_FRONT.png").write_bytes(b"png")
            _, res = _run(api, femb, ocr_root=root)
            self.assertEqual(res.photos, 1)
            img = [c for c in api.calls if c[0] == "image"][0]
            self.assertEqual(img[3], "image/png")
            _, res2 = _run(api, femb, ocr_root=root)
            self.assertEqual(res2.photos, 0)

    def test_no_local_chips_is_an_error_not_a_bare_femb(self):
        femb = _femb(chips=False)
        api = FakeApi()
        text, res = _run(api, femb)
        self.assertFalse(res.ok)
        self.assertIn("no chips recorded locally", res.error)
        self.assertEqual([c for c in api.calls if c[0] == "create"], [])


class FembViewsTest(TestCase):
    def setUp(self):
        self.client.force_login(make_cets_user())
        self.femb = _femb()
        _femb(sn="00003", batch="", chips=False)

    def test_index_groups_by_batch(self):
        resp = self.client.get(reverse("hwdb:femb"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "03192026")
        self.assertContains(resp, "(no batch)")
        self.assertContains(resp, reverse("hwdb:femb_batch", args=["unbatched"]))

    def test_index_stat_cards(self):
        # 00002 has chips and no stamp -> to upload; 00003 has no chips.
        stamped = _femb(sn="00004", batch="03192026", chips=False)
        stamped.hwdb_part_id = "D08101100041-00001"
        stamped.save()
        resp = self.client.get(reverse("hwdb:femb"))
        ctx = resp.context
        self.assertEqual(ctx["total"], 3)
        self.assertEqual(ctx["in_hwdb"], 1)
        self.assertEqual(ctx["to_upload"], 1)
        self.assertEqual(ctx["no_chips"], 2)
        self.assertContains(resp, "never synced")

    def test_batch_page_lists_fembs_with_chip_counts(self):
        resp = self.client.get(reverse("hwdb:femb_batch", args=["03192026"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "IO-1865-1L/00002")
        self.assertNotContains(resp, "00003")
        self.assertContains(resp, 'data-key="IO-1865-1L/00002"')
        self.assertContains(resp, "Upload this FEMB")
        self.assertContains(resp, "Sync HWDB")
        self.assertContains(resp, reverse("hwdb:femb_check", args=["03192026"]))

    def test_home_card_links_to_femb_page(self):
        resp = self.client.get(reverse("hwdb:home"))
        self.assertContains(resp, reverse("hwdb:femb"))

    @mock.patch("hwdb.views.mint_for", return_value="bearer")
    def test_run_streams_and_stamps_part_id_on_prod(self, _mint):
        self.client.post(reverse("hwdb:set_instance"), {"instance": "prod"})
        result = lib.FembResult(femb_label="x", part_id="D08101100041-00099")
        with mock.patch("hwdb.views.femb_lib.upload_femb", return_value=iter(["  line\n", result])):
            resp = self.client.post(reverse("hwdb:femb_run", args=["03192026"]),
                                    {"femb": "IO-1865-1L/00002"})
            # The body is a lazy generator: consume it while the patch holds.
            body = b"".join(resp.streaming_content).decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("[1/1] IO-1865-1L/00002", body)
        self.assertIn("Done: 1 ok, 0 failed.", body)
        self.femb.refresh_from_db()
        self.assertEqual(self.femb.hwdb_part_id, "D08101100041-00099")
        self.assertIsNotNone(self.femb.hwdb_checked_at)

    @mock.patch("hwdb.views.mint_for", return_value="bearer")
    def test_run_on_dev_does_not_stamp(self, _mint):
        self.client.post(reverse("hwdb:set_instance"), {"instance": "dev"})
        result = lib.FembResult(femb_label="x", part_id="D08100400001-00099")
        with mock.patch("hwdb.views.femb_lib.upload_femb", return_value=iter([result])):
            resp = self.client.post(reverse("hwdb:femb_run", args=["03192026"]))
            b"".join(resp.streaming_content)
        self.femb.refresh_from_db()
        self.assertEqual(self.femb.hwdb_part_id, "")


class FembCheckViewTest(TestCase):
    """"Sync HWDB" — read-only lookup that stamps hwdb_part_id on prod."""

    def setUp(self):
        self.client.force_login(make_cets_user())
        self.femb = _femb()
        self.other = _femb(sn="00003", batch="07272026", chips=False)
        self.other.hwdb_part_id = "D08101100041-00777"   # stale stamp, gone from HWDB
        self.other.save()

    def _api(self, found):
        api = mock.Mock()
        api.find_component_by_serial.side_effect = lambda type_id, serial: (
            {"part_id": found[serial]} if serial in found else None
        )
        return api

    @mock.patch("hwdb.views.mint_for", return_value="bearer")
    def test_prod_check_stamps_found_and_clears_missing(self, _mint):
        self.client.post(reverse("hwdb:set_instance"), {"instance": "prod"})
        api = self._api({"BNL/FEMB/IO-1865-1L/00002": "D08101100041-00042"})
        with mock.patch("hwdb.views.FnalDbApiClient", return_value=api):
            resp = self.client.post(reverse("hwdb:femb_check_all"))
            body = b"".join(resp.streaming_content).decode()
        self.assertIn("IO-1865-1L/00002: D08101100041-00042", body)
        self.assertIn("IO-1865-1L/00003: not in HWDB", body)
        self.assertIn("Done: 1 in HWDB, 1 missing, 0 failed.", body)
        self.femb.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.femb.hwdb_part_id, "D08101100041-00042")
        self.assertIsNotNone(self.femb.hwdb_checked_at)
        self.assertEqual(self.other.hwdb_part_id, "")
        # looked up under the prod VD type, by the full HWDB serial
        api.find_component_by_serial.assert_any_call("D08101100041", "BNL/FEMB/IO-1865-1L/00002")

    @mock.patch("hwdb.views.mint_for", return_value="bearer")
    def test_dev_check_reports_but_does_not_stamp(self, _mint):
        self.client.post(reverse("hwdb:set_instance"), {"instance": "dev"})
        api = self._api({"BNL/FEMB/IO-1865-1L/00002": "D08100400001-00093"})
        with mock.patch("hwdb.views.FnalDbApiClient", return_value=api):
            resp = self.client.post(reverse("hwdb:femb_check", args=["03192026"]))
            body = b"".join(resp.streaming_content).decode()
        self.assertIn("Checking 1 FEMB(s) of batch 03192026 against dev HWDB.", body)
        self.assertIn("dev: local stamps unchanged", body)
        self.femb.refresh_from_db()
        self.assertEqual(self.femb.hwdb_part_id, "")
        self.other.refresh_from_db()
        self.assertEqual(self.other.hwdb_part_id, "D08101100041-00777")

    def test_index_shows_last_check(self):
        self.femb.hwdb_checked_at = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
        self.femb.save()
        resp = self.client.get(reverse("hwdb:femb"))
        self.assertContains(resp, "Last HWDB check")
        self.assertContains(resp, reverse("hwdb:femb_check_all"))
