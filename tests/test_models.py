import json
from pathlib import Path
import tempfile
import unittest
from knxgatetool.models import Device, Registry, clean_id
from knxgatetool.protocol import decode_telegram

class RegistryTests(unittest.TestCase):
    def test_device_name_category(self):
        d = Device.from_mapping({
            "ID": "0EA1", "nome": "Apri Porta Ingresso",
            "categoria": "Luci", "tipo": "switch"})
        self.assertEqual(d.id, "0EA1")
        self.assertEqual(d.name, "Apri Porta Ingresso")
        self.assertEqual(d.category, "Luci")
        self.assertEqual(d.kind, "LUCE")

    def test_bad_id(self):
        for value in ("12345", "NOPE", "", "  "):
            with self.assertRaises(ValueError):
                clean_id(value)

    def test_capture_and_json_roundtrip(self):
        registry = Registry()
        sample = bytes.fromhex("B4 10 0E 0B 1D E1 00 81 23")
        device = registry.observe(decode_telegram(sample))
        self.assertEqual(device.status, "ON")
        self.assertIn("OFF", device.inferred)
        self.assertEqual(device.command_bytes("OFF")[-2:], b"\x80\x22")
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "ByMe_Lab_dispositivi.json"
            registry.export(destination)
            copy = Registry()
            self.assertEqual(copy.import_json(destination), 1)
            self.assertEqual(copy.devices["0B1D"].command_bytes("OFF"),
                             device.command_bytes("OFF"))

    def test_import_does_not_destroy_learnt_commands(self):
        registry = Registry()
        d = registry.observe(decode_telegram(
            bytes.fromhex("B4 10 0E 0B 1D E1 00 81 23")))
        registry.upsert(Device("0B1D", name="Ingresso", category="Luci"))
        self.assertEqual(registry.devices["0B1D"].name, "Ingresso")
        self.assertEqual(registry.devices["0B1D"].telegrams, d.telegrams)

    def test_import_legacy_sample(self):
        header = ",".join(f'"{item}"' for item in [
            "Line", "Adrs", "Sub", "Tipo", "Device name", "last cmd",
            "Status", "CLK", "COM", "MANDS", "", "maxP"])
        item = ",".join(f'"{value}"' for value in [
            "0E", "A1", "", "LUCE", "Apri Porta Ingresso",
            "", "", "", "", "", "", "0"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.txt"
            path.write_text("1,11\n" + header + ",\n" + item + ",\n",
                            encoding="cp1252")
            registry = Registry()
            self.assertEqual(registry.import_legacy(path), 1)
            self.assertEqual(registry.devices["0EA1"].name, "Apri Porta Ingresso")

    def test_export_structure(self):
        registry = Registry()
        registry.upsert(Device("0EA1", name="Luce Ingresso", category="Luci"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.json"
            registry.export(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["devices"][0]["id"], "0EA1")
            self.assertEqual(payload["version"], 1)

if __name__ == "__main__":
    unittest.main()
