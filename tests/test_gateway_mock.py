"""End-to-end TCP session against a simple gateway simulator; no real bus."""
import socket
import threading
import time
import unittest

from PySide6.QtCore import QCoreApplication

from knxgatetool.gateway import GatewayWorker


class GatewayMockTest(unittest.TestCase):
    def test_connect_download_and_monitor(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        errors = []
        received_from_client = []

        def serve():
            try:
                conn, _ = server.accept()
                conn.settimeout(6)
                with conn:
                    expected = [
                        (b'#setup {"uart":"tcp"}', b"#ok"),
                        (b"@q", b"qkKNXsim 1.0"),
                        (b'#getdevice {"devnum":"1"}',
                         b'#ok {"device":"0EA1","type":"1","maxp":"0","descr":"Luce"}'),
                        (b'#getdevice {"devnum":"2"}', b"#eof"),
                        (b"@\x16", b"k"), (b"@MX", b"k"), (b"@F0", b"k"),
                        (b"@b", b"k"), (b"@Y0", b"k"), (b"@l", b"k"),
                    ]
                    for command, reply in expected:
                        incoming = conn.recv(4096)
                        received_from_client.append(incoming)
                        if incoming != command:
                            raise AssertionError(
                                f"expected {command!r}, got {incoming!r}")
                        conn.sendall(reply)
                    time.sleep(0.35)
                    frame = bytes.fromhex("B4 10 0E 0B 1D E1 00 81 23")
                    conn.sendall(bytes([len(frame)]) + frame[:3])
                    time.sleep(0.08)
                    conn.sendall(frame[3:])
                    incoming = conn.recv(4096)
                    received_from_client.append(incoming)
                    if incoming != b"@W\x02\x01\x02":
                        raise AssertionError(f"Expected @W, got {incoming!r}")
                    conn.sendall(b"k")
                    time.sleep(0.3)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                server.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        worker = GatewayWorker()
        connections = []
        downloaded = []
        frames = []
        failures = []
        monitors = []
        worker.connected.connect(lambda firmware, gate: connections.append((firmware, gate)))
        worker.download_ready.connect(lambda devices: downloaded.extend(devices))
        worker.received.connect(frames.append)
        worker.failure.connect(failures.append)
        worker.monitoring.connect(monitors.append)
        worker.start()

        def await_condition(predicate, seconds=8):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                app.processEvents()
                if predicate():
                    return True
                time.sleep(0.02)
            return False

        try:
            worker.submit("connect", {"mode": "TCP", "host": "127.0.0.1",
                                      "port": port})
            self.assertTrue(await_condition(lambda: len(connections) > 0),
                            failures)
            self.assertEqual(connections[0][1], "KNX")
            worker.submit("download")
            self.assertTrue(await_condition(lambda: bool(downloaded)), failures)
            self.assertEqual(downloaded[0]["device"], "0EA1")
            worker.submit("start_monitor", "bus")
            self.assertTrue(await_condition(lambda: True in monitors), failures)
            self.assertTrue(await_condition(lambda: len(frames) > 0), failures)
            self.assertEqual(frames[0].hex().upper(), "B4100E0B1DE1008123")
            worker.submit("send", b"\x01\x02")
            self.assertTrue(await_condition(lambda: len(received_from_client) >= 11),
                            failures)
            self.assertFalse(errors, errors)
            self.assertFalse(failures, failures)
        finally:
            worker.shutdown()
            self.assertTrue(worker.wait(3000), "Worker non terminato")
            thread.join(1)


if __name__ == "__main__":
    unittest.main()
