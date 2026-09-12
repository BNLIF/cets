"""Type-wide plot data (#144): a live Item-Specifications sweep, one flat
row per item, streamed as NDJSON so the browser can show progress on big
types and cache the result (IndexedDB) for client-side plotting.

Why live, not mirrored: ``GET components?part_type_id=`` rows carry the full
nested ``specifications`` (identical to the detail record — 2026-09-10 dev
probe), so a whole type is one paginated sweep, not a per-item fan-out. The
mirror-light rule targets the latter. Test data has no such endpoint and
will arrive via #143 as a second source.
"""

from __future__ import annotations

import json
import re
from typing import Iterator

from django.db.models import Count, Sum

from . import parts
from .events import _parse_created, _ref_name
from .models import HwdbComponentEvent, HwdbTestData, HwdbTestValue

PAGE_SIZE = 500


def _latest_spec_data(row: dict):
    """The free-form ``DATA`` blob of the latest specifications entry (the
    same latest-entry rule as ``shipments._spec_block``); the entry itself
    when it has no ``DATA`` key; ``{}`` when there are no specs."""
    specs = row.get("specifications") or []
    entry = specs[-1] if specs else None
    if not isinstance(entry, dict):
        return {}
    data = entry.get("DATA")
    return data if isinstance(data, dict) else entry


def flat_row(row: dict) -> dict:
    """One list row → the item fields the plot page filters on + its spec data."""
    created, updated = _parse_created(row.get("created")), _parse_created(row.get("updated"))
    return {
        "pid": row.get("part_id") or "",
        "serial": row.get("serial_number") or "",
        "status": parts.normalize_status(row.get("status")) or "",
        "creator": _ref_name(row.get("creator")),
        "manufacturer": _ref_name(row.get("manufacturer")),
        "institution": _ref_name(row.get("institution")),
        "created": created.date().isoformat() if created else "",
        "updated": updated.date().isoformat() if updated else "",
        "data": _latest_spec_data(row),
    }


def _pages(api, part_type_id: str) -> Iterator[tuple[int, int, list]]:
    """``(page, pages, rows)`` per page of ``components?part_type_id=``."""
    page = 1
    while True:
        body = api._make_request(
            "GET", "components",
            params={"part_type_id": part_type_id, "page": page, "size": PAGE_SIZE},
        )
        rows = body.get("data") or []
        pages = (body.get("pagination") or {}).get("pages") or 1
        yield page, pages, rows
        if page >= pages or not rows:
            return
        page += 1


def stream_specs(api, part_type_id: str) -> Iterator[str]:
    """NDJSON lines: ``{"pages": P}`` first, one item row per line, a
    ``{"page": n}`` marker after each page, ``{"done": N}`` last. Errors
    surface as ``{"error": "..."}`` and end the stream."""
    n = 0
    try:
        for page, pages, rows in _pages(api, part_type_id):
            if page == 1:
                yield json.dumps({"pages": pages}) + "\n"
            for r in rows:
                n += 1
                yield json.dumps(flat_row(r), default=str) + "\n"
            yield json.dumps({"page": page}) + "\n"
    except Exception as e:  # network / HWDB — the client shows the message
        yield json.dumps({"error": f"{type(e).__name__}: {e}"}) + "\n"
        return
    yield json.dumps({"done": n}) + "\n"


# ---- test_data source (#143): served per key from the HwdbTestValue table ----

def walk_keys(node, prefix: tuple, acc: dict, nvals: dict | None = None) -> None:
    """Every leaf path under ``node`` → ``acc[path] += 1`` once per call
    (call once per item) and, when ``nvals`` is given, ``nvals[path]`` += the
    number of leaf values (an array of 1960 points counts 1960). Lists of
    dicts explode (their keys join the same prefix); a list of scalars is
    one leaf. Mirrors the Plot page's JS walk, so specs and test_data keys
    look the same to the user."""
    if isinstance(node, list):
        if any(isinstance(e, dict) for e in node):
            seen: dict = {}
            for e in node:
                if isinstance(e, dict):
                    walk_keys(e, prefix, seen, nvals)
            for k in seen:
                acc[k] = acc.get(k, 0) + 1
        elif prefix:
            acc[prefix] = acc.get(prefix, 0) + 1
            if nvals is not None:
                nvals[prefix] = nvals.get(prefix, 0) + len(node)
        return
    if isinstance(node, dict):
        for k, v in node.items():
            walk_keys(v, prefix + (str(k),), acc, nvals)
        return
    if prefix:
        acc[prefix] = acc.get(prefix, 0) + 1
        if nvals is not None:
            nvals[prefix] = nvals.get(prefix, 0) + 1


