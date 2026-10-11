from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-tps-inline/scripts"))
import monitor


class MonitorTests(unittest.TestCase):
    def check_enabled(self, enabled):
        thread = "00000000-0000-4000-8000-000000000001"
        client = MagicMock()
        client.evaluate.side_effect = [{"thread_id":thread, "enabled":enabled},
            {"ok":True, "rendered":int(enabled), "enabled":enabled, "toggle_rendered":True}]
        page = {"id":"test-page", "webSocketDebuggerUrl":"ws://127.0.0.1:9222/test"}
        with tempfile.TemporaryDirectory() as directory, patch.object(monitor, "STATE", Path(directory)), \
             patch.object(monitor.sys, "argv", ["monitor.py", "--once"]), \
             patch.object(monitor, "available_pages", return_value=(9222,[page])), \
             patch.object(monitor, "CDPClient", return_value=client), patch.object(monitor, "Catalog") as catalog, \
             redirect_stdout(io.StringIO()):
            catalog.return_value.poll.return_value = [{"thread_id":thread, "turns":[]}]
            self.assertEqual(monitor.main(), 0)
            state = json.loads((Path(directory) / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(state["diagnostics"][0]["stage"], "rendered" if enabled else "disabled")
            self.assertEqual(catalog.return_value.poll.call_count, int(enabled))

    def test_button_off_skips_token_log_polling(self): self.check_enabled(False)
    def test_button_on_resumes_token_log_polling(self): self.check_enabled(True)


if __name__ == "__main__": unittest.main()
