"""Layer 10 — MCP Proxy: Policy Checker"""

from tests.harness import run, section
from proxy.policy_checker import PolicyChecker, classify_risk, PolicyRule


def register(run_fn=run):
    section("Layer 10 — MCP Proxy: Policy Checker")

    def test_10_1():
        assert classify_risk("delete_repo") == "high"

    def test_10_2():
        assert classify_risk("send_email") == "medium"

    def test_10_3():
        assert classify_risk("get_weather") == "low"

    def test_10_4():
        assert classify_risk("custom_thing") == "unknown"

    def test_10_5():
        pc = PolicyChecker()
        d = pc.check_action("delete_repo", {})
        assert d.status == "blocked"

    def test_10_6():
        pc = PolicyChecker()
        d = pc.check_action("get_weather", {"location": "Rome"})
        assert d.status == "approved"

    def test_10_7():
        pc = PolicyChecker()
        d = pc.check_action("send_email", {"to": "a@b.com"})
        assert d.status in ("approved", "blocked")

    def test_10_8():
        pc = PolicyChecker()
        d = pc.check_action("delete_repo", {}, controls_active={
            "input_validation": True, "action_validation": False, "coherence_check": True
        })
        assert d.status == "bypassed"

    def test_10_9():
        pc = PolicyChecker()
        rule = PolicyRule(tool_pattern="send_*", blocked_for_roles=["viewer"])
        pc.add_rule(rule)
        d = pc.check_action("send_email", {}, user_role="viewer")
        assert d.status == "blocked"
        assert "role" in d.reason.lower()

    def test_10_10():
        pc = PolicyChecker()
        rule = PolicyRule(tool_pattern="get_*", max_calls_per_session=2, auto_approve=True)
        pc.add_rule(rule)
        from proxy.policy_checker import reset_session
        reset_session("rate_test")
        pc.check_action("get_data", {}, session_id="rate_test")
        pc.check_action("get_data", {}, session_id="rate_test")
        d = pc.check_action("get_data", {}, session_id="rate_test")
        assert d.status == "blocked"
        assert "rate limit" in d.reason.lower()

    def test_10_11():
        pc = PolicyChecker()
        d = pc.check_action("delete_repo", {}, controls_active={
            "input_validation": True, "action_validation": True, "coherence_check": False
        })
        assert d.status == "blocked"

    def test_10_12():
        pc = PolicyChecker()
        d = pc.check_action("send_email", {}, controls_active={
            "input_validation": True, "action_validation": True, "coherence_check": False
        })
        assert d.status == "bypassed"

    def test_10_13():
        d = PolicyChecker().check_action("get_weather", {"loc": "x"})
        dd = d.to_dict()
        assert "status" in dd
        assert "tool_name" in dd
        assert "controls_active" in dd
        assert "timestamp" in dd

    run_fn("10.1", "classify_risk: delete_* → high", test_10_1)
    run_fn("10.2", "classify_risk: send_* → medium", test_10_2)
    run_fn("10.3", "classify_risk: get_* → low", test_10_3)
    run_fn("10.4", "classify_risk: unknown pattern → unknown", test_10_4)
    run_fn("10.5", "High-risk tool → blocked", test_10_5)
    run_fn("10.6", "Low-risk tool → approved", test_10_6)
    run_fn("10.7", "Medium-risk tool → L2 flow", test_10_7)
    run_fn("10.8", "action_validation=False → bypassed", test_10_8)
    run_fn("10.9", "Role-blocked user → blocked", test_10_9)
    run_fn("10.10", "Rate limit exceeded → blocked", test_10_10)
    run_fn("10.11", "High risk: blocked at L1 even with L2 disabled", test_10_11)
    run_fn("10.12", "Medium risk, L2 disabled → bypassed", test_10_12)
    run_fn("10.13", "ActionDecision.to_dict() has all Vision fields", test_10_13)
