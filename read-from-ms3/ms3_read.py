#!/usr/bin/env python3
"""Read MegaSquirt 3 realtime data once and print it concisely."""

import sys
import struct
from binascii import crc32

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else '/dev/tty.usbserial-XXXX'
BAUD = 115200
TIMEOUT = 2

# Channel definitions extracted from EST-Miata mainController.ini [OutputChannels]
# (name, type, offset, multiplier, adder, unit)
CHANNELS = [
    ('RPM',     'U16', 6,  1.0,  0.0,  'rpm'),
    ('MAP',     'S16', 18, 0.1,  0.0,  'kPa'),    # offset 18 in EST-Miata (was 4)
    ('TPS',     'S16', 24, 0.1,  0.0,  '%'),      # S16 in EST-Miata
    ('CLT',     'S16', 22, 0.1,  0.0,  '°F'),     # °F scaling from .ini
    ('MAT',     'S16', 20, 0.1,  0.0,  '°F'),     # °F scaling from .ini
    ('AFR1',    'S16', 28, 0.1,  0.0,  'AFR'),    # afr1_old at offset 28
    ('Batt',    'S16', 26, 0.1,  0.0,  'V'),      # multiplier 0.1 in EST-Miata (was 0.01)
    ('Advance', 'S16', 8,  0.1,  0.0,  '°'),
]


def calc_crc(data: bytes) -> int:
    return crc32(data) & 0xFFFFFFFF


def build_read_request(table_id: int, offset: int, length: int) -> bytes:
    payload = struct.pack('>BBHH', 0x72, table_id, offset, length)
    header = struct.pack('>BBH', 0x01, 0x00, len(payload))
    frame = header + payload
    crc = struct.pack('>I', calc_crc(frame))
    return b'\xAA' + frame + crc


def read_response(ser: serial.Serial) -> bytes:
    # Wait for start-of-frame
    while True:
        b = ser.read(1)
        if not b:
            raise TimeoutError('No data from ECU')
        if b == b'\xAA':
            break

    header = ser.read(4)
    if len(header) != 4:
        raise TimeoutError('Incomplete response header')

    to_addr, from_addr, length = struct.unpack('>BBH', header)
    payload = ser.read(length)
    if len(payload) != length:
        raise TimeoutError('Incomplete response payload')

    crc_bytes = ser.read(4)
    if len(crc_bytes) != 4:
        raise TimeoutError('Incomplete response CRC')

    body = header + payload
    expected = struct.unpack('>I', crc_bytes)[0]
    actual = calc_crc(body)

    if expected != actual:
        raise ValueError(f'CRC mismatch: expected {expected:#010x}, got {actual:#010x}')

    return payload


def parse(data: bytes) -> dict:
    results = {}
    for name, dtype, offset, mult, adder, unit in CHANNELS:
        fmt = '>H' if dtype == 'U16' else '>h'
        raw = struct.unpack_from(fmt, data, offset)[0]
        results[name] = (raw * mult + adder, unit)
    return results


def main():
    try:
        with serial.Serial(PORT, BAUD, timeout=TIMEOUT) as ser:
            ser.write(build_read_request(table_id=7, offset=0, length=110))
            data = read_response(ser)
            values = parse(data)
    except serial.SerialException as e:
        print(f'Serial error: {e}', file=sys.stderr)
        sys.exit(1)
    except (TimeoutError, ValueError) as e:
        print(f'ECU error: {e}', file=sys.stderr)
        sys.exit(1)

    print('MS3 Realtime Data')
    print('-' * 25)
    for name in [c[0] for c in CHANNELS]:
        val, unit = values[name]
        print(f'{name:>8}: {val:>7.1f} {unit}')


if __name__ == '__main__':
    main()
