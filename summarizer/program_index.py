# summarizer/program_index.py

import json
import os
from collections import defaultdict
from typing import Dict, Any, Optional


def load_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────
# 1. Node index + CFG edges
# ─────────────────────────────────────────────────────────────

def build_node_index_from_cfg(cfg: dict) -> Dict[str, dict]:
    """
    Build node_index[node_id] = {
        id, label, tag, line, entityType, paragraph (filled later)
    }
    from CFG_<PROG>.json
    """
    node_index: Dict[str, dict] = {}

    node_list = cfg.get("nodes") or cfg.get("Nodes") or []
    for n in node_list:
        props = n.get("properties", {}) or {}
        node_id = props.get("uniqueId") or n.get("id") or n.get("name")
        if not node_id:
            continue
        node_id = str(node_id)

        label = props.get("stmtText") or n.get("name") or node_id
        tag = props.get("tag", "")
        line = props.get("stmtStartLineNumber", -1)
        entity_type = n.get("entityType", "")

        node_index[node_id] = {
            "id": node_id,
            "label": label,
            "tag": tag,
            "line": line,
            "entityType": entity_type,
            "paragraph": None,  # filled by assign_paragraphs()
        }

    return node_index


def build_cfg_edges(cfg: dict):
    """
    Build CFG successor / predecessor maps:
      cfg_succ[node_id] = [succ1, succ2, ...]
      cfg_pred[node_id] = [pred1, pred2, ...]
    """
    cfg_succ = defaultdict(list)
    cfg_pred = defaultdict(list)

    edge_list = cfg.get("edges") or cfg.get("Edges") or []
    for e in edge_list:
        src = (
            e.get("sourceUniqueId")
            or e.get("src")
            or e.get("source")
            or e.get("from")
        )
        dst = (
            e.get("targetUniqueId")
            or e.get("dst")
            or e.get("target")
            or e.get("to")
        )
        if not src or not dst:
            continue
        src = str(src)
        dst = str(dst)
        cfg_succ[src].append(dst)
        cfg_pred[dst].append(src)

    return cfg_succ, cfg_pred


def assign_paragraphs(node_index: Dict[str, dict]) -> None:
    """
    Infer paragraph name for each node using nodes tagged 'paragraphName'.
    """
    paragraphs = []
    for node_id, info in node_index.items():
        if (info.get("tag") or "").lower() == "paragraphname":
            paragraphs.append((info["line"], node_id, info["label"]))

    if not paragraphs:
        return

    paragraphs.sort(key=lambda x: x[0])  # by line

    for node_id, info in node_index.items():
        line = info.get("line", -1)
        para_name = None
        last_line = -1
        for (pline, _pid, plabel) in paragraphs:
            if isinstance(line, int) and pline <= line and pline >= last_line:
                last_line = pline
                para_name = plabel.split(".")[0].strip()
        info["paragraph"] = para_name


# ─────────────────────────────────────────────────────────────
# 2. DFG + PDG maps
# ─────────────────────────────────────────────────────────────

def build_dfg_maps(dfg_pruned: dict):
    """
    From DFG_<PROG>_pruned.json:
      {
        "nodes": [...],
        "edges": [
          { "def_node": "...", "use_node": "...", "variable": "VAR", ... },
          ...
        ]
      }
    Build:
      dfg_out[node_id] = [ (use_id, var), ... ]
      dfg_in[node_id]  = [ (def_id, var), ... ]
    """
    dfg_out = defaultdict(list)
    dfg_in = defaultdict(list)

    for e in dfg_pruned.get("edges", []):
        d = e.get("def_node")
        u = e.get("use_node")
        v = e.get("variable")
        if not d or not u or not v:
            continue
        d = str(d)
        u = str(u)
        v = str(v).upper()
        dfg_out[d].append((u, v))
        dfg_in[u].append((d, v))

    return dfg_in, dfg_out


