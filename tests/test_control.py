import json
from types import SimpleNamespace
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, call, patch


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
             patch.object(control, "app_info", return_value={"running": False}), \
             patch.object(control, "available_pages", side_effect=[CDPError("closed"), (9222, [{}])]):
            (Path(directory) / "launch.ps1").touch()
            result = control.launch_from_desktop(Path("task home"), "thread-id")
            self.assertEqual(result["stage"], "connected")
            command = run.call_args.args[0]
            self.assertTrue(any(arg.endswith("broker.ps1") for arg in command))
            arguments = command[command.index("-Arguments") + 1]
            self.assertIn("-ThreadId thread-id", arguments)
            self.assertIn('-CodexHome "task home"', arguments)

    def test_repeated_desktop_launches_reuse_the_page_without_starting_a_broker(self):
        page_url = "ws://127.0.0.1:9223/devtools/page/tps"
        with patch.object(control, "available_pages", return_value=(9223, [{"webSocketDebuggerUrl": page_url}])), \
             patch.object(control, "start") as start, patch.object(control, "CDPClient") as client, \
             patch.object(control.subprocess, "run") as process:
            for _ in range(3):
                result = control.launch_from_desktop(Path("task home"), "thread-id")
                self.assertEqual(result["stage"], "connected")
                self.assertTrue(result["reused"])
            self.assertEqual(start.call_count, 3)
            self.assertEqual(client.return_value.call.call_count, 3)
            client.return_value.call.assert_called_with("Page.bringToFront")
            self.assertEqual(client.return_value.close.call_count, 3)
            process.assert_not_called()

    def test_a_running_standard_client_does_not_start_the_desktop_broker(self):
        with patch.object(control, "available_pages", side_effect=CDPError("closed")), \
             patch.object(control, "app_info", return_value={"running": True}), \
             patch.object(control, "start") as start, \
             patch.object(control.subprocess, "run") as process:
            result = control.launch_from_desktop(Path("task home"), "thread-id")
            self.assertEqual(result["stage"], "restart_required")
            start.assert_not_called()
            process.assert_not_called()

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
            flags = activate.call_args.args[1]
            self.assertEqual(len(flags), 2)
            self.assertEqual(flags[0], "--remote-debugging-address=127.0.0.1")
            self.assertIn(flags[1], [f"--remote-debugging-port={port}" for port in range(9222, 9232)])
            self.assertFalse(any(flag.startswith("--user-data-dir") for flag in flags))
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

    def test_an_existing_windows_standard_client_never_opens_another_client(self):
        with patch.object(control.sys, "platform", "win32"), \
             patch.object(control, "available_pages", side_effect=CDPError("closed")), \
             patch.object(control, "app_info", return_value={"running": True}), \
             patch.object(control, "activate_app") as activate, \
             patch.object(control, "start") as start, \
             patch.object(control.time, "sleep") as sleep, \
             patch.object(control.subprocess, "Popen") as process:
            result = control.launch(Path("home"))
            self.assertEqual(result["stage"], "restart_required")
            activate.assert_not_called()
            start.assert_not_called()
            sleep.assert_not_called()
            process.assert_not_called()

    def test_a_cold_launch_opens_the_requested_conversation_in_the_native_profile(self):
        thread = "00000000-0000-4000-8000-000000000001"
        with patch.object(control, "available_pages", side_effect=[CDPError("closed"), (9222, [{}])]), \
             patch.object(control, "app_info", return_value={"aumid": "OpenAI.Codex_family!App"}), \
             patch.object(control, "activate_app", return_value=12345) as activate, \
             patch.object(control, "start"), \
             patch.object(control.time, "sleep"):
            result = control.launch(Path("home"), thread)
            self.assertEqual(result["stage"], "connected")
            self.assertEqual(activate.call_args.args[1][-1], f"codex://threads/{thread}")
            self.assertFalse(any(flag.startswith("--user-data-dir") for flag in activate.call_args.args[1]))

    def test_existing_page_is_reused_on_both_platforms_even_with_a_requested_thread(self):
        page_url = "ws://127.0.0.1:9223/devtools/page/tps"
        for platform in ("win32", "darwin"):
            for thread in (None, "00000000-0000-4000-8000-000000000001"):
                with self.subTest(platform=platform, thread=thread), \
                     patch.object(control.sys, "platform", platform), \
                     patch.object(control, "available_pages", return_value=(9223, [{"webSocketDebuggerUrl": page_url}])), \
                     patch.object(control, "start") as start, patch.object(control, "CDPClient") as client, \
                     patch.object(control, "app_info") as app_info, \
                     patch.object(control, "activate_app") as activate, \
                     patch.object(control, "activate_mac_app") as activate_mac:
                    result = control.launch(Path("home"), thread)
                    self.assertEqual(result["stage"], "connected")
                    self.assertEqual(result["port"], 9223)
                    self.assertTrue(result["reused"])
                    start.assert_called_once_with(Path("home"))
                    client.assert_called_once_with(page_url)
                    client.return_value.call.assert_called_once_with("Page.bringToFront")
                    client.return_value.close.assert_called_once()
                    app_info.assert_not_called()
                    activate.assert_not_called()
                    activate_mac.assert_not_called()

    def test_requested_thread_focuses_its_existing_page_and_closes_every_connection(self):
        thread = "requested-thread"
        urls = [f"ws://127.0.0.1:9223/devtools/page/{name}" for name in ("other", "requested", "last")]
        inspect_other, inspect_requested, focus = [Mock() for _ in range(3)]
        inspect_other.evaluate.return_value = "other-thread"
        inspect_requested.evaluate.return_value = thread
        with patch.object(control, "available_pages", return_value=(9223, [{"webSocketDebuggerUrl": url} for url in urls])), \
             patch.object(control, "start") as start, \
             patch.object(control, "CDPClient", side_effect=[inspect_other, inspect_requested, focus]) as client, \
             patch.object(control, "app_info") as app_info, \
             patch.object(control, "activate_app") as activate, \
             patch.object(control, "activate_mac_app") as activate_mac:
            result = control.launch(Path("home"), thread)
            self.assertTrue(result["reused"])
            start.assert_called_once_with(Path("home"))
            self.assertEqual(client.call_args_list, [call(urls[0]), call(urls[1]), call(urls[1])])
            inspect_other.evaluate.assert_called_once()
            inspect_requested.evaluate.assert_called_once()
            inspect_other.call.assert_not_called()
            inspect_requested.call.assert_not_called()
            focus.call.assert_called_once_with("Page.bringToFront")
            for connection in (inspect_other, inspect_requested, focus):
                connection.close.assert_called_once()
            app_info.assert_not_called()
            activate.assert_not_called()
            activate_mac.assert_not_called()

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
