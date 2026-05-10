# Megasquirt MS3 Serial Protocol Reference

## Connection Settings

| Parameter | Value |
|-----------|-------|
| Baud Rate | 115200 |
| Data Bits | 8 |
| Parity | None |
| Stop Bits | 1 |
| Format | 8N1 |

Connect via USB-to-serial adapter. Your device will appear as `/dev/tty.usbserial-XXXX` on macOS.

---

## Frame Structure

Every message — both requests and responses — uses the same framing format:

```
[0xAA] [to] [from] [length_hi] [length_lo] [cmd] [data...] [CRC32 - 4 bytes]
```

| Byte(s) | Value | Description |
|---------|-------|-------------|
| 0 | `0xAA` | Start of frame marker |
| 1 | `0x01` | Destination: ECU (host→ECU requests) |
| 2 | `0x00` | Source: host |
| 3–4 | e.g. `0x00 0x07` | Payload length, big-endian |
| 5 | `0xnn` | Command byte |
| 6..n | `...` | Command parameters / data |
| n+1..n+4 | `...` | CRC32 checksum |

> **CRC32 covers bytes 1 through end of data — not the `0xAA` start byte.**

In responses, `to` = `0x00` (host) and `from` = `0x01` (ECU).

---

## Commands

| Command | Byte | Direction | Description |
|---------|------|-----------|-------------|
| Read block | `0x72` (`r`) | Host → ECU | Read data from a table |
| Write block | `0x77` (`w`) | Host → ECU | Write data to a table |
| Burn to flash | `0x62` (`b`) | Host → ECU | Persist current page to flash |
| ECU signature | `0x65` (`e`) | Host → ECU | Request ECU identity string |
| Firmware version | `0x46` (`F`) | Host → ECU | Request firmware version string |
| OK / data response | `0x00` | ECU → Host | Acknowledge or data reply |
| Error response | `0x01` | ECU → Host | Error reply |

---

## Reading Realtime Data

### Request (host → ECU)

To request 110 bytes of realtime data from table 7, offset 0:

```
0xAA              Start of frame
0x01              To: ECU
0x00              From: host
0x00 0x07         Payload length = 7 bytes
0x72              Command: read
0x07              Table ID: 7 (realtime data)
0x00 0x00         Offset: 0
0x00 0x6E         Length: 110 bytes
[CRC32 - 4 bytes] Checksum over bytes 1 through end
```

### Response (ECU → host)

```
0xAA              Start of frame
0x00              To: host
0x01              From: ECU
0x00 0x6E         Payload length = 110 bytes
[110 bytes]       Realtime data
[CRC32 - 4 bytes] Checksum
```

---

## Table IDs

| Table ID | Contents |
|----------|----------|
| 0 | Page 0 — main constants |
| 1 | Page 1 — fuel table |
| 2 | Page 2 — ignition table |
| 3 | Page 3 — AFR table |
| 4 | Page 4 — boost table |
| **7** | **Realtime data** |
| 10 | Knock settings |
| 14 | CAN broadcast config |
| 20+ | Extended tables |

---

## Realtime Data Channel Offsets

These are the key offsets within the 110-byte realtime data block. All values are big-endian.

| Name | Type | Offset | Units | Multiplier | Adder |
|------|------|--------|-------|------------|-------|
| rpm | U16 | 6 | RPM | 1.0 | 0.0 |
| map | U16 | 4 | kPa | 0.1 | 0.0 |
| tps | U16 | 24 | % | 0.1 | 0.0 |
| clt | S16 | 22 | deg | 0.1 | 0.0 |
| mat | S16 | 20 | deg | 0.1 | 0.0 |
| afr1 | U16 | 28 | AFR | 0.1 | 0.0 |
| batt | U16 | 26 | V | 0.01 | 0.0 |
| advance | S16 | 8 | deg | 0.1 | 0.0 |

> **Note:** Exact offsets depend on your firmware version. Cross-reference with the `[OutputChannels]` section of your TunerStudio `.ini` file for your project. The formula is always:
> ```
> real_value = (raw_value * multiplier) + adder
> ```

---

## CRC32 Calculation

MS3 uses standard CRC32 (same polynomial as zip/ethernet), applied over all bytes **except** the leading `0xAA`.

