#!/usr/bin/env python3

import struct
from typing import Any
from datetime import datetime

# Command library
R001 = b"R001"  # Request 1
R002 = b"R002"  # Request 2
R003 = b"R003"  # Request 3
R004 = b"R004"  # Request 4
R005 = b"R005"  # Request 5 
SETD = b"SETD"  # Set Date

# Command constants
CMD_HEADER = b":"
CMD_FOOTER = b"\r\n"

# Response library
D001 = b"D001"  # Data 1
D002 = b"D002"  # Data 2
D003 = b"D003"  # Data 3
D004 = b"D004"  # Data 4
D005 = b"D005"  # Data 5

# Response constants
RESP_FOOTER = b"END" + CMD_FOOTER
CHECKSUM_HEADER = b"X"


def crc32(data: bytes | bytearray) -> int:
    """CRC-32/MPEG-2: poly=0x04C11DB7, init=0xFFFFFFFF, non-reflected, xorout=0."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def verify_frame_checksum(frame: bytes | bytearray) -> None:
    """Verify the 'X' marker and 8-bit modular sum from offset 5 up to the checksum."""
    checksum_offset = len(frame) - 12  # 2-byte checksum + 10-byte ':D00xEND\r\n'
    expected_sum = sum(frame[5:checksum_offset]) & 0xFF
    expected_bytes = CHECKSUM_HEADER + bytes([expected_sum])
    actual_bytes = bytes(frame[checksum_offset : checksum_offset + 2])

    if actual_bytes != expected_bytes:
        raise ValueError(
            f"Checksum mismatch: got {actual_bytes.hex(' ')}, expected {expected_bytes.hex(' ')}"
        )
    

def frame_formatter(raw_frame: bytes) -> bytes:
    """Escape intentional 0x0D bytes and append the CRLF frame terminator."""
    escaped_payload = raw_frame.replace(b'\r', b'\r\r')
    return CMD_HEADER + escaped_payload + CMD_FOOTER


def extract_response_frame(
    buffer: bytes | bytearray, resp_code: bytes, frame_length: int
) -> bytes:
    """Locate, unescape, and validate the header, footer, and checksum of a response frame."""
    expected_header = CMD_HEADER + resp_code
    expected_footer = expected_header + RESP_FOOTER  # e.g. b":D001END\r\n" (10 bytes)

    start = buffer.find(expected_header)
    if start == -1:
        raise ValueError(f"Header {expected_header!r} not found in buffer")

    end = buffer.find(expected_footer, start)
    if end == -1:
        raise ValueError(f"End terminator {expected_footer!r} not found after header")

    raw_frame = bytes(buffer[start : end + len(expected_footer)])

    # Unescape doubled 0x0D bytes inside the payload without altering the trailing CRLF
    body = raw_frame[: -len(CMD_FOOTER)].replace(b"\r\r", b"\r")
    frame = body + CMD_FOOTER

    if len(frame) != frame_length:
        raise ValueError(
            f"Unexpected frame length ({len(frame)} bytes); expected {frame_length} bytes"
        )

    verify_frame_checksum(frame)
    return frame


def unpack_bms_date(data: bytes | bytearray, offset: int) -> datetime | None:
    """Unpack a 6-byte BMS date (<HBBBB: year, month, day, hour, minute)."""
    year, month, day, hour, minute = struct.unpack_from("<HBBBB", data, offset)
    if year == 0 or month == 0 or day == 0:
        return None
    return datetime(year, month, day, hour, minute)


def build_r001() -> bytes:
    return frame_formatter(R001)


def parse_d001(buffer: bytes | bytearray) -> dict[str, Any]:
    """Locate and parse a :D001 telemetry frame from a raw UART buffer."""
    frame = extract_response_frame(buffer, D001, 61)

    # Offset 5: lengthHeader (1s), length (i -> INT32 LSB), dataHeader (1s)
    _, length, _ = struct.unpack_from("<1si1s", frame, 5)

    # Offset 11: 12 cell voltages (12H -> 12x UINT16 LSB, 24 bytes)
    raw_cells = struct.unpack_from("<12H", frame, 11)
    cell_voltages_v = [mv / 1000.0 for mv in raw_cells]

    # Offset 35: current (i), tempExt (h), tempInt (h),
    #            packVoltage (H), chargePercent (H), residualCharge (H)
    (
        raw_current,
        temp_ext,
        temp_int,
        raw_pack_v,
        charge_percent,
        raw_residual,
    ) = struct.unpack_from("<ihhHHH", frame, 35)

    return {
        "header": bytes(frame[0:5]).decode("ascii"),
        "length": length,
        "cell_voltages_v": cell_voltages_v,
        "current_a": raw_current / 1000.0,
        "temp_ext": temp_ext,
        "temp_int": temp_int,
        "pack_voltage_v": raw_pack_v / 1000.0,
        "charge_percent": charge_percent,
        "residual_charge": raw_residual / 10000.0,
        "checksum": bytes(frame[-12:-10]),
        "end_terminator": bytes(frame[-10:]),
    }


def build_r002() -> bytes:
    return frame_formatter(R002)


def parse_d002(buffer: bytes | bytearray) -> dict[str, Any]:
    """Locate and parse a :D002 status/alarm frame from a raw UART buffer."""
    frame = extract_response_frame(buffer, D002, 41)

    # Offset 5: lengthHeader (1s), length (i -> INT32 LSB), dataHeader (1s)
    _, length, _ = struct.unpack_from("<1si1s", frame, 5)

    # Offset 15: bmsStatus (H), hwVersion (H)
    bms_status, hw_version = struct.unpack_from("<HH", frame, 15)

    return {
        "header": bytes(frame[0:5]).decode("ascii"),
        "length": length,
        "equalization": bytes(frame[11:13]),
        "alarm_code": bytes(frame[13:15]),
        "bms_status": bms_status,
        "hw_version": hw_version,
        "reserved": bytes(frame[19:29]),
        "checksum": bytes(frame[-12:-10]),
        "end_terminator": bytes(frame[-10:]),
    }


def build_r003() -> bytes:
    return frame_formatter(R003)


def parse_d003(buffer: bytes | bytearray) -> dict[str, Any]:
    """Locate and parse a :D003 pack identity, cycle count, and date frame."""
    frame = extract_response_frame(buffer, D003, 68)

    # Offset 5: lengthHeader (1s), length (i -> INT32 LSB), dataHeader (1s)
    _, length, _ = struct.unpack_from("<1si1s", frame, 5)

    # Offset 11: bmsFirmwareVersion (minor, major -> e.g. 0x17, 0x02 => "2.23")
    fw_minor, fw_major = struct.unpack_from("<BB", frame, 11)

    # Offset 13..25: serialNumber (12 bytes)
    serial_number = bytes(frame[13:25]).rstrip(b"\x00").decode("ascii", errors="replace")

    # Offset 25..28: batteryConfig (3 bytes)
    battery_config = bytes(frame[25:28])

    # Offset 34..38: fullChargeCycles (H), partialChargeCycles (H)
    full_cycles, partial_cycles = struct.unpack_from("<HH", frame, 34)

    result: dict[str, Any] = {
        "header": bytes(frame[0:5]).decode("ascii"),
        "length": length,
        "bms_firmware_version": f"{fw_major}.{fw_minor:02d}",
        "serial_number": serial_number,
        "battery_config": battery_config,
        "battery_production_date": unpack_bms_date(frame, 28),
        "full_charge_cycles": full_cycles,
        "partial_charge_cycles": partial_cycles,
        "last_full_charge": unpack_bms_date(frame, 38),
        "last_charge": unpack_bms_date(frame, 44),
        "actual_date": unpack_bms_date(frame, 50),
        "checksum": bytes(frame[-12:-10]),
        "end_terminator": bytes(frame[-10:]),
    }

    return result


def build_r004() -> bytes:
    return frame_formatter(R004)


def build_r005() -> bytes:
    return frame_formatter(R005)


def build_setd(year: int, month: int, day: int, hour: int, minute: int) -> bytes:
    assert 2000 <= year <= 2099, "year out of nominal range"
    assert 1 <= month <= 12 and 1 <= day <= 31
    assert 0 <= hour <= 23 and 0 <= minute <= 59
    raw_payload = bytes([
        (year >> 8) & 0xFF,   # year high (big-endian)
        year & 0xFF,          # year low
        month, day, hour, minute,
    ])
    return frame_formatter(SETD + raw_payload)
