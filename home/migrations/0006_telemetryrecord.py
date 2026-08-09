from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0005_smartbin_last_command_smartbin_last_command_status_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='TelemetryRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('recorded_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('fill_level', models.FloatField(default=0)),
                ('gas_value', models.FloatField(default=0)),
                ('temperature', models.FloatField(default=0)),
                ('element_temp', models.FloatField(default=0)),
                ('humidity', models.FloatField(default=0)),
                ('metal', models.BooleanField(default=False)),
                ('uv', models.BooleanField(default=False)),
                ('heater', models.BooleanField(default=False)),
                ('lid', models.BooleanField(default=False)),
                ('bin_full', models.BooleanField(default=False)),
                ('interlock', models.BooleanField(default=False)),
                ('alert_status', models.CharField(default='NOMINAL', max_length=20)),
                ('smart_bin', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='telemetry_records', to='home.smartbin')),
            ],
            options={'ordering': ['-recorded_at']},
        ),
        migrations.AddIndex(
            model_name='telemetryrecord',
            index=models.Index(fields=['smart_bin', '-recorded_at'], name='telemetry_bin_time_idx'),
        ),
    ]
