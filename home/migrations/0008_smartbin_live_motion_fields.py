from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("home", "0007_smartbin_ip_address_smartbin_mac_address_and_more")]

    operations = [
        migrations.AddField(model_name="smartbin", name="lidState", field=models.IntegerField(default=0)),
        migrations.AddField(model_name="smartbin", name="limitClosed", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="smartbin", name="irDetected", field=models.BooleanField(default=False)),
    ]
