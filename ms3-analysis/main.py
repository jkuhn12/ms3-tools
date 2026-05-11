#!/usr/bin/env python3
"""Analyze MS3 TunerStudio datalog (.msl) for tuning insights.

Usage:
    python3 analyze_log.py /path/to/datalog.msl
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ColumnMap:
    """Maps human-readable channel names to datalog column names."""

    time: str | None = None
    rpm: str | None = None
    tps: str | None = None
    mat: str | None = None
    clt: str | None = None
    advance: str | None = None
    knock: str | None = None
    afr: str | None = None
    afrtgt: str | None = None
    ego: str | None = None
    pw: str | None = None
    map_: str | None = None


@dataclass(slots=True)
class SegmentResult:
    duration: float = 0.0
    rpm_start: float = 0.0
    rpm_end: float = 0.0
    avg_rpm: float = 0.0
    adv_min: float | None = None
    adv_max: float | None = None
    adv_avg: float | None = None
    knock_max: float | None = None
    knock_avg: float | None = None
    knock_events: int = 0
    mat_min: float | None = None
    mat_max: float | None = None
    mat_avg: float | None = None
    afr_min: float | None = None
    afr_max: float | None = None
    afr_avg: float | None = None
    afr_error_avg: float | None = None
    afr_error_max: float | None = None


def find_column(candidates: list[str], headers: list[str]) -> str | None:
    """Find the first matching column name (case-insensitive)."""
    headers_lower = {h.lower(): h for h in headers}
    for c in candidates:
        if c.lower() in headers_lower:
            return headers_lower[c.lower()]
    return None


def build_column_map(headers: list[str]) -> ColumnMap:
    """Auto-detect datalog columns from header row."""
    return ColumnMap(
        time=find_column(["Time", "secl", "seconds", "sec", "ms"], headers),
        rpm=find_column(["rpm", "RPM"], headers),
        tps=find_column(["tps", "TPS", "throttle"], headers),
        mat=find_column(["mat", "MAT", "iat", "IAT"], headers),
        clt=find_column(["clt", "CLT", "coolant"], headers),
        advance=find_column(
            ["advance", "spark", "timing", "SPK: Spark Advance"], headers
        ),
        knock=find_column(
            [
                "knkRetard",
                "knockRetard",
                "knk_retard",
                "knock retard",
                "SPK: Knock retard",
            ],
            headers,
        ),
        afr=find_column(
            ["afr1", "AFR1", "afr", "AFR", "afr1_old"], headers
        ),
        afrtgt=find_column(
            ["afrtgt1", "afrtarget", "afr_tgt", "afrTarget", "EgoV 1 Target"], headers
        ),
        ego=find_column(
            [
                "egoCorrection1",
                "egoCorrection",
                "ego_cor",
                "egoCorr",
                "EGO cor1",
            ],
            headers,
        ),
        pw=find_column(["pulseWidth1", "pw1", "pulse_width1", "pw_1", "PW"], headers),
        map_=find_column(["map", "MAP", "map_kpa"], headers),
    )


def parse_msl(filepath: Path) -> tuple[list[str], list[list[str]]]:
    """Parse a TunerStudio .msl file, skipping header metadata."""
    rows: list[list[str]] = []
    headers: list[str] = []

    with filepath.open("r", newline="", encoding="utf-8", errors="ignore") as f:
        # Detect delimiter: TunerStudio .msl files are tab-delimited by default
        sample = ""
        for _ in range(20):
            try:
                sample += next(f)
            except StopIteration:
                break
        f.seek(0)

        delimiter = "\t"
        if "\t" not in sample:
            try:
                dialect = csv.Sniffer().sniff(sample)
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = ","

        # Heuristic: find the CSV header row
        reader = csv.reader(f, delimiter=delimiter)
        for row in reader:
            if not row:
                continue
            first = row[0].strip().lower()
            if first in ("time", "secl", "seconds", "sec", "ms"):
                headers = [h.strip() for h in row]
                break

        if not headers:
            # Fallback: try to infer from first substantial row
            f.seek(0)
            reader = csv.reader(f, delimiter=delimiter)
            for row in reader:
                if row and len(row) > 5:
                    headers = [h.strip() for h in row]
                    break

        for row in reader:
            if not row or len(row) != len(headers):
                continue
            # Skip firmware signature lines
            if any(
                "firmware" in str(c).lower() or "signature" in str(c).lower()
                for c in row[:2]
            ):
                continue
            try:
                float(row[0])
            except ValueError:
                continue
            rows.append(row)

    return headers, rows


def to_floats(
    rows: list[list[str]], headers: list[str], col_name: str | None
) -> list[float]:
    """Extract a column as floats."""
    if col_name is None or col_name not in headers:
        return []
    idx = headers.index(col_name)
    vals: list[float] = []
    for r in rows:
        try:
            vals.append(float(r[idx]))
        except (ValueError, IndexError):
            vals.append(float("nan"))
    return vals


def find_wot_segments(
    rows: list[list[str]],
    headers: list[str],
    cols: ColumnMap,
    threshold: float = 90.0,
    min_duration: float = 0.5,
) -> list[tuple[int, int]]:
    """Find Wide Open Throttle segments (continuous TPS > threshold)."""
    if cols.tps is None or cols.time is None:
        return []

    tps_idx = headers.index(cols.tps)
    time_idx = headers.index(cols.time)

    segments: list[tuple[int, int]] = []
    in_wot = False
    start_idx = 0

    for i, row in enumerate(rows):
        try:
            tps = float(row[tps_idx])
        except (ValueError, IndexError):
            continue

        if tps >= threshold and not in_wot:
            in_wot = True
            start_idx = i
        elif tps < threshold and in_wot:
            in_wot = False
            try:
                t_start = float(rows[start_idx][time_idx])
                t_end = float(rows[i][time_idx])
                if t_end - t_start >= min_duration:
                    segments.append((start_idx, i))
            except (ValueError, IndexError):
                pass

    if in_wot:
        try:
            t_start = float(rows[start_idx][time_idx])
            t_end = float(rows[-1][time_idx])
            if t_end - t_start >= min_duration:
                segments.append((start_idx, len(rows) - 1))
        except (ValueError, IndexError):
            pass

    return segments


def _segment_col_vals(
    rows: list[list[str]], headers: list[str], col: str | None, start: int, end: int
) -> list[float]:
    """Extract a column's values for a segment range."""
    if col is None:
        return []
    idx = headers.index(col)
    vals: list[float] = []
    for i in range(start, end + 1):
        try:
            vals.append(float(rows[i][idx]))
        except (ValueError, IndexError):
            vals.append(float("nan"))
    return vals


