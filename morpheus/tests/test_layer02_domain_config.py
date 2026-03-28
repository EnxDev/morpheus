"""Layer 2 — Domain Config"""

from tests.harness import run, section
from intent.schema import INTENT_FIELDS
from domain.config import DomainConfig, FieldDefinition, CapabilityDefinition
from domain.registry import DomainRegistry


def register(run_fn=run):
    section("Layer 2 — Domain Config")

    def test_2_1():
        config = DomainRegistry.default()
        assert config.name == "generic_bi"

    def test_2_2():
        cfg = DomainConfig(
            name="test_domain",
            domain_description="Test",
            fields=[FieldDefinition(name="f1", label="F1", description="Field 1", threshold=0.7, weight=1.0, priority=1)],
            capabilities=[CapabilityDefinition(action="act1", field_weights={"f1": 1.0})],
        )
        DomainRegistry.register(cfg)
        got = DomainRegistry.get("test_domain")
        assert got.name == "test_domain"

    def test_2_3():
        config = DomainRegistry.default()
        assert len(config.fields) == 6

    def test_2_4():
        config = DomainRegistry.default()
        assert len(config.capabilities) == 4

    def test_2_5():
        config = DomainRegistry.default()
        names = config.field_names
        for f in INTENT_FIELDS:
            assert f in names, f"Missing field: {f}"

    def test_2_6():
        config = DomainRegistry.default()
        t = config.thresholds
        assert t["measure"] == 0.90
        assert t["comparison"] == 0.60

    run_fn("2.1", "DomainRegistry.default() returns Superset config", test_2_1)
    run_fn("2.2", "Register + get custom domain", test_2_2)
    run_fn("2.3", "Superset has 6 fields", test_2_3)
    run_fn("2.4", "Superset has 4 capabilities", test_2_4)
    run_fn("2.5", "field_names includes all INTENT_FIELDS", test_2_5)
    run_fn("2.6", "thresholds match spec", test_2_6)
