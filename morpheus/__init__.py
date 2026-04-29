"""Morpheus — a deterministic intent control layer for MCP-tool-calling agents.

This package exposes the user-facing modules under their documented import
paths so that ``from morpheus.proxy import MorpheusProxy``,
``from morpheus.policies.ibac import DeterministicEvaluator``,
``from morpheus.sdk import MorpheusClient`` and similar imports resolve when
the repository root is on ``sys.path`` (the standard installation layout).

The subpackages own their own re-exports — for instance
``morpheus/proxy/__init__.py`` already re-exports ``MorpheusProxy`` from
``proxy.proxy_server``. This file is intentionally a thin marker: turning
the directory into a regular package, holding the project-level docstring,
and version metadata, without performing eager imports that could create
circular-dependency surprises during the bootstrap of any submodule.

The project also runs from inside ``morpheus/`` as the working directory,
in which case the top-level packages are ``proxy``, ``policies``, ``sdk``
etc. directly. Both modes work; this shim only enables the
``morpheus.X``-prefixed form for code and documentation that prefers it.
"""

__version__ = "0.1.0-alpha"