def analyze_segment(
    rows: list[list[str]],
    headers: list[str],
    start: int,
    end: int,
    cols: ColumnMap,
) -> SegmentResult | None:
    """Analyze a single WOT segment."""
    time_vals = _segment_col_vals(rows, headers, cols.time, start, end)
    rpm_vals = _segment_col_vals(rows, headers, cols.rpm, start, end)
    adv_vals = _segment_col_vals(rows, headers, cols.advance, start, end)
    knock_vals = _segment_col_vals(rows, headers, cols.knock, start, end)
    mat_vals = _segment_col_vals(rows, headers, cols.mat, start, end)
    afr_vals = _segment_col_vals(rows, headers, cols.afr, start, end)
    afrtgt_vals = _segment_col_vals(rows, headers, cols.afrtgt, start, end)

    if not time_vals:
        return None

    result = SegmentResult(
        duration=time_vals[-1] - time_vals[0],
        rpm_start=min(rpm_vals) if rpm_vals else 0.0,
        rpm_end=max(rpm_vals) if rpm_vals else 0.0,
        avg_rpm=statistics.fmean(rpm_vals) if rpm_vals else 0.0,
    )

    if adv_vals:
        result.adv_min = min(adv_vals)
        result.adv_max = max(adv_vals)
        result.adv_avg = statistics.fmean(adv_vals)

    if knock_vals:
        result.knock_max = max(knock_vals)
        result.knock_avg = statistics.fmean(knock_vals)
        result.knock_events = sum(1 for k in knock_vals if k > 0)

    if mat_vals:
        result.mat_min = min(mat_vals)
        result.mat_max = max(mat_vals)
        result.mat_avg = statistics.fmean(mat_vals)

    valid_afr = [v for v in afr_vals if not math.isnan(v)]
    if valid_afr:
        result.afr_min = min(valid_afr)
        result.afr_max = max(valid_afr)
        result.afr_avg = statistics.fmean(valid_afr)

    if afrtgt_vals and valid_afr:
        diffs = [
            abs(a - t)
            for a, t in zip(afr_vals, afrtgt_vals)
            if not math.isnan(a) and not math.isnan(t)
        ]
        if diffs:
            result.afr_error_avg = statistics.fmean(diffs)
            result.afr_error_max = max(diffs)

    return result


def _fmt(v: float | None, width: int = 8, decimals: int = 1) -> str:
    if v is None or math.isnan(v):
        return "-".rjust(width)
    if decimals == 0:
        return f"{int(v)}".rjust(width)
    return f"{v:.{decimals}f}".rjust(width)


