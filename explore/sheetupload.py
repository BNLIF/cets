"""#177 / #178: a spreadsheet → HWDB, the utility's ``hwdb-upload`` Item and
Test record types in the Explorer (Hajime 2026-09-24). A CSV / Excel tab
in the utility's layout — an optional key/value block in columns A–B, a
blank row, then the column headers; plain names for the standard fields,
``S:`` for spec keys, ``C:`` for sub-component positions, ``T:`` for
test-result keys — is read into cells, mapped column by column, planned
against the type's live listing (create / patch / nothing / error per
item row, one test record per test row; nothing written) and applied one
row at a time: create or patch, location, positions — or a test record,
unless the item already holds one with the same data. Pure helpers plus
``apply_row`` / ``apply_test_row``, which take the client; the view
(``explore_sheet_upload_view``) owns the job record and the HTTP side."""

from __future__ import annotations

import copy
import csv
import io
import json
import re
import zipfile
from datetime import date, datetime

from .checklistforms import STATUS_OPTIONS

UPLOAD_MAX = 20 * 1024 * 1024
RETENTION_DAYS = 3      # a job goes this long after its last change; users rarely delete (Chao 2026-09-24)
ROWS_MAX = 5000
APPLY_SECONDS = 12      # one apply request works this long, then hands back (gunicorn's 30 s)
NEW_ITEM_STATUS = 110   # Waiting on QA/QC Tests — what New item mints with
NULL = "<null>"         # the utility's "clear this" cell value

_PID = re.compile(r"^[A-Za-z]\d{11}-\d{5}$")
_NUM = re.compile(r"^-?(0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?$")   # no leading zeros: 00123 is a serial
_REF = re.compile(r"^\((\d+)\)\s*(.*)$")

# sheet column header (lower-cased) → standard field; the utility's names
STANDARD = {
    "external id": "part_id", "part id": "part_id", "pid": "part_id",
    "serial number": "serial_number", "serial": "serial_number", "sn": "serial_number",
    "status": "status",
    "manufacturer": "manufacturer", "manufacturer id": "manufacturer", "manufacturer name": "manufacturer",
    "institution": "institution", "institution id": "institution", "institution name": "institution",
    "comments": "comments",
    "location": "location", "location id": "location", "location name": "location",
    "location comments": "location_comments",
    "arrived": "arrived", "location timestamp": "arrived",
    "part type id": "part_type_id",
    "record type": "record_type", "test name": "test_name",
    "image file": "image_file", "save as": "save_as", "history order": "hist_order",
    "data": "test_data", "test data": "test_data", "problem": "problem", "file": "",
}
# the per-item JSON schema of a zip upload (#178, Chao 2026-09-25): keys are matched
# case-insensitively, spaces and underscores alike; "data" holds the test DATA, else
# every other key does
ZIP_KEYS = {"part_id": "External ID", "external_id": "External ID", "pid": "External ID",
            "serial_number": "Serial Number", "serial": "Serial Number", "sn": "Serial Number",
            "test_name": "Test Name", "comments": "Comments", "data": "DATA"}
TEST_FIELD_LABELS = [("part_id", "External ID / PID"), ("serial_number", "Serial number"), ("comments", "Comments"),
                     ("test_data", "Test data (the whole DATA object)")]
IMAGE_FIELD_LABELS = [("part_id", "External ID / PID"), ("serial_number", "Serial number"),
                      ("image_file", "Image file (name)"), ("save_as", "Save as (name in HWDB)"),
                      ("comments", "Comments"), ("test_name", "Test name (a test's attachment)"),
                      ("hist_order", "History order (0 = latest test record)")]
FIELD_LABELS = [
    ("part_id", "External ID / PID"), ("serial_number", "Serial number"), ("status", "Status"),
    ("manufacturer", "Manufacturer"), ("institution", "Institution (owner of a new item)"),
    ("comments", "Comments"), ("location", "Location"), ("location_comments", "Location comments"),
    ("arrived", "Arrived"),
]


class SheetError(Exception):
    """A row HWDB refused or the sheet could not use — the message is shown on the row."""


# ---- reading ----------------------------------------------------------------

