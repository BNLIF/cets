from django.contrib import admin

from .models import (
    ComponentTypeNode,
    HierarchySyncState,
    HwdbComponentEvent,
    HwdbTestEvent,
)


@admin.register(ComponentTypeNode)
class ComponentTypeNodeAdmin(admin.ModelAdmin):
    list_display = ("part_type_id", "system_name", "subsystem_name",
                    "component_type_name", "n_components", "n_tests", "tests_synced_at")
    list_filter = ("system_name",)
    search_fields = ("part_type_id", "full_name")


admin.site.register([HwdbTestEvent, HwdbComponentEvent, HierarchySyncState])
