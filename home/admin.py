from django.contrib import admin

from .models import SmartBin, TelemetryRecord


@admin.register(SmartBin)
class SmartBinAdmin(admin.ModelAdmin):
    list_display = ("device_id", "location_name", "alert_status", "last_seen")
    search_fields = ("device_id", "location_name")
    list_filter = ("alert_status",)


@admin.register(TelemetryRecord)
class TelemetryRecordAdmin(admin.ModelAdmin):
    list_display = ("smart_bin", "recorded_at", "fill_level", "gas_value", "alert_status")
    list_filter = ("alert_status", "recorded_at")
    search_fields = ("smart_bin__device_id", "smart_bin__location_name")
    date_hierarchy = "recorded_at"
