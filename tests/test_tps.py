import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing


SCRIPT = Path(__file__).resolve().parents[1] / "plugins/codex-tps-inline/scripts/tps.py"
spec = importlib.util.spec_from_file_location("tps", SCRIPT)
tps = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tps
spec.loader.exec_module(tps)


def event(when, message, **values):
    return {"timestamp": when, "type": "event_msg", "payload": {"type": message, **values}}


def record(when, turn_id, output, reasoning=0):
    return {
        "timestamp": when,
        "type": "token_usage_record",
        "payload": {"turn_id": turn_id, "turn_token_usage": {"output_tokens": output, "reasoning_output_tokens": reasoning}},
    }


def legacy(when, output):
    return event(when, "token_count", info={"total_token_usage": {"output_tokens": output}})


class ThroughputTests(unittest.TestCase):
    def setUp(self):
        self.session = tps.Session("unused.jsonl", "thread")

    def consume(self, *events):
        for value in events:
            self.session.consume(value)

    def test_live_mean_changes_with_elapsed_time_and_final_value_freezes(self):
        self.consume(event(100, "task_started", turn_id="one"), record(110, "one", 100))
        self.assertEqual(self.session.snapshot(110)["current"]["average_tps"], 10)
        self.assertEqual(self.session.snapshot(120)["current"]["average_tps"], 5)
        self.consume(event(125, "task_complete", turn_id="one", duration_ms=20000))
        self.assertEqual(self.session.snapshot(1000)["current"]["average_tps"], 5)

    def test_reasoning_is_included_once_and_legacy_event_is_not_double_counted(self):
        self.consume(event(100, "task_started", turn_id="one"), record(110, "one", 100, 60), legacy(110, 100))
        metrics = self.session.snapshot(110)["current"]
        self.assertEqual(metrics["output_tokens"], 100)
        self.assertEqual(metrics["average_tps"], 10)

    def test_previous_turns_output_is_excluded(self):
        self.consume(
            event(100, "task_started", turn_id="one"), legacy(110, 100),
            event(110, "task_complete", turn_id="one"),
            event(200, "task_started", turn_id="two"), legacy(205, 150),
        )
        metrics = self.session.snapshot(205)
        self.assertEqual(metrics["current"]["output_tokens"], 50)
        self.assertEqual(metrics["current"]["average_tps"], 10)
        self.assertEqual(metrics["last_finished"]["output_tokens"], 100)

    def test_repeated_usage_and_start_do_not_reset_or_inflate_the_turn(self):
        self.consume(event(100, "task_started", turn_id="one"), legacy(110, 100),
                     event(111, "task_started", turn_id="one"), legacy(111, 100))
        self.assertEqual(self.session.snapshot(120)["current"]["average_tps"], 5)

    def test_missing_usage_stays_unavailable(self):
        self.consume(event(100, "task_started", turn_id="one"), event(101, "token_count", info=None))
        self.assertIsNone(self.session.snapshot(120)["current"]["average_tps"])

    def test_zero_duration_is_unavailable(self):
        self.consume(event(100, "task_started", turn_id="one"), record(100, "one", 100),
                     event(100, "task_complete", turn_id="one", duration_ms=0))
        self.assertIsNone(self.session.snapshot(120)["current"]["average_tps"])

    def test_counter_reset_does_not_produce_a_fake_speed(self):
        self.consume(event(100, "task_started", turn_id="one"), legacy(110, 100), legacy(115, 5))
        self.assertIsNone(self.session.snapshot(120)["current"]["average_tps"])

    def test_authoritative_turn_usage_can_recover_a_legacy_counter_reset(self):
        self.consume(event(100, "task_started", turn_id="one"), legacy(110, 100), legacy(115, 5),
                     record(120, "one", 150))
        self.assertEqual(self.session.snapshot(120)["current"]["average_tps"], 7.5)

    def test_another_turns_record_and_completion_are_ignored(self):
        self.consume(event(100, "task_started", turn_id="one"), record(110, "other", 999),
                     event(110, "task_complete", turn_id="other"))
        self.assertIsNone(self.session.current.output)
        self.assertIsNone(self.session.current.end)

    def test_aborted_task_has_a_separate_status(self):
        self.consume(event(100, "task_started", turn_id="one"), record(110, "one", 100),
                     event(120, "turn_aborted", turn_id="one"))
        self.assertEqual(self.session.snapshot(1000)["current"]["status"], "已中断")
        self.assertEqual(self.session.snapshot(1000)["last_finished"]["average_tps"], 5)

    def test_completed_turn_accepts_late_usage_without_changing_duration(self):
        self.consume(event(100, "task_started", turn_id="one"),
                     event(120, "task_complete", turn_id="one", duration_ms=20000),
                     record(125, "one", 100))
        self.assertEqual(self.session.snapshot(1000)["last_finished"]["average_tps"], 5)

    def test_history_keeps_each_turns_mean_and_exact_reply_ids(self):
        self.consume(event(100, "task_started", turn_id="one"),
                     event(101, "item_completed", item={"type": "UserMessage", "id": "user-one"}),
                     record(110, "one", 100),
                     {"timestamp": 110, "type": "response_item", "payload": {"type": "message", "phase": "final_answer", "id": "reply-one"}},
                     event(120, "task_complete", turn_id="one", duration_ms=20000),
                     event(200, "task_started", turn_id="two"), record(210, "two", 200))
        history = self.session.snapshot(210)["turns"]
        self.assertEqual(history[0]["average_tps"], 5)
        self.assertEqual(history[0]["final_ids"], ["reply-one"])
        self.assertEqual(history[0]["user_ids"], ["user-one"])
        self.assertEqual(history[1]["average_tps"], 20)
        self.assertEqual(history[1]["final_ids"], [])

    def test_partial_jsonl_write_is_retained_and_input_is_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            first = (json.dumps(event(100, "task_started", turn_id="one")) + "\n").encode()
            second = (json.dumps(record(110, "one", 100)) + "\n").encode()
            path.write_bytes(first + second[:15])
            session = tps.Session(path)
            session.poll()
            self.assertIsNone(session.current.output)
            with path.open("ab") as stream:
                stream.write(second[15:])
            expected = path.read_bytes()
            session.poll()
            session.poll()
            self.assertEqual(session.current.output, 100)
            self.assertEqual(path.read_bytes(), expected)

    def test_catalog_keeps_threads_separate_and_excludes_subagents(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            rows = []
            for name, source, output in [("main", "vscode", 100), ("other", "cli", 200), ("child", {"subagent": {}}, 999)]:
                path = home / (name + ".jsonl")
                records = [
                    {"timestamp": 99, "type": "session_meta", "payload": {"id": name, "source": source}},
                    event(100, "task_started", turn_id=name), record(110, name, output),
                ]
                path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
                rows.append((name, str(path), "中文对话 " + name, "model", 0, 100))
            with closing(sqlite3.connect(home / "state_5.sqlite")) as db, db:
                db.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT, title TEXT, model TEXT, archived INT, updated_at INT)")
                db.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?)", rows)
            snapshots = tps.Catalog(home).poll(now=110)
            rates = {s["thread_id"]: s["current"]["average_tps"] for s in snapshots}
            self.assertEqual(rates, {"main": 10, "other": 20})


if __name__ == "__main__":
    unittest.main()
