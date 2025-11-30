"""
pruned_dfg_builder.py

Build a Data Flow Graph (DFG) from a COBREX CFG JSON file
using classic Reaching Definitions Analysis, with support
for building a *pruned* DFG that only keeps nodes that
participate in at least one DFG edge.

This is tailored for the A-COBREX / COBREX CFG format:
- nodes: list of nodes with a "properties" field containing:
    - uniqueId
    - stmtText
    - tag
    - source_variables
    - target_variables
    - conditional_variables
- edges: list of edges with:
    - sourceUniqueId
    - targetUniqueId
"""

import json
from collections import defaultdict
from graphviz import Digraph


# ─────────────────────────────────────────────────────────────
# Basic CFG data structures
# ─────────────────────────────────────────────────────────────

class CFGNode:
    def __init__(self, node_id, label,
                 tag=None,
                 source_vars=None,
                 target_vars=None,
                 cond_vars=None):
        self.id = node_id          # COBREX uniqueId, e.g., "ATM:10:24"
        self.label = label         # Statement text
        self.tag = tag or ""       # COBREX tag, e.g., "move", "add", "if"

        self.source_vars = source_vars or []
        self.target_vars = target_vars or []
        self.cond_vars = cond_vars or []

        self.succ = set()          # successors (control-flow edges)
        self.pred = set()          # predecessors

        # Filled later by DEF/USE analysis
        self.defs = set()          # variables defined in this node
        self.uses = set()          # variables used in this node


class CFGGraph:
    def __init__(self):
        self.nodes = {}  # id -> CFGNode

    def add_node(self, node_id, label,
                 tag=None,
                 source_vars=None,
                 target_vars=None,
                 cond_vars=None):
        if node_id not in self.nodes:
            self.nodes[node_id] = CFGNode(
                node_id=node_id,
                label=label,
                tag=tag,
                source_vars=source_vars,
                target_vars=target_vars,
                cond_vars=cond_vars,
            )
        return self.nodes[node_id]

    def add_edge(self, src, dst):
        if src not in self.nodes or dst not in self.nodes:
            return
        self.nodes[src].succ.add(dst)
        self.nodes[dst].pred.add(src)


# ─────────────────────────────────────────────────────────────
# 1. Load COBREX CFG JSON into CFGGraph
# ─────────────────────────────────────────────────────────────

def load_cfg_from_json(path):
    """
    Load a COBREX CFG JSON and return a CFGGraph instance.

    Expected top-level keys:
        - "nodes": list of nodes
        - "edges": list of edges

    Each node has:
        - "id"                      (string)
        - "properties" dict that contains:
            - "uniqueId"            (string)
            - "stmtText"            (string)
            - "tag"                 (string)
            - "source_variables"    (list of strings)
            - "target_variables"    (list of strings)
            - "conditional_variables" (list of strings)
    """
    with open(path, "r") as f:
        data = json.load(f)

    # Accept a few alternative names just in case
    node_list = (
        data.get("nodes")
        or data.get("Nodes")
        or data.get("Vertices")
        or data.get("vertexes")
    )
    if node_list is None:
        raise ValueError("Could not find node list in CFG JSON")

    edge_list = (
        data.get("edges")
        or data.get("Edges")
        or data.get("links")
        or data.get("Links")
    )
    if edge_list is None:
        raise ValueError("Could not find edge list in CFG JSON")

    cfg = CFGGraph()

    # ---- Build nodes ----
    for n in node_list:
        props = n.get("properties", {}) or {}

        node_id = (
            props.get("uniqueId")
            or n.get("id")
            or n.get("name")
        )
        if node_id is None:
            raise KeyError(f"Cannot determine node id from entry: {n}")
        node_id = str(node_id)

        # Prefer statement text as label
        label = (
            props.get("stmtText")
            or n.get("name")
            or node_id
        )

        tag = props.get("tag", "")
        src_vars = props.get("source_variables") or []
        tgt_vars = props.get("target_variables") or []
        cond_vars = props.get("conditional_variables") or []

        cfg.add_node(
            node_id=node_id,
            label=label,
            tag=tag,
            source_vars=src_vars,
            target_vars=tgt_vars,
            cond_vars=cond_vars,
        )

    # ---- Build edges ----
    def get_edge_endpoints(e):
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
        if src is None or dst is None:
            raise KeyError(f"Cannot determine src/dst from edge entry: {e}")
        return str(src), str(dst)

    for e in edge_list:
        try:
            src, dst = get_edge_endpoints(e)
        except KeyError:
            continue
        if src in cfg.nodes and dst in cfg.nodes:
            cfg.add_edge(src, dst)

    return cfg


# ─────────────────────────────────────────────────────────────
# 2. DEF/USE extraction for each node
# ─────────────────────────────────────────────────────────────

