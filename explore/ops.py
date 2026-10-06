"""The ops page's data (#194): who uses the app, what broke, how the server
is doing — for the few accounts in ``settings.OPS_USERS``.

Everything here reads the local database and the warning log; nothing calls
HWDB, nothing counts the big mirror tables, and the log is tailed (the last
``TAIL_BYTES``), never parsed whole. Each collector is wrapped by ``collect()`` so one failing
source (a missing log file, a Linux-only /proc read on a laptop) leaves a
note on the page instead of a 500.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

import django
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone

from hwdb.models import HwdbSyncState

from . import sheetupload
from .middleware import CETS_GROUP
from .models import ActivityEvent, HierarchyNode, HierarchySyncState, SheetJob, UsageDay

TAIL_BYTES = 256 * 1024
ERROR_LINES = 200
WRITES_DAYS = 30
USAGE_RETENTION_DAYS = 400


def allowed(user) -> bool:
    return bool(user and user.is_authenticated
                and user.get_username() in settings.OPS_USERS)


def ago(dt, now) -> str:
    """``3 min ago`` / ``14 h ago`` / ``3 d ago``; empty for None."""
    if dt is None:
        return ""
    m = int((now - dt).total_seconds() // 60)
    if m < 1:
        return "just now"
    if m < 60:
        return f"{m} min ago"
    if m < 48 * 60:
        return f"{m // 60} h ago"
    return f"{m // (24 * 60)} d ago"


def tail(path, nbytes: int = TAIL_BYTES) -> list[str]:
    """The last whole lines of a file, oldest first; ``[]`` when unreadable."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    if size > nbytes and lines:
        lines = lines[1:]           # the first line was cut mid-way
    return lines


# ---- users -----------------------------------------------------------------

def users(now) -> dict:
    today = now.date()
    seen = {r["username"]: r for r in
            UsageDay.objects.values("username").annotate(last_seen=Max("last_seen"))}
    week = dict(UsageDay.objects.filter(day__gte=today - timedelta(days=6))
                .values_list("username").annotate(n=Sum("requests")))
    today_rows = UsageDay.objects.filter(day=today)
    members = set(get_user_model().objects.filter(groups__name=CETS_GROUP)
                  .values_list("username", flat=True))
    rows = []
    for u in get_user_model().objects.all():
        s = seen.get(u.username)
        last_seen = s["last_seen"] if s else None
        rows.append({
            "username": u.username, "joined": u.date_joined, "last_login": u.last_login,
            "last_seen": last_seen, "last_seen_ago": ago(last_seen, now),
            "week": week.get(u.username, 0),
            "member": u.username in members, "superuser": u.is_superuser,
        })
    epoch = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)
    rows.sort(key=lambda r: r["last_seen"] or r["last_login"] or r["joined"] or epoch,
              reverse=True)
    top = max((r["week"] for r in rows), default=0)
    for r in rows:
        r["pct"] = round(r["week"] / top * 100) if top else 0
    return {
        "rows": rows, "total": len(rows),
        "month": sum(1 for r in rows
                     if r["last_login"] and r["last_login"] >= now - timedelta(days=30)),
        "today": today_rows.count(),
        "requests_today": today_rows.aggregate(n=Sum("requests"))["n"] or 0,
        "tracked_since": UsageDay.objects.aggregate(d=Min("day"))["d"],
    }


# ---- errors (the WARNING+ file) --------------------------------------------

_LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (\w+) (\S+) ?(.*)$")


def errors(now) -> dict:
    path = Path(settings.LOG_FILE)
    entries = []
    for line in tail(path):
        m = _LOG_LINE.match(line)
        if m:
            ts = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt_timezone.utc)
            entries.append({"ts": ts, "level": m[2], "logger": m[3],
                            "message": m[4], "extra": []})
        elif entries:
            entries[-1]["extra"].append(line)     # traceback lines ride with their record
    entries = entries[-ERROR_LINES:]
    entries.reverse()
    day = now - timedelta(days=1)
    recent = [e for e in entries if e["ts"] >= day]
    for e in entries:
        e["ago"] = ago(e["ts"], now)
    size = path.stat().st_size if path.exists() else None
    return {"entries": entries, "path": str(path), "exists": path.exists(), "size": size,
            "warn_24h": len(recent),
            # every kept record is recent → the real day count is at least this
            "capped": len(entries) == ERROR_LINES and len(recent) == len(entries),
            "error_24h": sum(1 for e in recent if e["level"] in ("ERROR", "CRITICAL"))}


