"""Persistent, user-editable device registry."""
from __future__ import annotations

from dataclasses import dataclass, field
import csv
import io
import json
from pathlib import Path
import re

from .protocol import ACTIONS, CODE_TO_KIND, Event, complement

HEX_ID = re.compile(r"^[0-9A-Fa-f]{2,4}$")
VALID_KINDS = ("LUCE", "DIM", "D+-", "TAP", "STO", "UPD", "GEN")


def clean_id(value: object) -> str:
    text = str(value).strip().replace("0x", "").replace("0X", "").replace(" ", "")
    if not HEX_ID.fullmatch(text):
        raise ValueError(f"ID non valido: {value!r}")
    return text.upper().zfill(4)


@dataclass
class Device:
    id: str
    name: str = ""
    category: str = "Altro"
    kind: str = "LUCE"
    maxp: str = "0"
    status: str = ""
    last_command: str = ""
    telegrams: dict[str, str] = field(default_factory=dict)
    inferred: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.id = clean_id(self.id)
        self.kind = str(self.kind).upper()
        if self.kind not in VALID_KINDS:
            self.kind = "GEN"
        self.name = str(self.name)
        self.category = str(self.category or "Altro")
        self.maxp = str(self.maxp or "0")

    @classmethod
    def from_mapping(cls, data: dict) -> "Device":
        addr = data.get("id") or data.get("ID") or data.get("device") or data.get("indirizzo")
        if addr is None:
            line, address = data.get("line"), data.get("address")
            if line and address:
                addr = str(line).zfill(2) + str(address).zfill(2)
        kind = data.get("kind") or data.get("tipo") or data.get("type") or "LUCE"
        kind = CODE_TO_KIND.get(str(kind), str(kind).upper())
        if kind in ("SWITCH", "LIGHT", "LIGHTS"):
            kind = "LUCE"
        return cls(
            id=clean_id(addr),
            name=data.get("name") or data.get("nome") or data.get("descr") or "",
            category=data.get("category") or data.get("categoria") or "Altro",
            kind=kind,
            maxp=data.get("maxp") or "0",
            status=data.get("status") or "",
            last_command=data.get("last_command") or "",
            telegrams=dict(data.get("telegrams") or {}),
            inferred=list(data.get("inferred") or []),
        )

    def to_mapping(self) -> dict:
        return {"id": self.id, "name": self.name, "category": self.category,
                "kind": self.kind, "maxp": self.maxp, "status": self.status,
                "last_command": self.last_command,
                "telegrams": self.telegrams, "inferred": self.inferred}

    def learn(self, event: Event) -> None:
        self.last_command = event.command
        if event.action:
            self.status = event.action
        if event.kind_hint and self.kind in ("GEN", "LUCE") and event.kind_hint != "LUCE":
            self.kind = event.kind_hint
        if not event.command_source or not event.action:
            return
        if event.action in ACTIONS:
            self.telegrams[event.action] = event.telegram.hex().upper()
            if event.action in self.inferred:
                self.inferred.remove(event.action)
        sibling = complement(event)
        if sibling:
            action, payload = sibling
            if action not in self.telegrams:
                self.telegrams[action] = payload.hex().upper()
                if action not in self.inferred:
                    self.inferred.append(action)

    def command_bytes(self, action: str) -> bytes:
        if action not in self.telegrams:
            raise ValueError(f"Nessun telegramma {action} acquisito per {self.id}")
        try:
            telegram = bytes.fromhex(self.telegrams[action])
        except ValueError as exc:
            raise ValueError("Telegramma memorizzato non valido") from exc
        if not 1 <= len(telegram) <= 16:
            raise ValueError("Lunghezza telegramma memorizzato non valida")
        return telegram


class Registry:
    def __init__(self) -> None:
        self.devices: dict[str, Device] = {}

    def upsert(self, device: Device) -> Device:
        previous = self.devices.get(device.id)
        if previous:
            if not device.telegrams:
                device.telegrams = previous.telegrams
                device.inferred = previous.inferred
            if not device.name:
                device.name = previous.name
            if device.category == "Altro" and previous.category != "Altro":
                device.category = previous.category
        self.devices[device.id] = device
        return device

    def observe(self, event: Event) -> Device:
        device = self.devices.get(event.device_id)
        if device is None:
            device = Device(event.device_id, kind=event.kind_hint or "GEN")
            self.devices[device.id] = device
        device.learn(event)
        return device

    def values(self) -> list[Device]:
        return [self.devices[key] for key in sorted(self.devices)]

    def export(self, path: Path) -> None:
        payload = {"format": "KNXGateTool", "version": 1,
                   "devices": [dev.to_mapping() for dev in self.values()]}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    def import_json(self, path: Path) -> int:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            source = payload
        elif isinstance(payload, dict):
            source = payload.get("devices", payload.get("dispositivi"))
            if isinstance(source, dict):
                source = [{"id": key, **value} for key, value in source.items()]
        else:
            source = None
        if not isinstance(source, list):
            raise ValueError("Il file JSON deve contenere una lista 'devices' o 'dispositivi'")
        parsed = [Device.from_mapping(x) for x in source]
        for device in parsed:
            self.upsert(device)
        return len(parsed)

    def import_legacy(self, path: Path) -> int:
        """VB6 Print #/Input # uses quoted CSV with a dimensions header.

        Header: number of data rows, maximum column index. Each data row
        contains column values and one trailing empty value.
        """
        text = path.read_text(encoding="cp1252")
        rows = list(csv.reader(io.StringIO(text), skipinitialspace=True))
        if not rows or len(rows[0]) < 2:
            raise ValueError("Intestazione VB6 non valida")
        row_count, last_col = int(rows[0][0]), int(rows[0][1])
        if row_count > 2000 or last_col < 4:
            raise ValueError("Dimensioni VB6 non valide")
        entries = []
        for row in rows[2:row_count + 2]:
            fields = row + [""] * max(0, last_col + 1 - len(row))
            line, address = fields[0].strip(), fields[1].strip()
            if not address:
                continue
            entries.append(Device(
                id=clean_id((line or "00") + address),
                name=fields[4].strip(), kind=fields[3].strip() or "GEN",
                maxp=fields[11].strip() if len(fields) > 11 else "0"))
        for dev in entries:
            self.upsert(dev)
        return len(entries)