def extract_defs_uses_for_node(node: CFGNode):
    """
    Extract DEF and USE sets for a node using COBREX metadata.

    We rely on:
        - node.tag                  (COBOL construct type)
        - node.source_vars
        - node.target_vars
        - node.cond_vars

    Rules (simplified but COBOL-aware):

        DISPLAY:
            defs = {}
            uses = target_vars + cond_vars

        ACCEPT:
            defs = target_vars
            uses = cond_vars

        MOVE:
            defs = target_vars
            uses = source_vars + cond_vars

        ADD / SUBTRACT / DIVIDE / MULTIPLY / COMPUTE:
            defs = target_vars
            uses = source_vars + cond_vars + target_vars (read-modify-write)

        IF / EVALUATE / WHEN:
            defs = {}
            uses = cond_vars

        Other tags (fallback):
            defs = target_vars
            uses = source_vars + cond_vars
    """
    # Normalise everything to uppercase for consistency
    tag = (node.tag or "").upper()

    srcs = [s.upper() for s in node.source_vars]
    tgts = [t.upper() for t in node.target_vars]
    conds = [c.upper() for c in node.cond_vars]

    defs = set()
    uses = set()

    if tag == "DISPLAY":
        # Display reads variables (they appear as "target_variables" in COBREX)
        uses.update(tgts)
        uses.update(conds)

    elif tag == "ACCEPT":
        # ACCEPT VAR → VAR is defined (input from environment)
        defs.update(tgts)
        uses.update(conds)  # usually empty

    elif tag == "MOVE":
        defs.update(tgts)
        uses.update(srcs)
        uses.update(conds)

    elif tag in {"ADD", "SUBTRACT", "DIVIDE", "MULTIPLY", "COMPUTE"}:
        defs.update(tgts)
        uses.update(srcs)
        uses.update(conds)
        # LHS is also read in arithmetic statements: B = B + A
        uses.update(tgts)

    elif tag in {"IF", "EVALUATE", "WHEN"}:
        uses.update(conds)

    else:
        # Fallback heuristic for all other statements
        defs.update(tgts)
        uses.update(srcs)
        uses.update(conds)

    return defs, uses


def annotate_defs_uses(cfg: CFGGraph):
    """
    Populate node.defs and node.uses for every node in CFG.
    """
    for node in cfg.nodes.values():
        d, u = extract_defs_uses_for_node(node)
        node.defs = d
        node.uses = u


# ─────────────────────────────────────────────────────────────
# 3. Classic reaching definitions analysis
# ─────────────────────────────────────────────────────────────

def reaching_definitions(cfg: CFGGraph):
    """
    Forward dataflow analysis:

        IN[n]  = ⋃ OUT[p]  for all predecessors p
        OUT[n] = GEN[n] ∪ (IN[n] \ KILL[n])

    Each definition is represented as a pair: (var, node_id).
    """
    GEN = {}   # node_id -> set of definitions generated at n
    KILL = {}  # node_id -> set of definitions killed at n
    IN = {}
    OUT = {}

    defs_by_var = defaultdict(set)

    # Compute GEN and defs_by_var
    for n in cfg.nodes.values():
        GEN[n.id] = set()
        for v in n.defs:
            d = (v, n.id)
            GEN[n.id].add(d)
            defs_by_var[v].add(d)

    # Compute KILL
    for n in cfg.nodes.values():
        kill_set = set()
        for v in n.defs:
            for d in defs_by_var[v]:
                if d[1] != n.id:
                    kill_set.add(d)
        KILL[n.id] = kill_set

    # Initialise IN/OUT
    for n in cfg.nodes.values():
        IN[n.id] = set()
        OUT[n.id] = GEN[n.id].copy()

    # Iterative fixpoint
    changed = True
    while changed:
        changed = False

        for n in cfg.nodes.values():
            # IN[n] = union of OUT[p] for all predecessors
            new_in = set()
            for p in n.pred:
                new_in |= OUT[p]

            if new_in != IN[n.id]:
                IN[n.id] = new_in
                changed = True

            # OUT[n] = GEN[n] ∪ (IN[n] \ KILL[n])
            new_out = GEN[n.id] | (IN[n.id] - KILL[n.id])
            if new_out != OUT[n.id]:
                OUT[n.id] = new_out
                changed = True

    return IN, OUT


# ─────────────────────────────────────────────────────────────
# 4. Build DFG from reaching definitions
# ─────────────────────────────────────────────────────────────

def build_dfg(cfg: CFGGraph, IN):
    """
    Build DFG edges as:

        for each node n and each v in n.uses:
            for each (v, d_node) in IN[n]:
                add edge d_node -> n.id with label v

    Returns:
        dfg_edges: list of (def_node_id, use_node_id, var)
    """
    dfg_edges = []

    for n in cfg.nodes.values():
        for v in n.uses:
            for (var, def_node) in IN[n.id]:
                if var == v:
                    dfg_edges.append((def_node, n.id, v))

    return dfg_edges


