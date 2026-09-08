from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_femb_io_1865_1k_00020_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="femb",
            name="batch_id",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="femb",
            name="hwdb_part_id",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
    ]
