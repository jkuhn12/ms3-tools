# MS3 Datalog Analyzer

A command-line tool for analyzing TunerStudio `.msl` datalog files from MegaSquirt 3 ECUs. Extracts key tuning insights from WOT pulls without manually scrolling through thousands of rows.

## What It Does

- Parses TunerStudio `.msl` datalog files (handles header metadata automatically)
- Auto-detects common channel names (`rpm`, `advance`, `knkRetard`, `MAT`, `AFR1`, etc.)
- Identifies WOT pull segments (TPS ≥ 85%)
- Reports spark advance, knock retard, intake temps, and AFR for each pull
- Summarizes whether your tune is too aggressive or safe

## Usage

```bash
python3 analyze_log.py /path/to/your/datalog.msl
```

## Example Output

```
============================================================
MS3 Datalog Analysis
File: 2024-06-15_run3.msl
Total samples: 15234
Columns: 42
============================================================

--- Overall Stats ---
  RPM range: 950 - 7600
  MAT range: 88.0°F - 142.0°F  (avg: 105.3°F)
  Knock retard: 12 events, max 4.5°

--- WOT Pull Analysis (3 segment(s) found) ---

  Pull #1:  2.85s  |  RPM: 2600 → 7200
    Advance:  avg 36.2°  (min 31.5°, max 39.8°)
    ⚠️  Knock:   5 events, max 4.5° retard
    MAT:      avg 118.0°F  (peak 132.0°F)

--- Summary / Recommendations ---
  ⚠️  Knock detected across WOT pulls.
     Max retard: 4.5°  |  Average event: 2.1°
     → Heavy knock. Pull 3–4° from affected cells in advanceTable1.
  MAT during WOT: avg 118.0°F (peak 132.0°F)
     → Hot intake air. Consider improving cold-air ducting.
```

## Interpreting Results

| Result | Meaning | Action |
|--------|---------|--------|
| No knock detected | Timing is safe for these conditions | ✅ Leave it, or consider adding 1–2° if you want more torque |
| Light knock (1–3° max) | Edge of safety on 93 octane | ⚠️ Pull 2° from cells where knock occurs |
| Heavy knock (4°+ max) | Detonation risk — motor damage possible | ❌ Pull 3–4° immediately |
| MAT > 120°F during WOT | Intake is heat-soaked | 🌡️ Move filter to cold air, add insulation |

## Requirements

- Python 3.10+
- No external dependencies (uses only standard library)

## Supported Channels

The script auto-detects these common column names:

- `rpm`, `RPM`
- `tps`, `TPS`, `throttle`
- `advance`, `spark`, `timing`
- `knkRetard`, `knockRetard`, `knock retard`
- `mat`, `MAT`, `iat`, `IAT`
- `clt`, `CLT`, `coolant`
- `afr1`, `AFR1`, `afr`, `afr1_old`
- `afrtgt1`, `afrtarget`, `afrTarget`
- `egoCorrection1`, `egoCorrection`, `egoCorr`
- `pulseWidth1`, `pw1`, `pw_1`
- `map`, `MAP`

If your `.msl` file uses different names, the script will still parse but may skip that analysis section.

## Workflow

1. **Log data** in TunerStudio (Vehicle → Data Logging → Start Logging)
2. **Drive** — do a few WOT pulls, some cruise, some tip-in transients
3. **Run this script** on the `.msl` file
4. **Read the summary** — it tells you if timing is safe, if knock is happening, and if intake temps are good
5. **Tune in TunerStudio** based on findings
6. **Re-log and re-analyze** — iterate

## See Also

- [EST-Miata Datalog Tuning Guide](../read-from-ms3/EST-Miata-Datalog-Tuning-Guide.md) — detailed guide on what to log and how to act on it
