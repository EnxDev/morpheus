"""Layer 7 — Execution"""

from tests.harness import run, section
from domain.registry import DomainRegistry
from execution.plan import build_plan
from execution.engine import execute_plan
from execution.review import PlanReviewer
from audit.logger import AuditLogger


def register(run_fn=run):
    section("Layer 7 — Execution")

    def test_7_1():
        config = DomainRegistry.default()
        plan = build_plan("query_chart", config)
        assert len(plan) > 0
        assert all("step" in s and "type" in s for s in plan)

    def test_7_2():
        config = DomainRegistry.default()
        for action in ["query_chart", "export_csv", "save_dashboard", "compare_periods"]:
            plan = build_plan(action, config)
            assert len(plan) > 0, f"No plan for {action}"

    def test_7_3():
        config = DomainRegistry.default()
        plan = build_plan("query_chart", config)
        logger = AuditLogger()
        execute_plan(plan, logger)
        events = [e.event_type for e in logger.get_events()]
        assert "step_started" in events or "step_completed" in events

    def test_7_4():
        config = DomainRegistry.default()
        plan = build_plan("query_chart", config)
        reviewer = PlanReviewer()
        result = reviewer.review(plan, "query_chart")
        assert result.approved is True
        assert len([i for i in result.issues if i.severity == "error"]) == 0

    def test_7_5():
        config = DomainRegistry.default()
        reviewer = PlanReviewer()
        for action in ["query_chart", "export_csv", "save_dashboard", "compare_periods"]:
            plan = build_plan(action, config)
            result = reviewer.review(plan, action)
            assert result.approved is True, f"Plan for {action} was blocked: {result.issues}"

    def test_7_6():
        reviewer = PlanReviewer()
        result = reviewer.review([], "empty_action")
        assert result.blocked is True
        assert any("empty" in i.description.lower() for i in result.issues)

    def test_7_7():
        reviewer = PlanReviewer(constraints={"max_plan_steps": 3, "max_total_timeout_ms": 999999, "max_side_effect_steps": 99, "max_retries_per_step": 99})
        plan = [{"step": f"s{i}", "type": "pure", "timeout_ms": 100} for i in range(5)]
        result = reviewer.review(plan, "test")
        assert result.blocked is True
        assert any("exceeds max" in i.description for i in result.issues)

    def test_7_8():
        reviewer = PlanReviewer(constraints={"max_total_timeout_ms": 1000, "max_plan_steps": 99, "max_side_effect_steps": 99, "max_retries_per_step": 99})
        plan = [
            {"step": "fast", "type": "pure", "timeout_ms": 500},
            {"step": "slow", "type": "side_effect", "timeout_ms": 800},
        ]
        result = reviewer.review(plan, "test")
        assert result.blocked is True
        assert any("timeout" in i.description.lower() for i in result.issues)

    def test_7_9():
        config = DomainRegistry.default()
        plan = build_plan("query_chart", config)
        reviewer = PlanReviewer()
        result = reviewer.review(plan, "query_chart")
        s = result.plan_summary
        assert s["action"] == "query_chart"
        assert s["total_steps"] == len(plan)
        assert "has_side_effects" in s

    run_fn("7.1", "build_plan returns steps for query_chart", test_7_1)
    run_fn("7.2", "build_plan returns steps for all 4 actions", test_7_2)
    run_fn("7.3", "execute_plan logs step events", test_7_3)
    run_fn("7.4", "PlanReviewer approves valid plan", test_7_4)
    run_fn("7.5", "PlanReviewer approves all 4 domain plans", test_7_5)
    run_fn("7.6", "PlanReviewer blocks empty plan", test_7_6)
    run_fn("7.7", "PlanReviewer blocks plan exceeding max steps", test_7_7)
    run_fn("7.8", "PlanReviewer blocks plan exceeding total timeout", test_7_8)
    run_fn("7.9", "PlanReviewer summary includes correct metadata", test_7_9)
