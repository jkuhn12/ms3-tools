# ms3-tools

Tools for MegaSquirt 3 analysis using the MS3 serial protocol.

This repo contains scripts, documentation, and utilities for reading realtime data from a MegaSquirt 3 ECU and analyzing datalogs for tuning insights. It was built specifically for an autocross-focused 1990 Miata (NA6) running MS3 firmware, but the tools are generic enough to work with any MS3-based setup.

## What's Here

### `read-from-ms3/` — Live Realtime Data

A minimal Python script that queries the ECU once over serial, validates the CRC32, and prints key channels concisely to the console.

- **`ms3_read.py`** — Single-shot realtime reader. Prints RPM, MAP, TPS, CLT, MAT, AFR, battery voltage, and spark advance, then exits.
- **`requirements.txt`** — External dependency: `pyserial`

Usage:
```bash
cd read-from-ms3
uv pip install -r requirements.txt
uv run ms3_read.py /dev/tty.usbserial-XXXX
```

This is useful for quick checks in the paddock — verifying the ECU is responding, checking coolant temp before a run, or spot-checking AFR.

### `ms3-analysis/` — Datalog Analysis

A command-line analyzer for TunerStudio `.msl` datalog files.

- **`main.py`** — Parses datalogs, finds WOT pull segments, and reports knock retard, spark advance, intake temps, and AFR deviations. Tells you whether your tune is too aggressive or safe without scrolling through thousands of rows.

Usage:
```bash
cd ms3-analysis
uv run main.py /path/to/datalog.msl
```

No external dependencies — uses only the Python standard library.

### `ms3-gps-merger/` — GPS Sync & Merge

A zero-dependency Python script that merges high-rate MS3 SD card datalogs with 20 Hz Track Addict GPS telemetry. Produces a single CSV where every GPS point is paired with the nearest-in-time engine sample — useful for correlating knock events, timing trims, or fuel corrections with track position, speed, and G-load.

- **`main.py`** — Nearest-neighbor time merge of `.msl` and Track Addict `.csv`

Usage:
```bash
cd ms3-gps-merger
uv run main.py \
    --msl /path/to/onboard_log.msl \
    --gps /path/to/TrackAddict_export.csv \
    -o merged_session.csv
```

See the [ms3-gps-merger README](ms3-gps-merger/README.md) for full options and troubleshooting.

### Documentation

- **`reference.md`** — MS3 serial protocol reference (framing, CRC32, commands, realtime data offsets)
- **`EST-Miata-Tune-Summary.md`** — Parsed summary of the EST-Miata project's `CurrentTune.msq`
- **`EST-Miata-Torque-Dip-Analysis.md`** — Analysis of whether the tune successfully fills the stock B6 torque dip (2500–5000 RPM)
- **`EST-Miata-Heat-Soak-Power-Loss.md`** — Theoretical power loss from hot intake air and timing pull
- **`Custom-Intake-vs-RB-Nationals-Analysis.md`** — Comparing a custom GT-Power-designed intake vs. a Racing Beat intake for Solo Nationals competitiveness
- **`EST-Miata-Datalog-Tuning-Guide.md`** — How to use datalogs to verify and refine spark, fuel, and transient response

## Serial Protocol

All communication uses the MS3 binary framing protocol:

```
[0xAA] [to] [from] [length_hi] [length_lo] [cmd] [data...] [CRC32 - 4 bytes]
```

- 115200 baud, 8N1
- CRC32 covers bytes 1 through end of data (not the `0xAA` start byte)
- Standard CRC32 polynomial (same as zip/ethernet)

The live reader sends a **Read Block** command (`0x72`) for table 7 (realtime data) and parses the 110-byte response.

## Channel Offsets (110-byte Realtime Block)

These are the offsets used in `ms3_read.py`, extracted from the project's TunerStudio `.ini` file:

| Channel | Type | Offset | Multiplier | Unit |
|---------|------|--------|------------|------|
| RPM | U16 | 6 | 1.0 | rpm |
| MAP | S16 | 18 | 0.1 | kPa |
| TPS | S16 | 24 | 0.1 | % |
| CLT | S16 | 22 | 0.1 | °F |
| MAT | S16 | 20 | 0.1 | °F |
| AFR1 | S16 | 28 | 0.1 | AFR |
| Batt | S16 | 26 | 0.1 | V |
| Advance | S16 | 8 | 0.1 | ° |

> ⚠️ Offsets vary by firmware version. Cross-reference with your project's `[OutputChannels]` section in TunerStudio.

## Requirements

- Python 3.10+ (uses `dataclasses(slots=True)`, `statistics.fmean()`, `argparse`)
- `pyserial` (for live reading only)
- A USB-to-serial adapter matching your MS3's connection (common: FTDI, CH340, CP210x)

## Future Ideas

- [ ] Parse TunerStudio `.ini` files automatically to extract channel offsets
- [ ] Live dashboard mode (continuous polling instead of single-shot)
- [ ] Datalog visualizer (plot RPM, advance, knock, MAT over time)
- [ ] VE table auto-suggestion from wideband datalogs

## License

MIT — use at your own risk. Engine tuning can damage hardware. Verify everything with proper instrumentation and never trust a script more than your knock ears.
