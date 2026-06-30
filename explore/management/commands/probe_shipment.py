"""Spike: probe a shipping-box component type's real HWDB shape (ADR-0013, #42).

Read-only (no DB writes). For each item of a shipping-box component type
(default the anchor ``D08120200001`` "CE Shipping box"), dumps the raw
``/locations`` and ``/subcomponents`` responses, then prints a per-item summary
so we can settle the **status-inference rule** (in-transit vs. delivered) before
committing the ShipmentItem mirror schema.

Bearer handling mirrors ``list_systems``:

    python manage.py probe_shipment --login
    python manage.py probe_shipment --bearer-file /tmp/bt_u$(id -u)
    BEARER_TOKEN_FILE=/tmp/bt_u502 python manage.py probe_shipment --type D08120200001
"""
import json
import os
import time
import webbrowser
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from hwdb.api_client import FnalDbApiClient
from hwdb.fnal import flow

ANCHOR_TYPE = "D08120200001"  # FD CE › CE Shipping Box › "CE Shipping box"


class Command(BaseCommand):
    help = "Probe a shipping-box component type's /locations + /subcomponents (read-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--type", default=ANCHOR_TYPE,
            help=f"Component type id to probe (default: {ANCHOR_TYPE}).",
        )
        parser.add_argument(
            "--raw", action="store_true",
            help="Also dump the full raw JSON for each item's locations/subcomponents.",
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
            help="HWDB instance to read from (default: prod).",
        )

    def handle(self, *args, **opts):
        bearer = self._resolve_bearer(opts)
        api = FnalDbApiClient(settings.HWDB_PROFILES[opts["instance"]]["api"], bearer)
        type_id = opts["type"]

        body = api.get_component_types(type_id)
        items = body.get("data") or []
        if not items:
            self.stdout.write(f"No items found for component type {type_id}.")
            return

        self.stdout.write(f"Component type {type_id}: {len(items)} item(s)\n")
        for it in items:
            pid = it.get("part_id") or it.get("pid")
            self._probe_item(api, pid, raw=opts["raw"])

        self.stdout.write("")
        self.stdout.write(
            "Next: from the location entries above, decide the in-transit vs. "
            "delivered rule (e.g. is there a status field, a sentinel location "
            "name, or must we infer from the latest entry?) and record it on #42."
        )

    def _probe_item(self, api, pid, *, raw):
        self.stdout.write("=" * 64)
        self.stdout.write(f"item {pid}")

        locs = (api.get_locations(pid).get("data") or [])
        self.stdout.write(f"  locations: {len(locs)} event(s)")
        # Events come back newest-first; don't trust order — sort by arrived desc.
        for ev in sorted(locs, key=lambda e: e.get("arrived") or "", reverse=True):
            loc = ev.get("location") or {}
            self.stdout.write(
                f"    arrived={ev.get('arrived')!r}  "
                f"location={loc.get('name')!r} (id={loc.get('id')})  "
                f"creator={ev.get('creator')!r}  comments={ev.get('comments')!r}"
            )
        if locs:
            latest = max(locs, key=lambda e: e.get("arrived") or "")
            loc = latest.get("location") or {}
            in_transit = loc.get("id") == 0
            status = "IN TRANSIT" if in_transit else f"at {loc.get('name')!r}"
            self.stdout.write(
                f"  -> latest: {loc.get('name')!r} (location.id={loc.get('id')}) "
                f"arrived {latest.get('arrived')!r}  =>  status: {status}"
            )

        subs = api.get_subcomponents(pid).get("data")
        self.stdout.write(f"  subcomponents (manifest): {self._summarize_subs(subs)}")

        if raw:
            self.stdout.write("  --- raw locations ---")
            self.stdout.write(json.dumps(locs, indent=2))
            self.stdout.write("  --- raw subcomponents ---")
            self.stdout.write(json.dumps(subs, indent=2))

    @staticmethod
    def _summarize_subs(subs):
        """Manifest is a list of {part_id, type_name, functional_position,
        operation}. Summarize count + the functional positions held."""
        if not subs:
            return "0 (empty)"
        if isinstance(subs, list):
            positions = [s.get("functional_position") for s in subs]
            return f"{len(subs)} part(s) @ positions: {positions}"
        return repr(subs)

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
