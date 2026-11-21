#!/usr/bin/env python3

"""
Build the SUEX BMS UART ':SETD' (set-date) command frame that sets the
real-time clock and clears the 'CLC' alarm code.

Frame format:
    ':SETD'  +  <6 raw payload bytes>  +  '\r\n'
Payload bytes:
    [0] year  high byte   (year is BIG-ENDIAN)
    [1] year  low  byte
    [2] month (1-12)
    [3] day   (1-31)
    [4] hour  (0-23)
    [5] minute(0-59)
NOTE: There is no seconds field in :SETD.
NOTE: Year endianness is OPPOSITE of the :D003 read payload (which returns year LE).
NOTE: Intentional 0x0d's must be escaped by a second 0x0d to avoid incorrect CR terminator.

Example Usage of Fedora 44:
Set up the terminal interface: stty -F /dev/ttyUSB1 115200 cs8 -cstopb -parenb raw -echo
Send the generated 'frame repr' over UART with: printf 'frame repr' > /dev/ttyUSB0
Responses can be recorded with: cat /dev/ttyUSB0 > response_1.bin
Records can be viewed with: xxd response_1.bin
"""

import argparse
from datetime import datetime


def build_setd(year, month, day, hour, minute):
    assert 2000 <= year <= 2099, "year out of nominal range"
    assert 1 <= month <= 12 and 1 <= day <= 31
    assert 0 <= hour <= 23 and 0 <= minute <= 59
    raw_payload = bytes([
        (year >> 8) & 0xFF,   # year high (big-endian)
        year & 0xFF,          # year low
        month, day, hour, minute,
    ])
    escaped_payload = raw_payload.replace(b'\r', b'\r\r')
    return b':SETD' + escaped_payload + b'\r\n'


def fmt_byte(val):
    if val == 0x0D:
        return "0d 0d  (escaped 0x0d -> doubled to avoid CR terminator)"
    return f"{val:02x}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dt', help='YYYY-MM-DD HH:MM')
    args = ap.parse_args()
    if args.dt:
        t = datetime.strptime(args.dt, '%Y-%m-%d %H:%M')
    else:
        t = datetime.now()
    frame = build_setd(t.year, t.month, t.day, t.hour, t.minute)
    print(f'date/time : {t:%Y-%m-%d %H:%M}')
    print(f'frame hex : {frame.hex()}')
    print(f'frame len : {len(frame)} bytes')
    print('frame repr:', frame)
    print('breakdown :')
    print('  ":SETD" =', b':SETD'.hex())
    print(f'  year    = {t.year:#06x}')
    print(f'    high  = {fmt_byte((t.year >> 8) & 0xFF)}')
    print(f'    low   = {fmt_byte(t.year & 0xFF)}')
    print(f'  month   = {fmt_byte(t.month)}')
    print(f'  day     = {fmt_byte(t.day)}')
    print(f'  hour    = {fmt_byte(t.hour)}')
    print(f'  minute  = {fmt_byte(t.minute)}')
    print('  CR      = 0d     (end-of-frame marker)')
    print('  LF      = 0a     (confirms CR is terminator, not escaped 0x0d)')


if __name__ == '__main__':
    main()
