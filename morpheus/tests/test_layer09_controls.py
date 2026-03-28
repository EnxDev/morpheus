"""Layer 9 — Controls"""

from tests.harness import run, section
from controls import ControlManager, ControlConfig
from audit.logger import AuditLogger


def register(run_fn=run):
    section("Layer 9 — Controls")

    def test_9_1():
        cm = ControlManager()
        c = cm.get_controls()
        assert c.input_validation is True
        assert c.action_validation is True
        assert c.coherence_check is True

    def test_9_2():
        cm = ControlManager()
        cm.set_controls(input_validation=False)
        assert cm.get_controls().input_validation is False
        assert cm.get_controls().action_validation is True

    def test_9_3():
        logger = AuditLogger()
        cm = ControlManager(logger=logger)
        cm.set_controls(action_validation=False, reason="testing")
        log = logger.get_log()
        assert any(e["event_type"] == "control_state_changed" for e in log)

    def test_9_4():
        logger = AuditLogger()
        cm = ControlManager(logger=logger)
        cm.set_controls()
        assert len(logger.get_log()) == 0

    def test_9_5():
        c = ControlConfig()
        d = c.to_dict()
        assert d == {"input_validation": True, "action_validation": True, "coherence_check": True}

    run_fn("9.1", "Default controls: all enabled", test_9_1)
    run_fn("9.2", "Toggle individual control", test_9_2)
    run_fn("9.3", "State change logged to audit", test_9_3)
    run_fn("9.4", "No log when state unchanged", test_9_4)
    run_fn("9.5", "to_dict() returns correct structure", test_9_5)