def print_pull_detail(
    rows: list[list[str]],
    headers: list[str],
    cols: ColumnMap,
    start: int,
    end: int,
    pull_num: int,
) -> None:
    """Print a row-by-row table for a single WOT pull."""
    print(f"\n{'=' * 60}")
    print(f"  Detailed Breakdown — Pull #{pull_num}")
    print(f"{'=' * 60}")

    indices: dict[str, int | None] = {}
    for name, col in (
        ("Time", cols.time),
        ("RPM", cols.rpm),
        ("TPS", cols.tps),
        ("MAP", cols.map_),
        ("Advance", cols.advance),
        ("Knock", cols.knock),
        ("MAT", cols.mat),
        ("CLT", cols.clt),
        ("AFR", cols.afr),
        ("AFR Tgt", cols.afrtgt),
        ("EGO Cor", cols.ego),
        ("PW", cols.pw),
    ):
        indices[name] = headers.index(col) if col else None

    # Header row
    header_line = " | ".join(
        f"{name:>9}" if name != "Time" else f"{'Time':>10}"
        for name in indices
    )
    print(header_line)
    print("-" * len(header_line))

    for i in range(start, end + 1):
        row = rows[i]
        parts: list[str] = []
        for name, idx in indices.items():
            if idx is None:
                parts.append(_fmt(None, 9))
                continue
            try:
                val = float(row[idx])
            except (ValueError, IndexError):
                parts.append(_fmt(None, 9))
                continue
            if name == "Time":
                parts.append(_fmt(val, 10, 3))
            elif name in ("RPM"):
                parts.append(_fmt(val, 9, 0))
            elif name in ("TPS", "MAP", "Advance", "Knock", "MAT", "CLT"):
                parts.append(_fmt(val, 9, 1))
            elif name in ("AFR", "AFR Tgt"):
                parts.append(_fmt(val, 9, 2))
            else:
                parts.append(_fmt(val, 9, 2))
        print(" | ".join(parts))

    print()


