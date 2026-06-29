from django.contrib import admin

from .models import (
    HierarchyNode,
    HierarchySyncState,
    HwdbComponentEvent,
    HwdbTestEvent,
)


@admin.register(HierarchyNode)
class HierarchyNodeAdmin(admin.ModelAdmin):
    list_display = ("level", "name", "system_name", "subsystem_name",
                    "part_type_id", "n_components", "n_tests", "tests_synced_at")
    list_filter = ("level", "system_name")
    search_fields = ("part_type_id", "name", "full_name")


admin.site.register([HwdbTestEvent, HwdbComponentEvent, HierarchySyncState])
