import json
from types import SimpleNamespace
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/codex-tps-inline/scripts"
sys.path.insert(0, str(SCRIPTS))
import control
from cdp import CDPError


class ControlTests(unittest.TestCase):
    def test_restart_waits_for_old_monitor_exit_before_clearing_stop_marker(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, "STATE", Path(directory)), \
             patch.object(control, "monitor_alive", side_effect=[True, True, False]), \
             patch.object(control.time, "sleep") as sleep, patch.object(control, "start", return_value={"stage": "starting"}) as start:
            self.assertEqual(control.restart(Path("home"))["stage"], "starting")
            self.assertTrue((Path(directory) / "stop").is_file())
            self.assertEqual(sleep.call_count, 2)
            start.assert_called_once_with(Path("home"))

    def test_restart_timeout_preserves_stop_marker_and_does_not_spawn_monitor(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, "STATE", Path(directory)), \
             patch.object(control, "monitor_alive", return_value=True), \
             patch.object(control.time, "monotonic", side_effect=[0, 11]), patch.object(control, "start") as start:
            with self.assertRaises(RuntimeError):
                control.restart(Path("home"))
            self.assertTrue((Path(directory) / "stop").is_file())
            start.assert_not_called()

    def test_task_launch_is_forwarded_to_the_desktop_with_its_thread_and_home(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, "STATE", Path(directory)), \
             patch.object(control.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run, \
             patch.object(control, "available_pages", return_value=(9222,[{}])):
            (Path(directory) / "launch.ps1").touch()
            result = control.launch_from_desktop(Path("task home"), "thread-id")
            self.assertEqual(result["stage"], "connected")
            command = run.call_args.args[0]
            self.assertTrue(any(arg.endswith("broker.ps1") for arg in command))
            arguments = command[command.index("-Arguments") + 1]
            self.assertIn("-ThreadId thread-id", arguments)
            self.assertIn('-CodexHome "task home"', arguments)

    def test_packaged_app_launch_uses_windows_activation_and_preserves_switches(self):
        with patch.object(control, "available_pages", side_effect=[CDPError("closed"), (9222, [{}])]), \
             patch.object(control, "app_info", return_value={"running": False, "aumid": "OpenAI.Codex_family!App"}), \
             patch.object(control, "activate_app", return_value=12345) as activate, \
             patch.object(control, "start"), \
             patch.object(control.time, "sleep"), \
             patch.object(control.subprocess, "Popen") as process:
            result = control.launch(Path("home"))
            activate.assert_called_once()
            self.assertEqual(activate.call_args.args[0], "OpenAI.Codex_family!App")
            self.assertEqual(activate.call_args.args[1][:2], [
                f"--user-data-dir={control.STATE / 'codex-profile'}",
                "--remote-debugging-address=127.0.0.1"])
            self.assertIn(activate.call_args.args[1][2], [f"--remote-debugging-port={port}" for port in range(9222, 9232)])
            self.assertEqual(result["stage"], "connected")
            self.assertEqual(result["app_pid"], 12345)
            process.assert_not_called()

    def test_activation_errors_are_reported_before_waiting_for_a_connection(self):
        with patch.object(control, "available_pages", side_effect=CDPError("closed")), \
             patch.object(control, "app_info", return_value={"running": False, "aumid": "OpenAI.Codex_family!App"}), \
             patch.object(control, "activate_app", side_effect=RuntimeError("activation denied")), \
             patch.object(control, "start"), \
             patch.object(control.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "activation denied"):
                control.launch(Path("home"))
            sleep.assert_not_called()

    def test_activation_passes_windows_arguments_as_data(self):
        with patch.object(control.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout='{"pid":12345}', stderr="")) as run:
            flags = ["--remote-debugging-port=9222", r"--user-data-dir=C:\test profile"]
            self.assertEqual(control.activate_app("OpenAI.Codex_family!App", flags), 12345)
            command = run.call_args.args[0]
            self.assertIn("-File", command)
            self.assertEqual(command[-1], control.subprocess.list2cmdline(flags))
            self.assertIn("OpenAI.Codex_family!App", command)
            self.assertNotIn("-Command", command)

    def test_an_existing_standard_client_does_not_block_the_tps_window(self):
        with patch.object(control, "available_pages", side_effect=[CDPError("closed"), (9222, [{}])]), \
             patch.object(control, "app_info", return_value={"running": True, "aumid": "OpenAI.Codex_family!App"}), \
             patch.object(control, "activate_app", return_value=12345) as activate, \
             patch.object(control, "start"), \
             patch.object(control.time, "sleep"), \
             patch.object(control.subprocess, "Popen") as process:
            result = control.launch(Path("home"))
            self.assertEqual(result["stage"], "connected")
            self.assertIn(f"--user-data-dir={control.STATE / 'codex-profile'}", activate.call_args.args[1])
            process.assert_not_called()

    def test_the_new_tps_window_opens_the_requested_conversation(self):
        thread = "00000000-0000-4000-8000-000000000001"
        with patch.object(control, "available_pages", side_effect=[CDPError("closed"), (9222, [{}])]), \
             patch.object(control, "app_info", return_value={"aumid": "OpenAI.Codex_family!App"}), \
             patch.object(control, "activate_app", return_value=12345) as activate, \
             patch.object(control, "start"), \
             patch.object(control.time, "sleep"):
            result = control.launch(Path("home"), thread)
            self.assertEqual(result["stage"], "connected")
            self.assertEqual(activate.call_args.args[1][-1], f"codex://threads/{thread}")

    def test_an_existing_connection_reuses_the_port_and_activates_the_tps_window(self):
        with patch.object(control, "available_pages", return_value=(9223, [{}])), \
             patch.object(control, "start") as start, \
             patch.object(control, "app_info", return_value={"aumid":"OpenAI.Codex_family!App"}), \
             patch.object(control, "activate_app", return_value=12345) as activate, \
             patch.object(control.time, "sleep"):
            result = control.launch(Path("home"))
            self.assertEqual(result["port"], 9223)
            start.assert_called_once()
            self.assertIn("--remote-debugging-port=9223", activate.call_args.args[1])

    def test_old_saved_diagnostics_do_not_claim_current_display(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, "STATE", Path(directory)):
            (Path(directory) / "status.json").write_text(json.dumps({"updated_at": time.time() - 60, "stage": "connected", "rendered": 3}), encoding="utf-8")
            self.assertFalse(control.status()["fresh"])

    def test_start_is_idempotent_when_heartbeat_is_fresh(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, "STATE", Path(directory)), \
             patch.object(control, "monitor_alive", return_value=True), \
             patch.object(control.subprocess, "run") as process:
            (Path(directory) / "status.json").write_text(json.dumps({"updated_at": time.time(), "stage": "connected", "rendered": 3}), encoding="utf-8")
            self.assertEqual(control.start(Path(directory))["stage"], "connected")
            process.assert_not_called()

    def test_launch_after_client_exit_recovers_from_a_recent_but_dead_monitor(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, "STATE", Path(directory)), \
             patch.object(control, "monitor_alive", return_value=False), \
             patch.object(control.subprocess, "Popen"), \
             patch.object(control.subprocess, "run", return_value=SimpleNamespace(returncode=0, stderr="")) as process:
            (Path(directory) / "status.json").write_text(json.dumps({"updated_at": time.time(), "stage": "connected", "rendered": 3}), encoding="utf-8")
            self.assertEqual(control.start(Path(directory))["stage"], "starting")
            process.assert_called_once()
            command = process.call_args.args[0]
            self.assertIn("-File", command)
            self.assertTrue(any(arg.endswith("broker.ps1") for arg in command))


if __name__ == "__main__":
    unittest.main()
