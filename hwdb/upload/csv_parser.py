"""Parse Karla's LArASIC RTS analysis CSV files.

Lifted from ``.idea/ref/karla/submit_larasic_test.py`` (Karla Zucker, DUNE CE
group). Only the parsing pieces — no Django, no HWDB. The output is a dict
of structured values that ``build_datasheet_detailed`` consumes.

Expected filename pattern:
    XXX_XXXXX_YYYYMMDDHHMMSS_TrayNN_SKTN_{RT|LN}.csv

Expected CSV layout:
    metadata rows (key,value) — UTC_Time, RTS_timestamp, tester, testsite, env,
    RTS_Property_ID, Tray_ID, FE_in_Tray, DAT_SN, FE_in_Socket, …
    blank or header row, then
    Test_01_Power_Consumption,200mV_sedcBufOFF_seBuffOFF,vdda_P=N,vddo_P=N,vddp_P=N,
      CH0=(ped=N;rms=N;posAmp=N;negAmp=N), …, CH15=…

We only consume the metadata block and the target test row matching
``Test_01_Power_Consumption`` / ``200mV_sedcBufOFF_seBuffOFF``. Channels beyond
that one row are ignored, matching Karla's tool.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Optional

TARGET_TEST_ITEM = "Test_01_Power_Consumption"
TARGET_CONFIG = "200mV_sedcBufOFF_seBuffOFF"

_SN_RE = re.compile(r"(\d{3})_(\d{5})")
_FILENAME_TS_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})$")
_KV_RE = re.compile(r"\s*([A-Za-z0-9_]+)\s*=\s*([-+]?\d+(?:\.\d+)?)\s*$")
_CH_RE = re.compile(
    r"\s*CH(\d+)=\("
    r"ped=([-+]?\d+(?:\.\d+)?);"
    r"rms=([-+]?\d+(?:\.\d+)?);"
    r"posAmp=([-+]?\d+(?:\.\d+)?);"
    r"negAmp=([-+]?\d+(?:\.\d+)?)"
    r"\)\s*$"
)


def extract_serial(csv_path: Path) -> str:
    """``002_00797_….csv`` → ``002-00797`` (HWDB format)."""
    m = _SN_RE.search(csv_path.name)
    if not m:
        raise ValueError(f"no serial in filename: {csv_path.name}")
    return f"{m.group(1)}-{m.group(2)}"


def parse_filename(csv_path: Path) -> dict:
    """Returns ``{serial, timestamp, tray, socket, env}`` from filename tokens.

    ``env`` is ``"RT"``, ``"LN"``, or ``None``.
    """
    parts = csv_path.stem.split("_")
    out = {
        "serial": extract_serial(csv_path),
        "timestamp": parts[2] if len(parts) >= 3 else "",
        "tray": None,
        "socket": None,
        "env": None,
    }
    for tok in parts[3:]:
        u = tok.upper()
        if tok.lower().startswith("tray"):
            out["tray"] = tok
        elif u.startswith("SKT"):
            out["socket"] = tok
        elif u in {"RT", "LN"}:
            out["env"] = u
    return out


def _read_rows(csv_path: Path) -> list[list[str]]:
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def _extract_metadata(rows: list[list[str]]) -> dict[str, str]:
    """Metadata is every key/value row before the first ``Test_*`` row."""
    meta: dict[str, str] = {}
    for row in rows:
        if not row:
            continue
        key = row[0].strip()
        if key.startswith("Test_"):
            break
        if len(row) >= 2:
            meta[key] = row[1].strip()
    return meta


def _find_target_row(rows: list[list[str]]) -> list[str]:
    for row in rows:
        if len(row) >= 2 and row[0].strip() == TARGET_TEST_ITEM and row[1].strip() == TARGET_CONFIG:
            return row
    raise ValueError(f"no row matching {TARGET_TEST_ITEM!r}/{TARGET_CONFIG!r}")


def _parse_power(row: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for field in row[2:]:
        m = _KV_RE.match(field)
        if m:
            k, v = m.group(1), float(m.group(2))
            if k in {"vdda_P", "vddo_P", "vddp_P"}:
                out[k] = v
    missing = [k for k in ("vdda_P", "vddo_P", "vddp_P") if k not in out]
    if missing:
        raise ValueError(f"missing power fields: {missing}")
    return out


def _parse_channels(row: list[str]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for field in row[2:]:
        m = _CH_RE.match(field)
        if not m:
            continue
        ch = int(m.group(1))
        ped = float(m.group(2))
        rms = float(m.group(3))
        pos = float(m.group(4))
        neg = float(m.group(5))
        out[ch] = {
            "ped": ped,
            "rms": rms,
            "posAmp": pos,
            "negAmp": neg,
            "pulse_amplitude": pos - ped,
        }
    missing = [ch for ch in range(16) if ch not in out]
    if missing:
        raise ValueError(f"missing channels: {missing}")
    return out


def _split_utc(utc: str) -> tuple[str, str]:
    """``MM_DD_YYYY_HH_MM_SS`` → ``(YYYY/MM/DD, HH:MM:SS)``."""
    parts = utc.split("_")
    if len(parts) != 6:
        raise ValueError(f"bad UTC_Time: {utc}")
    mo, d, y, h, mi, s = parts
    return f"{y}/{mo}/{d}", f"{h}:{mi}:{s}"


def _yyyymmddhhmmss_to_date_time(ts: str) -> tuple[str, str]:
    """``YYYYMMDDHHMMSS`` → ``(YYYY/MM/DD, HH:MM:SS)``."""
    m = _FILENAME_TS_RE.fullmatch(ts or "")
    if not m:
        raise ValueError(f"bad timestamp: {ts}")
    y, mo, d, h, mi, s = m.groups()
    return f"{y}/{mo}/{d}", f"{h}:{mi}:{s}"


def parse_csv(csv_path: Path) -> dict:
    """Return everything ``build_datasheet_detailed`` needs from a CSV.

    Raises ``ValueError`` if the CSV doesn't match the expected layout.
    """
    rows = _read_rows(csv_path)
    metadata = _extract_metadata(rows)
    target = _find_target_row(rows)
    power = _parse_power(target)
    channels = _parse_channels(target)

    fn = parse_filename(csv_path)
    serial = fn["serial"]

    utc = metadata.get("UTC_Time", "").strip()
    if utc:
        test_date, test_time = _split_utc(utc)
    else:
        ts = metadata.get("RTS_timestamp", "").strip() or fn["timestamp"]
        test_date, test_time = _yyyymmddhhmmss_to_date_time(ts)

    env = (metadata.get("env") or fn["env"] or "").strip().upper()
    if env in {"RT", "ROOMT", "WARM"}:
        env = "RT"
    elif env in {"LN", "COLD", "LIQUID_NITROGEN"}:
        env = "LN"

    return {
        "csv_path": csv_path,
        "serial_hwdb": serial,
        "env": env,
        "test_date": test_date,
        "test_time": test_time,
        "test_location": (metadata.get("testsite", "") or "").strip() or "N/A",
        "operator_name": (metadata.get("tester", "") or "").strip() or "N/A",
        "rts_id": (metadata.get("RTS_Property_ID", "") or "").strip() or "N/A",
        "tray_id": (metadata.get("Tray_ID", "") or "").strip() or "N/A",
        "fe_in_tray": (metadata.get("FE_in_Tray", "") or "").strip()
        or fn["tray"]
        or "N/A",
        "dat_sn": (metadata.get("DAT_SN", "") or "").strip() or "N/A",
        "socket": (metadata.get("FE_in_Socket", "") or "").strip()
        or fn["socket"]
        or "N/A",
        "power": power,
        "channels": channels,
    }
