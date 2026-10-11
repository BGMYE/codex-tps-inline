import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/codex-tps-inline/scripts'))
from cdp import CDPClient, masked_websocket_frame, read_websocket_frame, select_target, CDPError
import monitor


class Socket:
    def __init__(self, data): self.data = bytearray(data); self.sent = bytearray()
    def recv(self, size):
        result = self.data[:size]; del self.data[:size]; return bytes(result)
    def sendall(self, data): self.sent.extend(data)


class CDPTests(unittest.TestCase):
    def test_windows_thread_route_is_not_discarded_as_a_utility_page(self):
        main = {'type':'page', 'title':'ChatGPT',
                'url':'app://-/index.html?initialRoute=%2Flocal%2F00000000-0000-4000-8000-000000000001',
                'webSocketDebuggerUrl':'ws://127.0.0.1:9222/main'}
        utility = {**main, 'url':'app://-/index.html?initialRoute=%2Favatar-overlay'}
        with patch.object(monitor, 'devtools_targets', return_value=[main, utility]):
            self.assertEqual(monitor.pages_on_port(9222), [main])

    def test_mask_roundtrip_handles_all_length_encodings(self):
        for size in (0, 125, 126, 65535, 65536):
            payload = b'x' * size
            self.assertEqual(read_websocket_frame(Socket(masked_websocket_frame(payload))), (1, payload, True))

    def test_fragmented_reply_and_ping_are_not_lost(self):
        client = object.__new__(CDPClient)
        client.sock = Socket(b'\x01\x07{"id":1' + b'\x89\x01x' + b'\x80\x01}')
        self.assertEqual(client._recv_json(), {'id': 1})
        self.assertEqual(read_websocket_frame(Socket(client.sock.sent)), (10, b'x', True))

    def test_external_websocket_is_rejected_before_connect(self):
        with self.assertRaises(ValueError): CDPClient('ws://example.com:9222/devtools/page/1')

    def test_target_selection_ignores_browser_and_utility_windows(self):
        main = {'type':'page','title':'ChatGPT','url':'app://-/index.html','webSocketDebuggerUrl':'ws://127.0.0.1/main'}
        utility = {**main, 'url':'app://-/index.html?initialRoute=avatar-overlay'}
        browser = {**main, 'url':'https://chatgpt.com'}
        self.assertEqual(select_target([utility,browser,main]), main)
        with self.assertRaises(CDPError): select_target([browser])


if __name__ == '__main__': unittest.main()