```python
from binascii import crc32

def calc_crc(data: bytes) -> int:
    return crc32(data) & 0xFFFFFFFF

# Verify a received frame
def verify_response(frame: bytes) -> bool:
    body     = frame[1:-4]          # skip 0xAA and trailing CRC
    expected = int.from_bytes(frame[-4:], 'big')
    return calc_crc(body) == expected
```

---

## Python Script — Live Realtime Data

Install dependency:

```bash
pip3 install pyserial
```

Full script:

```python
import serial
import struct
from binascii import crc32
import time

PORT = '/dev/tty.usbserial-XXXX'   # <-- change this
BAUD = 115200

def calc_crc(data):
    return crc32(data) & 0xFFFFFFFF

def build_read_request(table_id, offset, length):
    payload = struct.pack('>BBHH', 0x72, table_id, offset, length)
    header  = struct.pack('>BBH', 0x01, 0x00, len(payload))  # to=ECU, from=host
    frame   = header + payload
    crc     = struct.pack('>I', calc_crc(frame))
    return b'\xAA' + frame + crc

def read_response(ser):
    while True:
        b = ser.read(1)
        if b == b'\xAA':
            break

    header               = ser.read(4)
    to_addr, from_addr, length = struct.unpack('>BBH', header)
    payload              = ser.read(length)
    crc_bytes            = ser.read(4)

    body     = header + payload
    expected = struct.unpack('>I', crc_bytes)[0]
    actual   = calc_crc(body)

    if expected != actual:
        raise ValueError(f"CRC mismatch: {expected:#010x} vs {actual:#010x}")

    return payload

# Channel definitions: name -> (type, offset, units, multiplier, adder)
# Cross-reference with your .ini file's [OutputChannels] section
CHANNELS = {
    'rpm':      ('U16',  6,  'RPM',  1.0,  0.0),
    'map':      ('U16',  4,  'kPa',  0.1,  0.0),
    'tps':      ('U16', 24,  '%',    0.1,  0.0),
    'clt':      ('S16', 22,  'deg',  0.1,  0.0),
    'mat':      ('S16', 20,  'deg',  0.1,  0.0),
    'afr1':     ('U16', 28,  'AFR',  0.1,  0.0),
    'batt':     ('U16', 26,  'V',    0.01, 0.0),
    'advance':  ('S16',  8,  'deg',  0.1,  0.0),
}

def parse_realtime(data):
    results = {}
    for name, (dtype, offset, units, mult, adder) in CHANNELS.items():
        try:
            fmt = '>H' if dtype == 'U16' else '>h' if dtype == 'S16' \
                  else '>B' if dtype == 'U08' else '>b'
            raw = struct.unpack_from(fmt, data, offset)[0]
            results[name] = (name, raw * mult + adder, units)
        except struct.error:
            pass
    return results

with serial.Serial(PORT, BAUD, timeout=2) as ser:
    print(f"Connected to MS3 on {PORT}\n")
    while True:
        try:
            ser.write(build_read_request(table_id=7, offset=0, length=110))
            data   = read_response(ser)
            values = parse_realtime(data)

            print("\033[H\033[J", end='')   # clear screen
            print("── MS3 Realtime Data ──────────────────")
            for name, (_, val, units) in values.items():
                print(f"  {name:<12} {val:>8.1f}  {units}")
            print("────────────────────────────────────────")

        except ValueError as e:
            print(f"CRC Error: {e}")
        except KeyboardInterrupt:
            print("\nStopped.")
            break

        time.sleep(0.1)
```

---

## Finding Your Serial Port

```bash
ls /dev/tty.*
```

Look for `/dev/tty.usbserial-XXXX` or `/dev/tty.usbmodemXXXX`. If nothing appears, you may need a driver for your USB-to-serial chip:

| Chip | Driver source |
|------|--------------|
| CH340 / CH341 | wch.cn |
| FTDI | ftdichip.com |
| CP210x | silabs.com |

---

## TunerStudio .INI File

Your `.ini` file is the definitive reference for all channel offsets and scaling. Find it at:

```
~/Documents/TunerStudio MS/projects/<your_project>/<your_project>.ini
```

Look for the `[OutputChannels]` section. Each line follows this format:

```ini
rpm    = scalar, U16, 6,  "RPM", 1.0, 0.0
map    = scalar, U16, 4,  "kPa", 0.1, 0.0
```

Parsing this file automatically gives you every channel without hardcoding any offsets.
