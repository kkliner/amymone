#!/usr/bin/env python3

import struct
from typing import Any
from datetime import datetime
import math

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

# Alarm code library
ALARM_CODES: dict[int, str] = {
    1: "CHG_OVERCURRENT",
    2: "DSG_OVERCURRENT",
    3: "BMS_HW_MALFUNCTION",
    4: "OVERVOLTAGE",
    5: "CHG_SHORT_CIRCUIT",
    6: "DSG_SHORT_CIRCUIT",
    7: "UNDERVOLTAGE",
    8: "CLOCK_OUT_OF_DATE",
    9: "PCB_OVERTEMPERATURE",
    10: "DEEP_UNDERVOLTAGE",
    11: "CHANGE_BATTERY",
    12: "CELL_UNBALANCED",
    13: "UNDERTEMPERATURE",
    14: "OVERTEMPERATURE",
}


BMS_STATUS_BITS: dict[int, tuple[str, str]] = {
    0: ("MOSFET_DSG_OFF", "MOSFET_DSG_ON"),
    1: ("MOSFET_CHG_OFF", "MOSFET_CHG_ON"),
}


def decode_alarm_codes(alarm_code: bytes | bytearray | int) -> list[str]:
    """Decode a 2-byte LSB or integer BMS alarm bitmask into active alarm names."""
    if isinstance(alarm_code, (bytes, bytearray)):
        if len(alarm_code) != 2:
            raise ValueError(f"Expected 2-byte alarm_code, got {len(alarm_code)} bytes")
        mask = int.from_bytes(alarm_code, byteorder="little")
    else:
        mask = int(alarm_code)

    return [name for bit, name in ALARM_CODES.items() if mask & (1 << bit)]


def decode_bms_status(bms_status: bytes | bytearray | int) -> list[str]:
    """Decode a BMS status integer or LSB bytes into MOSFET state labels."""
    if isinstance(bms_status, (bytes, bytearray)):
        mask = int.from_bytes(bms_status, byteorder="little")
    else:
        mask = int(bms_status)

    return [
        on_label if (mask & (1 << bit)) else off_label
        for bit, (off_label, on_label) in BMS_STATUS_BITS.items()
    ]


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
    buffer: bytes | bytearray,
    resp_code: bytes,
    frame_length: int | None = None,
    verify_checksum: bool = True,
) -> bytes:
    """Locate and validate the header, footer, and checksum of a response frame."""
    expected_header = CMD_HEADER + resp_code
    expected_footer = expected_header + RESP_FOOTER  # e.g. b":D001END\r\n" (10 bytes)

    start = buffer.find(expected_header)
    if start == -1:
        raise ValueError(f"Header {expected_header!r} not found in buffer")

    end = buffer.find(expected_footer, start)
    if end == -1:
        raise ValueError(f"End terminator {expected_footer!r} not found after header")

    frame = bytes(buffer[start : end + len(expected_footer)])

    if frame_length is not None and len(frame) != frame_length:
        raise ValueError(
            f"Unexpected frame length ({len(frame)} bytes); expected {frame_length} bytes"
        )

    if verify_checksum:
        verify_frame_checksum(frame)

    return frame


def unpack_date(data: bytes | bytearray, offset: int) -> datetime | None:
    """Unpack a 6-byte date (<HBBBB: year, month, day, hour, minute)."""
    year, month, day, hour, minute = struct.unpack_from("<HBBBB", data, offset)
    if year == 0 or month == 0 or day == 0:
        return None
    return datetime(year, month, day, hour, minute)


def build_r001() -> bytes:
    return frame_formatter(R001)


