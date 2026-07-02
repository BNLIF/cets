"""Re-sync component detail for every previously-synced component type.

Backfills newly-added mirror columns (e.g. the #51 QC flags) after a schema
change: runs the same sync the leaf-page buttons use — default ``components``
mode (detail for all, tests for new only) — for every leaf on one instance
whose tests were already synced. Failures don't stop the sweep; they're
reported at the end.

Bearer handling mirrors ``sync_hierarchy``:

    BEARER_TOKEN_FILE=/tmp/bt_u502 python manage.py resync_components
    python manage.py resync_components --instance dev --login
    python manage.py resync_components --mode full   # also re-fetch all tests
"""
import os
import time
import webbrowser
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from explore.events import sync_test_events
from explore.models import HierarchyNode
from hwdb.fnal import flow


class Command(BaseCommand):
    help = "Re-sync component detail for all previously-synced component types."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode", default="components",
            choices=["incremental", "components", "full"],
            help="Sync mode per type (default: components — re-fetch detail "
                 "for all, tests for new components only).",
        )
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
            "--instance", default="prod", choices=list(settings.HWDB_PROFILES),
            help="HWDB instance to sync against (default: prod).",
        )

    def handle(self, *args, **opts):
        bearer = self._resolve_bearer(opts)
        inst = opts["instance"]
        api = settings.HWDB_PROFILES[inst]["api"]
        leaves = list(
            HierarchyNode.for_instance(inst)
            .filter(level=HierarchyNode.LEVEL_TYPE, tests_synced_at__isnull=False)
            .order_by("part_type_id")
        )
        self.stdout.write(
            f"{len(leaves)} previously-synced component type(s) on {inst!r} "
            f"(mode: {opts['mode']})"
        )
        failures = []
        for i, leaf in enumerate(leaves, 1):
            self.stdout.write(f"[{i}/{len(leaves)}] {leaf.part_type_id} · {leaf.name}")
            try:
                for line in sync_test_events(api, bearer, leaf.part_type_id,
                                             instance=inst, mode=opts["mode"]):
                    self.stdout.write("  " + line.rstrip())
            except Exception as e:  # keep sweeping; report at the end
                failures.append(leaf.part_type_id)
                self.stderr.write(f"  FAILED: {e}")

        if failures:
            raise CommandError(
                f"{len(failures)}/{len(leaves)} type(s) failed: {', '.join(failures)}"
            )
        self.stdout.write(f"all {len(leaves)} type(s) re-synced")

    def _resolve_bearer(self, opts) -> str:
        if opts["login"]:
            return self._login()
        bearer = opts["bearer"]
        if not bearer and opts["bearer_file"]:
            try:
                bearer = Path(opts["bearer_file"]).read_text().strip()
            except OSError as e:
                raise CommandError(f"could not read --bearer-file: {e}")
        if not bearer:
            raise CommandError(
                "No bearer. Use --login, or pass --bearer / --bearer-file "
                "(or set BEARER_TOKEN_FILE)."
            )
        return bearer

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
