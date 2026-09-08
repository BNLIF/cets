from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_femb_batch_id_hwdb_part_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="femb",
            name="hwdb_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
