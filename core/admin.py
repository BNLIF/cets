from django.contrib import admin
from .models import FEMB, FE


class FEMBAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "status", "last_update")


class FEAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "status", "tray_id", "last_update", "femb")


# admin.site.unregister(FEMB)
# admin.site.unregister(FE)
admin.site.register(FEMB, FEMBAdmin)
admin.site.register(FE, FEAdmin)
