from django.db import migrations

# Clarification supplied by the CE expert for this specific board (version
# string "I0-1865-1K", digit-zero — distinct from the letter-O "IO-1865-1K"
# boards): its PCB design version is actually 1865-1L (first batch of 1L),
# despite the I0-1865-1K label. It is distinct from the 1865-1L/00020 second
# batch. The mismatch was introduced during the PCB design process; no
# hardware or data correction is required — this only records the fact.
#
# This board is not in the local DB; the update() below no-ops where the row
# is absent and applies the note wherever the board exists (e.g. the server).
NOTE = (
    "PCB design version is actually 1865-1L (first batch of 1L), despite the "
    "I0-1865-1K label here. Distinct from the 1865-1L/00020 second batch. "
    "The mismatch was introduced during the PCB design process; no hardware or "
    "data change is required — recorded for clarification."
)


def set_note(apps, schema_editor):
    FEMB = apps.get_model("core", "FEMB")
    FEMB.objects.filter(version="I0-1865-1K", serial_number="00020").update(notes=NOTE)


def clear_note(apps, schema_editor):
    FEMB = apps.get_model("core", "FEMB")
    FEMB.objects.filter(version="I0-1865-1K", serial_number="00020").update(notes="")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_femb_notes"),
    ]

    operations = [
        migrations.RunPython(set_note, clear_note),
    ]
