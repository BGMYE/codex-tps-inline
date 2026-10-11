"""Launch or reuse one native Codex instance with local TPS footer support."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import time
from urllib.parse import quote

from monitor import STATE, MUTEX_NAME, available_pages
from cdp import CDPClient, CDPError
from tps import Catalog

POWERSHELL = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
MAC_APP_PATHS = tuple(root / name for root in (Path('/Applications'), Path.home() / 'Applications')
                      for name in ('Codex.app', 'ChatGPT.app'))


def status():
    try:
        result = json.loads((STATE / "status.json").read_text(encoding="utf-8"))
        result["fresh"] = time.time() - result["updated_at"] < 20
        return result
    except (OSError, ValueError, KeyError):
        return {"stage": "not_running", "fresh": False, "rendered": 0}


def monitor_alive():
    if sys.platform != "win32":
        try:
            os.kill(int(status()["pid"]), 0)
            return True
        except (OSError, ValueError, KeyError):
            return False
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, MUTEX_NAME)
    exists = kernel.GetLastError() == 183
    if handle:
        kernel.CloseHandle(ctypes.c_void_p(handle))
    return exists


def start(home):
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "stop").unlink(missing_ok=True)
    if status()["fresh"] and monitor_alive():
        return status()
    if sys.platform == "darwin":
        with (STATE / "monitor.log").open("ab") as log:
            subprocess.Popen([sys.executable, str(Path(__file__).with_name("monitor.py")), "--home", str(home)],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        return {"stage": "starting", "message": "TPS 后台监控已启动。"}
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    monitor = Path(__file__).with_name("monitor.py")
    arguments = subprocess.list2cmdline([str(monitor), "--home", str(home)])
    command = [POWERSHELL, "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File",
               str(Path(__file__).with_name("broker.ps1")), "-Executable", str(pythonw),
               "-Arguments", arguments, "-WorkingDirectory", str(monitor.parent)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=10)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "TPS 后台监控启动失败。")
    return {"stage": "starting", "message": "回复底部 TPS 监控已启动；等待客户端本机连接。"}


def stop():
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "stop").touch()
    deadline = time.monotonic() + 10
    while monitor_alive():
        if time.monotonic() >= deadline:
            raise RuntimeError("TPS 旧监控尚未停止；请稍后重新运行安装脚本。")
        time.sleep(0.1)
    return {"stage": "stopped", "message": "TPS 监控已停止，临时状态行已移除。"}


def restart(home):
    stop()
    return start(home)


def app_info():
    if sys.platform == "darwin":
        for bundle in MAC_APP_PATHS:
            metadata = bundle / "Contents/Info.plist"
            if not metadata.is_file():
                continue
            with metadata.open("rb") as stream:
                info = plistlib.load(stream)
            executable = bundle / "Contents/MacOS" / info.get("CFBundleExecutable", "")
            if executable.is_file():
                icon = bundle / "Contents/Resources" / info.get("CFBundleIconFile", "")
                if icon.suffix != ".icns":
                    icon = icon.with_suffix(".icns")
                return {"bundle": str(bundle), "exe": str(executable), "icon": str(icon)}
        raise RuntimeError("未找到 /Applications 或 ~/Applications 中的 Codex.app / ChatGPT.app。")
    if sys.platform != "win32":
        raise RuntimeError("原生 TPS 窗口目前支持 Windows 和 macOS。")
    script = """$p = Get-AppxPackage -Name 'OpenAI.Codex' | Sort-Object Version -Descending | Select-Object -First 1
