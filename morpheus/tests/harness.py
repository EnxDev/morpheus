"""Shared test harness — counters, helpers, service checks."""

import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ── Counters ─────────────────────────────────────────────────────────────────

PASSED = 0
FAILED = 0
SKIPPED = 0
ERRORS: list[str] = []


def run(test_id: str, description: str, fn, *, skip_reason: str | None = None):
    global PASSED, FAILED, SKIPPED
    if skip_reason:
        print(f"  [SKIP] {test_id} — {description} ({skip_reason})")
        SKIPPED += 1
        return
    try:
        fn()
        print(f"  [PASS] {test_id} — {description}")
        PASSED += 1
    except Exception as e:
        print(f"  [FAIL] {test_id} — {description}: {e}")
        FAILED += 1
        ERRORS.append(f"{test_id}: {e}")


def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def print_summary():
    section("SUMMARY")
    total = PASSED + FAILED + SKIPPED
    print(f"  Passed:  {PASSED}")
    print(f"  Failed:  {FAILED}")
    print(f"  Skipped: {SKIPPED}")
    print(f"  Total:   {total}")

    if ERRORS:
        print(f"\n  Failures:")
        for err in ERRORS:
            print(f"    ✗ {err}")

    print()
    return FAILED == 0


# ── Service checks ───────────────────────────────────────────────────────────

def check_ollama() -> bool:
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def check_backend() -> bool:
    try:
        import requests
        r = requests.get("http://localhost:8000/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


OLLAMA_AVAILABLE = check_ollama()
BACKEND_AVAILABLE = check_backend()