def build_pdg_maps(pdg: dict):
    """
    From PDG_<PROG>.json with:
      {
        "nodes": [...],
        "data_edges": [ {"src": ..., "dst": ..., "var": ...}, ... ],
        "control_edges": [ {"src": ..., "dst": ...}, ... ]
      }
    Build:
      pdg_data_out, pdg_data_in, pdg_control_out, pdg_control_in
    """
    pdg_data_out = defaultdict(list)
    pdg_data_in = defaultdict(list)
    pdg_control_out = defaultdict(list)
    pdg_control_in = defaultdict(list)

    for e in pdg.get("data_edges", []):
        src = e.get("src")
        dst = e.get("dst")
        var = e.get("var", "")
        if src is None or dst is None:
            continue
        src = str(src)
        dst = str(dst)
        var = str(var).upper()
        pdg_data_out[src].append((dst, var))
        pdg_data_in[dst].append((src, var))

    for e in pdg.get("control_edges", []):
        src = e.get("src")
        dst = e.get("dst")
        if src is None or dst is None:
            continue
        src = str(src)
        dst = str(dst)
        pdg_control_out[src].append(dst)
        pdg_control_in[dst].append(src)

    return pdg_data_in, pdg_data_out, pdg_control_in, pdg_control_out


# ─────────────────────────────────────────────────────────────
# 3. BR index: (A) paragraph-based fallback, (B) A-COBREX-based
# ─────────────────────────────────────────────────────────────

def build_br_index_from_paragraphs(node_index: Dict[str, dict]) -> Dict[str, dict]:
    """
    Fallback: treat each paragraph as a "rule unit".

    br_index[br_id] = {
      "br_text": ...,
      "paragraph": para_name,
      "node_ids": [...],
      "line_range": [start, end]
    }
    """
    from collections import defaultdict

    para_to_nodes = defaultdict(list)
    for node_id, info in node_index.items():
        para = info.get("paragraph")
        if not para:
            continue
        line = info.get("line", -1)
        para_to_nodes[para].append((line, node_id))

    br_index: Dict[str, dict] = {}
    for para, items in para_to_nodes.items():
        items.sort(key=lambda x: x[0])
        node_ids = [nid for _, nid in items]
        lines = [ln for ln, _ in items if isinstance(ln, int) and ln >= 0]
        br_id = f"PARAGRAPH::{para}"

        br_index[br_id] = {
            "br_text": f"Automatically generated rule unit for COBOL paragraph {para}.",
            "paragraph": para,
            "node_ids": node_ids,
            "line_range": [min(lines), max(lines)] if lines else [None, None],
        }

    return br_index


def build_br_index_from_acobrex(
    node_index: Dict[str, dict],
    acobrex_br_json: dict,
) -> Dict[str, dict]:
    """
    Build br_index from A-COBREX business rule JSON:

    {
      "program": "ATM",
      "business_rules": [
        { "id": "rule_1", "description": "...", "start_line": 15, "end_line": 28 },
        ...
      ]
    }

    For each rule:
      - select CFG nodes whose line ∈ [start_line, end_line].
    """
    rules = (
        acobrex_br_json.get("business_rules")
        or acobrex_br_json.get("rules")
        or acobrex_br_json
    )

    if not isinstance(rules, list):
        raise ValueError(
            "A-COBREX BR JSON format not recognized: expected a list under "
            "'business_rules' or 'rules', or the root to be a list."
        )

    br_index: Dict[str, dict] = {}

    # Map: line -> [node_ids] for fast lookup
    from collections import defaultdict
    line_to_nodes = defaultdict(list)
    for nid, info in node_index.items():
        ln = info.get("line", -1)
        if isinstance(ln, int) and ln >= 0:
            line_to_nodes[ln].append(nid)

    for idx, rule in enumerate(rules):
        br_id = (
            rule.get("id")
            or rule.get("rule_id")
            or rule.get("br_id")
            or f"BR_{idx+1}"
        )
        br_id = str(br_id)

        desc = (
            rule.get("description")
            or rule.get("text")
            or rule.get("rule_text")
            or ""
        )

        # Node IDs from explicit list if present
        node_ids = []
        explicit_nodes = rule.get("node_ids") or rule.get("nodes")
        if explicit_nodes and isinstance(explicit_nodes, list):
            for nid in explicit_nodes:
                nid = str(nid)
                if nid in node_index:
                    node_ids.append(nid)

        # Fallback to line-range
        if not node_ids:
            start = (
                rule.get("start_line")
                or rule.get("from_line")
                or rule.get("startLine")
            )
            end = (
                rule.get("end_line")
                or rule.get("to_line")
                or rule.get("endLine")
            )
            try:
                start = int(start) if start is not None else None
            except Exception:
                start = None
            try:
                end = int(end) if end is not None else None
            except Exception:
                end = None

            if start is not None and end is not None:
                for ln in range(start, end + 1):
                    for nid in line_to_nodes.get(ln, []):
                        node_ids.append(nid)

        # Deduplicate
        unique_nodes = []
        seen = set()
        for nid in node_ids:
            if nid in seen:
                continue
            seen.add(nid)
            unique_nodes.append(nid)

        # Compute line_range from actual nodes
        lines = []
        for nid in unique_nodes:
            ln = node_index[nid].get("line", -1)
            if isinstance(ln, int) and ln >= 0:
                lines.append(ln)
        if lines:
            line_range = [min(lines), max(lines)]
        else:
            line_range = [None, None]

        paragraphs = sorted(
            {
                node_index[nid].get("paragraph")
                for nid in unique_nodes
                if node_index[nid].get("paragraph")
            }
        )

        br_index[br_id] = {
            "br_text": desc,
            "paragraphs": paragraphs,
            "node_ids": unique_nodes,
            "line_range": line_range,
        }

    return br_index


