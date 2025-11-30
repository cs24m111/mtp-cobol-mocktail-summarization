# build_pdg.py
#
# CLI wrapper for pdg_builder:
#   python build_pdg.py path/to/CFG_xxx.json [path/to/DFG_xxx.json]
#
# If DFG path is not provided, we try to infer it from the CFG path:
#   .../CFG/CFG_FOO.json  -> .../DFG/DFG_FOO.json

import sys
import os

from pdg_builder import build_pdg, export_pdg_graph


def infer_paths(cfg_json_path: str, dfg_json_path: str = None):
    """
    Infer:
      - program name (e.g., ATM)
      - base directory (.../output/COBOL_ATM)
      - DFG path (if not given)
      - PDG JSON + PDF paths
    """
    cfg_json_path = os.path.abspath(cfg_json_path)
    cfg_dir = os.path.dirname(cfg_json_path)          # .../CFG
    base_dir = os.path.dirname(cfg_dir)              # .../COBOL_ATM
    cfg_filename = os.path.basename(cfg_json_path)   # CFG_ATM.json

    # extract program name from "CFG_<prog>.json"
    prog_name = cfg_filename
    if cfg_filename.startswith("CFG_"):
        prog_name = cfg_filename[len("CFG_"):]
    if prog_name.endswith(".json"):
        prog_name = prog_name[:-len(".json")]

    if dfg_json_path is None:
        # default: .../DFG/DFG_<prog>.json
        dfg_dir = os.path.join(base_dir, "DFG")
        dfg_json_path = os.path.join(dfg_dir, f"DFG_{prog_name}.json")

    pdg_dir = os.path.join(base_dir, "PDG")
    pdg_json_path = os.path.join(pdg_dir, f"PDG_{prog_name}.json")
    pdg_pdf_prefix = os.path.join(pdg_dir, f"PDG_{prog_name}")

    return dfg_json_path, pdg_json_path, pdg_pdf_prefix


def main():
    if len(sys.argv) < 2:
        print("Usage: python build_pdg.py path/to/CFG_xxx.json [path/to/DFG_xxx.json]")
        sys.exit(1)

    cfg_json_path = sys.argv[1]
    dfg_json_path_arg = sys.argv[2] if len(sys.argv) > 2 else None

    dfg_json_path, pdg_json_path, pdg_pdf_prefix = infer_paths(
        cfg_json_path, dfg_json_path_arg
    )

    print(f"CFG JSON: {cfg_json_path}")
    print(f"DFG JSON: {dfg_json_path}")
    print(f"PDG JSON (out): {pdg_json_path}")
    print(f"PDG PDF  (out): {pdg_pdf_prefix}.pdf")

    pdg = build_pdg(cfg_json_path, dfg_json_path, pdg_json_path)
    export_pdg_graph(pdg, pdg_pdf_prefix)

    print("PDG build complete.")


if __name__ == "__main__":
    main()
