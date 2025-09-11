from django.contrib import admin
from .models import FEMB, FE, ADC, COLDATA, FEMB_TEST


class FEMBAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "version", "status", "last_update")


class FEAdmin(admin.ModelAdmin):
    list_display = (
        "serial_number",
        "status",
        "tray_id",
        "last_update",
        "femb",
        "femb_pos",
    )


class ADCAdmin(admin.ModelAdmin):
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


class FEMB_TESTAdmin(admin.ModelAdmin):
    list_display = ("femb", "timestamp", "site", "test_type", "test_env", "status")


# admin.site.unregister(FEMB)
# admin.site.unregister(FE)
admin.site.register(FEMB, FEMBAdmin)
admin.site.register(FE, FEAdmin)
admin.site.register(ADC, ADCAdmin)
admin.site.register(COLDATA, COLDATAAdmin)
admin.site.register(FEMB_TEST, FEMB_TESTAdmin)

admin.site.site_header = "CETs Admin"
admin.site.site_title = "CETs Admin Portal"
admin.site.index_title = "Welcome to CETs Admin Portal"
