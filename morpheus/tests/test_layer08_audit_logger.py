"""Layer 8 — Audit Logger"""

import json
import os
import tempfile

from tests.harness import run, section
from audit.logger import AuditLogger, FileAuditSink, InMemorySink


def register(run_fn=run):
    section("Layer 8 — Audit Logger")

    def test_8_1():
        logger = AuditLogger()
        logger.log("test_event", {"key": "val"})
        log = logger.get_log()
        assert len(log) == 1
        assert log[0]["event_type"] == "test_event"
        assert "timestamp" in log[0]

    def test_8_2():
        logger = AuditLogger()
        for i in range(10):
            logger.log(f"event_{i}")
        last3 = logger.last(3)
        assert len(last3) == 3

    def test_8_3():
        logger = AuditLogger()
        logger.log("a")
        logger.log("a")
        logger.log("b")
        s = logger.summary()
        assert s["a"] == 2
        assert s["b"] == 1

    def test_8_4():
        logger = AuditLogger()
        logger.log("test", {"x": 1})
        j = logger.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, list)

    def test_8_5():
        logger = AuditLogger()
        logger.log("test", {"x": 1})
        csv_str = logger.export_csv()
        assert "event_type" in csv_str
        assert "timestamp" in csv_str

    def test_8_6():
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            sink = FileAuditSink(path)
            logger = AuditLogger(sinks=[sink])
            logger.log("file_test", {"key": "val"})
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == 1
            parsed = json.loads(lines[0])
            assert parsed["event_type"] == "file_test"
        finally:
            os.unlink(path)

    def test_8_7():
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            sink1 = FileAuditSink(path)
            l1 = AuditLogger(sinks=[sink1])
            l1.log("batch_1")
            sink2 = FileAuditSink(path)
            l2 = AuditLogger(sinks=[sink2])
            l2.log("batch_2")
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == 2
        finally:
            os.unlink(path)

    def test_8_8():
        logger_test = AuditLogger()
        logger_test.log("test", {"error": "Auth failed: sk-proj-abc123def456ghi789jkl012mno345", "key": "normal"})
        log = logger_test.get_log()
        payload = log[0]["payload"]
        assert "sk-proj-" not in payload["error"]
        assert "[REDACTED_API_KEY]" in payload["error"]
        assert payload["key"] == "normal"

    def test_8_9():
        logger_test = AuditLogger()
        logger_test.log("test", {"url": "postgresql://user:pass@db.internal:5432/prod"})
        log = logger_test.get_log()
        assert "postgresql://" not in log[0]["payload"]["url"]
        assert "[REDACTED_CONN_STRING]" in log[0]["payload"]["url"]

    def test_8_10():
        logger_test = AuditLogger()
        logger_test.log("test", {"nested": {"token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def"}})
        log = logger_test.get_log()
        assert "eyJ" not in json.dumps(log[0]["payload"])

    run_fn("8.1", "log() appends event with timestamp", test_8_1)
    run_fn("8.2", "last(n) returns correct count", test_8_2)
    run_fn("8.3", "summary() returns correct counts", test_8_3)
    run_fn("8.4", "to_json() produces valid JSON", test_8_4)
    run_fn("8.5", "export_csv() produces valid CSV", test_8_5)
    run_fn("8.6", "FileAuditSink writes JSONL", test_8_6)
    run_fn("8.7", "FileAuditSink appends on restart", test_8_7)
    run_fn("8.8", "Secret redaction: API keys redacted", test_8_8)
    run_fn("8.9", "Secret redaction: connection strings redacted", test_8_9)
    run_fn("8.10", "Secret redaction: nested dicts redacted", test_8_10)
