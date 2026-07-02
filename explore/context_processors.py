"""Template context for the URL-carried HWDB instance (#47): the banner flag
and the prod⇄dev switch targets rendered in explore/base.html."""

from django.urls import reverse

from .instances import NAMESPACE_BY_INSTANCE, instance_of


def instance(request):
    return {
        "hwdb_instance": instance_of(request),
        "instance_homes": {
            inst: reverse("explore:home", current_app=ns)
            for inst, ns in NAMESPACE_BY_INSTANCE.items()
        },
    }
