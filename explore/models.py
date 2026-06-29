from django.db import models


class ComponentTypeNode(models.Model):
    """One leaf of the FD-VD component hierarchy, mirrored from production HWDB.

    The skeleton that powers the /explore/ tree (ADR-0010, ADR-0011). One row
    per HWDB component type under a whitelisted FD-VD system; the row carries
    its place in the System → Subsystem → Component Type tree plus a component
    count. Populated by hierarchy.sync_hierarchy() — read-only, additive, and
    independent of the CE chip mirror (``hwdb.HwdbChip``) and the BNL chip
    models.

    The ``part_type_id`` encodes the path: ``D08100100003`` =
    ``D`` (project) · ``081`` (system) · ``001`` (subsystem) · ``00003`` (type).
    """

    part_type_id = models.CharField(max_length=20, primary_key=True)
    project = models.CharField(max_length=4, default="D")
    system_id = models.PositiveIntegerField(db_index=True)
    system_name = models.CharField(max_length=100)
    subsystem_id = models.PositiveIntegerField()
    subsystem_name = models.CharField(max_length=100)
    component_type_name = models.CharField(max_length=200)
    full_name = models.CharField(max_length=300, blank=True, default="")
    n_components = models.PositiveIntegerField(default=0)
    synced_at = models.DateTimeField(auto_now=True)
    # Per-type test-event sync state (issue #30). NULL tests_synced_at = the
    # leaf's tests have never been pulled; the explorer syncs lazily on first
    # visit. n_tests powers the "has test data" tree accent.
    tests_synced_at = models.DateTimeField(null=True, blank=True)
    n_tests = models.PositiveIntegerField(default=0)
    tests_sync_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["system_id", "subsystem_id", "component_type_name"]

    def __str__(self):
        return f"ComponentTypeNode({self.part_type_id}, {self.component_type_name})"


class HwdbTestEvent(models.Model):
    """One test record for one component, mirrored from production HWDB.

    The raw events behind the /explore/ "tests recorded per month" plots
    (ADR-0010). Stored from the uniform summary endpoint
    (``components/{part_id}/tests``): every consortium's record carries
    ``created`` (HWDB record timestamp) + ``test_type.name``, with no
    per-consortium date logic. Re-synced wholesale per component type, so rows
    for a ``part_type_id`` are deleted and rewritten on each sync.

    ``created`` holds the date the plot bins on: the physics ``test_data``
    date for component types we've mapped (CE → "Test Date"), else the HWDB
    record timestamp. See ``events.physics_date_field`` and ADR-0010. Rows are
    keyed by ``part_id`` so the incremental sync can append per component.
    """

    part_type_id = models.CharField(max_length=20, db_index=True)
    part_id = models.CharField(max_length=50)
    test_type_name = models.CharField(max_length=100)
    created = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["part_type_id", "created"])]

    def __str__(self):
        return f"HwdbTestEvent({self.part_type_id}, {self.test_type_name}, {self.created:%Y-%m-%d})"


class HwdbComponentEvent(models.Model):
    """One component registration for one component type, mirrored from HWDB.

    The raw events behind the /explore/ "components updated per month"
    plot (the inventory-activity view, complementing the test-record plot).
    From the component detail record (``components/{pid}``): ``created`` is the
    mint date; ``updated`` is the last-modified date the chart bins on (status
    change / QC upload bumps it). Synced in the same pass as ``HwdbTestEvent``;
    incremental syncs append new components, while ``components``/``full`` modes
    rewrite all rows. See ADR-0010.
    """

    part_type_id = models.CharField(max_length=20, db_index=True)
    part_id = models.CharField(max_length=50)
    created = models.DateTimeField(null=True, blank=True)   # HWDB mint date
    updated = models.DateTimeField(null=True, blank=True)   # HWDB last-modified

    class Meta:
        indexes = [models.Index(fields=["part_type_id", "updated"])]

    def __str__(self):
        return f"HwdbComponentEvent({self.part_type_id}, {self.updated:%Y-%m-%d})"


class HierarchySyncState(models.Model):
    """Singleton recording the last hierarchy (skeleton) sync run.

    Surfaces "hierarchy refreshed · 3h ago" and the node/system counts on
    /explore/. Mirrors the ``hwdb.LarasicSyncState`` singleton pattern.
    """

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    systems_count = models.PositiveIntegerField(default=0)
    nodes_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
