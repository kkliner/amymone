#!/usr/bin/env python3

"""
Patch the SUEX BMS SPI flash memory chip to reset the full and partial charge counters,
manufacture date, and total Amp-hours tracked.

This is intended to be done after the li-ion cells in a battery pack have been replaced.
"""

import argparse
from datetime import datetime
import struct
from pathlib import Path
import amymone_functions as amy

FMT_U32 = "<" + "I"
FMT_U16 = "<" + "H"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Patch a SUEX BMS SPI flash .bin to reset charge counters, "
            "Amp-hours, and manufacture date."
        )
    )
    parser.add_argument(
        "dump_file",
        type=Path,
        help="Path to the 4MB SPI flash binary dump (e.g., backup.bin)",
    )
    args = parser.parse_args()

    in_path: Path = args.dump_file
    if not in_path.is_file():
        parser.error(f"File not found: {in_path}")

    out_path = in_path.with_name(f"{in_path.stem}_patched{in_path.suffix}")

    image = bytearray(in_path.read_bytes())
    if len(image) < 0x200031:
        raise ValueError(f"File too small ({len(image)} bytes); expected 4MB dump")

    # --- Block 1: Cumulative Counters & Full Charge Cycles at 0x000000 (31 bytes + 4-byte CRC) ---
    blk1 = bytearray(image[0x00:0x1F])
    stored_crc1, = struct.unpack(FMT_U32, image[0x1F:0x23])
    computed_crc1 = amy.bms_crc32(blk1)

    if stored_crc1 != computed_crc1:
        raise ValueError(
            f"Block 1 (0x000000) CRC mismatch! Stored={stored_crc1:#010x}, Computed={computed_crc1:#010x}"
        )

    old_full_cycles, = struct.unpack(FMT_U32, blk1[0x10:0x14])
    print(f"[0x000000] Verified CRC32     : {stored_crc1:#010x}")
    print(f"[0x000000] Full charge cycles : {old_full_cycles} -> 0")
    print(
        f"[0x000000] Pack config        : {blk1[0x14]}S {blk1[0x15]}P (Profile {blk1[0x16]})"
    )

    # Zero cumulative counters (0x00..0x0F) and Full Charge Cycles (0x10..0x13)
    blk1[0x00:0x14] = b"\x00" * 20
    new_crc1 = amy.bms_crc32(blk1)
    image[0x00:0x1F] = blk1
    image[0x1F:0x23] = struct.pack(FMT_U32, new_crc1)
    print(f"[0x000000] Updated CRC32      : {new_crc1:#010x}")

    # --- Block 2: Battery Identity & Partial Charge Cycles at 0x200000 (45 bytes + 4-byte CRC) ---
    blk2_off = 0x200000
    blk2 = bytearray(image[blk2_off : blk2_off + 0x2D])
    stored_crc2, = struct.unpack(FMT_U32, image[blk2_off + 0x2D : blk2_off + 0x31])
    computed_crc2 = amy.bms_crc32(blk2)

    if stored_crc2 == computed_crc2:
        serial = blk2[0x02:0x0E].decode("ascii", errors="replace")
        old_blk2_full, = struct.unpack(FMT_U16, blk2[0x17:0x19])
        old_partial, = struct.unpack(FMT_U16, blk2[0x19:0x1B])
        print(f"[0x200000] Verified CRC32         : {stored_crc2:#010x}")
        print(f"[0x200000] Serial / BLE Name      : {serial!r}")
        print(f"[0x200000] Full cycles (mirrored) : {old_blk2_full} -> 0")
        print(f"[0x200000] Partial cycles         : {old_partial} -> 0")

        # Read existing manufacture date (0x11..0x16: uint16 year, uint8 month, day, hour, min)
        mfg_year, mfg_month, mfg_day, mfg_hour, mfg_min = struct.unpack(
            "<HBBBB", blk2[0x11:0x17]
        )
        now = datetime.now()
        blk2[0x11:0x17] = struct.pack(
            "<HBBBB", now.year, now.month, now.day, now.hour, now.minute
        )
        print(
            f"[0x200000] Manufacture date       : "
            f"{mfg_year:04d}-{mfg_month:02d}-{mfg_day:02d} {mfg_hour:02d}:{mfg_min:02d} -> "
            f"{now:%Y-%m-%d %H:%M}"
        )

        # Zero Full Charge Cycles (0x17..0x18) and Partial Charge Cycles (0x19..0x1A)
        blk2[0x17:0x1B] = b"\x00\x00\x00\x00"
        new_crc2 = amy.bms_crc32(blk2)
        image[blk2_off : blk2_off + 0x2D] = blk2
        image[blk2_off + 0x2D : blk2_off + 0x31] = struct.pack(FMT_U32, new_crc2)
        print(f"[0x200000] Updated CRC32      : {new_crc2:#010x}")
    elif all(b == 0xFF for b in blk2):
        print("[0x200000] Block is blank (0xFF); partial cycles will boot as 0.")
    else:
        raise ValueError(
            f"Block 2 (0x200000) CRC mismatch! Stored={stored_crc2:#010x}, Computed={computed_crc2:#010x}"
        )

    out_path.write_bytes(image)
    print(f"Wrote patched file            : {out_path} ({len(image)} bytes)")


if __name__ == "__main__":
    main()
