"""Wire-format helpers modelled on KnxScsGateTCP V6.0 Form1.frm.

Not KNXnet/IP. All addresses and telegrams are raw bytes from ESP KNX/SCS
gateway firmware. The VB6 monitor reads one length byte followed by that
many telegram bytes; @W sends at most 16 bytes, preceded by length.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

KIND_TO_CODE = {"LUCE": "1", "GEN": "11", "DIM": "4", "D+-": "24",
                "TAP": "8", "STO": "8", "UPD": "18"}
CODE_TO_KIND = {
    "1": "LUCE", "3": "DIM", "4": "DIM", "24": "D+-",
    "8": "TAP", "9": "TAP", "18": "UPD", "19": "UPD", "11": "GEN",
}
ACTIONS = ("ON", "OFF", "UP", "DOWN", "STOP", "MORE", "LESS")


@dataclass(frozen=True)
class Event:
    device_id: str
    protocol: str
    command: str
    action: str
    kind_hint: str
    telegram: bytes
    command_source: bool = True


class LengthFramer:
    """Incremental length-byte parser; keeps incomplete reads between polls."""

    def __init__(self, max_frame: int = 64):
        self.buffer = bytearray()
        self.max_frame = max_frame

    def feed(self, data: bytes) -> list[bytes]:
        self.buffer.extend(data)
        frames = []
        while self.buffer:
            size = self.buffer[0]
            if size == 0x6B:  # ASCII 'k' ACK after @W on some versions
                del self.buffer[0]
                continue
            if size < 7 or size > self.max_frame:
                del self.buffer[0]
                continue
            if len(self.buffer) < size + 1:
                break
            frames.append(bytes(self.buffer[1:size + 1]))
            del self.buffer[:size + 1]
        if len(self.buffer) > 4096:
            self.buffer.clear()
        return frames


def decode_telegram(frame: bytes, known_kind: str = "") -> Event | None:
    if len(frame) >= 7 and frame[0] == 0xA8 and frame[6] == 0xA3:
        dest, origin, network, cmd = frame[1:5]
        is_command = origin == 0
        if not is_command and dest != 0xB8:
            return None
        address = dest if is_command else origin
        device_id = f"{network:02X}{address:02X}"
        action = {0: "ON", 1: "OFF", 3: "MORE", 4: "LESS"}.get(cmd, "")
        return Event(device_id, "SCS", f"{cmd:02X}", action,
                     "DIM" if cmd in (3, 4) else "LUCE", frame, is_command)

    if len(frame) < 9 or frame[0] not in (0xB4, 0xB8, 0xBC):
        return None
    command_length = frame[5] & 0x0F
    if command_length < 1 or 8 + command_length > len(frame):
        return None
    network, destination = frame[3], frame[4]
    long_press = destination % 2 == 0
    normal_destination = destination - 1 if long_press else destination
    device_id = f"{network:02X}{normal_destination:02X}"
    payload = frame[7:7 + command_length]
    action, hint = "", ""
    if command_length == 1:
        cmd = payload[0]
        if long_press:
            if known_kind == "DIM":
                action = {0x80: "ON", 0x81: "LESS", 0x88: "ON",
                          0x89: "MORE"}.get(cmd, "")
                hint = "DIM"
            else:
                action = {0x80: "UP", 0x81: "DOWN", 0x88: "ON",
                          0x89: "MORE"}.get(cmd, "")
                hint = "DIM" if cmd in (0x88, 0x89) else "TAP"
        else:
            action = {0x80: "OFF", 0x81: "ON"}.get(cmd, "")
            hint = "" if known_kind else "LUCE"
            if known_kind in ("TAP", "STO") and cmd in (0x80, 0x81):
                action = "STOP"
    return Event(device_id, "KNX", payload.hex(" ").upper(), action, hint,
                 frame, True)


def complement(event: Event) -> tuple[str, bytes] | None:
    """VB6 XOR complement, for known one-byte actions only.

    Values are derived from an observed telegram. Never fabricate a checksum
    without one, or infer UP/DOWN STOP from frames not observed.
    """
    raw = event.telegram
    flip = {"ON": "OFF", "OFF": "ON", "UP": "DOWN",
            "DOWN": "UP", "MORE": "LESS", "LESS": "MORE"}
    other = flip.get(event.action)
    if not other or not event.command_source:
        return None
    if event.protocol == "SCS" and len(raw) == 7:
        delta = 7 if event.action in ("MORE", "LESS") else 1
        if raw[4] not in (0, 1, 3, 4):
            return None
        return other, raw[:4] + bytes((raw[4] ^ delta, raw[5] ^ delta)) + raw[6:]
    if event.protocol == "KNX" and len(raw) == 9 and (raw[5] & 0x0F) == 1:
        if raw[7] not in (0x80, 0x81):
            return None
        return other, raw[:7] + bytes((raw[7] ^ 1, raw[8] ^ 1))
    return None


def write_telegram(telegram: bytes) -> bytes:
    """VB6 writeTlg: @W + length(1 byte) + up to 16 bytes."""
    if not 1 <= len(telegram) <= 16:
        raise ValueError("Il telegramma deve contenere 1-16 byte")
    return b"@W" + bytes((len(telegram),)) + telegram


def device_type_code(kind: str, gate: str, cover_percentage: bool = False) -> str:
    kind = kind.upper()
    if kind == "DIM":
        return "3" if gate == "SCS" else "4"
    if kind in ("TAP", "STO"):
        return "9" if cover_percentage else "8"
    if kind == "UPD":
        return "19" if cover_percentage else "18"
    if kind not in KIND_TO_CODE:
        raise ValueError(f"Tipo dispositivo sconosciuto: {kind}")
    return KIND_TO_CODE[kind]


def format_command(command: str, payload: dict) -> bytes:
    """Firmware command is an ASCII verb + a compact JSON object."""
    if not re.fullmatch(r"#[a-z]+", command):
        raise ValueError("Comando non valido")
    return (command + " " + json.dumps(payload, ensure_ascii=True,
                                      separators=(",", ":"))).encode("ascii")


def parse_device_response(response: bytes | str) -> dict | None:
    text = response.decode("utf-8", "replace") if isinstance(response, bytes) else response
    if "#eof" in text.lower():
        return None
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and "device" in obj:
        return {key: str(value) for key, value in obj.items()}
    return None
