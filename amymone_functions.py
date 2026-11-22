#!/usr/bin/env python3

# Command library
R001 = b"R001"
R002 = b"R002"
R003 = b"R003"
R004 = b"R004"
R005 = b"R005"
SETD = b"SETD"

# Command constants
CMD_PREAMBLE = b":"
CMD_POSTAMBLE = b"\r\n"

def bms_crc32(data: bytes) -> int:
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


def frame_formatter(raw_frame: bytes) -> bytes:
    """Escape intentional 0x0D bytes and append the CRLF frame terminator."""
    escaped_payload = raw_frame.replace(b'\r', b'\r\r')
    return CMD_PREAMBLE + escaped_payload + CMD_POSTAMBLE


def build_r001() -> bytes:
    return frame_formatter(R001)


def build_r002() -> bytes:
    return frame_formatter(R002)


def build_r003() -> bytes:
    return frame_formatter(R003)


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