# ─────────────────────────────────────────────────────────────
# 4b. Helpers for pruning / filtering DFG nodes
# ─────────────────────────────────────────────────────────────

def get_dfg_connected_nodes(dfg_edges):
    """
    Return the set of node IDs that actually participate
    in at least one DFG edge (either as def or use).

    This is what we will keep for the *pruned* DFG.
    """
    connected = set()
    for def_id, use_id, _ in dfg_edges:
        connected.add(def_id)
        connected.add(use_id)
    return connected


# ─────────────────────────────────────────────────────────────
# 5. Persist DFG as JSON and Graphviz PDF
# ─────────────────────────────────────────────────────────────

def save_dfg_to_json(cfg: CFGGraph, dfg_edges, path, node_filter=None):
    """
    Save DFG as JSON with explicit def/use statements:

    {
      "nodes": [
        {
          "id": "ATM:10:24",
          "label": "MOVE 'Y' TO VALID",
          "tag": "MOVE",
          "defs": ["VALID"],
          "uses": []
        },
        ...
      ],
      "edges": [
        {
          "def_node": "ATM:10:24",
          "use_node": "ATM:3:15",
          "variable": "VALID",
          "def_stmt": "MOVE 'Y' TO VALID",
          "use_stmt": "PERFORM ENTER-PIN UNTIL VALID = 'Y'"
        },
        ...
      ]
    }

    If node_filter is not None, only nodes whose id is in node_filter
    are included in the "nodes" section. Edges are also filtered so
    that both def_node and use_node are in node_filter.
    """
    if node_filter is not None:
        node_filter = set(node_filter)

    node_entries = []
    for node in cfg.nodes.values():
        if node_filter is not None and node.id not in node_filter:
            continue
        node_entries.append({
            "id": node.id,
            "label": node.label,
            "tag": node.tag,
            "defs": sorted(list(node.defs)),
            "uses": sorted(list(node.uses)),
        })

    edge_entries = []
    for def_id, use_id, var in dfg_edges:
        if node_filter is not None:
            if def_id not in node_filter or use_id not in node_filter:
                continue
        def_node = cfg.nodes.get(def_id)
        use_node = cfg.nodes.get(use_id)
        edge_entries.append({
            "def_node": def_id,
            "use_node": use_id,
            "variable": var,
            "def_stmt": def_node.label if def_node else "",
            "use_stmt": use_node.label if use_node else "",
        })

    data = {
        "nodes": node_entries,
        "edges": edge_entries,
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def export_dfg_graph(cfg: CFGGraph, dfg_edges, out_prefix, node_filter=None):
    """
    Build a Graphviz Digraph for the DFG and render to PDF.

    To avoid port warnings with IDs like "ATM:10:24", we map each
    original node id to a safe id "n0", "n1", ... in the DOT graph.

    If node_filter is not None, only those node IDs are included
    in the graph (nodes + edges).

    out_prefix example:
        /.../output/COBOL_ATM/DFG/DFG_ATM

    This will generate:
        DFG_ATM        (DOT source)
        DFG_ATM.pdf    (PDF graph)
    """
    dot = Digraph(comment="COBOL DFG", format="pdf")

    if node_filter is not None:
        node_filter = set(node_filter)

    # Map original ids -> safe DOT ids
    id_map = {}
    idx = 0
    for node_id in cfg.nodes.keys():
        if node_filter is not None and node_id not in node_filter:
            continue
        id_map[node_id] = f"n{idx}"
        idx += 1

    # Add nodes with labels
    for node in cfg.nodes.values():
        if node.id not in id_map:
            continue
        safe_id = id_map[node.id]
        stmt = node.label.replace("\n", " ")
        if len(stmt) > 60:
            stmt = stmt[:57] + "..."
        label = f"{node.id}\\n{stmt}"
        dot.node(safe_id, label=label)

    # Add edges (def -> use [var])
    for def_id, use_id, var in dfg_edges:
        if def_id not in id_map or use_id not in id_map:
            continue
        safe_def = id_map[def_id]
        safe_use = id_map[use_id]
        dot.edge(safe_def, safe_use, label=var)

    dot.render(out_prefix, cleanup=False)


# ─────────────────────────────────────────────────────────────
# 6. Convenience wrapper
# ─────────────────────────────────────────────────────────────

def build_dfg_from_cfg_json(cfg_json_path):
    """
    High-level helper:
        1. Load CFG from JSON.
        2. Annotate DEF/USE.
        3. Run reaching definitions.
        4. Build DFG edges.

    Returns:
        cfg        (CFGGraph)
        dfg_edges  (list of (def_node_id, use_node_id, var))
    """
    cfg = load_cfg_from_json(cfg_json_path)
    annotate_defs_uses(cfg)
    IN, OUT = reaching_definitions(cfg)
    dfg_edges = build_dfg(cfg, IN)
    return cfg, dfg_edges
