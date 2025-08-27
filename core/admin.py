from django.contrib import admin
from .models import FEMB, FE, ADC, COLDATA


class FEMBAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "status", "last_update")


class FEAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "status", "tray_id", "last_update", "femb")


class ADCAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "status", "tray_id", "last_update", "femb")


class COLDATAAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "status", "tray_id", "last_update", "femb")


# admin.site.unregister(FEMB)
# admin.site.unregister(FE)
admin.site.register(FEMB, FEMBAdmin)
admin.site.register(FE, FEAdmin)
admin.site.register(ADC, ADCAdmin)
admin.site.register(COLDATA, COLDATAAdmin)

admin.site.site_header = "CETs Admin"
admin.site.site_title = "CETs Admin Portal"
admin.site.index_title = "Welcome to CETs Admin Portal"
