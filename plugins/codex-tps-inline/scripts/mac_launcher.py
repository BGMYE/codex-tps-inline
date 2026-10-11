"""Create the local Finder launcher for the installed TPS plugin."""

from pathlib import Path
import argparse
import os
import plistlib
import shlex
import shutil
import sys

from control import app_info
from monitor import STATE


IDENTIFIER = "local.codex-tps-inline.launcher"


def owned(application):
    metadata = application / "Contents/Info.plist"
    if application.is_symlink() or not metadata.is_file():
        return False
    with metadata.open("rb") as stream:
        return plistlib.load(stream).get("CFBundleIdentifier") == IDENTIFIER


def create_launcher(application, python, control, state, icon=None, home=None):
    if application.exists() and not owned(application):
        raise RuntimeError(f"路径已被其他应用使用：{application}")
    contents = application / "Contents"
    executable = contents / "MacOS/launch"
    executable.parent.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    arguments = [str(python), str(control), "launch"]
    if home is not None:
        arguments.extend(["--home", str(home)])
    command = shlex.join(arguments)
    executable.write_text(f"#!/bin/bash\nexec {command} >> {shlex.quote(str(state / 'launcher.log'))} 2>&1\n", encoding="utf-8")
    executable.chmod(0o755)
    metadata = {"CFBundleIdentifier": IDENTIFIER, "CFBundleExecutable": "launch",
                "CFBundleName": "Codex TPS", "CFBundlePackageType": "APPL",
                "CFBundleVersion": "0.3.0", "LSUIElement": True}
    if icon and Path(icon).is_file():
        resources = contents / "Resources"
        resources.mkdir(exist_ok=True)
        shutil.copyfile(icon, resources / "Codex.icns")
        metadata["CFBundleIconFile"] = "Codex.icns"
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(metadata, stream)


def remove_launcher(application):
    if not application.exists():
        return
    if not owned(application):
        raise RuntimeError(f"不会移除其他应用：{application}")
    shutil.rmtree(application)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "remove"))
    parser.add_argument("--home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    args = parser.parse_args()
    application = Path.home() / "Applications/Codex TPS.app"
    if args.action == "install":
        create_launcher(application, sys.executable, Path(__file__).with_name("control.py"), STATE, app_info().get("icon"), Path(args.home))
        print(f"已生成 {application}；可以拖到 Dock。")
    else:
        remove_launcher(application)
