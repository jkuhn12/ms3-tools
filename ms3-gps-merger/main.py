#!/usr/bin/env python3
"""
ms3-gps-merger
Merge MegaSquirt MSL datalogs with Track Addict GPS CSV exports.
Uses only the Python standard library. Python 3.10+.

Example:
    uv run main.py \
        --msl /path/to/onboard_log.msl \
        --gps /path/to/trackaddict.csv \
        -o merged_session.csv \
        --offset 0.0
"""
import argparse
import bisect
import csv
import re
import sys
from datetime import datetime, timedelta, timezone

# Timezone abbreviations we might see in TunerStudio capture headers
TZ_MAP = {
    "EST": timedelta(hours=-5),
    "EDT": timedelta(hours=-4),
    "CST": timedelta(hours=-6),
    "CDT": timedelta(hours=-5),
    "MST": timedelta(hours=-7),
    "MDT": timedelta(hours=-6),
    "PST": timedelta(hours=-8),
    "PDT": timedelta(hours=-7),
    "UTC": timedelta(hours=0),
    "GMT": timedelta(hours=0),
}


def parse_msl_header(f):
    """Read first two lines and return (format_line, capture_dt_utc or None)."""
    fmt = f.readline().strip()
    capture_line = f.readline().strip()
    dt = None
    m = re.search(r"Capture Date:\s+([^,]+)", capture_line)
    if m:
        dt = parse_capture_date(m.group(1).strip())
    return fmt, dt


def parse_capture_date(s):
    """
    Parse strings like 'Sun May 10 19:32:56 EDT 2026'.
    Returns timezone-aware datetime in UTC, or naive datetime if TZ unknown.
    """
    # Pattern: Day Mon DD HH:MM:SS TZ YYYY
    m = re.match(
        r"(\w{3}\s+\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+([A-Z]{2,4})\s+(\d{4})",
        s,
    )
    if not m:
        # Try without timezone
        m2 = re.match(
            r"(\w{3}\s+\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\d{4})", s
        )
        if m2:
            return datetime.strptime(
                m2.group(1) + " " + m2.group(2), "%a %b %d %H:%M:%S %Y"
            )
        return None

    dt_str, tz_name, year = m.group(1), m.group(2), m.group(3)
    dt = datetime.strptime(f"{dt_str} {year}", "%a %b %d %H:%M:%S %Y")
    offset = TZ_MAP.get(tz_name)
    if offset is not None:
        dt = dt.replace(tzinfo=timezone(offset))
        return dt.astimezone(timezone.utc)
    return dt  # naive if unknown


def read_msl_data(f):
    """
    MSL format after headers:
      Line 3: tab-separated column names
      Line 4: tab-separated units
      Line 5+: tab-separated data
    Returns (headers, rows) where rows is a list of dicts.
    """
    header_line = f.readline()
    if not header_line:
        return [], []
    headers = header_line.strip().split("\t")
    # Unit line
    f.readline()
    reader = csv.DictReader(f, fieldnames=headers, delimiter="\t")
    rows = []
    for r in reader:
        # Skip completely empty rows
        if any(v is not None and v != "" for v in r.values()):
            rows.append(r)
    return headers, rows


def load_msl(path):
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
        fmt, capture_dt = parse_msl_header(f)
        headers, rows = read_msl_data(f)
    return fmt, capture_dt, headers, rows


def clean_msl_times(rows):
    """
    MSL files sometimes have an anomalous first row (e.g., Time=485 when
    subsequent rows start near 0). Detect and drop it.
    """
    if len(rows) < 3:
        return rows
    try:
        t0 = float(rows[0].get("Time", 0))
        t1 = float(rows[1].get("Time", 0))
    except (ValueError, TypeError):
        return rows

    if t0 > t1 + 10:
        print(
            f"[WARN] Dropping anomalous first MSL row (Time={t0:.3f} >> Time={t1:.3f})",
            file=sys.stderr,
        )
        return rows[1:]
    return rows


