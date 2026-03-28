import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domain.registry import DomainRegistry

# Backwards compatibility: expose the legacy format
# New code should use config.capabilities directly.


def _to_legacy_format(cap):
    requires = [f for f, w in cap.field_weights.items() if w >= 0.8]
    optional = [f for f, w in cap.field_weights.items() if 0 < w < 0.8]
    return {"action": cap.action, "requires": requires, "optional": optional}


def get_capabilities():
    config = DomainRegistry.default()
    return [_to_legacy_format(cap) for cap in config.capabilities]


CAPABILITIES = [
    {
        "action":   "query_chart",
        "requires": ["measure", "time_range"],
        "optional": ["dimension", "filters", "granularity", "comparison"],
    },
    {
        "action":   "export_csv",
        "requires": ["measure", "time_range"],
        "optional": ["filters"],
    },
    {
        "action":   "save_dashboard",
        "requires": ["measure", "time_range", "dimension"],
        "optional": ["filters", "granularity"],
    },
    {
        "action":   "compare_periods",
        "requires": ["measure", "time_range", "comparison"],
        "optional": ["dimension", "filters"],
    },
]
