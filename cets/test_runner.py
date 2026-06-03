from django.conf import settings
from django.test.runner import DiscoverRunner
from django.urls import set_script_prefix


class CetsTestRunner(DiscoverRunner):
    """Run tests as if the app were mounted at ``/``.

    Production serves under ``FORCE_SCRIPT_NAME=/twister/cets`` (set in
    ``.env``). With that prefix active, ``reverse()`` emits
    ``/twister/cets/...`` URLs, but the Django test client leaves the whole
    string in ``PATH_INFO`` without stripping the script name — so the URL
    resolver (rooted at ``/``) 404s on every view request. Neutralizing the
    prefix for the test run lets ``reverse()`` and resolution agree again,
    independent of whatever ``.env`` the developer happens to have.

    We clear both halves: ``FORCE_SCRIPT_NAME`` so each request's handler
    recomputes the prefix as ``/``, and the already-set thread-local script
    prefix so ``reverse()`` calls made before the first request emit ``/``-
    rooted URLs too.
    """

    def setup_test_environment(self, **kwargs):
        settings.FORCE_SCRIPT_NAME = None
        set_script_prefix("/")
        super().setup_test_environment(**kwargs)
