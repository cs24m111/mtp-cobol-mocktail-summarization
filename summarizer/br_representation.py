# summarizer/br_representation.py

import json
import os
from collections import defaultdict
from typing import Dict, Any, List, Tuple


def load_program_index(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def sanitize_br_id(br_id: str) -> str:
    s = br_id.replace("::", "__")
    for ch in ["/", "\\", " ", ":", "\"", "'"]:
        s = s.replace(ch, "_")
    return s


def group_nodes_by_line(node_index: Dict[str, dict], node_ids: List[str]) -> List[Tuple[int, str]]:
    items = []
    for nid in node_ids:
        info = node_index.get(nid)
        if not info:
            continue
        line = info.get("line", -1)
        items.append((line, nid))
    items.sort(key=lambda x: (x[0], x[1]))
    return items


def build_raw_code_view(node_index: Dict[str, dict], node_ids: List[str]) -> Dict[str, Any]:
    ordered = group_nodes_by_line(node_index, node_ids)
    raw_code_lines: List[str] = []
    lines: List[int] = []

    for line, nid in ordered:
        info = node_index[nid]
        label = (info.get("label") or "").strip("\n")
        raw_code_lines.append(label)
        if isinstance(line, int) and line >= 0:
            lines.append(line)

    line_range = [min(lines), max(lines)] if lines else [None, None]
    paragraphs = sorted(
        {
            node_index[nid].get("paragraph")
            for _, nid in ordered
            if node_index[nid].get("paragraph")
        }
    )

    return {
        "raw_code": raw_code_lines,
        "code_span": {
            "paragraphs": paragraphs,
            "lines": line_range,
        },
    }


def build_data_flow_summary(
    node_index: Dict[str, dict],
    node_ids: List[str],
    dfg_in: Dict[str, list],
    dfg_out: Dict[str, list],
) -> List[Dict[str, Any]]:
    """
    For all variables involved in this rule unit, build:
      variable -> definitions[], uses[]
    """
    defs_by_var = defaultdict(set)
    uses_by_var = defaultdict(set)

    node_set = set(node_ids)

    for nid in node_ids:
        # Uses (incoming defs to nid)
        for def_id, var in dfg_in.get(nid, []):
            def_label = node_index.get(def_id, {}).get("label", "")
            defs_by_var[var].add((def_id, def_label))
            use_label = node_index.get(nid, {}).get("label", "")
            uses_by_var[var].add((nid, use_label))

        # Outgoing edges also indicate nid defines something used elsewhere
        for use_id, var in dfg_out.get(nid, []):
            def_label = node_index.get(nid, {}).get("label", "")
            defs_by_var[var].add((nid, def_label))

    summary: List[Dict[str, Any]] = []
    all_vars = sorted(set(list(defs_by_var.keys()) + list(uses_by_var.keys())))

    for var in all_vars:
        def_entries = [lbl for (_nid, lbl) in sorted(defs_by_var[var])]
        use_entries = [lbl for (_nid, lbl) in sorted(uses_by_var[var])]
        summary.append({
            "variable": var,
            "definitions": def_entries,
            "uses": use_entries,
        })

    return summary


def build_control_flow_facts(
    node_index: Dict[str, dict],
    node_ids: List[str],
) -> List[str]:
    """
    Simple heuristic: pick out control constructs (IF, EVALUATE, PERFORM ... UNTIL).
    """
    facts: List[str] = []
    ordered = group_nodes_by_line(node_index, node_ids)

    for line, nid in ordered:
        info = node_index[nid]
        tag = (info.get("tag") or "").lower()
        label = (info.get("label") or "").strip()

        if tag in {"if", "evaluate", "when"}:
            facts.append(f"Decision: {label}")
        elif tag == "perform":
            if "UNTIL" in label.upper():
                facts.append(f"Loop: {label}")
            else:
                facts.append(f"Control transfer: {label}")

    if not facts and ordered:
        first_line, _ = ordered[0]
        last_line, _ = ordered[-1]
        paras = sorted(
            {
                node_index[nid].get("paragraph")
                for _, nid in ordered
                if node_index[nid].get("paragraph")
            }
        )
        facts.append(
            f"Control: statements from line {first_line} to {last_line} "
            f"in paragraphs {', '.join(paras)}."
        )

    return facts


def build_categories(node_index: Dict[str, dict], node_ids: List[str]) -> Dict[str, bool]:
    """
    Basic "multiple checkups" categories based on tags + labels.
    """
    has_validation = False
    updates_state = False
    does_io = False
    has_loop = False
    has_error_message = False

    for nid in node_ids:
        info = node_index.get(nid, {})
        tag = (info.get("tag") or "").lower()
        label = (info.get("label") or "").upper()

        if tag in {"if", "evaluate", "when"}:
            has_validation = True
        if tag in {"add", "subtract", "divide", "multiply", "compute", "move"}:
            updates_state = True
        if tag in {"display", "accept"}:
            does_io = True
        if tag == "perform" and "UNTIL" in label:
            has_loop = True
        if "INSUFFICIENT" in label or "ERROR" in label or "INVALID" in label:
            has_error_message = True

    return {
        "has_validation": has_validation,
        "updates_state": updates_state,
        "does_io": does_io,
        "has_loop": has_loop,
        "has_error_message": has_error_message,
    }


def build_br_representation_for_prog(
    prog_name: str,
    base_output_dir: str,
) -> None:
    """
    Load ProgramIndex_<PROG>.json and for each br_id
    build a BR representation JSON with multi-view info.
    """
    index_path = os.path.join(
        base_output_dir, "INDEX", f"ProgramIndex_{prog_name}.json"
    )
    if not os.path.isfile(index_path):
        raise FileNotFoundError(f"ProgramIndex not found: {index_path}")

    program_index = load_program_index(index_path)
    node_index: Dict[str, dict] = program_index["node_index"]
    br_index: Dict[str, dict] = program_index["br_index"]
    dfg_in: Dict[str, list] = program_index["dfg_in"]
    dfg_out: Dict[str, list] = program_index["dfg_out"]

    out_dir = os.path.join(base_output_dir, "BR_REP")
    os.makedirs(out_dir, exist_ok=True)

    for br_id, br_info in br_index.items():
        node_ids = br_info.get("node_ids", [])
        if not node_ids:
            continue

        raw_code_view = build_raw_code_view(node_index, node_ids)
        data_flow_summary = build_data_flow_summary(
            node_index, node_ids, dfg_in, dfg_out
        )
        control_flow_facts = build_control_flow_facts(node_index, node_ids)
        categories = build_categories(node_index, node_ids)

        rep = {
            "program": prog_name,
            "br_id": br_id,
            "br_text": br_info.get("br_text", ""),
            "code_span": raw_code_view["code_span"],
            "raw_code": raw_code_view["raw_code"],
            "data_flow_summary": data_flow_summary,
            "control_flow_facts": control_flow_facts,
            "categories": categories,
        }

        safe_id = sanitize_br_id(br_id)
        out_path = os.path.join(out_dir, f"BR_{prog_name}_{safe_id}.json")
        with open(out_path, "w") as f:
            json.dump(rep, f, indent=2)

        print(f"[BR_REP] {br_id} -> {out_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build multi-view BR representations for a COBOL program."
    )
    parser.add_argument("--prog", required=True, help="Program name, e.g. ATM")
    parser.add_argument(
        "--base-dir",
        required=True,
        help="Base output dir, e.g. output/COBOL_ATM",
    )
    args = parser.parse_args()

    build_br_representation_for_prog(args.prog, args.base_dir)
