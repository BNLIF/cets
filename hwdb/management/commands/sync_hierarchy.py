"""Walk the FD-VD HWDB hierarchy into the local ComponentTypeNode mirror.

Headless counterpart of the "Refresh hierarchy" button (ADR-0010). Management
commands have no Django session, so they can't mint a bearer the way the web
views do — pass one explicitly:

    python manage.py sync_hierarchy --bearer-file /tmp/bt_u$(id -u)
    BEARER_TOKEN_FILE=/tmp/bt_u502 python manage.py sync_hierarchy

If you don't have a bearer on hand, use the web "Refresh hierarchy" button,
which mints one from your linked FNAL session.
"""
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from hwdb.api_client import FnalDbApiClient
from hwdb.hierarchy import sync_hierarchy


class Command(BaseCommand):
    help = "Sync the FD-VD HWDB component hierarchy into ComponentTypeNode."

    def add_arguments(self, parser):
        parser.add_argument("--bearer", help="FNAL bearer token (raw string).")
        parser.add_argument(
            "--bearer-file",
            default=os.environ.get("BEARER_TOKEN_FILE"),
            help="Path to a file holding the bearer (default: $BEARER_TOKEN_FILE).",
        )
        parser.add_argument(
            "--instance",
            default="prod",
            choices=list(settings.HWDB_PROFILES),
            help="HWDB instance to read from (default: prod).",
        )

    def handle(self, *args, **opts):
        bearer = opts["bearer"]
        if not bearer and opts["bearer_file"]:
            try:
                bearer = Path(opts["bearer_file"]).read_text().strip()
            except OSError as e:
                raise CommandError(f"could not read --bearer-file: {e}")
        if not bearer:
            raise CommandError(
                "No bearer. Pass --bearer / --bearer-file, set BEARER_TOKEN_FILE, "
                "or use the 'Refresh hierarchy' button in the web UI."
            )

        api = FnalDbApiClient(settings.HWDB_PROFILES[opts["instance"]]["api"], bearer)
        for line in sync_hierarchy(api):
            self.stdout.write(line.rstrip())
