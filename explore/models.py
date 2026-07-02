from django.db import models


class InstanceScoped(models.Model):
    """Mirror rows are per HWDB instance (#47): prod and dev share tables,
    disambiguated by this column — part-type ids are NOT guaranteed disjoint
    across instances, so every mirror read must scope through
    ``for_instance()`` rather than raw ``objects``."""

    instance = models.CharField(max_length=8, default="prod", db_index=True)

    class Meta:
        abstract = True

    @classmethod
    def for_instance(cls, instance: str):
        return cls.objects.filter(instance=instance)


class HierarchyNode(InstanceScoped):
    """One node of the DUNE hardware structure, mirrored from one HWDB instance.

    The structure-first skeleton that powers the /explore/ tree (ADR-0012,
    generalizing the leaf-only ``ComponentTypeNode`` of ADR-0010). One row per
    HWDB **System**, **Subsystem**, *and* **Component Type** under a curated
    system — including empty intermediate nodes, so a system registered upstream
    with no component types yet is still navigable. ``parent`` links a node to
    its container (systems have none; Region/Family come from the curation YAML
    at render time, not from this mirror). Populated by
    hierarchy.sync_hierarchy() — read-only, additive, independent of the CE chip
    mirror (``hwdb.HwdbChip``).

    Denormalized ``system_*``/``subsystem_*`` fields are carried on every node so
    the tree and a selected leaf render without walking parents. The leaf-only
    fields (``part_type_id`` and the test-sync state) are blank/zero on
    System/Subsystem rows. ``part_type_id`` keys the event tables and encodes the
    path: ``D08100100003`` = ``D``·``081``·``001``·``00003``.
    """

    LEVEL_SYSTEM = "system"
    LEVEL_SUBSYSTEM = "subsystem"
    LEVEL_TYPE = "component_type"
    LEVEL_CHOICES = [
        (LEVEL_SYSTEM, "System"),
        (LEVEL_SUBSYSTEM, "Subsystem"),
        (LEVEL_TYPE, "Component type"),
    ]

    level = models.CharField(max_length=16, choices=LEVEL_CHOICES, db_index=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    project = models.CharField(max_length=4, default="D")
    system_id = models.PositiveIntegerField(db_index=True)
    system_name = models.CharField(max_length=100)
    subsystem_id = models.PositiveIntegerField(null=True, blank=True)
    subsystem_name = models.CharField(max_length=100, blank=True, default="")
    name = models.CharField(max_length=200)  # this node's own display name
    full_name = models.CharField(max_length=300, blank=True, default="")

    # Component-type leaves only (blank/zero on System & Subsystem rows):
    part_type_id = models.CharField(max_length=20, blank=True, default="", db_index=True)
    n_components = models.PositiveIntegerField(default=0)
    # NULL tests_synced_at = the leaf's tests have never been pulled; the
    # explorer syncs lazily on first visit. n_tests powers the tree accent.
    tests_synced_at = models.DateTimeField(null=True, blank=True)
    n_tests = models.PositiveIntegerField(default=0)
    tests_sync_error = models.TextField(blank=True, default="")
    # Set once a shipment sync has run for a shipping-type leaf (#43+). Distinct
    # from tests_synced_at; NULL = never synced, so "synced with 0 non-empty
    # boxes" is not mistaken for "never synced" (which would re-trigger the
    # auto-sync and loop).
    shipments_synced_at = models.DateTimeField(null=True, blank=True)

    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["system_id", "subsystem_id", "name"]
        indexes = [models.Index(fields=["level", "system_id"])]

    def __str__(self):
        return f"HierarchyNode({self.level}, {self.name})"


class HwdbTestEvent(InstanceScoped):
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


class HwdbComponentEvent(InstanceScoped):
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
    serial_number = models.CharField(max_length=120, blank=True, default="")
    created_by = models.CharField(max_length=120, blank=True, default="")  # HWDB creator
    # Categorical facets off the same detail record, for the component-breakdown
    # bar charts (mirror-only, no extra fetch). Empty when not (yet) synced.
    status = models.CharField(max_length=120, blank=True, default="")
    manufacturer = models.CharField(max_length=160, blank=True, default="")
    institution = models.CharField(max_length=160, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["part_type_id", "updated"])]

    def __str__(self):
        return f"HwdbComponentEvent({self.part_type_id}, {self.updated:%Y-%m-%d})"


class ShipmentItem(InstanceScoped):
    """One shipping box (an item of a curated shipping-type leaf), mirrored from
    HWDB production (ADR-0013).

    Holds **only the latest location** — enough to render the Shipments panel's
    items list ("where is every box now") with zero live calls. The full
    location timeline and the box's manifest (subcomponents) are *not* mirrored;
    they're fetched live when a user expands a box (#44).

    ``location_id == 0`` is the HWDB "In Transit" sentinel (settled by the #42
    spike): ``is_in_transit`` keys off it. Rewritten wholesale per
    ``part_type_id`` on each sync — a disposable cache, like the rest of the
    mirror (ADR-0007).
    """

    part_type_id = models.CharField(max_length=20, db_index=True)
    part_id = models.CharField(max_length=50)  # the box's PID
    location_name = models.CharField(max_length=200, blank=True, default="")
    location_id = models.IntegerField(null=True, blank=True)  # 0 = "In Transit"
    n_contents = models.PositiveIntegerField(default=0)  # current subcomponents (#45+)
    last_arrived = models.DateTimeField(null=True, blank=True)
    # Derived from the full timeline at sync time (#45): shipped = first time it
    # entered transit; received = arrival at its current real location (null
    # while still in transit).
    shipped_date = models.DateTimeField(null=True, blank=True)
    received_date = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["part_id"]
        indexes = [models.Index(fields=["part_type_id"])]

    @property
    def is_in_transit(self) -> bool:
        return self.location_id == 0

    @property
    def status_label(self) -> str:
        if self.location_id == 0:
            return "In transit"
        if self.location_id is not None:
            return "Delivered"
        return "Unknown"

    def __str__(self):
        return f"ShipmentItem({self.part_id}, {self.location_name})"


class HierarchySyncState(models.Model):
    """One row per HWDB instance recording that instance's last hierarchy
    (skeleton) sync run.

    Surfaces "hierarchy refreshed · 3h ago" and the node/system counts on
    /explore/. Was a singleton (the ``hwdb.LarasicSyncState`` pattern) until
    the dev instance arrived (#47).
    """

    instance = models.CharField(max_length=8, default="prod", unique=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    systems_count = models.PositiveIntegerField(default=0)
    nodes_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    @classmethod
    def get(cls, instance: str):
        obj, _ = cls.objects.get_or_create(instance=instance)
        return obj