def read_gps(path):
    with open(path, "r", newline="") as f:
        lines = f.readlines()

    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("#"):
            continue
        if "UTC Time" in line:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Could not find GPS CSV header line (missing 'UTC Time')")

    headers = [h.strip('"').strip() for h in lines[header_idx].strip().split(",")]
    reader = csv.DictReader(lines[header_idx + 1 :], fieldnames=headers)
    rows = []
    for r in reader:
        if any(v not in (None, "") for v in r.values()):
            if (r.get("UTC Time") or "").strip():
                rows.append(r)
    return headers, rows


def prefix_dict(d, prefix):
    return {f"{prefix}{k}": v for k, v in d.items()}


def merge(msl_rows, msl_base_unix, gps_rows):
    # Build sorted MSL timeline
    msl_times = []
    for r in msl_rows:
        try:
            t = msl_base_unix + float(r["Time"])
        except (ValueError, KeyError):
            continue
        msl_times.append((t, r))

    if not msl_times:
        raise ValueError("No valid MSL timestamps")

    msl_times.sort(key=lambda x: x[0])
    msl_ts = [t for t, _ in msl_times]

    gps_rows_sorted = sorted(
        gps_rows, key=lambda g: float(g.get("UTC Time", 0))
    )

    merged = []
    for g in gps_rows_sorted:
        try:
            gps_t = float(g["UTC Time"])
        except (ValueError, KeyError):
            continue

        idx = bisect.bisect_left(msl_ts, gps_t)
        if idx == 0:
            nearest_idx = 0
        elif idx >= len(msl_ts):
            nearest_idx = len(msl_ts) - 1
        else:
            if abs(msl_ts[idx] - gps_t) <= abs(msl_ts[idx - 1] - gps_t):
                nearest_idx = idx
            else:
                nearest_idx = idx - 1

        ecu_r = msl_times[nearest_idx][1]
        row = {}
        row.update(prefix_dict(g, "gps_"))
        row.update(prefix_dict(ecu_r, "ecu_"))
        row["_utc_time"] = gps_t
        row["_time_delta_s"] = abs(msl_ts[nearest_idx] - gps_t)
        merged.append(row)

    return merged


def main():
    parser = argparse.ArgumentParser(
        description="Merge MS3 MSL log with Track Addict GPS CSV"
    )
    parser.add_argument("--msl", required=True, help="Path to .msl datalog")
    parser.add_argument("--gps", required=True, help="Path to Track Addict .csv")
    parser.add_argument("-o", "--output", required=True, help="Output merged CSV path")
    parser.add_argument(
        "--offset",
        type=float,
        default=0.0,
        help="Manual ECU time offset in seconds (positive = shift ECU forward)",
    )
    args = parser.parse_args()

    fmt, capture_dt, msl_headers, msl_rows = load_msl(args.msl)
    print(f"[INFO] MSL format: {fmt[:60]}...")
    print(f"[INFO] MSL capture: {capture_dt}")

    msl_rows = clean_msl_times(msl_rows)
    print(f"[INFO] MSL rows: {len(msl_rows)}")

    gps_headers, gps_rows = read_gps(args.gps)
    print(f"[INFO] GPS rows: {len(gps_rows)}")

    if capture_dt is None:
        print(
            "[WARN] No capture date in MSL; assuming start-of-epoch. Use --offset to fix.",
            file=sys.stderr,
        )
        msl_base_unix = 0.0
    else:
        msl_base_unix = capture_dt.timestamp()

    msl_base_unix += args.offset

    merged = merge(msl_rows, msl_base_unix, gps_rows)
    print(f"[INFO] Merged rows: {len(merged)}")

    if not merged:
        print("[ERROR] Nothing to write.", file=sys.stderr)
        sys.exit(1)

    fieldnames = list(merged[0].keys())
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged)

    print(f"[INFO] Wrote {args.output}")


if __name__ == "__main__":
    main()
