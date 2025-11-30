# pdg_builder.py
#
# Build a Program Dependence Graph (PDG) for COBOL using:
#   - CFG JSON from A-COBREX
#   - DFG JSON (our DDG) from build_dfg.py
#
# PDG = CDG (control dependence) + DDG (data dependence).
#
# Output JSON format:
# {
#   "nodes": [
#     { "id": "...", "label": "...", "line": 24,
#       "entityType": "Statement", "tag": "move" },
#     ...
#   ],
#   "data_edges": [
#     { "src": "...", "dst": "...", "var": "BALANCE" },
#     ...
#   ],
#   "control_edges": [
#     { "src": "...", "dst": "...", "kind": "control" },
#     ...
#   ]
# }

import json
import os
from typing import Dict, List, Tuple, Any

from graphviz import Digraph


# ─────────────────────────────────────────────────────────────
# 0. Local CFG classes (copied from dfg_builder to avoid imports)
# ─────────────────────────────────────────────────────────────

class CFGNode:
    def __init__(self, node_id, label):
        self.id = node_id          # unique id (string)
        self.label = label         # COBOL statement text or description
        self.succ = set()          # successors (control-flow edges)
        self.pred = set()          # predecessors
        # optional: attach properties later if needed
        self.properties = {}


class CFGGraph:
    def __init__(self):
        self.nodes: Dict[str, CFGNode] = {}

    def add_node(self, node_id, label):
        if node_id not in self.nodes:
            self.nodes[node_id] = CFGNode(node_id, label)
        return self.nodes[node_id]

    def add_edge(self, src, dst):
        if src not in self.nodes or dst not in self.nodes:
            return
        self.nodes[src].succ.add(dst)
        self.nodes[dst].pred.add(src)


# ─────────────────────────────────────────────────────────────
# 1. Load CFG with extra metadata (line, entityType, tag)
# ─────────────────────────────────────────────────────────────

def load_cfg_with_meta(path: str) -> Tuple[CFGGraph, Dict[str, Dict[str, Any]]]:
    """
    Load a COBREX CFG JSON and build:
      - CFGGraph (id, label, succ, pred)
      - meta[id] = { line, entityType, tag }
    """
    with open(path) as f:
        data = json.load(f)

    node_list = data.get("nodes")
    if node_list is None:
        raise ValueError("Could not find 'nodes' key in CFG JSON")

    edge_list = data.get("edges")
    if edge_list is None:
        raise ValueError("Could not find 'edges' key in CFG JSON")

    cfg = CFGGraph()
    meta: Dict[str, Dict[str, Any]] = {}

    # Helper: get node id and label
    def get_node_id(n: Dict[str, Any]) -> str:
        # COBREX puts id in "id", with details in "properties.uniqueId"
        if "id" in n:
            return str(n["id"])
        props = n.get("properties", {})
        if "uniqueId" in props:
            return str(props["uniqueId"])
        raise KeyError(f"Cannot determine node id from node entry: {n}")

    def get_node_label(n: Dict[str, Any]) -> str:
        props = n.get("properties", {})
        if "stmtText" in props:
            return str(props["stmtText"])
        if "name" in n:
            return str(n["name"])
        return get_node_id(n)

    # Build nodes + meta
    for n in node_list:
        nid = get_node_id(n)
        label = get_node_label(n)
        node = cfg.add_node(nid, label)

        props = n.get("properties", {})
        node.properties = props  # attach for possible later use

        meta[nid] = {
            "line": props.get("stmtStartLineNumber"),
            "entityType": n.get("entityType") or props.get("entityType"),
            "tag": props.get("tag"),
        }

    # Helper: get edge endpoints
    def get_edge_src(e: Dict[str, Any]) -> str:
        for k in ("sourceUniqueId", "src", "source", "from"):
            if k in e:
                return str(e[k])
        raise KeyError(f"Cannot determine source from edge: {e}")

    def get_edge_dst(e: Dict[str, Any]) -> str:
        for k in ("targetUniqueId", "dst", "target", "to"):
            if k in e:
                return str(e[k])
        raise KeyError(f"Cannot determine target from edge: {e}")

    # Build edges
    for e in edge_list:
        src = get_edge_src(e)
        dst = get_edge_dst(e)
        # In COBREX JSON, nodes[id] are the "id" field,
        # but edges use "sourceUniqueId"/"targetUniqueId" which match properties.uniqueId.
        # We therefore added nodes keyed by "id"; edges refer to "id" as well,
        # because CFG_ATM.json stores "id" as "ATM:xx:yy".
        if src in cfg.nodes and dst in cfg.nodes:
            cfg.add_edge(src, dst)

    return cfg, meta