# ─────────────────────────────────────────────────────────────
# 4. Main builder
# ─────────────────────────────────────────────────────────────

def build_program_index(
    prog_name: str,
    base_output_dir: str,
    acobrex_br_json_path: Optional[str] = None,
) -> dict:
    """
    Builds and writes ProgramIndex_<PROG>.json in:
      <base_output_dir>/INDEX/ProgramIndex_<PROG>.json
    """
    cfg_path = os.path.join(base_output_dir, "CFG", f"CFG_{prog_name}.json")
    dfg_pruned_path = os.path.join(base_output_dir, "DFG", f"DFG_{prog_name}_pruned.json")
    pdg_path = os.path.join(base_output_dir, "PDG", f"PDG_{prog_name}.json")

    if not os.path.isfile(cfg_path):
        raise FileNotFoundError(f"CFG not found: {cfg_path}")
    if not os.path.isfile(dfg_pruned_path):
        raise FileNotFoundError(f"Pruned DFG not found: {dfg_pruned_path}")
    if not os.path.isfile(pdg_path):
        raise FileNotFoundError(f"PDG not found: {pdg_path}")

    cfg = load_json(cfg_path)
    dfg_pruned = load_json(dfg_pruned_path)
    pdg = load_json(pdg_path)

    node_index = build_node_index_from_cfg(cfg)
    assign_paragraphs(node_index)

    cfg_succ, cfg_pred = build_cfg_edges(cfg)
    dfg_in, dfg_out = build_dfg_maps(dfg_pruned)
    (
        pdg_data_in,
        pdg_data_out,
        pdg_control_in,
        pdg_control_out,
    ) = build_pdg_maps(pdg)

    # BR index
    if acobrex_br_json_path and os.path.isfile(acobrex_br_json_path):
        print(f"[ProgramIndex] Using A-COBREX BR JSON: {acobrex_br_json_path}")
        acobrex_data = load_json(acobrex_br_json_path)
        br_index = build_br_index_from_acobrex(node_index, acobrex_data)
    else:
        print("[ProgramIndex] No A-COBREX BR JSON specified/found; "
              "falling back to paragraph-based rule units.")
        br_index = build_br_index_from_paragraphs(node_index)

    program_index: Dict[str, Any] = {
        "program": prog_name,
        "node_index": node_index,
        "cfg_succ": cfg_succ,
        "cfg_pred": cfg_pred,
        "dfg_in": dfg_in,
        "dfg_out": dfg_out,
        "pdg_data_in": pdg_data_in,
        "pdg_data_out": pdg_data_out,
        "pdg_control_in": pdg_control_in,
        "pdg_control_out": pdg_control_out,
        "br_index": br_index,
    }

    index_dir = os.path.join(base_output_dir, "INDEX")
    os.makedirs(index_dir, exist_ok=True)
    out_path = os.path.join(index_dir, f"ProgramIndex_{prog_name}.json")
    with open(out_path, "w") as f:
        json.dump(program_index, f, indent=2)

    print(f"[ProgramIndex] Written to {out_path}")
    return program_index


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build ProgramIndex_<PROG>.json (multi-view index for one COBOL program)."
    )
    parser.add_argument("--prog", required=True, help="Program name, e.g. ATM")
    parser.add_argument(
        "--base-dir",
        required=True,
        help="Base output dir, e.g. output/COBOL_ATM",
    )
    parser.add_argument(
        "--br-json",
        required=False,
        default=None,
        help="Optional path to A-COBREX business rule JSON file.",
    )
    args = parser.parse_args()

    build_program_index(args.prog, args.base_dir, args.br_json)