def values_at(node, segs: list, i: int = 0) -> list:
    """All leaf values under a path; lists at any depth flatten (the JS
    ``valuesAt``)."""
    if isinstance(node, list):
        out = []
        for e in node:
            out.extend(values_at(e, segs, i))
        return out
    if i == len(segs):
        return [node] if node is not None and not isinstance(node, (dict, list)) else []
    if isinstance(node, dict) and segs[i] in node:
        return values_at(node[segs[i]], segs, i + 1)
    return []


def flatten(node, prefix: tuple = (), out: dict | None = None) -> dict:
    """``{path tuple: [leaf values]}`` for a whole record — every key
    ``walk_keys`` would list, with the values ``values_at`` would return.
    One pass per record at store time (``events.store_test_data``)."""
    if out is None:
        out = {}
    if isinstance(node, dict):
        for k, v in node.items():
            flatten(v, prefix + (str(k),), out)
    elif isinstance(node, list):
        if any(isinstance(e, dict) for e in node):
            for e in node:
                if isinstance(e, dict):
                    flatten(e, prefix, out)
                elif e is not None and not isinstance(e, list) and prefix:
                    out.setdefault(prefix, []).append(e)
        elif prefix:
            vals = out.setdefault(prefix, [])
            for e in node:
                if isinstance(e, list):
                    vals.extend(values_at(e, [], 0))
                elif e is not None:
                    vals.append(e)
    elif node is not None and prefix:
        out.setdefault(prefix, []).append(node)
    return out


def nested(node, segs: list, i: int = 0):
    """Leaf values under a path with the list structure kept (#154): a list
    per list level holding only the elements that contribute, a scalar at
    the leaf, None for nothing. ``leaves(nested(...))`` == ``values_at``."""
    if isinstance(node, list):
        out = []
        for e in node:
            r = nested(e, segs, i)
            if r is not None and r != []:
                out.append(r)
        return out
    if i == len(segs):
        return None if node is None or isinstance(node, (dict, list)) else node
    if isinstance(node, dict) and segs[i] in node:
        return nested(node[segs[i]], segs, i + 1)
    return None


def leaves(v) -> list:
    """Flatten a nested value."""
    if not isinstance(v, list):
        return [v]
    out = []
    for e in v:
        out.extend(leaves(e))
    return out


def dims(v) -> list[int]:
    """Max length per list level of a nested value — ``[6, 6, 1960]`` for a
    per-run, per-SiPM sweep; ``[1]`` for a scalar; ``[]`` for a bare leaf."""
    if not isinstance(v, list):
        return []
    sub: list[int] = []
    for e in v:
        for k, n in enumerate(dims(e)):
            if k < len(sub):
                sub[k] = max(sub[k], n)
            else:
                sub.append(n)
    return [len(v)] + sub


def dim_labels(node, segs: list) -> list[str]:
    """The path segment at which each list level of ``nested(node, segs)``
    occurs, following the first contributing branch."""
    out, i = [], 0
    while True:
        if isinstance(node, list):
            out.append(segs[i - 1] if i else "")
            node = next((e for e in node if nested(e, segs, i) not in (None, [])), None)
            if node is None:
                return out
            continue
        if i == len(segs):
            return out
        if isinstance(node, dict) and segs[i] in node:
            node, i = node[segs[i]], i + 1
            continue
        return out


def select(v, idx: list, d: int = 0) -> list:
    """Pin one index per list level (None = every element) and flatten the
    rest; an index past a level's end contributes nothing."""
    if not isinstance(v, list):
        return [v]
    i = idx[d] if d < len(idx) else None
    if i is None:
        out = []
        for e in v:
            out.extend(select(e, idx, d + 1))
        return out
    return select(v[i], idx, d + 1) if 0 <= i < len(v) else []


def path_key(path) -> str:
    """The stored ``HwdbTestValue.path`` text for a path (list or tuple)."""
    return json.dumps([str(x) for x in path])


