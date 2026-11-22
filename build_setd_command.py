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
import amymone_functions as amy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dt', help='YYYY-MM-DD HH:MM')
    args = ap.parse_args()
    if args.dt:
        t = datetime.strptime(args.dt, '%Y-%m-%d %H:%M')
    else:
        t = datetime.now()

    frame = amy.build_setd(t.year, t.month, t.day, t.hour, t.minute)

    # Run each payload byte through frame_formatter (stripping trailing \r\n)
    # so the breakdown reflects the exact bytes produced on the wire.
    fields = [
        ('high  ', (t.year >> 8) & 0xFF),
        ('low   ', t.year & 0xFF),
        ('month ', t.month),
        ('day   ', t.day),
        ('hour  ', t.hour),
        ('minute', t.minute),
    ]
    formatted = {
        name: (
            amy.frame_formatter(bytes([val]))
            .removeprefix(amy.CMD_PREAMBLE)
            .removesuffix(amy.CMD_POSTAMBLE)
            .hex(' ')
        )
        for name, val in fields
    }


    print(f'date/time : {t:%Y-%m-%d %H:%M}')
    print(f'frame hex : {frame.hex()}')
    print(f'frame len : {len(frame)} bytes')
    print('frame repr:', frame)
    print('breakdown :')
    print('  ":SETD" =', b':SETD'.hex())
    print(f'  year    = {t.year:#06x}')
    print(f'    high  = {formatted["high  "]}')
    print(f'    low   = {formatted["low   "]}')
    print(f'  month   = {formatted["month "]}')
    print(f'  day     = {formatted["day   "]}')
    print(f'  hour    = {formatted["hour  "]}')
    print(f'  minute  = {formatted["minute"]}')
    print('  CR      = 0d     (end-of-frame marker)')
    print('  LF      = 0a     (confirms CR is terminator, not escaped 0x0d)')


if __name__ == '__main__':
    main()
