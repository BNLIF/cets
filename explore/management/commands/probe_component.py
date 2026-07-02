"""Spike: dump raw ``components/{pid}`` records to locate the QC flags (#51).

Read-only (no DB writes). Fetches the full component detail record for a few
items of a component type (or explicit --pid list), prints the raw JSON, and
scans every key path for flag candidates (installed / certified / qa-qc /
uploaded) — so we can confirm whether Hajime's three binary flags live on the
record the events sync already fetches, before touching the mirror schema.

Bearer handling mirrors ``probe_shipment``:

    python manage.py probe_component --login --save-bearer /tmp/bt_u$(id -u)
    BEARER_TOKEN_FILE=/tmp/bt_u502 python manage.py probe_component --type D08100100003
    BEARER_TOKEN_FILE=/tmp/bt_u502 python manage.py probe_component --instance dev --pid D00599800007-00133
"""
import json
import os
import re
import time
import webbrowser
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from hwdb.api_client import FnalDbApiClient
from hwdb.fnal import flow

_FLAG_RE = re.compile(r"instal|certif|qa|qc|upload|status", re.IGNORECASE)


class Command(BaseCommand):
    help = "Dump raw components/{pid} records and scan for QC-flag fields (read-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--type", help="Component type id: probe its first -n items.",
        )
        parser.add_argument(
            "--pid", action="append", default=[],
            help="Explicit part id to probe (repeatable; overrides --type sampling).",
        )
        parser.add_argument(
            "-n", "--count", type=int, default=2,
            help="How many items to sample from --type's listing (default: 2).",
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
            "--save-bearer",
            help="After --login, also write the minted bearer to this file "
                 "(so follow-up probes can reuse it via --bearer-file).",
        )
        parser.add_argument(
            "--instance", default="prod", choices=list(settings.HWDB_PROFILES),
            help="HWDB instance to read from (default: prod).",
        )

    def handle(self, *args, **opts):
        bearer = self._resolve_bearer(opts)
        api = FnalDbApiClient(settings.HWDB_PROFILES[opts["instance"]]["api"], bearer)

        pids = list(opts["pid"])
        if not pids:
            if not opts["type"]:
                raise CommandError("Pass --type <part_type_id> or --pid <part_id>.")
            body = api._make_request(
                "GET", f"component-types/{opts['type']}/components",
                params={"page": 1, "size": max(opts["count"], 1)},
            )
            pids = [r["part_id"] for r in (body.get("data") or []) if r.get("part_id")]
            pids = pids[: opts["count"]]
            if not pids:
                self.stdout.write(f"No items found for component type {opts['type']}.")
                return

        for pid in pids:
            self._probe(api, pid)

    def _probe(self, api, pid):
        self.stdout.write("=" * 64)
        self.stdout.write(f"component {pid}")
        body = api._make_request("GET", f"components/{pid}")
        d = body.get("data") if isinstance(body.get("data"), dict) else body
        self.stdout.write(json.dumps(d, indent=2, default=str))
        hits = []
        self._scan(d, "", hits)
        self.stdout.write("  --- flag candidates (key path matches "
                          "installed/certified/qa/qc/upload/status) ---")
        if hits:
            for path, val in hits:
                self.stdout.write(f"    {path} = {val!r}")
        else:
            self.stdout.write("    (none)")

    def _scan(self, node, path, hits):
        """Collect (path, value) for every key anywhere in the record whose
        name looks flag-ish. Values are truncated — the raw dump above has
        the full detail."""
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{path}.{k}" if path else k
                if _FLAG_RE.search(str(k)) and not isinstance(v, (dict, list)):
                    hits.append((p, v))
                self._scan(v, p, hits)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                self._scan(v, f"{path}[{i}]", hits)

    def _resolve_bearer(self, opts) -> str:
        if opts["login"]:
            bearer = self._login()
            if opts["save_bearer"]:
                p = Path(opts["save_bearer"])
                p.write_text(bearer)
                p.chmod(0o600)
                self.stdout.write(f"  bearer saved to {p} (mode 600, ~10h lifetime)")
            return bearer
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