def value_rows(instance: str, part_type_id: str, part_id: str, test_type_id: int,
               test_data: dict) -> list:
    """``HwdbTestValue`` instances (unsaved) for one record. ``values`` keeps
    the list structure (#154) — a flat list for one-level data, so rows
    written before look the same."""
    rows = []
    for p in flatten(test_data):
        v = nested(test_data, list(p))
        if v is None or v == []:
            continue
        if not isinstance(v, list):
            v = [v]
        rows.append(HwdbTestValue(instance=instance, part_type_id=part_type_id, part_id=part_id,
                                  test_type_id=test_type_id, path=path_key(p), values=v,
                                  nv=len(leaves(v))))
    return rows


def test_sources(instance: str, part_type_id: str) -> list[dict]:
    """Test types with mirrored records for this type: ``[{id, name, n}]``."""
    rows = (HwdbTestData.for_instance(instance).filter(part_type_id=part_type_id)
            .values("test_type_id", "test_type_name").annotate(n=Count("id"))
            .order_by("test_type_name"))
    return [{"id": r["test_type_id"], "name": r["test_type_name"], "n": r["n"]} for r in rows]


def _records(instance, part_type_id, test_type_id):
    return HwdbTestData.for_instance(instance).filter(
        part_type_id=part_type_id, test_type_id=test_type_id)


def _values(instance, part_type_id, test_type_id):
    return HwdbTestValue.for_instance(instance).filter(
        part_type_id=part_type_id, test_type_id=test_type_id)


# Cap on one values response. A per-SiPM IV curve is ~2000 points per
# item; over the 8420-board type that key is 16.8M floats (2026-09-11) —
# the page must narrow to an item (PID filter) for such keys.
MAX_VALUES = 2_000_000
BIG_PER_ITEM = 16       # a key with more values per item than this is an array key


class TooManyValues(Exception):
    def __init__(self, n):
        super().__init__(f"{n:,} values exceed the {MAX_VALUES:,} limit — narrow the PID filter")
        self.n = n


def test_keys(instance: str, part_type_id: str, test_type_id: int) -> dict:
    """``{"keys": [{"path": [...], "n": items-with-key, "nv": total values,
    "big": array-like}], "n_items": N, "max_values": cap}`` for one test
    type — a GROUP BY over the value table. ``big`` marks keys averaging
    more than ``BIG_PER_ITEM`` values per item (per-channel arrays), as
    opposed to a scalar that merely repeats across a record's list entries."""
    rows = (_values(instance, part_type_id, test_type_id).values("path")
            .annotate(n=Count("id"), nv=Sum("nv")).order_by("-n", "path"))
    keys = [{"path": json.loads(r["path"]), "n": r["n"], "nv": r["nv"],
             "big": r["nv"] > BIG_PER_ITEM * r["n"]} for r in rows]
    # #154: array keys' shapes — [{seg, n}] per list level, labelled by the
    # path segment the list sits at — read off ONE sample item (the one with
    # the largest row): two queries, not one per key. Keys the sample lacks
    # (rare keys) report no shape.
    vals = _values(instance, part_type_id, test_type_id)
    pid = vals.order_by("-nv").values_list("part_id", flat=True).first()
    if pid:
        samples = {pid: dict(vals.filter(part_id=pid).values_list("path", "values"))}
        records: dict = {}

        def record(p):
            if p not in records:
                records[p] = (_records(instance, part_type_id, test_type_id).filter(part_id=p)
                              .values_list("test_data", flat=True).first()) or {}
            return records[p]

        for k in keys:
            pk, spid = path_key(k["path"]), pid
            if pk not in samples[pid]:      # a key the sample item lacks: its own largest row
                row = vals.filter(path=pk).order_by("-nv").values_list("part_id", "values").first()
                if not row:
                    continue
                spid = row[0]
                samples.setdefault(spid, {})[pk] = row[1]
            d = dims(samples[spid][pk])
            if max(d, default=0) <= 1:
                continue
            labels = dim_labels(record(spid), k["path"])
            k["dims"] = [{"seg": labels[j] if j < len(labels) else "", "n": n} for j, n in enumerate(d)]
    return {"keys": keys, "n_items": _records(instance, part_type_id, test_type_id).count(),
            "max_values": MAX_VALUES}


