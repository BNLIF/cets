"""Walk the FD-VD HWDB hierarchy into the local ComponentTypeNode mirror.

Headless counterpart of the "Refresh hierarchy" button (ADR-0010). Management
commands have no Django session, so they can't mint a bearer the way the web
views do — pass one explicitly:

    python manage.py sync_hierarchy --login
    python manage.py sync_hierarchy --bearer-file /tmp/bt_u$(id -u)
    BEARER_TOKEN_FILE=/tmp/bt_u502 python manage.py sync_hierarchy

If you don't have a bearer on hand, use ``--login`` (inline CILogon device
flow) or the web "Refresh hierarchy" button, which mints one from your session.
"""
import os
import time
import webbrowser
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from explore.hierarchy import sync_hierarchy
from hwdb.api_client import FnalDbApiClient
from hwdb.fnal import flow


class Command(BaseCommand):
    help = "Sync the FD-VD HWDB component hierarchy into ComponentTypeNode."

    def add_arguments(self, parser):
        parser.add_argument(
            "--login", action="store_true",
            help="Mint a fresh bearer inline via CILogon device flow (browser).",
        )
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
        if opts["login"]:
            bearer = self._login()
        else:
            bearer = opts["bearer"]
            if not bearer and opts["bearer_file"]:
                try:
                    bearer = Path(opts["bearer_file"]).read_text().strip()
                except OSError as e:
                    raise CommandError(f"could not read --bearer-file: {e}")
            if not bearer:
                raise CommandError(
                    "No bearer. Use --login, pass --bearer / --bearer-file, set "
                    "BEARER_TOKEN_FILE, or use the 'Refresh hierarchy' web button."
                )

        api = FnalDbApiClient(settings.HWDB_PROFILES[opts["instance"]]["api"], bearer)
        for line in sync_hierarchy(api):
            self.stdout.write(line.rstrip())

    def _login(self) -> str:
        start = flow.start()
        self.stdout.write("\nSign in with Fermilab — open this URL in your browser:")
        self.stdout.write(f"  {start.auth_url}\n")
        if start.user_code:
            self.stdout.write(f"  (user code: {start.user_code})")
        try:
            webbrowser.open(start.auth_url)
        except Exception:
            pass

        interval = 5
        self.stdout.write("Waiting for you to complete the login…")
        for _ in range(120):  # ~10 min ceiling at 5s
            time.sleep(interval)
            result = flow.poll(start.poll_body)
            if result.outcome == "complete":
                login = flow.complete(result.auth or {})
                self.stdout.write(f"  signed in as {login.credkey!r}; minting bearer…")
                return flow.mint_bearer(login.vault_token, login.credkey)
            if result.outcome == "slow_down":
                interval += 5
        raise CommandError("device flow timed out before you completed the login.")
