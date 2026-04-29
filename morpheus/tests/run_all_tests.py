"""Morpheus — Comprehensive Test Runner

Runs all testable layers without external services (except Ollama if available).
No pytest needed — pure Python with assert.

Usage:
    cd morpheus
    python tests/run_all_tests.py
"""

import sys
import os
from pathlib import Path

# Ensure project root is on path (before any project imports)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from tests.harness import (
    run, print_summary,
    OLLAMA_AVAILABLE, BACKEND_AVAILABLE,
)

print(f"Ollama:  {'✓ running' if OLLAMA_AVAILABLE else '✗ not running (some tests will be skipped)'}")
print(f"Backend: {'✓ running' if BACKEND_AVAILABLE else '✗ not running (API tests will be skipped)'}")

# Import and register all test layers
from tests.test_layer01_intent_schema import register as reg01
from tests.test_layer02_domain_config import register as reg02
from tests.test_layer03_confidence_policy import register as reg03
from tests.test_layer03b_sanitizer import register as reg03b
from tests.test_layer03c_coherence import register as reg03c
from tests.test_layer03d_session_guard import register as reg03d
from tests.test_layer04_validator import register as reg04
from tests.test_layer05_clarifier import register as reg05
from tests.test_layer06_decision_engine import register as reg06
from tests.test_layer07_execution import register as reg07
from tests.test_layer08_audit_logger import register as reg08
from tests.test_layer09_controls import register as reg09
from tests.test_layer10_policy_checker import register as reg10
from tests.test_layer11_proxy_server import register as reg11
from tests.test_layer11b_streamable_http import register as reg11b
from tests.test_layer12_mcp_server import register as reg12
from tests.test_layer13_fastapi import register as reg13
from tests.test_layer14_e2e import register as reg14
from tests.test_layer15_ibac import register as reg15

reg01(run)
reg02(run)
reg03(run)
reg03b(run)
reg03c(run)
reg03d(run)
reg04(run)
reg05(run)
reg06(run)
reg07(run)
reg08(run)
reg09(run)
reg10(run)
reg11(run)
reg11b(run)
reg12(run)
reg13(run)
reg14(run)
reg15(run)

# ── Summary ─────────────────────────────────────────────────────────────────

success = print_summary()
sys.exit(0 if success else 1)