if ($p) {
    $exe = Join-Path $p.InstallLocation 'app/ChatGPT.exe'
    $running = @(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'" | Where-Object {
        $_.ExecutablePath -eq $exe -and $_.CommandLine -notlike '*--type=*'
    }).Count -gt 0
    @{exe=$exe;aumid=($p.PackageFamilyName + '!App');running=$running} | ConvertTo-Json -Compress
}"""
    result = subprocess.run([POWERSHELL, "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8", timeout=20)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("未找到 Windows Codex 桌面安装包。")
    info = json.loads(result.stdout)
    if not Path(info["exe"]).is_file():
        raise RuntimeError("Codex 客户端启动文件不存在。")
    return info


def activate_app(aumid, flags):
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(Path(__file__).with_name("activate.ps1")), "-AppUserModelId", aumid,
               "-Arguments", subprocess.list2cmdline(flags)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Windows 应用激活失败。")
    return int(json.loads(result.stdout)["pid"])


def activate_mac_app(bundle, flags, home):
    command = ["/usr/bin/open", "-a", bundle,
               "--env", f"CODEX_HOME={home}", "--args", *flags]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=20)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "macOS Codex 启动失败。")


def reuse_window(home, port, pages, thread_id=None):
    start(home)
    selected = pages[0]
    if thread_id and len(pages) > 1:
        overlay = Path(__file__).with_name("overlay.js").read_text(encoding="utf-8-sig")
        for page in pages:
            client = CDPClient(page["webSocketDebuggerUrl"])
            try:
                if client.evaluate(f"({overlay})(null)") == thread_id:
                    selected = page
                    break
            finally:
                client.close()
    client = CDPClient(selected["webSocketDebuggerUrl"])
    try:
        client.call("Page.bringToFront")
    finally:
        client.close()
    return {"stage": "connected", "port": port, "reused": True,
            "message": "已复用现有 Codex 窗口；TPS 会跟随当前对话，不另开窗口。"}


def restart_required():
    return {"stage": "restart_required", "message": "Codex 已在运行，但本次启动没有启用 TPS 连接。请先完成当前工作并完整退出 Codex，再从桌面或开始菜单的新 Codex 快捷方式打开一次；不会另外创建一个 Codex。"}


def launch_from_desktop(home, thread_id=None):
    try:
        port, pages = available_pages()
    except CDPError:
        pass
    else:
        return reuse_window(home, port, pages, thread_id)
    if app_info().get("running"):
        return restart_required()
    launcher = STATE / "launch.ps1"
    if not launcher.is_file():
        raise RuntimeError("请先运行 Windows install.ps1，建立桌面启动入口。")
    arguments = ["-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", str(launcher),
                 "-PythonExe", sys.executable, "-ControlScript", str(Path(__file__).resolve()), "-CodexHome", str(home)]
    if thread_id:
        arguments.extend(["-ThreadId", thread_id])
    command = [POWERSHELL, "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File",
               str(Path(__file__).with_name("broker.ps1")), "-Executable", POWERSHELL,
               "-Arguments", subprocess.list2cmdline(arguments), "-WorkingDirectory", str(STATE)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=10)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Codex TPS 桌面启动失败。")
    for _ in range(30):
        try:
            port, _pages = available_pages()
            return {"stage": "connected", "port": port, "message": "Codex TPS 窗口已连接。"}
        except CDPError:
            time.sleep(0.5)
    return {"stage": "connection_unavailable", "message": f"启动仍未连接，请查看 {STATE / 'launcher.log'}。"}


def launch(home, thread_id=None):
    try:
        port, _pages = available_pages()
    except CDPError:
        for port in range(9222, 9232):
            with socket.socket() as sock:
                try:
                    sock.bind(("127.0.0.1", port))
                    break
                except OSError:
                    continue
        else:
            raise RuntimeError("没有可用的本机 TPS 连接端口。")
    else:
        return reuse_window(home, port, _pages, thread_id)
    info = app_info()
    if info.get("running"):
        return restart_required()
    start(home)
    flags = ["--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}"]
    if thread_id:
        flags.append(f"codex://threads/{quote(thread_id, safe='')}")
    app_pid = activate_mac_app(info["bundle"], flags, home) if sys.platform == "darwin" else activate_app(info["aumid"], flags)
    for _ in range(20):
        time.sleep(1)
        try:
            connected, _pages = available_pages()
            return {"stage": "connected", "port": connected, "app_pid": app_pid, "message": "已打开 Codex；TPS 监控已连接，等待匹配对应回复。"}
        except CDPError:
            continue
    return {"stage": "connection_unavailable", "app_pid": app_pid, "port": port, "message": f"客户端已启动，但未连接到页面。启动诊断保存在 {STATE / 'launch-result.json'}；请运行 $tps 检查。"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "restart", "status", "stop", "launch", "inspect", "app-info"))
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    parser.add_argument("--thread")
    parser.add_argument("--direct-launch", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.action == "app-info":
        result = app_info()
    elif args.action == "start":
        result = start(args.home)
    elif args.action == "restart":
        result = restart(args.home)
    elif args.action == "launch":
        thread = args.thread or os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
        result = launch_from_desktop(args.home, thread) if sys.platform == "win32" and not args.direct_launch else launch(args.home, thread)
    elif args.action == "stop":
        result = stop()
    elif args.action == "inspect":
        thread = args.thread or os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
        catalog = Catalog(args.home, thread)
        sessions = catalog.poll()
        chosen = next((s for s in sessions if s["thread_id"] == thread), None) if thread else (sessions[0] if sessions else None)
        if chosen:
            chosen.pop("turns", None)
        result = {"monitor": status(), "session": chosen}
        try:
            result["launcher"] = json.loads((STATE / "launch-result.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            pass
    else:
        result = status()
    if args.action == "launch":
        STATE.mkdir(parents=True, exist_ok=True)
        (STATE / "launch-result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"stage": "error", "message": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
