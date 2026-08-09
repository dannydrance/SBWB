from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("home", "0006_telemetryrecord")]

    operations = [
        migrations.AddField(model_name="smartbin", name="system_name", field=models.CharField(default="Smart Biomedical Waste Bin", max_length=100)),
        migrations.AddField(model_name="smartbin", name="system_version", field=models.CharField(blank=True, default="", max_length=40)),
        migrations.AddField(model_name="smartbin", name="mac_address", field=models.CharField(blank=True, default="", max_length=32)),
        migrations.AddField(model_name="smartbin", name="wifi_ssid", field=models.CharField(blank=True, default="", max_length=64)),
        migrations.AddField(model_name="smartbin", name="ip_address", field=models.CharField(blank=True, default="", max_length=45)),
    ]