# ---- sync health -----------------------------------------------------------

_HTTP_ERR = re.compile(r"^(\d{3} [A-Z ]+?) for https?://\S+")


def _short(err: str) -> str:
    """``403 FORBIDDEN`` out of the API client's long message; other errors
    keep their first clause. The full text goes in the row's tooltip."""
    m = _HTTP_ERR.match(err)
    return m[1].strip() if m else err.split(":")[0][:80]


def sync(now) -> dict:
    out = []
    for inst in ("prod", "dev"):
        st = HierarchySyncState.objects.filter(instance=inst).first()
        types = HierarchyNode.for_instance(inst).filter(level=HierarchyNode.LEVEL_TYPE)
        agg = types.aggregate(
            n=Count("id"), synced=Count("tests_synced_at"),
            newest=Max("tests_synced_at"), oldest=Min("tests_synced_at"),
            errors=Count("id", filter=~Q(tests_sync_error="")),
            items=Sum("n_components"), tests=Sum("n_tests"))
        running = bool(st and st.started_at and (not st.finished_at or st.started_at > st.finished_at))
        bad = bool(st and st.last_error) or agg["errors"] > 0
        out.append({
            "instance": inst, "state": st, "running": running,
            "finished_ago": ago(st.finished_at if st else None, now),
            "status": "running" if running else "bad" if bad else "ok" if st and st.finished_at else "none",
            "types": agg["n"], "synced": agg["synced"], "newest": agg["newest"],
            "newest_ago": ago(agg["newest"], now), "oldest": agg["oldest"],
            "errors": agg["errors"], "items": agg["items"] or 0, "tests": agg["tests"] or 0,
            "error_types": [{"part_type_id": t[0], "name": t[1], "full": t[2], "short": _short(t[2])}
                            for t in types.exclude(tests_sync_error="").order_by("-synced_at")
                            .values_list("part_type_id", "name", "tests_sync_error")[:5]],
        })
    chips = [{"family": c.family, "finished": c.finished_at,
              "finished_ago": ago(c.finished_at, now), "total": c.chips_total,
              "new": c.chips_new, "gone": c.chips_disappeared, "error": c.last_error}
             for c in HwdbSyncState.objects.order_by("family")]
    return {"instances": out, "chips": chips}


# ---- writes (the Activities feed, by day) ----------------------------------

