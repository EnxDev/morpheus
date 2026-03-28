"""Layer 15 — Intent-Based Access Control (IBAC)"""

from tests.harness import run, section
from policies.ibac import (
    AuthorizationTuple,
    TupleTemplate,
    IntentPolicyMapper,
    DeterministicEvaluator,
    TupleEvaluator,
)
from domain.registry import DomainRegistry


def register(run_fn=run):
    section("Layer 15 — IBAC: Authorization Tuples")

    # ── AuthorizationTuple matching ──────────────────────────────────

    def test_15_1():
        t = AuthorizationTuple("E003", "read", "payroll:E003")
        assert t.matches("read", "payroll:E003") is True

    def test_15_2():
        t = AuthorizationTuple("E003", "read", "payroll:E003")
        assert t.matches("write", "payroll:E003") is False

    def test_15_3():
        t = AuthorizationTuple("E003", "read", "payroll:E003")
        assert t.matches("read", "payroll:E001") is False

    def test_15_4():
        # Wildcard: data:* matches data:revenue, data:orders, and bare "data"
        t = AuthorizationTuple("system", "read", "data:*")
        assert t.matches("read", "data:revenue") is True
        assert t.matches("read", "data:orders") is True
        assert t.matches("read", "data") is True
        assert t.matches("write", "data:revenue") is False

    def test_15_5():
        # Action wildcard
        t = AuthorizationTuple("system", "*", "logs")
        assert t.matches("read", "logs") is True
        assert t.matches("delete", "logs") is True

    # ── TupleTemplate resolution ─────────────────────────────────────

    def test_15_6():
        tmpl = TupleTemplate(action="read", resource="payroll:{subject}", required_fields=["subject"])
        resolved = tmpl.resolve("E003", {"subject": "E003"})
        assert resolved is not None
        assert resolved.resource == "payroll:E003"
        assert resolved.principal == "E003"

    def test_15_7():
        # Missing required field → None
        tmpl = TupleTemplate(action="read", resource="payroll:{subject}", required_fields=["subject"])
        assert tmpl.resolve("E003", {"subject": None}) is None

    def test_15_8():
        # No required fields → always resolves
        tmpl = TupleTemplate(action="read", resource="data:*")
        resolved = tmpl.resolve("system", {})
        assert resolved is not None
        assert resolved.resource == "data:*"

    # ── IntentPolicyMapper ───────────────────────────────────────────

    def test_15_9():
        mapper = IntentPolicyMapper()
        result = mapper.map(
            intent_values={"measure": "revenue"},
            intent_confidences={"measure": 0.95},
            templates=[TupleTemplate(action="read", resource="data:{measure}", required_fields=["measure"])],
            thresholds={"measure": 0.90},
            principal="user1",
            action_name="query_chart",
        )
        assert len(result.tuples) == 1
        assert result.tuples[0].resource == "data:revenue"
        assert not result.has_errors

    def test_15_10():
        # Low confidence → tuple NOT generated, error recorded
        mapper = IntentPolicyMapper()
        result = mapper.map(
            intent_values={"measure": "revenue"},
            intent_confidences={"measure": 0.50},
            templates=[TupleTemplate(action="read", resource="data:{measure}", required_fields=["measure"])],
            thresholds={"measure": 0.90},
            principal="user1",
            action_name="query_chart",
        )
        assert len(result.tuples) == 0
        assert result.has_errors
        assert result.errors[0].field_name == "measure"

    def test_15_11():
        # Null field value → error
        mapper = IntentPolicyMapper()
        result = mapper.map(
            intent_values={"measure": None},
            intent_confidences={"measure": 0.95},
            templates=[TupleTemplate(action="read", resource="data:{measure}", required_fields=["measure"])],
            thresholds={"measure": 0.90},
            principal="user1",
            action_name="query_chart",
        )
        assert result.has_errors

    def test_15_12():
        # Multiple templates, partial resolution
        mapper = IntentPolicyMapper()
        result = mapper.map(
            intent_values={"measure": "revenue", "subject": None},
            intent_confidences={"measure": 0.95, "subject": 0.0},
            templates=[
                TupleTemplate(action="read", resource="data:{measure}", required_fields=["measure"]),
                TupleTemplate(action="read", resource="user:{subject}", required_fields=["subject"]),
            ],
            thresholds={"measure": 0.90, "subject": 0.80},
            principal="user1",
            action_name="test",
        )
        assert len(result.tuples) == 1  # only data:revenue
        assert result.has_errors  # subject failed

    # ── DeterministicEvaluator ───────────────────────────────────────

    def test_15_13():
        # Pure steps always allowed
        e = DeterministicEvaluator()
        r = e.evaluate([], {"step": "build_query", "type": "pure"})
        assert r.allowed is True

    def test_15_14():
        # Side-effect with matching tuple → allowed
        e = DeterministicEvaluator()
        tuples = [AuthorizationTuple("system", "read", "data:*")]
        r = e.evaluate(tuples, {"step": "execute_query", "type": "side_effect", "requires": "read:data"})
        assert r.allowed is True

    def test_15_15():
        # Side-effect with NO matching tuple → blocked
        e = DeterministicEvaluator()
        tuples = [AuthorizationTuple("system", "read", "data:*")]
        r = e.evaluate(tuples, {"step": "send_email", "type": "side_effect", "requires": "write:email"})
        assert r.allowed is False

    def test_15_16():
        # delete_records blocked when only read tuples exist
        e = DeterministicEvaluator()
        tuples = [AuthorizationTuple("system", "read", "data:*")]
        r = e.evaluate(tuples, {"step": "delete_records", "type": "side_effect", "requires": "delete:data"})
        assert r.allowed is False

    def test_15_17():
        # Full plan from BI domain passes with correct tuples
        e = DeterministicEvaluator()
        tuples = [
            AuthorizationTuple("system", "read", "chart:revenue"),
            AuthorizationTuple("system", "read", "data:*"),
        ]
        plan = [
            {"step": "resolve_time_range", "type": "pure"},
            {"step": "build_sql_query",    "type": "pure"},
            {"step": "execute_query",      "type": "side_effect", "requires": "read:data"},
            {"step": "render_chart",       "type": "pure"},
        ]
        for step in plan:
            r = e.evaluate(tuples, step)
            assert r.allowed is True, f"Step {step['step']} should be allowed but: {r.reason}"

    def test_15_18():
        # Plan with rogue step is blocked
        e = DeterministicEvaluator()
        tuples = [AuthorizationTuple("system", "read", "data:*")]
        plan = [
            {"step": "build_query", "type": "pure"},
            {"step": "execute_query", "type": "side_effect", "requires": "read:data"},
            {"step": "send_to_ceo", "type": "side_effect", "requires": "write:email"},
        ]
        results = [e.evaluate(tuples, s) for s in plan]
        assert results[0].allowed is True   # pure
        assert results[1].allowed is True   # read:data matches
        assert results[2].allowed is False  # write:email has no tuple

    def test_15_19():
        # Protocol compliance
        e = DeterministicEvaluator()
        assert isinstance(e, TupleEvaluator)

    def test_15_20():
        # Full integration: domain config → mapper → evaluator
        config = DomainRegistry.default()
        cap = None
        for c in config.capabilities:
            if c.action == "query_chart":
                cap = c
                break
        assert cap is not None
        assert len(cap.authorized_tuples) > 0

        # Map intent to tuples
        mapper = IntentPolicyMapper()
        templates = [
            TupleTemplate(
                action=t["action"],
                resource=t["resource"],
                required_fields=t.get("required_fields", []),
            )
            for t in cap.authorized_tuples
        ]
        result = mapper.map(
            intent_values={"measure": "revenue"},
            intent_confidences={"measure": 0.95},
            templates=templates,
            thresholds=config.thresholds,
            principal="test_user",
            action_name="query_chart",
        )
        assert len(result.tuples) >= 1
        assert not result.has_errors

    run_fn("15.1", "AuthTuple: exact match", test_15_1)
    run_fn("15.2", "AuthTuple: wrong action rejected", test_15_2)
    run_fn("15.3", "AuthTuple: wrong resource rejected", test_15_3)
    run_fn("15.4", "AuthTuple: wildcard data:* matches data:revenue and data", test_15_4)
    run_fn("15.5", "AuthTuple: action wildcard * matches any action", test_15_5)
    run_fn("15.6", "TupleTemplate: resolves {subject} from intent", test_15_6)
    run_fn("15.7", "TupleTemplate: null required field → None", test_15_7)
    run_fn("15.8", "TupleTemplate: no required fields → always resolves", test_15_8)
    run_fn("15.9", "PolicyMapper: generates tuple from intent", test_15_9)
    run_fn("15.10", "PolicyMapper: low confidence → tuple blocked + error", test_15_10)
    run_fn("15.11", "PolicyMapper: null field value → error", test_15_11)
    run_fn("15.12", "PolicyMapper: partial resolution (1 ok, 1 error)", test_15_12)
    run_fn("15.13", "Evaluator: pure steps always allowed", test_15_13)
    run_fn("15.14", "Evaluator: side-effect with matching tuple → allowed", test_15_14)
    run_fn("15.15", "Evaluator: side-effect with no match → blocked", test_15_15)
    run_fn("15.16", "Evaluator: delete blocked when only read tuples", test_15_16)
    run_fn("15.17", "Evaluator: full BI plan passes with correct tuples", test_15_17)
    run_fn("15.18", "Evaluator: rogue step in plan → blocked", test_15_18)
    # ── Sensitive resources ─────────────────────────────────────────

    def test_15_21():
        # Wildcard covers non-sensitive resource
        t = AuthorizationTuple("system", "read", "payroll:*")
        assert t.matches("read", "payroll:self") is True
        assert t.matches("read", "payroll:E003") is True

    def test_15_22():
        # Wildcard BLOCKED on sensitive resource
        t = AuthorizationTuple("system", "read", "payroll:*")
        sensitive = {"payroll:ceo", "payroll:all_employees"}
        assert t.matches("read", "payroll:self", sensitive) is True       # not sensitive
        assert t.matches("read", "payroll:ceo", sensitive) is False       # sensitive → blocked
        assert t.matches("read", "payroll:all_employees", sensitive) is False

    def test_15_23():
        # Exact tuple still works on sensitive resource
        t = AuthorizationTuple("system", "read", "payroll:ceo")
        sensitive = {"payroll:ceo"}
        assert t.matches("read", "payroll:ceo", sensitive) is True  # exact match, always works

    def test_15_24():
        # Evaluator with sensitive resources blocks wildcard on sensitive step
        e = DeterministicEvaluator(sensitive_resources={"payroll:all_salaries"})
        tuples = [AuthorizationTuple("system", "read", "payroll:*")]

        ok_step = {"step": "fetch_my_payroll", "type": "side_effect", "requires": "read:payroll:self"}
        r = e.evaluate(tuples, ok_step)
        assert r.allowed is True  # payroll:self is not sensitive

        bad_step = {"step": "export_salaries", "type": "side_effect", "requires": "read:payroll:all_salaries"}
        r = e.evaluate(tuples, bad_step)
        assert r.allowed is False  # payroll:all_salaries is sensitive, wildcard blocked

    run_fn("15.19", "Evaluator: implements TupleEvaluator Protocol", test_15_19)
    run_fn("15.20", "Integration: domain config → mapper → evaluator", test_15_20)
    run_fn("15.21", "Wildcard covers non-sensitive resources", test_15_21)
    run_fn("15.22", "Wildcard BLOCKED on sensitive resources", test_15_22)
    run_fn("15.23", "Exact tuple works on sensitive resources", test_15_23)
    run_fn("15.24", "Evaluator: sensitive resource blocks wildcard", test_15_24)