# ─────────────────────────────────────────────────────────────
# 2. Postdominator computation
# ─────────────────────────────────────────────────────────────

def add_exit_node(cfg: CFGGraph, exit_id: str = "__EXIT__") -> str:
    """
    Add a synthetic EXIT node and connect all nodes with no successors to it.
    Returns the ID of the EXIT node.
    """
    if exit_id in cfg.nodes:
        return exit_id

    cfg.add_node(exit_id, "EXIT")
    exit_candidates = [nid for nid, n in cfg.nodes.items() if not n.succ]
    for nid in exit_candidates:
        cfg.add_edge(nid, exit_id)
    return exit_id


def compute_postdominators(cfg: CFGGraph, exit_id: str) -> Dict[str, set]:
    """
    Classical iterative algorithm for postdominators:
      postdom(exit) = { exit }
      postdom(n != exit) = all_nodes
      Repeat:
        postdom(n) = {n} ∪ ⋂_{s in succ(n)} postdom(s)
    """
    nodes = list(cfg.nodes.keys())
    postdom: Dict[str, set] = {n: set(nodes) for n in nodes}
    postdom[exit_id] = {exit_id}

    changed = True
    while changed:
        changed = False
        for n in nodes:
            if n == exit_id:
                continue
            succs = cfg.nodes[n].succ
            if not succs:
                new_s = postdom[exit_id].copy()
            else:
                new_s = None
                for s in succs:
                    if new_s is None:
                        new_s = postdom[s].copy()
                    else:
                        new_s &= postdom[s]

            if new_s is None:
                new_s = set()

            new_pd = {n} | new_s
            if new_pd != postdom[n]:
                postdom[n] = new_pd
                changed = True

    return postdom


def compute_ipostdom(postdom: Dict[str, set], exit_id: str) -> Dict[str, str]:
    """
    Compute immediate postdominator for each node from postdom sets.
    ipdom[n] is the closest postdominator of n (or None for EXIT).
    """
    ipdom: Dict[str, str] = {}
    nodes = list(postdom.keys())

    for n in nodes:
        if n == exit_id:
            ipdom[n] = None  # type: ignore
            continue

        candidates = postdom[n] - {n}
        if not candidates:
            ipdom[n] = None  # type: ignore
            continue

        best = None
        for m in candidates:
            # m is immediate if no other q in candidates is strictly
            # closer to n (i.e., m is not postdominated by q)
            dominated_by_other = False
            for q in candidates:
                if q == m:
                    continue
                if q in postdom[m]:
                    dominated_by_other = True
                    break
            if not dominated_by_other:
                best = m
                break
        ipdom[n] = best  # type: ignore

    return ipdom


# ─────────────────────────────────────────────────────────────
# 3. Build Control Dependence Graph (CDG)
# ─────────────────────────────────────────────────────────────

def build_cdg(cfg: CFGGraph,
              ipdom: Dict[str, str],
              exit_id: str) -> List[Tuple[str, str]]:
    """
    Ferrante–Ottenstein–Warren algorithm:

    For each node b (≠ EXIT), for each predecessor a of b:
        runner = a
        while runner != ipdom[b]:
            add edge runner -> b
            runner = ipdom[runner]
    """
    control_edges: List[Tuple[str, str]] = []

    for b_id, b_node in cfg.nodes.items():
        if b_id == exit_id:
            continue
        for a_id in b_node.pred:
            runner = a_id
            while runner is not None and runner != ipdom.get(b_id):
                control_edges.append((runner, b_id))
                runner = ipdom.get(runner)

    # deduplicate
    control_edges = list({(s, t) for (s, t) in control_edges})
    return control_edges


# ─────────────────────────────────────────────────────────────
# 4. Load DFG (DDG) edges
# ─────────────────────────────────────────────────────────────

