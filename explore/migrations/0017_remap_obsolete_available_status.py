# Remap mirrored component statuses stuck on HWDB's obsolete pre-vocabulary
# set (ids 1-3) to "Unknown" (Shipping Procedure Appendix B, #75). The events
# sync now normalizes on write; this catches rows synced before that. Only
# the unambiguous legacy NAMES can be remapped here — the mirror stores no
# ids, and "Permanently Unavailable" doubles as the modern id 170, so those
# rows are left for the id-aware sync to correct on their next walk.

from django.db import migrations


def remap(apps, schema_editor):
    E = apps.get_model("explore", "HwdbComponentEvent")
    E.objects.filter(
        status__in=["Available", "Temporarily Unavailable"]
    ).update(status="Unknown")


class Migration(migrations.Migration):

    dependencies = [
        ("explore", "0016_hierarchynode_cable_ends_hierarchynode_category"),
    ]

    operations = [
        migrations.RunPython(remap, migrations.RunPython.noop),
    ]
