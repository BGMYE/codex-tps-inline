from pathlib import Path
import plistlib
import shlex
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-tps-inline/scripts"))
import control
import mac_launcher
from cdp import CDPError


class MacTests(unittest.TestCase):
    def test_reopening_the_finder_launcher_brings_existing_tps_page_to_front(self):
        with patch.object(control.sys, "platform", "darwin"), \
             patch.object(control, "available_pages", return_value=(9222, [{"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tps"}])), \
             patch.object(control, "CDPClient") as client, patch.object(control, "start") as start, \
             patch.object(control, "activate_mac_app") as activate, patch.object(control, "app_info") as app_info:
            result = control.launch(Path("task home"))
            self.assertEqual(result["stage"], "connected")
            start.assert_called_once_with(Path("task home"))
            client.return_value.call.assert_called_once_with("Page.bringToFront")
            client.return_value.close.assert_called_once()
            activate.assert_not_called()
            app_info.assert_not_called()

    def test_bundle_metadata_finds_the_actual_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "Codex.app"
            (bundle / "Contents/MacOS").mkdir(parents=True)
            (bundle / "Contents/MacOS/Codex").touch()
            with (bundle / "Contents/Info.plist").open("wb") as stream:
                plistlib.dump({"CFBundleExecutable":"Codex", "CFBundleIconFile":"Codex.icns"}, stream)
            with patch.object(control.sys, "platform", "darwin"), patch.object(control, "MAC_APP_PATHS", (bundle,)):
                self.assertEqual(control.app_info()["exe"], str(bundle / "Contents/MacOS/Codex"))

    def test_open_uses_the_existing_app_identity_and_preserves_codex_home(self):
        with patch.object(control.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            control.activate_mac_app("/Applications/Codex.app", ["--remote-debugging-port=9222"], Path("task home"))
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ["/usr/bin/open", "-a", "/Applications/Codex.app"])
            self.assertNotIn("-n", command)
            self.assertIn("CODEX_HOME=task home", command)
            self.assertFalse(any(arg.startswith("CODEX_ELECTRON_USER_DATA_PATH=") for arg in command))
            self.assertEqual(command[-2:], ["--args", "--remote-debugging-port=9222"])

    def test_mac_cold_launch_passes_debugging_flags_without_a_separate_profile(self):
        thread = "00000000-0000-4000-8000-000000000001"
        with patch.object(control.sys, "platform", "darwin"), \
             patch.object(control, "available_pages", side_effect=[CDPError("closed"), (9222, [{}])]), \
             patch.object(control, "app_info", return_value={"running": False, "bundle": "/Applications/Codex.app"}), \
             patch.object(control, "activate_mac_app") as activate, \
             patch.object(control, "activate_app") as activate_windows, \
             patch.object(control, "start") as start, patch.object(control.time, "sleep"):
            result = control.launch(Path("task home"), thread)
            self.assertEqual(result["stage"], "connected")
            start.assert_called_once_with(Path("task home"))
            activate.assert_called_once()
            bundle, flags, home = activate.call_args.args
            self.assertEqual(bundle, "/Applications/Codex.app")
            self.assertEqual(home, Path("task home"))
            self.assertEqual(len(flags), 3)
            self.assertEqual(flags[0], "--remote-debugging-address=127.0.0.1")
            self.assertIn(flags[1], [f"--remote-debugging-port={port}" for port in range(9222, 9232)])
            self.assertEqual(flags[2], f"codex://threads/{thread}")
            self.assertFalse(any(flag.startswith("--user-data-dir") for flag in flags))
            activate_windows.assert_not_called()

    def test_mac_monitor_is_detached_from_the_calling_session(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, "STATE", Path(directory)), \
             patch.object(control.sys, "platform", "darwin"), patch.object(control, "monitor_alive", return_value=False), \
             patch.object(control.subprocess, "Popen") as process, patch.object(control.subprocess, "run") as run:
            self.assertEqual(control.start(Path(directory))["stage"], "starting")
            self.assertTrue(process.call_args.kwargs["start_new_session"])
            run.assert_not_called()

    def test_mac_monitor_process_lookup_does_not_send_a_signal(self):
        with patch.object(control.sys, "platform", "darwin"), patch.object(control, "status", return_value={"pid":12345}), \
             patch.object(control.os, "kill", side_effect=ProcessLookupError) as kill:
            self.assertFalse(control.monitor_alive())
            kill.assert_called_once_with(12345, 0)

    def test_finder_launcher_quotes_paths_and_refuses_other_apps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = root / "Applications/Codex TPS.app"
            python = root / "Python with spaces/python3"
            script = root / "User's plugin/control.py"
            mac_launcher.create_launcher(application, python, script, root / "state")
            with (application / "Contents/Info.plist").open("rb") as stream:
                self.assertEqual(plistlib.load(stream)["CFBundleIdentifier"], mac_launcher.IDENTIFIER)
            command = (application / "Contents/MacOS/launch").read_text(encoding="utf-8").splitlines()[1]
            self.assertEqual(shlex.split(command)[1:4], [str(python), str(script), "launch"])
            mac_launcher.create_launcher(application, python, script, root / "state")
            mac_launcher.remove_launcher(application)
            self.assertFalse(application.exists())
            (application / "Contents").mkdir(parents=True)
            with (application / "Contents/Info.plist").open("wb") as stream:
                plistlib.dump({"CFBundleIdentifier":"another.app"}, stream)
            with self.assertRaises(RuntimeError): mac_launcher.create_launcher(application, python, script, root / "state")
            with self.assertRaises(RuntimeError): mac_launcher.remove_launcher(application)

    def test_finder_launcher_preserves_custom_codex_home_without_shell_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = root / "Applications/Codex TPS.app"
            home = root / "Task home"
            python = Path("/usr/local/bin/python3")
            control_script = Path("/plugin/control.py")
            mac_launcher.create_launcher(application, python, control_script, root / "state", home=home)
            command = (application / "Contents/MacOS/launch").read_text(encoding="utf-8").splitlines()[1]
            self.assertEqual(shlex.split(command)[1:6], [str(python), str(control_script), "launch", "--home", str(home)])


if __name__ == "__main__": unittest.main()
