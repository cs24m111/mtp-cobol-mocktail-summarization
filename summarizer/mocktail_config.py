"""
Central configuration of mocktail combinations for COBOL summarization.

Views:
  CODE        - COBOL source code
  AST         - syntax tree / node types / simple paths
  CFG         - control-flow info (branches, loops, edges)
  DFG_PRUNED  - pruned data-flow (defs/uses)
  PDG         - program dependence (control + data deps)
  BR          - A-COBREX business rule text
  BRR         - business rule realisation (paragraphs, lines, semantic tags)

Note: current BR_REP only contains:
  - CODE (raw_code)
  - DFG_PRUNED (via data_flow_summary)
  - some CFG-ish facts (control_flow_facts)
  - BR text
  We still expose AST/CFG/PDG/BRR as *view labels* so the LLM
  knows that structural analysis was performed, but we derive
  the text from the available summaries.
"""

from typing import Dict, List

MOCKTAIL_VIEWS: Dict[str, List[str]] = {
    # 1) Code-only baseline
    "C": ["CODE"],

    # 2) Code + BR rule text
    "C_BR": ["CODE", "BR"],

    # 3) Code + BR rule text + BR realisation
    # (BRR currently not stored in BR_REP; we add a placeholder block.)
    "C_BR_BRR": ["CODE", "BR", "BRR"],

    # 4) Code + AST + pruned DFG (structural)
    "C_AST_DFGP": ["CODE", "AST", "DFG_PRUNED"],

    # 5) Full structural graphs, no rules
    "C_AST_CFG_DFGP_PDG": ["CODE", "AST", "CFG", "DFG_PRUNED", "PDG"],

    # 6) Everything: code + graphs + rules + realisation
    "FULL": ["CODE", "AST", "CFG", "DFG_PRUNED", "PDG", "BR", "BRR"],
}

MOCKTAIL_LABELS: Dict[str, str] = {
    "C": "Code-only",
    "C_BR": "Code + BR",
    "C_BR_BRR": "Code + BR + BRR",
    "C_AST_DFGP": "Code + AST + pruned DFG",
    "C_AST_CFG_DFGP_PDG": "Code + AST + CFG + DFGᵖ + PDG",
    "FULL": "Full (Code + Graphs + BR + BRR)",
}

DEFAULT_MOCKTAIL_MODES = tuple(MOCKTAIL_VIEWS.keys())
