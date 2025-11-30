#!/usr/bin/env python3
"""
build_dfg.py

CLI script to build a Data Flow Graph (DFG) from a COBREX CFG JSON file.

It uses pruned_dfg_builder.py to:
  1. Load the CFG (COBREX JSON format).
  2. Annotate DEF/USE sets.
  3. Run reaching definitions.
  4. Build the DFG edges.
  5. Save:
       - RAW DFG  (all CFG nodes)       → DFG_<name>.json / .pdf
       - PRUNED DFG (only connected nodes) → DFG_<name>_pruned.json / .pdf

Directory layout (assumed):

  <SOME_ROOT>/<PROGRAM_NAME>/
      CFG/CFG_<PROGRAM_NAME>.json
      DFG/DFG_<PROGRAM_NAME>.json
          DFG_<PROGRAM_NAME>.pdf
          DFG_<PROGRAM_NAME>_pruned.json
          DFG_<PROGRAM_NAME>_pruned.pdf

By default, we infer the DFG folder as a sibling of CFG:

  cfg_json_path = .../COBOL_ATM/CFG/CFG_ATM.json

  → base_dir = .../COBOL_ATM
  → dfg_dir  = .../COBOL_ATM/DFG

Usage:
    python build_dfg.py path/to/CFG_<name>.json

"""

import os
import sys
import argparse

from pruned_dfg_builder import (
    build_dfg_from_cfg_json,
    save_dfg_to_json,
    export_dfg_graph,
    get_dfg_connected_nodes,
)


def main():
    parser = argparse.ArgumentParser(
        description="Build RAW and PRUNED DFG from a COBREX CFG JSON."
    )
    parser.add_argument(
        "cfg_json_path",
        help="Path to the COBREX CFG JSON file (e.g., CFG_ATM.json)",
    )
    args = parser.parse_args()

    cfg_json_path = args.cfg_json_path

    if not os.path.isfile(cfg_json_path):
        print(f"ERROR: CFG JSON file not found: {cfg_json_path}")
        sys.exit(1)

    print(f"[*] Building DFG from CFG JSON: {cfg_json_path}")

    # 1. Build DFG in memory
    cfg, dfg_edges = build_dfg_from_cfg_json(cfg_json_path)

    print(f"[*] Loaded CFG with {len(cfg.nodes)} nodes")
    print(f"[*] Built DFG with {len(dfg_edges)} edges")

    # Show a few sample edges
    if dfg_edges:
        print("[*] Sample DFG edges (def_node -> use_node [var]):")
        for e in dfg_edges[:20]:
            print(f"    {e[0]} -> {e[1]}  [{e[2]}]")
    else:
        print("[!] No DFG edges were generated (check DEF/USE rules).")

    # Compute connected nodes (nodes that participate in at least one DFG edge)
    connected_nodes = get_dfg_connected_nodes(dfg_edges)
    print(
        f"[*] DFG connected nodes (participating in at least one edge): "
        f"{len(connected_nodes)} / {len(cfg.nodes)}"
    )

    # 2. Derive DFG output paths from CFG path
    cfg_dir = os.path.dirname(cfg_json_path)         # e.g., .../COBOL_ATM/CFG
    base_dir = os.path.dirname(cfg_dir)             # e.g., .../COBOL_ATM
    dfg_dir = os.path.join(base_dir, "DFG")
    os.makedirs(dfg_dir, exist_ok=True)

    cfg_filename = os.path.basename(cfg_json_path)   # e.g., CFG_ATM.json
    core = cfg_filename
    if core.startswith("CFG_"):
        core = core[len("CFG_"):]                   # ATM.json
    if core.endswith(".json"):
        core = core[:-5]                            # ATM

    # RAW (all nodes) base name
    dfg_base_raw = f"DFG_{core}"                    # DFG_ATM
    # PRUNED (only connected nodes) base name
    dfg_base_pruned = f"DFG_{core}_pruned"          # DFG_ATM_pruned

    json_out_raw = os.path.join(dfg_dir, dfg_base_raw + ".json")
    json_out_pruned = os.path.join(dfg_dir, dfg_base_pruned + ".json")

    pdf_prefix_raw = os.path.join(dfg_dir, dfg_base_raw)
    pdf_prefix_pruned = os.path.join(dfg_dir, dfg_base_pruned)

    # 3. Persist RAW DFG JSON + PDF/DOT (all CFG nodes)
    print(f"[*] Writing RAW DFG JSON to: {json_out_raw}")
    save_dfg_to_json(cfg, dfg_edges, json_out_raw)

    print(f"[*] Rendering RAW DFG graph to: {pdf_prefix_raw}.pdf")
    export_dfg_graph(cfg, dfg_edges, pdf_prefix_raw)

    # 4. Persist PRUNED DFG JSON + PDF/DOT (only connected DFG nodes)
    print(f"[*] Writing PRUNED DFG JSON to: {json_out_pruned}")
    save_dfg_to_json(cfg, dfg_edges, json_out_pruned, node_filter=connected_nodes)

    print(f"[*] Rendering PRUNED DFG graph to: {pdf_prefix_pruned}.pdf")
    export_dfg_graph(cfg, dfg_edges, pdf_prefix_pruned, node_filter=connected_nodes)

    print("[✓] Done.")


if __name__ == "__main__":
    main()
