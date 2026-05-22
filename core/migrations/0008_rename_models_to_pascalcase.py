import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Rename five models to product-canonical names / PEP 8 PascalCase:
      FE          -> LArASIC
      ADC         -> ColdADC
      FEMB_TEST   -> FembTest
      FEMB_REPAIR -> FembRepair
      CABLE_TEST  -> CableTest

    RenameModel also renames the underlying DB table (e.g. core_fe ->
    core_larasic). The AlterField calls below update related_name on the
    FKs into FembRepair to follow the new chip class names.
    """

    dependencies = [
        ("core", "0007_add_femb_repair_history"),
    ]

    operations = [
        migrations.RenameModel(old_name="FE", new_name="LArASIC"),
        migrations.RenameModel(old_name="ADC", new_name="ColdADC"),
        migrations.RenameModel(old_name="FEMB_TEST", new_name="FembTest"),
        migrations.RenameModel(old_name="FEMB_REPAIR", new_name="FembRepair"),
        migrations.RenameModel(old_name="CABLE_TEST", new_name="CableTest"),

        migrations.AlterField(
            model_name="larasic",
            name="installed_at_repair",
            field=models.ForeignKey(
                blank=True,
                help_text="NULL = original assembly; set when installed during a repair",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="installed_larasics",
                to="core.fembrepair",
            ),
        ),
        migrations.AlterField(
            model_name="larasic",
            name="removed_at_repair",
            field=models.ForeignKey(
                blank=True,
                help_text="NULL = still on FEMB; set when removed during a repair",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="removed_larasics",
                to="core.fembrepair",
            ),
        ),
        migrations.AlterField(
            model_name="coldadc",
            name="installed_at_repair",
            field=models.ForeignKey(
                blank=True,
                help_text="NULL = original assembly; set when installed during a repair",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="installed_coldadcs",
                to="core.fembrepair",
            ),
        ),
        migrations.AlterField(
            model_name="coldadc",
            name="removed_at_repair",
            field=models.ForeignKey(
                blank=True,
                help_text="NULL = still on FEMB; set when removed during a repair",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="removed_coldadcs",
                to="core.fembrepair",
            ),
        ),
        # COLDATA's related_names stay the same but its `to=` reference must
        # follow the renamed FembRepair model.
        migrations.AlterField(
            model_name="coldata",
            name="installed_at_repair",
            field=models.ForeignKey(
                blank=True,
                help_text="NULL = original assembly; set when installed during a repair",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="installed_coldatas",
                to="core.fembrepair",
            ),
        ),
        migrations.AlterField(
            model_name="coldata",
            name="removed_at_repair",
            field=models.ForeignKey(
                blank=True,
                help_text="NULL = still on FEMB; set when removed during a repair",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="removed_coldatas",
                to="core.fembrepair",
            ),
        ),
    ]
