"""Read local Codex turn throughput for inline reply statistics."""

import json
import os
from pathlib import Path
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime



def timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


@dataclass
class Turn:
    id: str
    start: float
    output: int | None = None
    reasoning: int = 0
    reported_at: float | None = None
    end: float | None = None
    duration: float | None = None
    status: str = "运行中"
    authoritative: bool = False
    valid: bool = True
    final_ids: list = field(default_factory=list)
    user_ids: list = field(default_factory=list)
    models: list = field(default_factory=list)

    def metrics(self, now):
        seconds = self.duration if self.duration is not None else (self.end or now) - self.start
        seconds = max(0.0, seconds)
        return {
            "turn_id": self.id,
            "status": self.status,
            "output_tokens": self.output,
            "reasoning_tokens": self.reasoning,
            "elapsed_seconds": seconds,
            "average_tps": self.output / seconds if self.valid and self.output is not None and seconds > 0 else None,
            "reported_at": self.reported_at,
            "complete": self.end is not None,
            "valid": self.valid,
            "final_ids": sorted(set(self.final_ids)),
            "user_ids": sorted(set(self.user_ids)),
            "models": self.models,
        }


class Session:
    def __init__(self, path, thread_id="", title="", model=""):
        self.path = Path(path)
        self.id = thread_id
        self.title = title or thread_id[:8]
        self.model = model or "未知模型"
        self.offset = 0
        self.current = None
        self.turns = []
        self.last_finished = None
        self.total = 0
        self.base = 0
        self.subagent = False
        self.error = ""

    def consume(self, event):
        payload = event.get("payload") or {}
        kind = event.get("type")
        when = timestamp(event["timestamp"])
        if kind == "session_meta":
            self.id = payload.get("id", self.id)
            if not self.title:
                self.title = self.id[:8]
            self.subagent = isinstance(payload.get("source"), dict)
        elif kind == "turn_context":
            self.model = payload.get("model", self.model)
            if self.current and self.model not in self.current.models:
                self.current.models.append(self.model)
        elif kind == "response_item" and self.current:
            if payload.get("type") == "message" and payload.get("phase") == "final_answer" and payload.get("id"):
                self.current.final_ids.append(payload["id"])
        elif kind == "event_msg":
            message = payload.get("type")
            if message == "task_started":
                turn_id = payload.get("turn_id", str(when))
                if self.current and self.current.id == turn_id:
                    return
                if self.current and self.current.end is None:
                    self.current.end = when
                    self.current.status = "未完整结束"
                    self.current.valid = False
                self.current = Turn(turn_id, when)
                self.turns.append(self.current)
                self.turns = self.turns[-200:]
                self.base = self.total
            elif message == "item_completed" and self.current:
                item = payload.get("item") or {}
                if item.get("type") == "UserMessage" and item.get("id"):
                    self.current.user_ids.append(item["id"])
                if item.get("type") == "AgentMessage" and item.get("phase") == "final_answer" and item.get("id"):
                    self.current.final_ids.append(item["id"])
            elif message == "token_count":
                info = payload.get("info") or {}
                usage = info.get("total_token_usage")
                if not usage or "output_tokens" not in usage:
                    return
                total = usage["output_tokens"]
                turn = self.current
                if turn and not turn.authoritative:
                    if total < self.total or total < self.base:
                        turn.valid = False
                    turn.output = max(0, total - self.base)
                    turn.reasoning = 0
                    turn.reported_at = when
                self.total = total
            elif message in ("task_complete", "turn_aborted") and self.current:
                turn = self.current
                if payload.get("turn_id", turn.id) != turn.id:
                    return
                turn.end = when
                turn.status = "已完成" if message == "task_complete" else "已中断"
                duration_ms = payload.get("duration_ms")
                if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
                    turn.duration = duration_ms / 1000
                self.last_finished = turn
        elif kind == "token_usage_record":
            turn = self.current
            if not turn or payload.get("turn_id") != turn.id:
                return
            usage = payload.get("turn_token_usage") or {}
            if "output_tokens" not in usage:
                return
            turn.authoritative = True
            turn.valid = True
            turn.output = usage["output_tokens"]
            turn.reasoning = usage.get("reasoning_output_tokens", 0)
            turn.reported_at = when

    def poll(self):
        try:
            if self.path.stat().st_size < self.offset:
                self.__init__(self.path, self.id, self.title, self.model)
            with self.path.open("rb") as stream:
                if self.error.startswith("日志暂不可读"):
                    self.error = ""
                stream.seek(self.offset)
                while True:
                    line = stream.readline()
                    if not line or not line.endswith(b"\n"):
                        break
                    self.offset = stream.tell()
                    try:
                        self.consume(json.loads(line))
                    except (ValueError, KeyError, TypeError):
                        self.error = "日志包含无法解析的记录，读数可能不完整"
                        if self.current:
                            self.current.valid = False
        except OSError as exc:
            self.error = f"日志暂不可读：{exc.strerror or type(exc).__name__}"

    def snapshot(self, now):
        return {
            "thread_id": self.id,
            "title": self.title,
            "model": self.model,
            "start": self.current.start if self.current else 0,
            "current": self.current.metrics(now) if self.current else None,
            "last_finished": self.last_finished.metrics(now) if self.last_finished else None,
            "turns": [turn.metrics(now) for turn in self.turns],
            "error": self.error,
            "metric": "output_tokens / turn_elapsed_seconds",
            "notice": "token 用量按模型请求完成事件更新；每秒刷新的是本轮平均 TPS，不是逐秒解码速度。输出包含推理与工具调用；耗时包含工具和请求等待。",
        }


class Catalog:
    def __init__(self, home, thread_id=None):
        self.home = Path(home).resolve()
        self.thread_id = thread_id
        self.sessions = {}
        self.error = ""

    def discover(self):
        db_path = self.home / "state_5.sqlite"
        if db_path.exists():
            try:
                with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
                    rows = db.execute("SELECT id, rollout_path, title, model FROM threads WHERE archived=0 ORDER BY updated_at DESC LIMIT 30").fetchall()
                    if self.thread_id:
                        rows += db.execute("SELECT id, rollout_path, title, model FROM threads WHERE id=?", (self.thread_id,)).fetchall()
                self.error = ""
                return rows
            except sqlite3.Error:
                self.error = "会话索引暂不可读，正在使用日志目录"
        paths = sorted((self.home / "sessions").glob("**/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if self.thread_id:
            paths = [p for p in paths if self.thread_id in p.name] + paths[:30]
        return [("", str(path), "", "") for path in paths[:31]]

    def poll(self, now=None):
        now = time.time() if now is None else now
        rows = self.discover()
        wanted = {path for _, path, _, _ in rows}
        self.sessions = {path: s for path, s in self.sessions.items() if path in wanted}
        for thread_id, path, title, model in rows:
            session = self.sessions.setdefault(path, Session(path, thread_id, title, model))
            if title:
                session.title = title
            session.poll()
        snapshots = [s.snapshot(now) for s in self.sessions.values() if not s.subagent and s.current]
        return sorted(snapshots, key=lambda s: s["start"], reverse=True)
