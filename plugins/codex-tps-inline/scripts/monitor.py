"""Update inline Codex turn averages through a local renderer connection."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time

from cdp import CDPClient, CDPError, devtools_targets, is_codex_renderer_target, target_score
from tps import Catalog


STATE = (Path.home() / "Library/Application Support" if sys.platform == "darwin" else
         Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache")))) / "CodexTPSInline"
MUTEX_NAME = "Local\\CodexTPSInlineMonitor"


def pages_on_port(port):
    return [p for p in devtools_targets(port) if p.get("type") == "page"
            and is_codex_renderer_target(p) and target_score(p) >= 100
            and p.get("webSocketDebuggerUrl")]


def available_pages():
    for port in range(9222, 9232):
        try:
            pages = pages_on_port(port)
            if pages:
                return port, pages
        except (CDPError, OSError, ValueError):
            pass
    raise CDPError("尚未连接到 TPS 窗口；运行 $tps 或打开“Codex TPS”入口即可，无需退出当前客户端。")


def inline_turn(turn):
    status = "running" if not turn["complete"] else "completed" if turn["status"] == "已完成" else "interrupted"
    return {"turn_id": turn["turn_id"], "status": status,
            "wall_tps": turn["average_tps"], "wall_seconds": turn["elapsed_seconds"],
            "output_tokens": turn["output_tokens"], "reported_at": turn["reported_at"],
            "final_ids": turn["final_ids"], "user_ids": turn["user_ids"], "models": turn["models"],
            "notes": [] if turn["valid"] else ["计数发生重置或记录不完整，均值不可用"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    mutex = None
    lock = None
    if os.name == "nt" and not args.once:
        kernel = ctypes.windll.kernel32
        kernel.CreateMutexW.restype = ctypes.c_void_p
        mutex = kernel.CreateMutexW(None, False, MUTEX_NAME)
        if kernel.GetLastError() == 183:
            kernel.CloseHandle(ctypes.c_void_p(mutex))
            return 0
    elif os.name != "nt" and not args.once:
        import fcntl
        lock = (STATE / "monitor.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return 0
    overlay = Path(__file__).with_name("overlay.js").read_text(encoding="utf-8-sig")
    catalog = Catalog(args.home)
    clients = {}
    stop_file = STATE / "stop"
    try:
        while not stop_file.exists():
            started = time.monotonic()
            diagnostics = []
            try:
                port, pages = available_pages()
                live = {page["id"] for page in pages}
                for key in list(clients):
                    if key not in live:
                        clients.pop(key).close()
                for page in pages:
                    key = page["id"]
                    if key not in clients:
                        clients[key] = CDPClient(page["webSocketDebuggerUrl"], timeout=3)
                    client = clients[key]
                    context = client.evaluate(f"({{thread_id: ({overlay})(null), enabled: window.__codexTPSInline?.isEnabled?.() ?? true}})")
                    thread = context["thread_id"]
                    catalog.thread_id = thread
                    snapshots = catalog.poll() if context["enabled"] else []
                    session = next((s for s in snapshots if s["thread_id"] == thread), None)
                    payload = {"thread_id": thread, "turns": [inline_turn(t) for t in session["turns"]] if session else []}
                    result = client.evaluate(f"({overlay})({json.dumps(payload, ensure_ascii=False)})")
                    if not isinstance(result, dict) or not result.get("ok"):
                        raise CDPError("客户端未返回有效的 TPS 界面状态。")
                    count = result.get("rendered", 0)
                    stage = ("disabled" if not result.get("enabled", True) else
                             "toggle_not_matched" if not result.get("toggle_rendered") else
                             "rendered" if count else "thread_not_found" if not thread else "session_not_found" if not session else "reply_not_matched")
                    diagnostics.append({"window_id": key, "thread_id": thread, "rendered": count, "stage": stage,
                                        "enabled": result.get("enabled", True), "toggle_rendered": result.get("toggle_rendered", False)})
                status = {"stage": "connected", "port": port, "rendered": sum(d["rendered"] for d in diagnostics), "diagnostics": diagnostics}
            except (CDPError, OSError, ValueError, KeyError, TypeError) as exc:
                for client in clients.values():
                    client.close()
                clients.clear()
                status = {"stage": "waiting_for_launcher", "rendered": 0, "message": str(exc)}
            status.update(pid=os.getpid(), updated_at=time.time())
            temp = STATE / "status.tmp"
            temp.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
            temp.replace(STATE / "status.json")
            if args.once:
                print(json.dumps(status, ensure_ascii=False))
                return 0 if status["stage"] == "connected" else 1
            time.sleep(max(0.05, 1 - (time.monotonic() - started)))
    finally:
        for client in clients.values():
            try:
                if not args.once:
                    client.evaluate("window.__codexTPSInline?.stop()")
            except (CDPError, OSError):
                pass
            client.close()
        if mutex:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mutex))
        if lock:
            lock.close()
    return 0


if __name__ == "__main__":
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