# #155: "00120..06000", "D00400300001-00120..06000", open ends ("00120..",
# "..06000") — the digits are the PID's numeric suffix
_RANGE = re.compile(r"^\s*(?:[A-Za-z]\d{11}-)?(\d*)\s*\.\.\s*(\d*)\s*$")


def pid_range(text: str | None) -> tuple[str | None, str | None] | None:
    """``(lo, hi)`` five-digit suffixes (either may be None for an open end)
    when ``text`` is a PID range, else None. A lone ``..`` is not a range."""
    m = _RANGE.match(text or "")
    if not m or not (m.group(1) or m.group(2)):
        return None
    lo, hi = m.group(1), m.group(2)
    return (lo.zfill(5) if lo else None, hi.zfill(5) if hi else None)


def _pid_filtered(qs, pid_re: str | None, part_type_id: str | None = None):
    """Push the page's PID filter into SQL: a range (#155) as a lexicographic
    between on the fixed-width PID, else regex (case-insensitive), or a
    substring match when the pattern is not a valid regex — same fallback
    as the page."""
    if not pid_re:
        return qs
    rng = pid_range(pid_re)
    if rng and part_type_id:
        lo, hi = rng
        if lo:
            qs = qs.filter(part_id__gte=f"{part_type_id}-{lo}")
        if hi:
            qs = qs.filter(part_id__lte=f"{part_type_id}-{hi}")
        return qs
    try:
        re.compile(pid_re)
    except re.error:
        return qs.filter(part_id__icontains=pid_re)
    m = re.fullmatch(r"\^([A-Za-z0-9-]+)\$", pid_re)      # the item-picker's anchored form
    if m:
        return qs.filter(part_id__iexact=m.group(1))
    return qs.filter(part_id__iregex=pid_re)


def test_items(instance: str, part_type_id: str, test_type_id: int) -> list[dict]:
    """One row per item holding this test type — the Plot page's item list:
    pid + the component facets (from the component mirror) + the record's
    HWDB created date."""
    recs = list(_records(instance, part_type_id, test_type_id)
                .values_list("part_id", "created"))
    comps = {c.part_id: c for c in HwdbComponentEvent.for_instance(instance)
             .filter(part_type_id=part_type_id, part_id__in=[p for p, _ in recs])}
    out = []
    for pid, created in sorted(recs):
        c = comps.get(pid)
        out.append({
            "pid": pid,
            "serial": c.serial_number if c else "",
            "status": c.status if c else "",
            "creator": c.created_by if c else "",
            "manufacturer": c.manufacturer if c else "",
            "institution": c.institution if c else "",
            "created": c.created.date().isoformat() if c and c.created else "",
            "updated": c.updated.date().isoformat() if c and c.updated else "",
            "tested": created.date().isoformat() if created else "",
        })
    return out


def test_values(instance: str, part_type_id: str, test_type_id: int, path: list,
                pid_re: str | None = None, idx: list | None = None) -> dict:
    """``{pid: [leaf values]}`` for one key (items without it are omitted).
    ``pid_re`` narrows to matching PIDs in SQL; ``idx`` (#154) pins one
    index per list level (None = all). Raises ``TooManyValues`` when the
    matching rows' ``nv`` sum passes ``MAX_VALUES`` — checked with one
    aggregate before any row is read; with ``idx`` the sum is scaled by the
    pinned dimensions' sizes first, and the true count is checked as rows
    are read."""
    qs = _pid_filtered(_values(instance, part_type_id, test_type_id).filter(path=path_key(path)),
                       pid_re, part_type_id)
    n = qs.aggregate(t=Sum("nv"))["t"] or 0
    if idx and any(i is not None for i in idx):
        sample = qs.order_by("-nv").values_list("values", flat=True).first()
        est = float(n)
        for d, size in enumerate(dims(sample) if sample is not None else []):
            if d < len(idx) and idx[d] is not None and size > 1:
                est /= size
        if est > MAX_VALUES:
            raise TooManyValues(int(est))
        out, total = {}, 0
        for pid, v in qs.values_list("part_id", "values").iterator():
            sel = select(v, idx)
            if sel:
                out[pid] = sel
                total += len(sel)
                if total > MAX_VALUES:
                    raise TooManyValues(total)
        return out
    if n > MAX_VALUES:
        raise TooManyValues(n)
    return {pid: leaves(v) for pid, v in qs.values_list("part_id", "values")}
