from django.contrib import admin
from .models import FEMB, LArASIC, ColdADC, COLDATA, FembRepair, FembTest, CABLE, CableTest


class FEMBAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "version", "status", "last_update")


class LArASICAdmin(admin.ModelAdmin):
    list_display = (
        "serial_number",
        "status",
        "tray_id",
        "last_update",
        "femb",
        "femb_pos",
    )


class ColdADCAdmin(admin.ModelAdmin):
    list_display = (
        "serial_number",
        "status",
        "tray_id",
        "last_update",
        "femb",
        "femb_pos",
    )


class COLDATAAdmin(admin.ModelAdmin):
    list_display = (
        "serial_number",
        "status",
        "tray_id",
        "last_update",
        "femb",
        "femb_pos",
    )


class FembRepairAdmin(admin.ModelAdmin):
    list_display = ("femb", "iteration_number", "date", "operator", "batch_id", "what_was_fixed")
    list_filter = ("femb__version",)
    search_fields = ("femb__serial_number", "operator", "batch_id")


class FembTestAdmin(admin.ModelAdmin):
    list_display = ("femb", "timestamp", "site", "test_type", "test_env", "status")


class CABLEAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "batch_number", "status", "last_update")


class CableTestAdmin(admin.ModelAdmin):
    list_display = ("cable", "timestamp", "site", "test_type", "test_env", "status")


admin.site.register(FEMB, FEMBAdmin)
admin.site.register(LArASIC, LArASICAdmin)
admin.site.register(ColdADC, ColdADCAdmin)
admin.site.register(COLDATA, COLDATAAdmin)
admin.site.register(FembRepair, FembRepairAdmin)
admin.site.register(FembTest, FembTestAdmin)
admin.site.register(CABLE, CABLEAdmin)
admin.site.register(CableTest, CableTestAdmin)

admin.site.site_header = "CETs Admin"
admin.site.site_title = "CETs Admin Portal"
admin.site.index_title = "Welcome to CETs Admin Portal"
