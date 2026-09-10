"""
SAP change-impact analysis for abapGit exports and SAP BTP (CAP / Fiori) code.

Two layers, deliberately separated:

  1. deterministic  -- scan a directory, classify every development object and
                       extract the reference graph from the source syntax.
                       Reproducible, auditable, no model in the loop.
  2. explanatory    -- hand the resulting (closed) impact set to an LLM to
                       explain business impact, regression scope and rollout
                       risk in natural language.

Entry point: python -m tools.sap_impact.cli --help
"""

from .model import CodeBase, Reference, SapObject          # noqa: F401
from .scanner import scan                                   # noqa: F401
from .graph import Graph                                    # noqa: F401
from .impact import analyze, ImpactReport                   # noqa: F401

__all__ = ["CodeBase", "Reference", "SapObject", "scan", "Graph", "analyze", "ImpactReport"]