def parse_d001(buffer: bytes | bytearray) -> dict[str, Any]:
    """Locate and parse a :D001 telemetry frame."""
    frame = extract_response_frame(buffer, D001, 61)

    # Offset 5: lengthHeader (1s), length (i -> INT32 LSB), dataHeader (1s)
    _, length, _ = struct.unpack_from("<1sI1s", frame, 5)

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
    """Locate and parse a :D002 status/alarm frame."""
    frame = extract_response_frame(buffer, D002, 41)

    # Offset 5: lengthHeader (1s), length (I -> UINT32 LSB), dataHeader (1s)
    _, length, _ = struct.unpack_from("<1sI1s", frame, 5)

    # Offset 11: equalization (2B), alarmCode (2B), bmsStatus (H -> UINT16 LSB)
    equalization = bytes(frame[11:13])
    raw_alarm_code = bytes(frame[13:15])
    (bms_status,) = struct.unpack_from("<H", frame, 15)

    return {
        "header": bytes(frame[0:5]).decode("ascii"),
        "length": length,
        "equalization": equalization,
        "alarm_code": raw_alarm_code,
        "alarms": decode_alarm_codes(raw_alarm_code),
        "bms_status": bms_status,
        "mosfet_states": decode_bms_status(bms_status),
        "reserved": bytes(frame[17:29]),
        "checksum": bytes(frame[-12:-10]),
        "end_terminator": bytes(frame[-10:]),
    }


def build_r003() -> bytes:
    return frame_formatter(R003)


def parse_d003(buffer: bytes | bytearray) -> dict[str, Any]:
    """Locate and parse a :D003 pack identity, cycle count, and date frame."""
    frame = extract_response_frame(buffer, D003, 68)

    # Offset 5: lengthHeader (1s), length (i -> INT32 LSB), dataHeader (1s)
    _, length, _ = struct.unpack_from("<1sI1s", frame, 5)

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
        "battery_production_date": unpack_date(frame, 28),
        "full_charge_cycles": full_cycles,
        "partial_charge_cycles": partial_cycles,
        "last_full_charge": unpack_date(frame, 38),
        "last_charge": unpack_date(frame, 44),
        "actual_date": unpack_date(frame, 50),
        "checksum": bytes(frame[-12:-10]),
        "end_terminator": bytes(frame[-10:]),
    }

    return result


def build_r004() -> bytes:
    return frame_formatter(R004)


def parse_d004(buffer: bytes | bytearray) -> dict[str, Any]:
    """Locate and parse a variable-length :D004 event/alarm history frame."""
    frame = extract_response_frame(buffer, D004, frame_length=None, verify_checksum=False)

    if len(frame) < 22:
        raise ValueError(f"Frame too short ({len(frame)} bytes); expected at least 22 bytes")

    # Offset 5: lengthHeader (1s), length (I -> UINT32 LSB)
    _, length = struct.unpack_from("<1sI", frame, 5)
    payload = frame[10:-12]

    # Empty log edge case: device sends 4-byte b"NULL" and checksum b"X\xff"
    if payload == b"NULL":
        if bytes(frame[-12:-10]) != CHECKSUM_HEADER + b"\xff":
            raise ValueError(
                f"Checksum mismatch on empty :D004 frame: got {bytes(frame[-12:-10]).hex(' ')}"
            )
        events: list[dict[str, Any]] = []
    else:
        verify_frame_checksum(frame)
        if len(payload) != length or len(payload) % 10 != 0:
            raise ValueError(
                f"Invalid :D004 payload length ({len(payload)} bytes); expected {length} bytes (multiple of 10)"
            )

        events = []
        for offset in range(0, len(payload), 10):
            # Each 10-byte record: 'D' (1s), eventType (B), eventCode (B), 'A' (1s), date (6B)
            _, event_type, event_code, _ = struct.unpack_from("<1sBB1s", payload, offset)
            events.append(
                {
                    "event_type": event_type,
                    "event_code": event_code,
                    "timestamp": unpack_date(payload, offset + 4),
                }
            )

    return {
        "header": bytes(frame[0:5]).decode("ascii"),
        "length": length,
        "event_count": len(events),
        "events": events,
        "checksum": bytes(frame[-12:-10]),
        "end_terminator": bytes(frame[-10:]),
    }


