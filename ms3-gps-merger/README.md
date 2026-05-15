# ms3-gps-merger

Merge MegaSquirt MSL datalogs with Track Addict GPS CSV exports for post-session analysis.

This is a zero-dependency Python script that performs nearest-neighbor time merging of high-rate ECU data (from an MS3 onboard SD card log) with 20 Hz GPS telemetry (from Track Addict). The result is a single CSV where every GPS point is paired with the closest-in-time engine sample — useful for correlating knock events, timing trims, or fuel corrections with track position, speed, and G-load.

## Requirements

- Python 3.10+
- Standard library only (no pip install required)

## Quick Start

```bash
cd ms3-gps-merger
uv run main.py \
    --msl /path/to/onboard_log.msl \
    --gps /path/to/TrackAddict_export.csv \
    -o merged_session.csv
```

## Command-Line Options

| Flag | Required | Description |
|------|----------|-------------|
| `--msl` | Yes | Path to the `.msl` datalog from your MS3 SD card |
| `--gps` | Yes | Path to the Track Addict `.csv` export |
| `-o`, `--output` | Yes | Output path for the merged CSV |
| `--offset` | No | Manual ECU time offset in seconds. Positive shifts ECU data **forward** in time; negative shifts it backward. Use this if your logs are slightly misaligned. |

### Offset Example

If the ECU clock was 2.5 seconds behind the GPS clock:

```bash
uv run main.py --msl datalog1.msl --gps session.csv -o merged.csv --offset 2.5
```

## Input File Formats

### MSL (MegaSquirt Log)

The `.msl` file is written directly to the MS3's SD card by TunerStudio. The script expects:

- **Line 1:** Firmware/format header  
- **Line 2:** Capture date header (e.g. `Capture Date: Sun May 10 19:32:56 EDT 2026`)  
- **Line 3:** Tab-separated column names  
- **Line 4:** Tab-separated units  
- **Line 5+:** Tab-separated data rows

The capture date header is parsed as the absolute time anchor. The `Time` column (elapsed seconds since capture) is added to that anchor to reconstruct a UTC timestamp for every ECU sample.

> **Note:** Some MSL files begin with an anomalous first row (e.g. `Time=485` when the real log starts near `0`). The script detects and drops this automatically.

### Track Addict CSV

Export from Track Addict via **Share → Export Data → CSV**. The script expects:

- Comment lines beginning with `#` are skipped.
- A header row containing `UTC Time` (comma-separated, may be quoted).
- Data rows with a `UTC Time` column (Unix epoch, float with fractional seconds).

## Output Format

The merged CSV prefixes every column to avoid name collisions:

- `gps_` — columns from the Track Addict export (e.g. `gps_UTC Time`, `gps_Speed (MPH)`, `gps_Latitude`, `gps_Longitude`, `gps_Accel X`)
- `ecu_` — columns from the MSL log (e.g. `ecu_Time`, `ecu_RPM`, `ecu_MAP`, `ecu_TPS`, `ecu_SPK: Spark Advance`)

Two diagnostic columns are appended:

- `_utc_time` — the GPS timestamp used for the row
- `_time_delta_s` — absolute time difference between the GPS point and the nearest ECU sample

### Quality Check

After merging, scan `_time_delta_s`. Values should be small (ideally < 0.05 s for a 10–25 ms ECU log rate). If you see large deltas (> 0.5 s), your logs are misaligned — use `--offset` or verify the MSL capture date.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `Could not find GPS CSV header line` | The GPS file doesn't contain a `UTC Time` column | Re-export from Track Addict as CSV |
| `No valid MSL timestamps` | Missing or unparseable `Time` column | Verify the MSL is not truncated |
| Large `_time_delta_s` values | Clock skew between ECU and phone | Use `--offset` to shift ECU data |
| `UnicodeDecodeError` on MSL read | Non-UTF-8 characters (e.g. degree symbols) | Already handled with `errors="replace"`; if column names look wrong, check the MSL encoding |

## How It Works

1. Parse the MSL capture date to UTC and convert to a Unix timestamp.
2. Add each row's `Time` value to that base to build an absolute ECU timeline.
3. Sort both timelines.
4. For every GPS point, use `bisect` to find the nearest ECU sample in time.
5. Write the paired row with prefixed columns and the computed delta.

## See Also

- [EST-Miata Onboard SD Datalogging & GPS Sync Guide](../EST-Guides/EST-Miata-Onboard-Datalogging-Guide.md) — full workflow for enabling SD logging, recording GPS sessions, and using this script.
