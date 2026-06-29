"""Audit live HWDB systems against the curation (`explore/curation.yaml`).

Read-only probe (no DB writes). Labels each top-level `systems/D` entry
**curated** or **not curated**, and separately reports curated ids that have
disappeared from HWDB — so curation drift (new systems to adopt, stale entries
to drop) is caught deliberately rather than silently.

Easiest: mint a fresh bearer inline via CILogon (no token-file juggling) —

    python manage.py list_systems --login

Or reuse an existing bearer, same handling as `sync_hierarchy`:

    python manage.py list_systems --bearer-file /tmp/bt_u$(id -u)
    BEARER_TOKEN_FILE=/tmp/bt_u502 python manage.py list_systems

Output: every system id + name, with KEEP (would be mirrored today) or skip,
per explore.hierarchy.is_fdvd_system.
"""
import os
import time
import webbrowser
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from explore import curation
from hwdb.api_client import FnalDbApiClient
from hwdb.fnal import flow


class Command(BaseCommand):
    help = "Audit live HWDB systems against curation.yaml (curated / not curated / drift)."

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
        parser.add_argument(
            "--project", default="D", help="Project part1 (default: D = DUNE)."
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
                    "No bearer. Use --login, or pass --bearer / --bearer-file "
                    "(or set BEARER_TOKEN_FILE)."
                )

        api = FnalDbApiClient(settings.HWDB_PROFILES[opts["instance"]]["api"], bearer)
        body = api.get_systems(opts["project"])
        systems = sorted(
            (body.get("data") or []), key=lambda s: s.get("id") or 0
        )

        curated = curation.curated_system_ids()
        live_ids = {s.get("id") for s in systems}

        # Per-system: curated vs in-HWDB-but-not-curated.
        self.stdout.write(f"{'id':>4}  {'status':<13}  name")
        self.stdout.write("-" * 52)
        n_curated = 0
        for s in systems:
            sid = s.get("id")
            name = s.get("name") or ""
            is_curated = sid in curated
            n_curated += is_curated
            self.stdout.write(
                f"{sid:>4}  {'curated' if is_curated else 'not curated':<13}  {name}"
            )

        # Drift: curated in the YAML but no longer present in HWDB.
        missing = sorted(curated - live_ids)
        if missing:
            self.stdout.write("")
            self.stdout.write("curated but missing from HWDB (stale curation.yaml entries):")
            for sid in missing:
                self.stdout.write(f"  {sid}")

        not_curated = len(systems) - n_curated
        self.stdout.write("-" * 52)
        self.stdout.write(
            f"{len(systems)} systems in HWDB · {n_curated} curated · "
            f"{not_curated} not curated · {len(missing)} curated-but-missing"
        )
        if not_curated:
            self.stdout.write(
                "Review the 'not curated' systems above; add any newly-relevant "
                "ones to explore/curation.yaml."
            )

    def _login(self) -> str:
        """Run the CILogon device flow in the terminal and mint a fresh bearer.

        Reuses hwdb.fnal.flow (the same vault flow the web login uses); the
        ~10 min device-flow lifetime bounds the poll loop.
        """
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
