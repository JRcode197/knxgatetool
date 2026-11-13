import unittest
from knxgatetool.protocol import (
    LengthFramer, complement, decode_telegram, device_type_code,
    format_command, parse_device_response, write_telegram,
)

class ProtocolTests(unittest.TestCase):
    def test_vb6_knx_sample(self):
        raw = bytes.fromhex("B4 10 0E 0B 1D E1 00 81 23")
        event = decode_telegram(raw)
        self.assertEqual(event.device_id, "0B1D")
        self.assertEqual(event.protocol, "KNX")
        self.assertEqual(event.action, "ON")
        kind, swapped = complement(event)
        self.assertEqual(kind, "OFF")
        self.assertEqual(swapped.hex(" ").upper(), "B4 10 0E 0B 1D E1 00 80 22")

    def test_knx_long_press(self):
        raw = bytes.fromhex("B4 10 0E 0B 1C E1 00 80 23")
        event = decode_telegram(raw)
        self.assertEqual(event.device_id, "0B1B")
        self.assertEqual(event.action, "UP")

    def test_scs_light_and_complement(self):
        raw = bytes.fromhex("A8 2A 00 12 00 7C A3")
        event = decode_telegram(raw)
        self.assertEqual(event.device_id, "122A")
        self.assertEqual(event.action, "ON")
        self.assertEqual(complement(event)[1],
                         bytes.fromhex("A8 2A 00 12 01 7D A3"))

    def test_scs_status_is_not_transmitted(self):
        event = decode_telegram(bytes.fromhex("A8 B8 2A 12 01 7D A3"))
        self.assertEqual(event.device_id, "122A")
        self.assertFalse(event.command_source)
        self.assertIsNone(complement(event))

    def test_fragments_and_coalescing(self):
        first = bytes.fromhex("B4 10 0E 0B 1D E1 00 81 23")
        second = bytes.fromhex("A8 2A 00 12 00 7C A3")
        parser = LengthFramer()
        self.assertEqual(parser.feed(bytes([len(first)]) + first[:2]), [])
        self.assertEqual(parser.feed(first[2:] + b"k" +
                                     bytes([len(second)]) + second),
                         [first, second])

    def test_packet_building(self):
        self.assertEqual(write_telegram(b"\x01\x02"),
                         b"@W\x02\x01\x02")
        with self.assertRaises(ValueError):
            write_telegram(b"\x01" * 17)
        self.assertEqual(format_command("#getdevice", {"devnum": "1"}),
                         b'#getdevice {"devnum":"1"}')

    def test_device_response(self):
        self.assertEqual(parse_device_response(
            '#ok {"device":"0EA1","type":"1","maxp":"0","descr":"Ingresso"}'),
            {"device": "0EA1", "type": "1", "maxp": "0", "descr": "Ingresso"})
        self.assertIsNone(parse_device_response("#eof"))
        self.assertIsNone(parse_device_response('#ok {"device":'))

    def test_type_mapping(self):
        self.assertEqual(device_type_code("DIM", "SCS"), "3")
        self.assertEqual(device_type_code("DIM", "KNX"), "4")
        self.assertEqual(device_type_code("TAP", "KNX", True), "9")

if __name__ == "__main__":
    unittest.main()
