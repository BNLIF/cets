"""Template context for the URL-carried HWDB instance (#47): the banner flag
and the prod⇄dev switch targets rendered in explore/base.html. Plus the
watched-activity badge (#90), computed lazily so only templates that render
it (explore/base.html) pay its two small mirror queries."""

from django.urls import reverse
from django.utils.functional import SimpleLazyObject

from .instances import NAMESPACE_BY_INSTANCE, instance_of


def instance(request):
    def _unread():
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return 0
        from . import activity, watches
        return watches.unread_count(instance_of(request),
                                    activity.actor_of(request))

    def _initials():
        # Proper first+last initials ("Chao Zhang" → CZ) when the full name
        # is known — whoami caches it in the session (the FNAL link itself
        # carries only the credkey). Empty string lets the template fall back
        # to its credkey/username slice.
        session = getattr(request, "session", None)
        user = getattr(request, "user", None)
        name = (session.get("fnal_full_name", "") if session is not None else "")
        if not name and user is not None and user.is_authenticated:
            name = user.get_full_name()
        words = name.split()
        if len(words) >= 2:
            return (words[0][0] + words[-1][0]).upper()
        return name[:2].upper()

    return {
        "hwdb_instance": instance_of(request),
        "instance_homes": {
            inst: reverse("explore:home", current_app=ns)
            for inst, ns in NAMESPACE_BY_INSTANCE.items()
        },
        "watch_unread": SimpleLazyObject(_unread),
        "user_initials": SimpleLazyObject(_initials),
    }
