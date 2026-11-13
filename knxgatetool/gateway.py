"""Asynchronous gateway connection, serialization and configuration operations.

All socket/serial I/O lives in a worker thread. Qt widgets never do blocking I/O.
TCP commands follow the ESP gateway's proprietary #verb JSON protocol.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import queue
import socket
import threading
import time

from PySide6.QtCore import QThread, Signal

from .protocol import format_command, parse_device_response, write_telegram


class GatewayWorker(QThread):
    connected = Signal(str, str)        # firmware, SCS/KNX/UNKNOWN
    disconnected = Signal()
    monitoring = Signal(bool)
    received = Signal(bytes)
    log_line = Signal(str)
    failure = Signal(str)
    progress = Signal(str)
    download_ready = Signal(object)     # list of decoded device records
    upload_complete = Signal(str)       # backup location

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tasks: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stopping = threading.Event()
        self.connection = None
        self.connection_mode = ""
        self.monitor_mode = ""
        self.protocol = "UNKNOWN"
        self.config: dict = {}
        self._incoming = bytearray()
        self._frame_buffer = bytearray()

    def submit(self, action: str, payload=None) -> None:
        self.tasks.put((action, payload))

    def shutdown(self) -> None:
        self.stopping.set()
        self.submit("quit")

    def run(self) -> None:
        while not self.stopping.is_set():
            try:
                task, payload = self.tasks.get(timeout=0.06)
            except queue.Empty:
                task = ""
                payload = None
            if task:
                try:
                    self._execute(task, payload)
                except Exception as exc:
                    self.failure.emit(f"{task}: {exc}")
                    self.log_line.emit(f"ERRORE: {task}: {exc}")
                    if task in ("connect", "start_monitor", "stop_monitor"):
                        self._disconnect()
            if self.monitor_mode and self.connection:
                try:
                    chunk = self._read_raw()
                    if chunk:
                        self._consume_monitor(chunk)
                except (ConnectionError, OSError, EOFError) as exc:
                    self.failure.emit(f"Connessione interrotta: {exc}")
                    self._disconnect()
        self._disconnect()

    def _execute(self, task: str, payload) -> None:
        if task == "quit":
            return
        if task == "connect":
            self._disconnect()
            self.config = dict(payload)
            self._connect()
        elif task == "disconnect":
            self._disconnect()
        elif task == "query":
            self._require_connection()
            if self.monitor_mode:
                raise ValueError("Arrestare il monitor prima di interrogare il firmware")
            firmware, gate = self._query_firmware()
            self.protocol = gate
            self.connected.emit(firmware, gate)
        elif task == "start_monitor":
            self._require_connection()
            self._start_monitor(str(payload or "bus"))
        elif task == "stop_monitor":
            self._require_connection()
            if self.monitor_mode:
                # The V6 monitor has no documented exit command. Reconnect cleanly.
                self._disconnect()
                self._connect()
        elif task == "download":
            self._require_idle()
            data = self._download()
            self.download_ready.emit(data)
        elif task == "upload":
            self._require_idle()
            records, gate, cover, backup_path = payload
            self._upload(records, gate, cover, Path(backup_path))
        elif task == "frequency":
            self._require_idle()
            value = str(payload)
            if value not in ("80", "160"):
                raise ValueError("Frequenza ammessa: 80 o 160 MHz")
            self._send(format_command("#setup", {"frequency": value}))
            answer = self._read_response()
            if not self._is_ok(answer):
                raise ConnectionError(f"Setup frequenza non confermato: {answer!r}")
            self.log_line.emit(f"Frequenza impostata: {value} MHz")
        elif task == "send":
            self._require_connection()
            if self.monitor_mode != "bus":
                raise ValueError("Avviare il monitor telegrammi prima di inviare comandi")
            frame = write_telegram(bytes(payload))
            self._send(frame)
            self.log_line.emit("TX  " + frame.hex(" ").upper())
        else:
            raise ValueError(f"Operazione sconosciuta: {task}")

    def _connect(self) -> None:
        mode = self.config.get("mode", "TCP")
        if mode == "TCP":
            host = str(self.config.get("host", "")).strip()
            port = int(self.config.get("port", 5045))
            if not host or not 1 <= port <= 65535:
                raise ValueError("Host o porta non validi")
            self.connection = socket.create_connection((host, port), timeout=5)
            self.connection.settimeout(0.12)
            self.connection_mode = "TCP"
            self.log_line.emit(f"TCP connesso a {host}:{port}")
            self._send(format_command("#setup", {"uart": "tcp"}))
            answer = self._read_response(timeout=2)
            self.log_line.emit("UART TCP: " + answer.decode("utf-8", "replace")[:160])
        else:
            import serial

            port = str(self.config.get("serial_port", "")).strip()
            if not port:
                raise ValueError("Seleziona la porta seriale")
            baud = int(self.config.get("baud", 115200))
            self.connection = serial.Serial(port, baudrate=baud, timeout=0.12, write_timeout=2)
            self.connection_mode = "SERIAL"
            self.log_line.emit(f"Seriale connessa a {port} @ {baud}")
        self.monitor_mode = ""
        self._incoming.clear()
        self._frame_buffer.clear()
        try:
            firmware, gate = self._query_firmware()
            self.protocol = gate
            self.connected.emit(firmware, gate)
        except Exception:
            self._disconnect()
            raise

    def _query_firmware(self) -> tuple[str, str]:
        self._send(b"@q")
        answer = self._read_response(timeout=2.5).decode("latin-1", "replace")
        # Original tool accepts qk... (echo) and k...
        if answer.startswith("qk"):
            answer = answer[1:]
        pos = answer.find("k")
        if pos < 0:
            raise ConnectionError(f"Il gateway non ha risposto a @q: {answer[:140]!r}")
        firmware = answer[pos + 1:].strip() or "(versione non comunicata)"
        gate = "KNX" if firmware.upper().startswith("KNX") else "SCS"
        self.log_line.emit(f"Firmware: {firmware}, modalità {gate}")
        return firmware, gate

    def _require_connection(self) -> None:
        if self.connection is None:
            raise ConnectionError("Gateway non collegato")

    def _require_idle(self) -> None:
        self._require_connection()
        if self.monitor_mode:
            raise ValueError("Arrestare il monitor prima di trasferire la configurazione")
        if self.connection_mode != "TCP":
            raise ValueError("Le operazioni #getdevice/#putdevice richiedono TCP")

    def _start_monitor(self, mode: str) -> None:
        if self.monitor_mode:
            return
        if mode == "ascii":
            self._send(b"@MA")
            answer = self._read_response(timeout=2)
            self.log_line.emit("Monitor ASCII: " + answer.hex(" ").upper())
            self.monitor_mode = "ascii"
            self.monitoring.emit(True)
            return
        for command in (b"@\x16", b"@MX", b"@F0", b"@b", b"@Y0", b"@l"):
            self._send(command)
            answer = self._read_response(timeout=2)
            if b"k" not in answer:
                raise ConnectionError(
                    f"Handshake monitor fallito ({command!r}): {answer[:80]!r}"
                )
            self.log_line.emit("Handshake OK: " + command.hex(" ").upper())
        self.monitor_mode = "bus"
        self._incoming.clear()
        self._frame_buffer.clear()
        self.monitoring.emit(True)
        self.log_line.emit("Monitor telegrammi avviato")

    def _download(self, *, quiet: bool = False) -> list[dict]:
        result = []
        for index in range(1, 513):
            if self.stopping.is_set():
                raise InterruptedError("Operazione annullata")
            self._send(format_command("#getdevice", {"devnum": str(index)}))
            response = self._read_response(timeout=2.2)
            if b"#eof" in response.lower():
                if not quiet:
                    self.log_line.emit(f"Download terminato: {len(result)} dispositivi")
                return result
            record = parse_device_response(response)
            if record is None:
                raise ConnectionError(f"Risposta getdevice {index} non valida: {response[:180]!r}")
            result.append(record)
            if not quiet and index % 10 == 0:
                self.progress.emit(f"Download: {index} dispositivi")
        raise RuntimeError("Limite di sicurezza: 512 dispositivi senza #eof")

    def _upload(self, records: list[dict], gate: str,
                cover: bool, backup_path: Path) -> None:
        from .protocol import device_type_code
        if gate not in ("KNX", "SCS"):
            raise ValueError("Identificare prima il tipo di gateway KNX o SCS")
        if not records:
            raise ValueError("Non è consentito caricare una configurazione vuota")
        if len(records) > 512:
            raise ValueError("Troppi dispositivi (massimo 512)")
        # Validate before sending even the first destructive command.
        encoded = []
        for record in records:
            addr = str(record["id"]).upper()
            if len(addr) != 4 or any(x not in "0123456789ABCDEF" for x in addr):
                raise ValueError(f"ID di dispositivo non valido: {addr}")
            if len(str(record.get("name", ""))) > 80:
                raise ValueError(f"Descrizione troppo lunga: {addr}")
            payload = {
                "device": addr if gate == "KNX" else addr[-2:],
                "type": device_type_code(str(record["kind"]), gate, cover),
                "maxp": str(record.get("maxp") or "0"),
                "descr": str(record.get("name") or "")}
            encoded.append(format_command("#putdevice", payload))
        self.progress.emit("Backup della configurazione remota prima della scrittura...")
        remote = self._download(quiet=True)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(json.dumps({
            "format": "knxgatetool-remote-backup",
            "created_at": datetime.now().astimezone().isoformat(),
            "gateway": self.config.get("host", self.config.get("serial_port", "")),
            "devices": remote}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.log_line.emit(f"Backup gateway salvato: {backup_path}")

        # VB6 V6 starts by clearing the remote list; each next command needs #ok.
        self._send(format_command("#putdevice",
                                  {"coverpct": "true" if cover else "false",
                                   "devclear": "true"}))
        response = self._read_response()
        if not self._is_ok(response):
            raise ConnectionError(f"Cancellazione remota non confermata: {response[:120]!r}")

        for i, command in enumerate(encoded, 1):
            if self.stopping.is_set():
                raise InterruptedError("Upload interrotto; ripristino manuale necessario")
            self._send(command)
            response = self._read_response()
            if not self._is_ok(response):
                raise ConnectionError(
                    f"Upload parziale al dispositivo {i}/{len(encoded)}: {response[:160]!r}")
            if i % 10 == 0:
                self.progress.emit(f"Upload: {i}/{len(encoded)}")
        self._send(format_command("#setup", {"commit": "true"}))
        response = self._read_response()
        if not self._is_ok(response):
            raise ConnectionError(f"Commit non confermato: {response[:160]!r}")
        self.upload_complete.emit(str(backup_path))

    @staticmethod
    def _is_ok(data: bytes) -> bool:
        return data.lstrip().lower().startswith(b"#ok")

    def _send(self, raw: bytes) -> None:
        self._require_connection()
        if self.connection_mode == "TCP":
            self.connection.sendall(raw)
        else:
            self.connection.write(raw)

    def _read_raw(self) -> bytes:
        if self.connection_mode == "TCP":
            try:
                data = self.connection.recv(512)
            except socket.timeout:
                return b""
            if not data:
                raise EOFError("Socket TCP chiuso dal gateway")
            return data
        return self.connection.read(512)

    def _read_response(self, timeout: float = 2.0) -> bytes:
        """Accumulate raw reply until an idle gap, without assuming TCP packet boundaries."""
        data = bytearray()
        deadline = time.monotonic() + timeout
        last = None
        while not self.stopping.is_set() and time.monotonic() < deadline:
            chunk = self._read_raw()
            if chunk:
                data.extend(chunk)
                last = time.monotonic()
                if len(data) > 65536:
                    raise RuntimeError("Risposta del gateway eccessiva")
            elif last is not None and time.monotonic() - last > 0.20:
                break
        return bytes(data)

    def _consume_monitor(self, chunk: bytes) -> None:
        if self.monitor_mode == "ascii":
            self.log_line.emit("RX ASCII " + chunk.decode("latin-1", "replace").rstrip())
            return
        self._frame_buffer.extend(chunk)
        while self._frame_buffer:
            size = self._frame_buffer[0]
            if size == 0x6B:  # acknowledgement
                del self._frame_buffer[0]
                continue
            if size < 7 or size > 64:
                self.log_line.emit(f"RX byte non incorniciato: {size:02X}")
                del self._frame_buffer[0]
                continue
            if len(self._frame_buffer) < size + 1:
                break
            frame = bytes(self._frame_buffer[1:size + 1])
            del self._frame_buffer[:size + 1]
            self.received.emit(frame)
        if len(self._frame_buffer) > 4096:
            self._frame_buffer.clear()
            self.log_line.emit("Buffer monitor azzerato per dimensioni anomale")

    def _disconnect(self) -> None:
        was_open = self.connection is not None
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
        self.connection = None
        self.monitor_mode = ""
        self._incoming.clear()
        self._frame_buffer.clear()
        if was_open:
            self.monitoring.emit(False)
            self.disconnected.emit()