def build_r005() -> bytes:
    return frame_formatter(R005)


def parse_d005(
    buffer: bytes | bytearray,
    *,
    verify_checksum: bool = False,
) -> dict[str, Any]:
    """Locate and parse a variable-length :D005 historical telemetry log frame.

    Unique validation strategy:
    1. Structural markers: ':D005' header, 'L' length marker, 'X' checksum marker,
       ':D005END\\r\\n' terminator, and per-record 'A'/'D' field markers.
    2. Record count cross-check: Adjusts for the protocol's 102-byte (0x66) vs.
       103-byte length-header scaling offset to verify the expected record count
       against the received payload length.
    3. Checksum handling: Validates the 'X' checksum marker by default without
       enforcing the modular byte sum, as multi-packet :D005 transfers can have
       interleaved status traffic (e.g., :S0400...) affect the running checksum.
    """
    frame = extract_response_frame(buffer, D005, frame_length=None, verify_checksum=False)

    if len(frame) < 22:
        raise ValueError(f"Frame too short ({len(frame)} bytes); expected at least 22 bytes")

    # Offset 5: lengthHeader ('L', 1s), length (I -> UINT32 LSB)
    length_header, declared_length = struct.unpack_from("<1sI", frame, 5)
    if length_header != b"L":
        raise ValueError(f"Invalid :D005 length marker: got {length_header!r}, expected b'L'")

    # Validate the 1-byte 'X' checksum designation right before the 10-byte ':D005END\r\n' footer
    if bytes(frame[-12:-11]) != CHECKSUM_HEADER:
        raise ValueError(
            f"Missing checksum marker 'X' on :D005 frame: got {bytes(frame[-12:-10]).hex(' ')}"
        )

    payload = frame[10:-12]

    # Empty log edge case: device sends 4-byte b"NULL" and checksum b"X\xff"
    if payload == b"NULL":
        if bytes(frame[-12:-10]) != CHECKSUM_HEADER + b"\xff":
            raise ValueError(
                f"Checksum mismatch on empty :D005 frame: got {bytes(frame[-12:-10]).hex(' ')}"
            )
        records: list[dict[str, Any]] = []
    else:
        if verify_checksum:
            verify_frame_checksum(frame)

        # Each record is 105 bytes on the wire (103 data bytes + 'A' and 'D' markers)
        if len(payload) % 105 != 0:
            raise ValueError(
                f"Invalid :D005 payload length ({len(payload)} bytes); expected multiple of 105"
            )
        record_size = 105

        actual_record_count = len(payload) // record_size

        # Protocol length-header scaling adjustment:
        # Each record consists of 103 unframed data bytes (6-byte timestamp + 97-byte payload)
        # plus 2 framing markers ('A' and 'D') added on the wire for 105 bytes total.
        # The protocol header calculates declared_length from unframed_bytes (103 * N) using:
        #     declared_length = ((unframed_bytes * 2) // 102) + unframed_bytes
        # Dividing by 102 instead of 103 inflates declared_length by ~2/102
        # (e.g., for 1,374 records: unframed=141,522, wire=144,270, declared=144,296).
        #
        # Invert that scaling factor to verify the expected record count:
        #     ceil((51 / 52) * (record_size / 103) * declared_length) / record_size
        # (51/52 reverses the 104/102 inflation back to unframed_bytes; record_size/103
        # scales unframed_bytes to wire payload bytes.)
        if declared_length > 0:
            estimated_payload_bytes = math.ceil((51 / 52) * (record_size / 103) * declared_length)
            expected_record_count = round(estimated_payload_bytes / record_size)
            if expected_record_count != actual_record_count:
                raise ValueError(
                    f"Record count mismatch on :D005 frame: header implies {expected_record_count} "
                    f"records (declared_length={declared_length}), but payload has "
                    f"{actual_record_count} records ({len(payload)} bytes)"
                )

        records = []
        for offset in range(0, len(payload), record_size):
            date_marker = payload[offset : offset + 1]
            data_marker = payload[offset + 7 : offset + 8]
            if date_marker != b"A" or data_marker != b"D":
                raise ValueError(
                    f"Invalid :D005 record markers at offset {offset}: {date_marker!r}, {data_marker!r}"
                )

            (raw_pack_v,) = struct.unpack_from("<I", payload, offset + 8)
            raw_cells = struct.unpack_from("<12H", payload, offset + 12)
            raw_load_v, load_power_w = struct.unpack_from("<Ii", payload, offset + 36)
            temp_int, temp_equ = struct.unpack_from("<hh", payload, offset + 44)
            temp_ext = list(struct.unpack_from("<4h", payload, offset + 48))
            (temp_ext_avg,) = struct.unpack_from("<h", payload, offset + 56)
            raw_gpio = struct.unpack_from("<5h", payload, offset + 58)
            soc, raw_load_i, raw_logic_i = struct.unpack_from("<hii", payload, offset + 68)
            (
                raw_coulomb,
                raw_n_coulomb,
                charge_cycles,
                raw_capacity_mah,
                equalization,
                bms_status,
            ) = struct.unpack_from("<QQii2sB", payload, offset + 78)

            record: dict[str, Any] = {
                "timestamp": unpack_date(payload, offset + 1),
                "pack_voltage_v": raw_pack_v / 1000.0,
                "cell_voltages_v": [mv / 1000.0 for mv in raw_cells],
                "load_voltage_v": raw_load_v / 1000.0,
                "load_power_w": load_power_w,
                "temp_int": temp_int,
                "temp_equ": temp_equ,
                "temp_ext": temp_ext,
                "temp_ext_avg": temp_ext_avg,
                "voltage_gpio_v": [mv / 1000.0 for mv in raw_gpio],
                "soc": soc,
                "load_current_a": raw_load_i / 1000.0,
                "logic_current_a": raw_logic_i / 1000.0,
                "coulomb_count_c": raw_coulomb / 1_000_000.0,
                "n_coulomb_count_c": raw_n_coulomb / 1_000_000.0,
                "charge_cycles": charge_cycles,
                "battery_capacity_ah": raw_capacity_mah / 1000.0,
                "equalization": equalization,
                "bms_status": bms_status,
                "mosfet_states": decode_bms_status(bms_status)
            }

            records.append(record)

    return {
        "header": bytes(frame[0:5]).decode("ascii"),
        "length": declared_length,
        "record_count": len(records),
        "records": records,
        "checksum": bytes(frame[-12:-10]),
        "end_terminator": bytes(frame[-10:]),
    }