def load_ddg_edges(dfg_json_path: str) -> List[Dict[str, Any]]:
    """
    Load DDG (DFG) edges from JSON.
    Handles two styles:
      1) top-level list of edges:
         [ {def_node, use_node, variable, ...}, ... ]
      2) { "edges": [ ... ], "nodes": [ ... ] }
    Normalises to:
      { "src": def_node, "dst": use_node, "var": variable }
    """
    with open(dfg_json_path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        edges = data.get("edges", [])
    else:
        edges = data

    norm_edges: List[Dict[str, Any]] = []
    for e in edges:
        if isinstance(e, dict):
            src = e.get("def_node") or e.get("src")
            dst = e.get("use_node") or e.get("dst")
            var = e.get("variable") or e.get("var")
            if src is None or dst is None or var is None:
                continue
            norm_edges.append({
                "src": str(src),
                "dst": str(dst),
                "var": str(var)
            })
        else:
            try:
                def_node, use_node, var = e
            except Exception:
                continue
            norm_edges.append({
                "src": str(def_node),
                "dst": str(use_node),
                "var": str(var)
            })

    return norm_edges


# ─────────────────────────────────────────────────────────────
# 5. Build PDG JSON
# ─────────────────────────────────────────────────────────────

def build_pdg(cfg_json_path: str,
              dfg_json_path: str,
              pdg_json_path: str) -> Dict[str, Any]:
    """
    High-level helper to build PDG and write it to pdg_json_path.
    Returns the PDG dict as well.
    """
    # 1. Load CFG + meta
    cfg, meta = load_cfg_with_meta(cfg_json_path)

    # 2. Add EXIT and compute postdom / ipostdom / CDG
    exit_id = add_exit_node(cfg)
    postdom = compute_postdominators(cfg, exit_id)
    ipdom = compute_ipostdom(postdom, exit_id)
    cdg_edges = build_cdg(cfg, ipdom, exit_id)

    # 3. Load DDG (DFG) edges
    ddg_edges = load_ddg_edges(dfg_json_path)

    # 4. Assemble PDG JSON
    nodes_json: List[Dict[str, Any]] = []
    for nid, node in cfg.nodes.items():
        if nid == exit_id:
            continue
        m = meta.get(nid, {})
        nodes_json.append({
            "id": nid,
            "label": node.label,
            "line": m.get("line"),
            "entityType": m.get("entityType"),
            "tag": m.get("tag"),
        })

    data_edges_json = []
    for e in ddg_edges:
        if e["src"] not in cfg.nodes or e["dst"] not in cfg.nodes:
            continue
        if e["src"] == exit_id or e["dst"] == exit_id:
            continue
        data_edges_json.append({
            "src": e["src"],
            "dst": e["dst"],
            "var": e["var"],
        })

    control_edges_json = []
    for (src, dst) in cdg_edges:
        if src == exit_id or dst == exit_id:
            continue
        if src not in cfg.nodes or dst not in cfg.nodes:
            continue
        control_edges_json.append({
            "src": src,
            "dst": dst,
            "kind": "control",
        })

    pdg = {
        "nodes": nodes_json,
        "data_edges": data_edges_json,
        "control_edges": control_edges_json,
    }

    os.makedirs(os.path.dirname(pdg_json_path), exist_ok=True)
    with open(pdg_json_path, "w") as f:
        json.dump(pdg, f, indent=2)

    return pdg


# ─────────────────────────────────────────────────────────────
# 6. Optional: Graphviz visualisation
# ─────────────────────────────────────────────────────────────

def export_pdg_graph(pdg: Dict[str, Any], out_prefix: str) -> None:
    """
    Export PDG to Graphviz PDF.
    We map COBOL node IDs (with colons) to n0, n1, ... to avoid port warnings.
    """
    dot = Digraph(comment="COBOL PDG", format="pdf")

    nodes = pdg.get("nodes", [])
    data_edges = pdg.get("data_edges", [])
    control_edges = pdg.get("control_edges", [])

    # Map real id -> graphviz id
    id_map: Dict[str, str] = {}
    for idx, n in enumerate(nodes):
        real_id = n["id"]
        gv_id = f"n{idx}"
        id_map[real_id] = gv_id

        label_parts = [real_id, n.get("label", "")]
        line = n.get("line")
        if line is not None:
            label_parts.append(f"(line {line})")
        label = "\\n".join(str(p) for p in label_parts if p)
        dot.node(gv_id, label)

    # Data edges (dashed)
    for e in data_edges:
        src = id_map.get(e["src"])
        dst = id_map.get(e["dst"])
        if not src or not dst:
            continue
        dot.edge(src, dst, label=e.get("var", ""), style="dashed")

    # Control edges (solid)
    for e in control_edges:
        src = id_map.get(e["src"])
        dst = id_map.get(e["dst"])
        if not src or not dst:
            continue
        dot.edge(src, dst, label=e.get("kind", "ctl"))

    dot.render(out_prefix, cleanup=False)
