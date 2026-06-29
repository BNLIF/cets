"""Create the `cets` group and enroll every existing user (ADR-0011, #34).

Membership in this group marks a CETS-zone user (the shared `guest` account +
real team accounts that exist today). FNAL-provisioned explore users created
later get no group → explore-only. Reversible: drops the group.
"""

from django.conf import settings
from django.db import migrations

CETS_GROUP = "cets"


def add_existing_users_to_cets(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("auth", "User")
    group, _ = Group.objects.get_or_create(name=CETS_GROUP)
    group.user_set.add(*User.objects.all())


def remove_cets_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=CETS_GROUP).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("explore", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(add_existing_users_to_cets, remove_cets_group),
    ]