def build_setd(year: int, month: int, day: int, hour: int, minute: int) -> bytes:
    """Build a :SETD command frame to set the device real-time clock."""
    if not (2000 <= year <= 2099):
        raise ValueError(f"Year out of nominal range (2000..2099): {year}")
    if not (1 <= month <= 12 and 1 <= day <= 31):
        raise ValueError(f"Invalid month/day: {month}/{day}")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid hour/minute: {hour}:{minute}")

    raw_payload = bytes([
        (year >> 8) & 0xFF,   # year high (big-endian)
        year & 0xFF,          # year low
        month,
        day,
        hour,
        minute,
    ])
    return frame_formatter(SETD + raw_payload)


def parse_setd(buffer: bytes | bytearray) -> dict[str, Any]:
    """Locate and validate a :SETDOK acknowledgment frame."""
    SETD_ACK = CMD_HEADER + SETD + b"OK" + CMD_FOOTER  # b":SETDOK\r\n"
    start = buffer.find(SETD_ACK)
    if start == -1:
        raise ValueError(f"Acknowledgment {SETD_ACK!r} not found in buffer")

    frame = bytes(buffer[start : start + len(SETD_ACK)])

    return {
        "header": bytes(frame[0:5]).decode("ascii"),
        "status": bytes(frame[5:7]).decode("ascii"),
        "end_terminator": bytes(frame[7:9]),
    }

