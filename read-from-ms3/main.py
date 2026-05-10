#!/usr/bin/env python3
"""Read MegaSquirt 3 realtime data once and print it concisely."""

from __future__ import annotations

import argparse
import struct
from binascii import crc32
from dataclasses import dataclass

import serial

BAUD = 115200
TIMEOUT = 2


@dataclass(frozen=True, slots=True)
class Channel:
    name: str
    dtype: str
    offset: int
    mult: float
    adder: float
    unit: str


# Channel definitions extracted from EST-Miata mainController.ini [OutputChannels]
CHANNELS: list[Channel] = [
    Channel("RPM", "U16", 6, 1.0, 0.0, "rpm"),
    Channel("MAP", "S16", 18, 0.1, 0.0, "kPa"),  # offset 18 in EST-Miata (was 4)
    Channel("TPS", "S16", 24, 0.1, 0.0, "%"),  # S16 in EST-Miata
    Channel("CLT", "S16", 22, 0.1, 0.0, "°F"),  # °F scaling from .ini
    Channel("MAT", "S16", 20, 0.1, 0.0, "°F"),  # °F scaling from .ini
    Channel("AFR1", "S16", 28, 0.1, 0.0, "AFR"),  # afr1_old at offset 28
    Channel("Batt", "S16", 26, 0.1, 0.0, "V"),  # multiplier 0.1 in EST-Miata (was 0.01)
    Channel("Advance", "S16", 8, 0.1, 0.0, "°"),
]


def calc_crc(data: bytes) -> int:
    return crc32(data) & 0xFFFFFFFF


def build_read_request(table_id: int, offset: int, length: int) -> bytes:
    payload = struct.pack(">BBHH", 0x72, table_id, offset, length)
    header = struct.pack(">BBH", 0x01, 0x00, len(payload))
    frame = header + payload
    crc = struct.pack(">I", calc_crc(frame))
    return b"\xaa" + frame + crc


def read_response(ser: serial.Serial) -> bytes:
    # Wait for start-of-frame
    while True:
        b = ser.read(1)
        if not b:
            raise TimeoutError("No data from ECU")
        if b == b"\xaa":
            break

    header = ser.read(4)
    if len(header) != 4:
        raise TimeoutError("Incomplete response header")

    to_addr, from_addr, length = struct.unpack(">BBH", header)
    payload = ser.read(length)
    if len(payload) != length:
        raise TimeoutError("Incomplete response payload")

    crc_bytes = ser.read(4)
    if len(crc_bytes) != 4:
        raise TimeoutError("Incomplete response CRC")

    body = header + payload
    expected = struct.unpack(">I", crc_bytes)[0]
    actual = calc_crc(body)

    if expected != actual:
        raise ValueError(f"CRC mismatch: expected {expected:#010x}, got {actual:#010x}")

    return payload


def parse(data: bytes) -> dict[str, tuple[float, str]]:
    results = {}
    for ch in CHANNELS:
        fmt = ">H" if ch.dtype == "U16" else ">h"
        raw = struct.unpack_from(fmt, data, ch.offset)[0]
        results[ch.name] = (raw * ch.mult + ch.adder, ch.unit)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read MS3 realtime data once and print it."
    )
    parser.add_argument(
        "port",
        nargs="?",
        default="/dev/tty.usbserial-XXXX",
        help="Serial port (e.g. /dev/tty.usbserial-XXXX)",
    )
    args = parser.parse_args()

    try:
        with serial.Serial(args.port, BAUD, timeout=TIMEOUT) as ser:
            ser.write(build_read_request(table_id=7, offset=0, length=110))
            data = read_response(ser)
            values = parse(data)
    except serial.SerialException as e:
        raise SystemExit(f"Serial error: {e}")
    except (TimeoutError, ValueError) as e:
        raise SystemExit(f"ECU error: {e}")

    print("MS3 Realtime Data")
    print("-" * 25)
    for ch in CHANNELS:
        val, unit = values[ch.name]
        print(f"{ch.name:>8}: {val:>7.1f} {unit}")


if __name__ == "__main__":
    main()
