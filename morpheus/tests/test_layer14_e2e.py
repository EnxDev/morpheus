"""Layer 14 — Pipeline E2E (mock)"""

from tests.harness import run, section


def register(run_fn=run):
    section("Layer 14 — Pipeline E2E (mock)")

    def test_14_1():
        from tests.test_cases import run_e2e_tests
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_e2e_tests()
        output = buf.getvalue()
        assert "Results:" in output
        for line in output.split("\n"):
            if line.startswith("Results:"):
                parts = line.split()
                ratio = parts[1]
                passed_count = int(ratio.split("/")[0])
                assert passed_count >= 15, f"Only {passed_count}/20 passed"

    run_fn("14.1", "E2E mock tests: 15+ of 20 pass", test_14_1)