def print_report(
    filepath: Path,
    headers: list[str],
    rows: list[list[str]],
    detail_pull: int | None = None,
) -> None:
    """Print a concise analysis report."""
    cols = build_column_map(headers)

    print(f"\n{'=' * 60}")
    print("MS3 Datalog Analysis")
    print(f"File: {filepath}")
    print(f"Total samples: {len(rows)}")
    print(f"Columns: {len(headers)}")
    print(f"{'=' * 60}\n")

    # Overall stats
    print("--- Overall Stats ---")
    if cols.rpm:
        rpm_vals = to_floats(rows, headers, cols.rpm)
        print(f"  RPM range: {min(rpm_vals):.0f} - {max(rpm_vals):.0f}")
    if cols.mat:
        mat_vals = to_floats(rows, headers, cols.mat)
        print(
            f"  MAT range: {min(mat_vals):.1f}°F - {max(mat_vals):.1f}°F  "
            f"(avg: {statistics.fmean(mat_vals):.1f}°F)"
        )
    if cols.clt:
        clt_vals = to_floats(rows, headers, cols.clt)
        print(f"  CLT range: {min(clt_vals):.1f}°F - {max(clt_vals):.1f}°F")
    if cols.tps:
        tps_vals = to_floats(rows, headers, cols.tps)
        print(f"  TPS max: {max(tps_vals):.1f}%")
    if cols.knock:
        knock_vals = to_floats(rows, headers, cols.knock)
        knock_events = [k for k in knock_vals if k > 0]
        if knock_events:
            print(
                f"  Knock retard: {len(knock_events)} events, max {max(knock_events):.1f}°"
            )
        else:
            print("  Knock retard: none detected")
    print()

    # WOT segment analysis
    wot_segments = find_wot_segments(
        rows, headers, cols, threshold=85.0, min_duration=0.3
    )
    print(
        f"--- WOT Pull Analysis ({len(wot_segments)} segment(s) found, TPS >= 85%) ---\n"
    )

    if not wot_segments:
        print(
            "  No WOT segments found. Try lowering TPS threshold or check log has WOT data."
        )
        return

    detail_start_end: tuple[int, int] | None = None

    for i, (start, end) in enumerate(wot_segments, 1):
        seg = analyze_segment(rows, headers, start, end, cols)
        if seg is None:
            continue

        print(
            f"  Pull #{i}:  {seg.duration:.2f}s  |  "
            f"RPM: {seg.rpm_start:.0f} → {seg.rpm_end:.0f}"
        )

        if detail_pull == i:
            detail_start_end = (start, end)

        if seg.adv_avg is not None:
            print(
                f"    Advance:  avg {seg.adv_avg:.1f}°  "
                f"(min {seg.adv_min:.1f}°, max {seg.adv_max:.1f}°)"
            )

        if seg.knock_max is not None and seg.knock_max > 0:
            print(
                f"    ⚠️  Knock:   {seg.knock_events} events, "
                f"max {seg.knock_max:.1f}° retard"
            )
            print(f"               (avg retard: {seg.knock_avg:.1f}°)")
        elif seg.knock_max is not None:
            print("    Knock:    none")

        if seg.mat_avg is not None:
            print(
                f"    MAT:      avg {seg.mat_avg:.1f}°F  "
                f"(min {seg.mat_min:.1f}°, max {seg.mat_max:.1f}°)"
            )

        if seg.afr_avg is not None:
            print(
                f"    AFR:      avg {seg.afr_avg:.1f}  "
                f"(min {seg.afr_min:.1f}, max {seg.afr_max:.1f})"
            )
            if seg.afr_error_avg is not None:
                print(
                    f"    AFR Error: avg {seg.afr_error_avg:.2f} from target  "
                    f"(max dev: {seg.afr_error_max:.2f})"
                )

        print()

    # Summary recommendations
    print("--- Summary / Recommendations ---")

    all_knock: list[float] = []
    all_mat_wot: list[float] = []
    for start, end in wot_segments:
        if cols.knock:
            idx = headers.index(cols.knock)
            for i in range(start, end + 1):
                try:
                    k = float(rows[i][idx])
                    if k > 0:
                        all_knock.append(k)
                except (ValueError, IndexError):
                    pass
        if cols.mat:
            idx = headers.index(cols.mat)
            for i in range(start, end + 1):
                try:
                    all_mat_wot.append(float(rows[i][idx]))
                except (ValueError, IndexError):
                    pass

    if all_knock:
        avg_knock = statistics.fmean(all_knock)
        max_knock = max(all_knock)
        print("  ⚠️  Knock detected across WOT pulls.")
        print(f"     Max retard: {max_knock:.1f}°  |  Average event: {avg_knock:.1f}°")
        if max_knock >= 4.0:
            print("     → Heavy knock. Pull 3–4° from affected cells in advanceTable1.")
        elif max_knock >= 1.5:
            print("     → Light knock. Pull 2° from cells where it occurs.")
        else:
            print("     → Minor knock. Monitor, but likely acceptable on 93 octane.")
    else:
        print("  ✅ No knock detected on WOT pulls.")
        print("     Timing appears safe for these conditions.")

    if all_mat_wot:
        avg_mat = statistics.fmean(all_mat_wot)
        max_mat = max(all_mat_wot)
        print(f"  MAT during WOT: avg {avg_mat:.1f}°F  (peak {max_mat:.1f}°F)")
        if max_mat > 120:
            print(
                "     → Hot intake air. Consider improving cold-air ducting or insulation."
            )
        elif max_mat > 100:
            print("     → Warm but acceptable. Watch on 90°F+ days.")
        else:
            print("     → Good cold air intake temps.")
    else:
        print("  MAT data not available during WOT.")

    print()

    if detail_pull is not None and detail_start_end is not None:
        start, end = detail_start_end
        print_pull_detail(rows, headers, cols, start, end, detail_pull)
    elif detail_pull is not None:
        print(f"⚠️  Pull #{detail_pull} not found. Only {len(wot_segments)} segment(s) detected.\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze MS3 TunerStudio datalog (.msl)"
    )
    parser.add_argument("msl_file", type=Path, help="Path to the .msl datalog file")
    parser.add_argument(
        "--pull",
        type=int,
        metavar="N",
        help="Print a detailed row-by-row breakdown for pull number N",
    )
    args = parser.parse_args()

    if not args.msl_file.exists():
        raise SystemExit(f"Error: file not found: {args.msl_file}")

    # Detect unsupported binary .mlg format early
    with args.msl_file.open("rb") as f:
        header = f.read(5)
        if header == b"MLVLG":
            raise SystemExit(
                "Error: this is a TunerStudio .mlg binary datalog.\n"
                "       This script only supports .msl (text/CSV) datalogs.\n\n"
                "       To fix:\n"
                "       1. In TunerStudio, go to Tools → Data Logging → Settings\n"
                "          and set the log format to .msl for future logs.\n"
                "       2. Or open this .mlg in TunerStudio and use\n"
                "          File → Export Data Log to save it as .msl or .csv."
            )

    headers, rows = parse_msl(args.msl_file)
    if not headers or not rows:
        raise SystemExit("Error: could not parse datalog. Check file format.")

    print_report(args.msl_file, headers, rows, detail_pull=args.pull)


if __name__ == "__main__":
    main()