def _cell(v):
    """A cell as a JSON-safe typed value: Excel keeps its types (an integral
    float becomes an int, a date its ISO text); CSV text becomes a number
    when it reads as one without a leading zero (a serial like 00123 stays
    text); blank is None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() and abs(v) < 1e15 else v
    if isinstance(v, int):
        return v
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    s = str(v).strip()
    if s == "":
        return None
    if _NUM.match(s):
        return float(s) if "." in s or "e" in s.lower() else int(s)
    if s[:1] in "{[" and s[-1:] in "}]":   # a JSON object or list in one cell stays nested
        try:
            return json.loads(s)
        except ValueError:
            pass
    return s


def _show(v) -> str:
    """A cell for a message: JSON for a nested value, plain text otherwise."""
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else _text(v)


def _json_sheet(name: str, blob: bytes) -> dict:
    """A JSON file as one sheet: a list of records (objects), or an object
    keyed by External ID, or an object with the records under ``data`` /
    ``rows`` / ``records`` and its other scalar entries as the key/value
    block (Record Type, Test Name, Part Type ID …). Each record's top-level
    keys are the columns; nested values stay nested (never pass through a
    cell). Row numbers count records from 1."""
    doc = json.loads(blob.decode("utf-8-sig"))
    values, recs = {}, None
    if isinstance(doc, dict):
        for k in ("data", "rows", "records"):
            if isinstance(doc.get(k), list):
                recs = doc[k]
                values = {str(a): b for a, b in doc.items() if a != k and not isinstance(b, (dict, list))}
                break
        if recs is None:
            recs = [{"External ID": k, **v} for k, v in doc.items() if isinstance(v, dict)]
    elif isinstance(doc, list):
        recs = doc
    recs = [r for r in (recs or []) if isinstance(r, dict)]
    columns: list[str] = []
    for r in recs:
        for k in r:
            if str(k) not in columns:
                columns.append(str(k))
    rows = [[i + 1, [r.get(c) if r.get(c) not in ("", None) else None for c in columns]] for i, r in enumerate(recs)]
    return {"name": name.rsplit(".", 1)[0], "values": values, "columns": columns,
            "rows": rows[:ROWS_MAX], "over": max(0, len(rows) - ROWS_MAX)}


def _zip_sheet(name: str, blob: bytes) -> dict:
    """A zip of one JSON file per item as one sheet (#178, Chao 2026-09-25):
    each file is an object with ``part_id`` or ``serial_number``, an optional
    ``test_name`` and ``comments``, and the test DATA under ``data`` — or,
    without a ``data`` key, every remaining key. Columns: File, External ID,
    Serial Number, Test Name, Comments, DATA (the nested object in one
    cell), Problem (a file that is not such an object). Row numbers count
    files from 1."""
    columns = ["File", "External ID", "Serial Number", "Test Name", "Comments", "DATA", "Problem"]
    rows = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = sorted(n for n in zf.namelist()
                       if n.lower().endswith(".json") and not n.endswith("/") and "__MACOSX" not in n)
        for i, n in enumerate(names):
            cells: dict = {"File": n}
            try:
                doc = json.loads(zf.read(n).decode("utf-8-sig"))
                if not isinstance(doc, dict):
                    raise ValueError("not a JSON object")
                rest = {}
                for k, v in doc.items():
                    col = ZIP_KEYS.get(str(k).strip().lower().replace(" ", "_"))
                    if col:
                        cells[col] = v
                    else:
                        rest[k] = v
                if "DATA" not in cells:
                    cells["DATA"] = rest
                if not isinstance(cells["DATA"], dict):
                    raise ValueError("“data” is not an object")
                if not _text(cells.get("External ID")) and not _text(cells.get("Serial Number")):
                    raise ValueError("no part_id and no serial_number")
            except (ValueError, UnicodeDecodeError) as e:
                cells["Problem"] = f"{n}: {e}"
            rows.append([i + 1, [cells.get(c) if cells.get(c) not in ("", None) else None for c in columns]])
    return {"name": name.rsplit(".", 1)[0], "values": {"Record Type": "Test"}, "columns": columns,
            "rows": rows[:ROWS_MAX], "over": max(0, len(rows) - ROWS_MAX)}


def _raw_rows(name: str, blob: bytes) -> list[tuple[str, list[list]]]:
    """Every tab as (name, rows of raw cells)."""
    if (name or "").lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
        try:
            return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
        finally:
            wb.close()
    text = blob.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [(name.rsplit(".", 1)[0] if "." in name else name,
             [list(r) for r in csv.reader(io.StringIO(text), dialect)])]


def _blank(row) -> bool:
    return all(c is None or str(c).strip() == "" for c in row)


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def read_sheets(name: str, blob: bytes) -> list[dict]:
    """Every tab of the file as ``{name, values, columns, rows}``: ``values`` =
    the utility's key/value block (the rows above the first blank row, when
    that block is two columns wide and a header row follows), ``columns`` =
    the header row's texts, ``rows`` = ``[sheet row number, cells]`` for
    every non-blank data row. A tab with no header row is left out. A
    ``.json`` file is one sheet of records (``_json_sheet``)."""
    if (name or "").lower().endswith(".json"):
        sheet = _json_sheet(name, blob)
        return [sheet] if sheet["columns"] else []
    if (name or "").lower().endswith(".zip"):
        sheet = _zip_sheet(name, blob)
        return [sheet] if sheet["rows"] else []
    out = []
    for tab, raw in _raw_rows(name, blob):
        raw = [r for r in raw]
        values, start = {}, 0
        for i, r in enumerate(raw):
            if _blank(r):
                block = raw[:i]
                if block and all(_text(b[0]) and _blank(b[2:]) for b in block) and i + 1 < len(raw):
                    values = {_text(b[0]): _cell(b[1] if len(b) > 1 else None) for b in block}
                    start = i + 1
                break
        head = next((j for j in range(start, len(raw)) if not _blank(raw[j])), None)
        if head is None:
            continue
        columns = [_text(c) for c in raw[head]]
        while columns and not columns[-1]:
            columns.pop()
        if not columns:
            continue
        rows = []
        for j in range(head + 1, len(raw)):
            cells = [_cell(c) for c in raw[j][:len(columns)]]
            cells += [None] * (len(columns) - len(cells))
            if any(c is not None for c in cells):
                rows.append([j + 1, cells])
        out.append({"name": tab, "values": values, "columns": columns, "rows": rows[:ROWS_MAX],
                    "over": max(0, len(rows) - ROWS_MAX)})
    return out


# ---- mapping ----------------------------------------------------------------

def auto_map(columns: list[str], template: dict, connectors: dict, test_keys=(),
             kind: str = "item") -> dict[str, str]:
    """Column header → assignment: a standard name, ``S:key`` / ``C:position``
    / ``T:key`` (the utility's prefixes), or a bare header that names a spec
    key, a position or (``test_keys``) a test-result key. On a Test sheet
    every other header is a test-result key too (the utility's Test
    Results datasheet takes any column); on an Item sheet it stays
    unassigned ("")."""
    specs = {k.lower(): k for k in template}
    poss = {str(p).lower(): str(p) for p in connectors}
    tests = {str(k).lower(): str(k) for k in test_keys}
    out = {}
    for c in columns:
        low = c.lower()
        if low in STANDARD:
            out[c] = STANDARD[low]
        elif c[:2].upper() == "S:" and c[2:].strip():
            out[c] = "spec:" + c[2:].strip()
        elif c[:2].upper() == "C:" and c[2:].strip():
            out[c] = "pos:" + c[2:].strip()
        elif c[:2].upper() == "T:" and c[2:].strip():
            out[c] = "test:" + c[2:].strip()
        elif low in tests:
            out[c] = "test:" + tests[low]
        elif low in specs:
            out[c] = "spec:" + specs[low]
        elif low in poss:
            out[c] = "pos:" + poss[low]
        elif kind == "test":
            out[c] = "test:" + c
        else:
            out[c] = ""
    return out


def detect_kind(sheet: dict) -> tuple[str, str]:
    """(kind, test name) from the sheet: a ``Record Type`` of Item Image /
    Test Image in the key/value block, or an ``Image File`` column, makes
    it an Image sheet; a Record Type of Test, or any ``T:`` column, a Test
    sheet; the block's ``Test Name`` names the test."""
    values = {k.lower(): v for k, v in (sheet.get("values") or {}).items()}
    rt = _text(values.get("record type")).lower()
    cols = [c.lower() for c in sheet["columns"]]
    if "image" in rt or "image file" in cols:
        kind = "image"
    elif rt.startswith("test") or any(c[:2] == "t:" for c in cols):
        kind = "test"
    else:
        kind = "item"
    return kind, _text(values.get("test name"))


def records(sheet: dict, mapping: dict, merge: bool = True) -> list[dict]:
    """The sheet's rows as records: the mapped cells of each row, with the
    key/value block as per-sheet defaults (the utility's precedence: a cell
    beats the block). With ``merge`` (an Item sheet) rows naming the same
    item (by External ID, else by serial) become one record (later
    non-blank cells win); a Test sheet keeps one record per row. ``specs`` /
    ``positions`` / ``tests`` hold the ``spec:`` / ``pos:`` / ``test:``
    assignments; the standard fields sit at the top."""
    defaults = {}
    for k, v in (sheet.get("values") or {}).items():
        a = mapping.get(k) or auto_map([k], {}, {}).get(k) or ""
        if a and v is not None:
            defaults[a] = v
    cols = [(i, mapping.get(c) or "") for i, c in enumerate(sheet["columns"])]
    merged: dict[tuple, dict] = {}
    for n, cells in sheet["rows"]:
        vals = dict(defaults)
        for i, a in cols:
            if a and i < len(cells) and cells[i] is not None:
                vals[a] = cells[i]
        rec = {"n": n, "rows": [n], "specs": {}, "positions": {}, "tests": {}}
        for a, v in vals.items():
            if a.startswith("spec:"):
                rec["specs"][a[5:]] = v
            elif a.startswith("pos:"):
                rec["positions"][a[4:]] = v
            elif a.startswith("test:"):
                rec["tests"][a[5:]] = v
            else:
                rec[a] = v
        pid = _text(rec.get("part_id")).upper()
        if pid in ("", "<UNASSIGNED>"):
            pid = ""
        rec["part_id"] = pid
        rec["serial_number"] = _text(rec.get("serial_number"))
        key = ((pid, "") if pid else ("", rec["serial_number"]) if rec["serial_number"] else (None, n)) if merge else (None, n)
        if key in merged:
            m = merged[key]
            m["rows"].append(n)
            m["specs"].update(rec["specs"])
            m["positions"].update(rec["positions"])
            m["tests"].update(rec["tests"])
            m.update({k: v for k, v in rec.items() if k not in ("n", "rows", "specs", "positions", "tests")})
        else:
            merged[key] = rec
    return list(merged.values())


# ---- planning ---------------------------------------------------------------

def _ref(value, options: list[dict]) -> dict | None:
    """``(id) Name``, an id or a name → the option ``{id, name, …}``; None when
    nothing matches."""
    if value is None:
        return None
    s = _text(value)
    m = _REF.match(s)
    if m:
        s = m.group(1)
    if isinstance(value, int) or s.isdigit():
        i = int(s)
        return next((o for o in options if o.get("id") == i), None)
    return next((o for o in options if (o.get("name") or "").lower() == s.lower()), None)


def _status(value) -> int | None:
    if value is None:
        return None
    s = _text(value)
    for o in STATUS_OPTIONS:
        if s == str(o["value"]) or s.lower() == o["label"].lower():
            return o["value"]
    return None


def _set_path(d: dict, path: str, value) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[keys[-1]] = value


def _get_path(d, path: str):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return _MISSING
        d = d[k]
    return d


_MISSING = object()


def _spec_value(v):
    return None if v == NULL else v


def check_specs(specs: dict, template: dict) -> str | None:
    """Every spec key must be one the type's datasheet defines (HWDB
    validates against the template); a dotted key may reach into a nested
    object such as DATA. The first offending key, or None."""
    for k in specs:
        top = k.split(".")[0]
        if top not in template:
            return f"“{k}” is not a key of the type’s Item Specs"
        if "." in k and not isinstance(template.get(top), dict):
            return f"“{k}”: “{top}” is not a nested object in the type’s Item Specs"
    return None


def plan(records_: list[dict], ptid: str, live: dict, makers: dict, template: dict,
         connectors: dict, institutions: list[dict], manufacturers: list[dict]) -> list[dict]:
    """The dry run: each record against the type's live listing (pid → row)
    and the mirror's manufacturer names (pid → name) → a plan row ``{n, rows,
    key, pid, action, changes, error, state, rec}``. ``action`` = create
    (serial unknown to the type), patch (something differs), skip (nothing
    to do) or error (the row cannot be applied as it stands); ``state`` =
    pending for create / patch, done for skip, error. Positions and the
    location are compared at apply time (the listing lacks them), so they
    always count as a change here."""
    by_serial: dict[str, list[str]] = {}
    for pid, r in live.items():
        sn = _text(r.get("serial_number"))
        if sn:
            by_serial.setdefault(sn.lower(), []).append(pid)
    out = []
    for rec in records_:
        row = {"n": rec["n"], "rows": rec["rows"], "key": rec["part_id"] or rec["serial_number"],
               "pid": rec["part_id"], "action": "patch", "changes": [], "error": "",
               "state": "pending", "rec": {}}
        out.append(row)
        try:
            if rec.get("problem"):
                raise SheetError(_text(rec["problem"]))
            row["rec"] = _resolve(rec, ptid, template, connectors, institutions, manufacturers)
            cur = None
            if rec["part_id"]:
                if not rec["part_id"].startswith(ptid + "-"):
                    raise SheetError(f"{rec['part_id']} is not a {ptid} item")
                cur = live.get(rec["part_id"])
                if cur is None:
                    raise SheetError(f"{rec['part_id']} is not in HWDB")
            elif rec["serial_number"]:
                hits = by_serial.get(rec["serial_number"].lower()) or []
                if len(hits) > 1:
                    raise SheetError(f"serial number {rec['serial_number']} is on {len(hits)} items: "
                                     f"{', '.join(hits)} — give the PID")
                if hits:
                    row["pid"] = hits[0]
                    cur = live[hits[0]]
                else:
                    row["action"] = "create"
            else:
                raise SheetError("no External ID and no serial number")
            r = row["rec"]
            if row["action"] == "create":
                if not r.get("institution"):
                    raise SheetError("a new item needs an institution")
                row["changes"] = ["new item"] + _extra_changes(r)
                continue
            row["changes"] = _diff(r, cur, makers.get(row["pid"]) or "") + _extra_changes(r)
            if not row["changes"]:
                row["action"], row["state"] = "skip", "done"
        except SheetError as e:
            row.update(action="error", state="error", error=str(e))
    return out


def _extra_changes(r: dict) -> list[str]:
    ch = []
    if r.get("location"):
        ch.append(f"location → {r['location']['name']}")
    for pos, v in r.get("positions", {}).items():
        ch.append(f"{pos} → {'empty' if v == NULL else v}")
    return ch


def _resolve(rec: dict, ptid: str, template: dict, connectors: dict,
             institutions: list[dict], manufacturers: list[dict]) -> dict:
    """The record's cells as HWDB values: status id, manufacturer / institution /
    location options, checked spec keys and positions. ``SheetError`` names
    the first cell that cannot be used."""
    r: dict = {"serial_number": rec["serial_number"], "specs": {}, "positions": {}}
    if rec.get("part_type_id") is not None and _text(rec["part_type_id"]).upper() != ptid:
        raise SheetError(f"Part Type ID {_text(rec['part_type_id'])} is not {ptid}")
    if rec.get("status") is not None:
        r["status_id"] = _status(rec["status"])
        if r["status_id"] is None:
            raise SheetError(f"unknown status “{_text(rec['status'])}”")
    if rec.get("manufacturer") is not None:
        m = _ref(rec["manufacturer"], manufacturers)
        if m is None:
            raise SheetError(f"“{_text(rec['manufacturer'])}” is not a manufacturer of this type")
        r["manufacturer"] = {"id": m["id"], "name": m.get("name") or ""}
    for f in ("institution", "location"):
        if rec.get(f) is not None:
            o = _ref(rec[f], institutions)
            if o is None:
                raise SheetError(f"unknown {f} “{_text(rec[f])}”")
            r[f] = {"id": o["id"], "name": o.get("name") or "", "country_code": o.get("country_code") or ""}
    if rec.get("comments") is not None:
        r["comments"] = _text(rec["comments"])
    for f in ("location_comments", "arrived"):
        if rec.get(f) is not None:
            r[f] = _text(rec[f])
    err = check_specs(rec["specs"], template)
    if err:
        raise SheetError(err)
    r["specs"] = {k: _spec_value(v) for k, v in rec["specs"].items()}
    for pos, v in rec["positions"].items():
        if pos not in connectors:
            raise SheetError(f"this type has no “{pos}” position")
        r["positions"][pos] = _text(v)
    return r


def _diff(r: dict, cur: dict, maker: str) -> list[str]:
    ch = []
    if r["serial_number"] and r["serial_number"].lower() != _text(cur.get("serial_number")).lower():
        ch.append(f"serial → {r['serial_number']}")
    if "status_id" in r:
        st = cur.get("status") or {}
        if r["status_id"] != (st.get("id") if isinstance(st, dict) else st):
            ch.append("status → " + next(o["label"] for o in STATUS_OPTIONS if o["value"] == r["status_id"]))
    if "comments" in r and r["comments"] != _text(cur.get("comments")):
        ch.append(f"comments → “{r['comments']}”")
    if "manufacturer" in r and r["manufacturer"]["name"].lower() != (maker or "").lower():
        ch.append(f"manufacturer → {r['manufacturer']['name']}")
    specs = cur.get("specifications") or [{}]
    latest = specs[-1] if isinstance(specs[-1], dict) else {}
    for k, v in r["specs"].items():
        if _get_path(latest, k) is _MISSING or _get_path(latest, k) != v:
            ch.append(f"{k} → {_show(v)}")
    return ch


def _segs(key: str) -> list[tuple[str, bool]]:
    """``a.b[].c`` → [(a, False), (b, True), (c, False)]: a ``[]`` segment is a list."""
    return [(seg[:-2], True) if seg.endswith("[]") else (seg, False) for seg in key.split(".")]


def _row_scalars(tests: dict) -> dict[tuple, dict]:
    """The row's plain values grouped by the list path they sit under —
    what identifies a list element (the utility's group keys: an element's
    scalar members)."""
    out: dict[tuple, dict] = {}
    for k, v in tests.items():
        segs = _segs(k)
        if segs[-1][1]:
            continue                       # a trailing [] appends a value, it names nothing
        lists = tuple(n for n, is_list in segs if is_list)
        last = max((i for i, (_, is_list) in enumerate(segs) if is_list), default=-1)
        out.setdefault(lists, {})[".".join(n for n, _ in segs[last + 1:])] = _spec_value(v)
    return out


def _insert(data: dict, key: str, value, scalars: dict[tuple, dict]) -> None:
    """Set ``key`` in ``data``, walking ``[]`` segments into lists: the
    element for this row is the one whose scalar members equal the row's
    (``scalars``), else a new one seeded with them; a trailing ``[]``
    appends the value."""
    node, prefix = data, ()
    segs = _segs(key)
    for name, is_list in segs[:-1]:
        if is_list:
            lst = node.setdefault(name, [])
            if not isinstance(lst, list):
                lst = node[name] = []
            prefix += (name,)
            ident = scalars.get(prefix, {})
            elem = next((e for e in lst if isinstance(e, dict) and all(_get_path(e, k) == v for k, v in ident.items())), None)
            if elem is None:
                elem = {}
                for k, v in ident.items():
                    _set_path(elem, k, v)
                lst.append(elem)
            node = elem
        else:
            if not isinstance(node.get(name), dict):
                node[name] = {}
            node = node[name]
    name, is_list = segs[-1]
    if is_list:
        node.setdefault(name, []).append(_spec_value(value))
    else:
        node[name] = _spec_value(value)


def group_tests(records_: list[dict]) -> list[dict]:
    """#179: rows whose test keys use ``[]`` (``Subtests[].Name``,
    ``Subtests[].Trials[].Value``) build lists: rows naming the same item
    with the same plain (non-list) values are one test record, and inside
    it each ``[]`` level holds one element per distinct set of scalar
    members — the utility's nested encoder groups, spelled in the header.
    Without any ``[]`` key every row is its own record (as #178)."""
    if not any("[]" in k for r in records_ for k in r["tests"]):
        for r in records_:
            r["data"] = {}
            for k, v in r["tests"].items():
                _set_path(r["data"], k, _spec_value(v))
        return records_
    out: list[dict] = []
    index: dict[tuple, dict] = {}
    for r in records_:
        scalars = _row_scalars(r["tests"])
        ident = (r["part_id"], r["serial_number"].lower(), _text(r.get("test_name")),
                 json.dumps(scalars.get((), {}), sort_keys=True, default=str))
        rec = index.get(ident)
        if rec is None:
            rec = index[ident] = {**r, "rows": list(r["rows"]), "tests": dict(r["tests"]), "data": {}}
            out.append(rec)
        else:
            rec["rows"] += r["rows"]
            rec["tests"].update(r["tests"])
            if r.get("comments") is not None:
                rec["comments"] = r["comments"]
        for k, v in r["tests"].items():
            _insert(rec["data"], k, v, scalars)
    return out


def plan_tests(records_: list[dict], ptid: str, live: dict, test_name: str) -> list[dict]:
    """#178: the dry run of a Test sheet — each row names an existing item
    (by External ID, else by serial) and carries ``T:`` values; the plan
    row's ``rec`` = ``{test_name, comments, data}`` with dotted keys nested
    and ``[]`` keys grouped into lists (``group_tests``). Whether the item
    already holds a test with the same data is checked at apply time (the
    listing has no tests)."""
    by_serial: dict[str, list[str]] = {}
    for pid, r in live.items():
        sn = _text(r.get("serial_number"))
        if sn:
            by_serial.setdefault(sn.lower(), []).append(pid)
    out = []
    for rec in group_tests(records_):
        name = test_name or _text(rec.get("test_name"))   # the page's name wins; the sheet's only fills a blank
        row = {"n": rec["n"], "rows": rec["rows"], "key": rec["part_id"] or rec["serial_number"],
               "pid": rec["part_id"], "action": "test", "changes": [], "error": "", "state": "pending",
               "rec": {"test_name": name, "comments": _text(rec.get("comments")), "data": {}}}
        out.append(row)
        try:
            if rec.get("problem"):
                raise SheetError(_text(rec["problem"]))
            if rec.get("part_type_id") is not None and _text(rec["part_type_id"]).upper() != ptid:
                raise SheetError(f"Part Type ID {_text(rec['part_type_id'])} is not {ptid}")
            if not name:
                raise SheetError("no test name")
            if rec["part_id"]:
                if not rec["part_id"].startswith(ptid + "-"):
                    raise SheetError(f"{rec['part_id']} is not a {ptid} item")
                if rec["part_id"] not in live:
                    raise SheetError(f"{rec['part_id']} is not in HWDB")
            elif rec["serial_number"]:
                hits = by_serial.get(rec["serial_number"].lower()) or []
                if len(hits) > 1:
                    raise SheetError(f"serial number {rec['serial_number']} is on {len(hits)} items: "
                                     f"{', '.join(hits)} — give the PID")
                if not hits:
                    raise SheetError(f"no {ptid} item has serial number {rec['serial_number']}")
                row["pid"] = hits[0]
            else:
                raise SheetError("no External ID and no serial number")
            whole = rec.get("test_data")
            if whole is not None and not isinstance(whole, dict):
                raise SheetError("the test data cell is not a JSON object")
            if not rec["tests"] and not whole:
                raise SheetError("no test values (T: columns or test data) in this row")
            row["rec"]["data"] = {**(whole or {}), **rec["data"]}
            row["changes"] = [f"{name}: " + (_show(row["rec"]["data"]) if whole or any("[]" in k for k in rec["tests"]) else
                                             ", ".join(f"{k} = {_show(v)}" for k, v in rec["tests"].items()))]
        except SheetError as e:
            row.update(action="error", state="error", error=str(e))
    return out


def plan_images(records_: list[dict], ptid: str, live: dict, test_name: str) -> list[dict]:
    """#179: the dry run of an Image sheet — each row names an existing
    item and a file (``Image File``; ``Save As`` renames it in HWDB); with
    a test name the file goes onto that test's record (``History Order``
    0 = the latest). The files themselves are picked in the browser at
    upload time and matched by name; nothing is stored here."""
    by_serial: dict[str, list[str]] = {}
    for pid, r in live.items():
        sn = _text(r.get("serial_number"))
        if sn:
            by_serial.setdefault(sn.lower(), []).append(pid)
    out = []
    for rec in records_:
        name = _text(rec.get("test_name")) or test_name
        file = _text(rec.get("image_file")).replace("\\", "/").rsplit("/", 1)[-1]
        row = {"n": rec["n"], "rows": rec["rows"], "key": rec["part_id"] or rec["serial_number"],
               "pid": rec["part_id"], "action": "image", "changes": [], "error": "", "state": "pending",
               "rec": {"file": file, "save_as": _text(rec.get("save_as")) or file, "comments": _text(rec.get("comments")),
                       "test_name": name, "hist_order": 0}}
        out.append(row)
        try:
            if rec.get("problem"):
                raise SheetError(_text(rec["problem"]))
            if rec.get("part_type_id") is not None and _text(rec["part_type_id"]).upper() != ptid:
                raise SheetError(f"Part Type ID {_text(rec['part_type_id'])} is not {ptid}")
            if rec["part_id"]:
                if not rec["part_id"].startswith(ptid + "-"):
                    raise SheetError(f"{rec['part_id']} is not a {ptid} item")
                if rec["part_id"] not in live:
                    raise SheetError(f"{rec['part_id']} is not in HWDB")
            elif rec["serial_number"]:
                hits = by_serial.get(rec["serial_number"].lower()) or []
                if len(hits) > 1:
                    raise SheetError(f"serial number {rec['serial_number']} is on {len(hits)} items: "
                                     f"{', '.join(hits)} — give the PID")
                if not hits:
                    raise SheetError(f"no {ptid} item has serial number {rec['serial_number']}")
                row["pid"] = hits[0]
            else:
                raise SheetError("no External ID and no serial number")
            if not file:
                raise SheetError("no image file")
            if rec.get("hist_order") is not None:
                try:
                    row["rec"]["hist_order"] = max(0, int(rec["hist_order"]))
                except (TypeError, ValueError):
                    raise SheetError(f"history order “{_text(rec['hist_order'])}” is not a number")
            row["changes"] = [f"{file}" + (f" as {row['rec']['save_as']}" if row["rec"]["save_as"] != file else "")
                              + (f" → test “{name}”" + (f" #{row['rec']['hist_order']}" if row["rec"]["hist_order"] else "")
                                 if name else " → item")]
        except SheetError as e:
            row.update(action="error", state="error", error=str(e))
    return out


# ---- applying ---------------------------------------------------------------

def merged_specs(base: dict, specs: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in specs.items():
        _set_path(out, k, v)
    return out


def apply_row(api, ptid: str, row: dict, template: dict, connectors: dict,
              manufacturers: list[dict], serial_lookup, arrived_default: str) -> tuple[str, list[str]]:
    """Write one plan row to HWDB: a create (after a live serial re-check —
    a chunk that timed out after its POST landed must not create twice),
    else a PATCH of the standard fields + specs when anything differs from
    the current record; then the location when it differs and the
    positions when they differ (one read + one PATCH). Returns (pid, what
    changed); ``SheetError`` when HWDB refuses; request errors propagate.
    ``serial_lookup(type_id, serial) -> [pids]`` resolves serials."""
    r, pid, done = row["rec"], row.get("pid") or "", []
    if row["action"] == "create":
        hits = serial_lookup(ptid, r["serial_number"])
        if len(hits) > 1:
            raise SheetError(f"serial number {r['serial_number']} is now on {len(hits)} items: {', '.join(hits)}")
        if hits:
            pid = hits[0]                          # created by an earlier attempt — patch it instead
        else:
            payload = {
                "component_type": {"part_type_id": ptid},
                "country_code": r["institution"]["country_code"],
                "institution": {"id": r["institution"]["id"]},
                "serial_number": r["serial_number"],
                "comments": r.get("comments") or "",
                "specifications": merged_specs(template, r["specs"]),
                "status": {"id": r.get("status_id", NEW_ITEM_STATUS)},
            }
            if "manufacturer" in r:
                payload["manufacturer"] = {"id": r["manufacturer"]["id"]}
            elif len(manufacturers) == 1 and manufacturers[0].get("id") is not None:
                payload["manufacturer"] = {"id": manufacturers[0]["id"]}
            body = api.create_component(ptid, payload)
            pid = body.get("part_id") if body.get("status") == "OK" else None
            if not pid:
                raise SheetError(str(body.get("data") or body))
            done.append("created")
    item = None
    if "created" not in done:
        item = api.get_component(pid).get("data") or {}
        specs = item.get("specifications") or [{}]
        latest = specs[-1] if isinstance(specs[-1], dict) else {}
        man = item.get("manufacturer") if isinstance(item.get("manufacturer"), dict) else None
        st = item.get("status") if isinstance(item.get("status"), dict) else {}
        same_serial = r["serial_number"].lower() == _text(item.get("serial_number")).lower()
        payload = {
            "part_id": pid,
            "serial_number": item.get("serial_number") if same_serial else r["serial_number"] or item.get("serial_number"),
            "manufacturer": {"id": r["manufacturer"]["id"]} if "manufacturer" in r
                            else ({"id": man["id"]} if man else None),
            "specifications": merged_specs(latest, r["specs"]),
            "status": {"id": r["status_id"] if "status_id" in r else st.get("id")},
            "comments": r["comments"] if "comments" in r else (item.get("comments") or ""),
        }
        current = {
            "part_id": pid, "serial_number": item.get("serial_number"),
            "manufacturer": {"id": man["id"]} if man else None, "specifications": latest,
            "status": {"id": st.get("id")}, "comments": item.get("comments") or "",
        }
        if payload != current:
            body = api.patch_component(pid, payload)
            if body.get("status") != "OK":
                raise SheetError(str(body.get("data") or body))
            done.append("updated")
    if r.get("location"):
        loc = item.get("location") if item else None
        cur_id = loc.get("id") if isinstance(loc, dict) else None
        if cur_id != r["location"]["id"]:
            body = api.post_location(pid, {
                "location": {"id": r["location"]["id"]},
                "arrived": r.get("arrived") or arrived_default,
                "comments": r.get("location_comments") or "Sheet upload via HWDB Explorer"})
            if body.get("status") != "OK":
                raise SheetError(f"location — {body.get('data') or body}")
            done.append("location")
    if r.get("positions"):
        occupants = {(m.get("functional_position") or ""): m.get("part_id")
                     for m in (api.get_subcomponents(pid).get("data") or []) if isinstance(m, dict)}
        current = {pos: occupants.get(pos) for pos in connectors}
        wanted = dict(current)
        for pos, v in r["positions"].items():
            if v in ("", NULL):
                wanted[pos] = None
            elif _PID.match(v):
                wanted[pos] = v.upper()
            else:
                hits = serial_lookup(connectors[pos], v)
                if len(hits) != 1:
                    raise SheetError(f"{pos}: serial number {v} matches {len(hits)} {connectors[pos]} items")
                wanted[pos] = hits[0]
        if wanted != current:
            body = api.patch_subcomponents(pid, {"component": {"part_id": pid}, "subcomponents": wanted})
            if body.get("status") != "OK":
                raise SheetError(f"positions — {body.get('data') or body}")
            done.append("positions")
    return pid, done


def apply_test_row(api, ptid: str, row: dict, test_type_id) -> tuple[str, list[str]]:
    """#178: post the row's test record — unless the item already holds a
    record of that test type with the same DATA (HWDB never dedups; a chunk
    that timed out after its POST landed must not post twice, and re-running
    a sheet is harmless). ``test_type_id(name) -> id`` resolves (and
    creates) the test type. Returns (pid, what happened)."""
    r, pid = row["rec"], row["pid"]
    tid = test_type_id(r["test_name"])
    if tid is not None:
        for t in api.get_tests(pid, test_type_id=tid, history=True).get("data") or []:
            if isinstance(t, dict) and (t.get("test_data") or {}).get("DATA") == r["data"]:
                return pid, ["already recorded"]
    body = api.post_test(pid, {"comments": r["comments"], "test_type": r["test_name"],
                               "test_data": {"DATA": r["data"]}})
    if body.get("status") != "OK":
        raise SheetError(str(body.get("data") or body))
    return pid, ["test posted"]


def apply_image_row(api, row: dict, fileobj, content_type: str, test_type_id) -> tuple[str, list[str]]:
    """#179: attach the picked file to the row's item, or to one of its
    test records (``test_name`` + ``hist_order``, 0 = latest), unless an
    attachment of that name is already there. Returns (pid, what happened)."""
    r, pid = row["rec"], row["pid"]
    name = r["save_as"] or r["file"]
    comments = r["comments"] or "Sheet upload via HWDB Explorer"
    if r["test_name"]:
        tid = test_type_id(r["test_name"])
        if tid is None:
            raise SheetError(f"this type has no “{r['test_name']}” test type")
        tests = [t for t in (api.get_tests(pid, test_type_id=tid, history=True).get("data") or []) if isinstance(t, dict)]
        if r["hist_order"] >= len(tests):
            raise SheetError(f"{pid} has {len(tests)} “{r['test_name']}” record{'s' if len(tests) != 1 else ''}, "
                             f"no #{r['hist_order']}")
        try:
            have = {i.get("image_name") for i in (api.get_test_images(pid, tid).get("data") or []) if isinstance(i, dict)}
        except Exception:
            have = set()
        if name in have:
            return pid, ["already attached"]
        body = api.post_test_image(tests[r["hist_order"]].get("id"), fileobj, name, comments, content_type)
    else:
        have = {i.get("image_name") for i in (api.get_images(pid).get("data") or []) if isinstance(i, dict)}
        if name in have:
            return pid, ["already attached"]
        body = api.post_component_image(pid, fileobj, name, comments, content_type)
    if body.get("status", "OK") != "OK":
        raise SheetError(str(body.get("data") or body))
    return pid, ["attached"]
