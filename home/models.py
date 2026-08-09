from datetime import timedelta

from django.db import models
from django.utils import timezone


class SmartBin(models.Model):
    ALERT_CHOICES = [
        ('NOMINAL', 'Nominal Secure'),
        ('BIN_FULL', 'Critical Warning: Bin Full'),
        ('METAL', 'Sharps Alert: Metal Found'),
    ]

    device_id = models.CharField(max_length=50, unique=True)
    location_name = models.CharField(max_length=100)
    system_name = models.CharField(max_length=100, default='Smart Biomedical Waste Bin')
    system_version = models.CharField(max_length=40, blank=True, default='')
    mac_address = models.CharField(max_length=32, blank=True, default='')
    wifi_ssid = models.CharField(max_length=64, blank=True, default='')
    ip_address = models.CharField(max_length=45, blank=True, default='')
    fill_level = models.IntegerField(default=0)
    gas_value = models.IntegerField(default=0)
    alert_status = models.CharField(max_length=20, choices=ALERT_CHOICES, default='NOMINAL')
    last_seen = models.DateTimeField(auto_now=True)
    temperature = models.FloatField()
    elementTemp = models.FloatField()
    humidity = models.FloatField()
    metal = models.BooleanField()
    uv = models.BooleanField()
    heater = models.BooleanField()
    lid = models.BooleanField()
    binFull = models.BooleanField()
    interlock = models.BooleanField()
    binLevel = models.FloatField()
    heaterState = models.BooleanField(default=False)
    uvState = models.BooleanField(default=False)

    pending_command = models.CharField(max_length=50, blank=True, null=True, default=None)

    COMMAND_STATUS_CHOICES = [
        ('NONE', 'No command sent'),
        ('PENDING', 'Sent — awaiting device confirmation'),
        ('ACKED', 'Confirmed applied by device'),
        ('TIMEOUT', 'No confirmation received in time'),
    ]
    last_command = models.CharField(max_length=50, blank=True, null=True, default=None)
    last_command_status = models.CharField(max_length=10, choices=COMMAND_STATUS_CHOICES, default='NONE')
    last_command_time = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-last_seen']

    def __str__(self):
        return f"{self.device_id} — {self.location_name}"

    @property
    def is_online(self):
        return timezone.now() - self.last_seen < timedelta(seconds=12)

    @property
    def duration_status(self):
        diff = timezone.now() - self.last_seen
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        if diff.days > 0:
            return f"{diff.days}d {hours}h ago"
        if hours > 0:
            return f"{hours}h {minutes}m ago"
        if minutes == 0:
            seconds = max(0, diff.seconds)
            return "just now" if seconds < 3 else f"{seconds}s ago"
        return f"{minutes}m ago"


class TelemetryRecord(models.Model):
    """Immutable telemetry sample used for analytics and reporting."""

    smart_bin = models.ForeignKey(SmartBin, on_delete=models.CASCADE, related_name='telemetry_records')
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)
    fill_level = models.FloatField(default=0)
    gas_value = models.FloatField(default=0)
    temperature = models.FloatField(default=0)
    element_temp = models.FloatField(default=0)
    humidity = models.FloatField(default=0)
    metal = models.BooleanField(default=False)
    uv = models.BooleanField(default=False)
    heater = models.BooleanField(default=False)
    lid = models.BooleanField(default=False)
    bin_full = models.BooleanField(default=False)
    interlock = models.BooleanField(default=False)
    alert_status = models.CharField(max_length=20, default='NOMINAL')

    class Meta:
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['smart_bin', '-recorded_at'], name='telemetry_bin_time_idx'),
        ]

    def __str__(self):
        return f"{self.smart_bin.device_id} @ {self.recorded_at:%Y-%m-%d %H:%M:%S}"
