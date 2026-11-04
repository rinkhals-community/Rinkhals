import importlib.util
import struct
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / (
    'files/4-apps/home/rinkhals/apps/10-hostname-dns/mdns_responder.py'
)
spec = importlib.util.spec_from_file_location('testsupport.mdns_responder', MODULE_PATH)
mdns = importlib.util.module_from_spec(spec)
with mock.patch("logging.basicConfig"):
    spec.loader.exec_module(mdns)


class MdnsPacketTests(unittest.TestCase):
    def test_valid_compressed_name_retains_question_offset(self):
        name = mdns.encode_dns_name('printer.local')
        data = name + b'\xc0\x00' + b'\x00\x01\x00\x01'
        self.assertEqual(mdns.parse_dns_name(data, len(name)), ('printer.local', len(name) + 2))

    def test_invalid_names_are_rejected(self):
        cases = [
            b'\xc0',  # Missing second pointer byte.
            b'\xc0\xff',  # Pointer outside packet.
            b'\x04abc',  # Truncated label.
            b'\x03abc',  # Missing terminating zero.
            b'\x40\x00',  # Reserved label encoding.
            (b'\x3f' + b'a' * 63) * 4 + b'\x00',  # Name over 255 bytes.
        ]
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    mdns.parse_dns_name(data, 0)

    def test_pointer_cycles_are_rejected_without_hanging(self):
        # A subprocess deadline makes a regression fail instead of hanging the suite.
        code = (
            'import runpy; m = runpy.run_path(' + repr(str(MODULE_PATH)) + ')\n'
            'for data in (b"\\xc0\\x00", b"\\xc0\\x02\\xc0\\x00"):\n'
            '    try: m["parse_dns_name"](data, 0)\n'
            '    except ValueError: pass\n'
            '    else: raise AssertionError("cycle accepted")\n'
        )
        subprocess.run([sys.executable, '-c', code], check=True, timeout=2,
                       capture_output=True, text=True)

    def test_malformed_query_is_dropped_and_next_query_works(self):
        sock = mock.Mock()
        header = struct.pack('!HHHHHH', 0, 0, 1, 0, 0, 0)
        name = mdns.encode_dns_name('printer.local')
        with mock.patch.object(mdns, 'get_local_ip', return_value='192.168.1.12'):
            mdns.handle_query(header + b'\xc0', 'printer.local', name, sock)
            sock.sendto.assert_not_called()
            query = header + name + struct.pack('!HH', mdns.DNS_TYPE_A, mdns.DNS_CLASS_IN)
            mdns.handle_query(query, 'printer.local', name, sock)
        sock.sendto.assert_called_once_with(
            mdns.build_response(0, name, '192.168.1.12'),
            (mdns.MDNS_ADDR, mdns.MDNS_PORT),
        )


if __name__ == '__main__':
    unittest.main()
