"""Tests for the probe_shipment spike command (issue #42, ADR-0013).

The HWDB calls are mocked — no network, no bearer needed.

    python manage.py test explore
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase


def _run(*, items, locations, subcomponents, raw=False):
    api = mock.MagicMock()
    api.get_component_types.return_value = {"data": items}
    api.get_locations.return_value = {"data": locations}
    api.get_subcomponents.return_value = {"data": subcomponents}
    out = StringIO()
    args = ["probe_shipment", "--bearer", "x"]
    if raw:
        args.append("--raw")
    with mock.patch("explore.management.commands.probe_shipment.FnalDbApiClient",
                    return_value=api):
        call_command(*args, stdout=out)
    return out.getvalue(), api


class ProbeShipmentTest(TestCase):
    ITEMS = [{"part_id": "D08120200001-00001"}, {"part_id": "D08120200001-00002"}]
    # Real shape: location is a nested {id, name}; id==0 is the "In Transit"
    # sentinel; events arrive newest-first.
    LOCS_DELIVERED = [
        {"arrived": "2026-04-04T07:06:47-05:00", "id": 2, "creator": "A",
         "comments": "", "location": {"id": 128, "name": "BNL"}},
        {"arrived": "2026-04-01T07:00:00-05:00", "id": 1, "creator": "A",
         "comments": "packed", "location": {"id": 1, "name": "FNAL"}},
    ]
    LOCS_IN_TRANSIT = [
        {"arrived": "2026-06-10T12:10:28-05:00", "id": 3, "creator": "K",
         "comments": "", "location": {"id": 0, "name": "In Transit"}},
        {"arrived": "2026-06-03T12:17:54-05:00", "id": 2, "creator": "K",
         "comments": "", "location": {"id": 128, "name": "BNL"}},
    ]
    SUBS = [
        {"part_id": "D08101100041-00001", "type_name": "MiniSAS FEMB FD-VD",
         "functional_position": "VD FEMB 1", "operation": "mount"},
        {"part_id": "D08101100041-00002", "type_name": "MiniSAS FEMB FD-VD",
         "functional_position": "VD FEMB 2", "operation": "mount"},
    ]

    def test_latest_is_newest_arrived_not_list_order(self):
        # Newest event (BNL, 04-04) wins even though it is first in the list.
        out, _ = _run(items=self.ITEMS[:1], locations=self.LOCS_DELIVERED,
                      subcomponents=self.SUBS)
        self.assertIn("latest: 'BNL'", out)
        self.assertIn("status: at 'BNL'", out)

    def test_in_transit_status_from_location_id_zero(self):
        out, _ = _run(items=self.ITEMS[:1], locations=self.LOCS_IN_TRANSIT,
                      subcomponents=[])
        self.assertIn("status: IN TRANSIT", out)

    def test_renders_events_and_manifest_positions(self):
        out, _ = _run(items=self.ITEMS[:1], locations=self.LOCS_DELIVERED,
                      subcomponents=self.SUBS)
        self.assertIn("locations: 2 event(s)", out)
        self.assertIn("location='FNAL' (id=1)", out)
        self.assertIn("2 part(s) @ positions", out)
        self.assertIn("VD FEMB 1", out)

    def test_empty_manifest(self):
        out, _ = _run(items=self.ITEMS[:1], locations=self.LOCS_IN_TRANSIT,
                      subcomponents=[])
        self.assertIn("manifest): 0 (empty)", out)

    def test_read_only_no_writes(self):
        _, api = _run(items=self.ITEMS, locations=self.LOCS_DELIVERED,
                      subcomponents=self.SUBS)
        api.post_location.assert_not_called()
        api.patch_component.assert_not_called()
        api.create_component.assert_not_called()

    def test_handles_no_items(self):
        out, _ = _run(items=[], locations=[], subcomponents=None)
        self.assertIn("No items found", out)