def writes(now) -> dict:
    start = (now - timedelta(days=WRITES_DAYS - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    by_day: dict = defaultdict(lambda: defaultdict(int))
    totals: dict = defaultdict(int)
    for ts, kind in ActivityEvent.objects.filter(created_at__gte=start).values_list("created_at", "kind"):
        by_day[ts.date()][kind] += 1
        totals[kind] += 1
    order = list(ActivityEvent.KIND_LABELS) + sorted(k for k in totals if k not in ActivityEvent.KIND_LABELS)
    days = [start.date() + timedelta(days=i) for i in range(WRITES_DAYS)]
    top = max((sum(by_day[d].values()) for d in days), default=0)
    bars = []
    for d in days:
        segs = [{"kind": k, "label": ActivityEvent.KIND_LABELS.get(k, k), "n": by_day[d][k],
                 "pct": by_day[d][k] / top * 100} for k in order if by_day[d].get(k)]
        bars.append({"day": d, "total": sum(by_day[d].values()), "segs": segs})
    return {"bars": bars, "first": days[0], "mid": days[len(days) // 2], "last": days[-1],
            "legend": [{"kind": k, "label": ActivityEvent.KIND_LABELS.get(k, k), "n": totals[k]}
                       for k in order if totals.get(k)],
            "total": sum(totals.values()), "days": WRITES_DAYS}


# ---- sheet uploads ---------------------------------------------------------

def jobs(now) -> dict:
    rows = []
    for j in SheetJob.objects.filter(updated_at__gte=now - timedelta(days=sheetupload.RETENTION_DAYS)):
        c = j.counts()
        status = "in progress" if c["pending"] else "failed" if c["failed"] else "done"
        rows.append({"job": j, "updated_ago": ago(j.updated_at, now), "rows": len(j.rows),
                     "counts": c, "status": status,
                     "errors": [r.get("error") or r.get("message") or "" for r in j.rows
                                if r.get("state") == "error"][:3]})
    return {"rows": rows, "days": sheetupload.RETENTION_DAYS}


# ---- machine ---------------------------------------------------------------

def _git_rev() -> str:
    try:
        head = (Path(settings.BASE_DIR) / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            ref = Path(settings.BASE_DIR) / ".git" / head[5:]
            if ref.exists():
                return ref.read_text().strip()[:7]
            for line in (Path(settings.BASE_DIR) / ".git" / "packed-refs").read_text().splitlines():
                if line.endswith(" " + head[5:]):
                    return line.split()[0][:7]
            return ""
        return head[:7]
    except OSError:
        return ""


def _master_started():
    """When the gunicorn master (this worker's parent) started — Linux only."""
    try:
        with open("/proc/stat") as f:
            btime = next(int(l.split()[1]) for l in f if l.startswith("btime "))
        with open(f"/proc/{os.getppid()}/stat") as f:
            ticks = int(f.read().rsplit(")", 1)[1].split()[19])
        return datetime.fromtimestamp(btime + ticks / os.sysconf("SC_CLK_TCK"), dt_timezone.utc)
    except (OSError, StopIteration, ValueError, IndexError):
        return None


def machine(now) -> dict:
    out = {"python": sys.version.split()[0], "django": django.get_version(),
           "sqlite": sqlite3.sqlite_version, "rev": _git_rev(),
           "started": _master_started(), "pid": os.getpid()}
    out["started_ago"] = ago(out["started"], now)
    if connection.vendor == "sqlite":
        db = Path(str(connection.settings_dict["NAME"]))
        if db.is_file():
            out["db"] = db
            out["db_size"] = db.stat().st_size
            wal = db.with_name(db.name + "-wal")
            out["wal_size"] = wal.stat().st_size if wal.exists() else 0
            with connection.cursor() as cur:
                cur.execute("PRAGMA freelist_count")
                free = cur.fetchone()[0]
                cur.execute("PRAGMA page_size")
                out["free_bytes"] = free * cur.fetchone()[0]
            du = shutil.disk_usage(db.parent)
            out["disk_free"], out["disk_total"] = du.free, du.total
            out["disk_pct"] = round(du.used / du.total * 100)
    try:
        out["load"] = os.getloadavg()
    except OSError:
        pass
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k] = int(v.split()[0]) * 1024
        out["mem_total"] = mem["MemTotal"]
        out["mem_used"] = mem["MemTotal"] - mem["MemAvailable"]
        out["mem_pct"] = round(out["mem_used"] / mem["MemTotal"] * 100)
    except (OSError, KeyError, ValueError):
        pass
    return out


# ---- the page --------------------------------------------------------------

COLLECTORS = (("users", users), ("errors", errors), ("sync", sync), ("writes", writes),
              ("jobs", jobs), ("machine", machine))


def collect() -> dict:
    """Every section's data plus ``problems``: the sections that failed and
    why. Also prunes usage rows past retention — cheap, and this is the only
    reader of the table."""
    now = timezone.now()
    out: dict = {"now": now, "problems": []}
    try:
        UsageDay.objects.filter(day__lt=now.date() - timedelta(days=USAGE_RETENTION_DAYS)).delete()
    except Exception as e:           # pragma: no cover — shown on the page
        out["problems"].append(f"usage prune: {e}")
    for name, fn in COLLECTORS:
        try:
            out[name] = fn(now)
        except Exception as e:
            out[name] = None
            out["problems"].append(f"{name}: {type(e).__name__}: {e}")
    return out
