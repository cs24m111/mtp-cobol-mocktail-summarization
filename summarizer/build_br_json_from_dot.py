# summarizer/build_br_json_from_dot.py

import os
import re
import json
from typing import Dict, Any, List


def build_acobrex_br_from_dot(rules_dir: str, prog_name: str) -> Dict[str, Any]:
    """
    Scan rule_*.dot (or rule_* without extension) in rules_dir and build:

    {
      "program": "ATM",
      "business_rules": [
        {
          "id": "rule_1",
          "description": "PERFORM ENTER-PIN UNTIL VALID = 'Y'",
          "start_line": 15,
          "end_line": 28
        },
        ...
      ]
    }

    We infer start/end line from node IDs like "AU ATM AU 15 15 87".
    """
    business_rules: List[Dict[str, Any]] = []

    for fname in sorted(os.listdir(rules_dir)):
        if not fname.startswith("rule_"):
            continue
        path = os.path.join(rules_dir, fname)
        with open(path, "r", errors="ignore") as f:
            lines = f.read().splitlines()

        starts: List[int] = []
        ends: List[int] = []
        first_label = None

        for line in lines:
            # Node declaration with [label=...]
            m = re.search(r'"([^"]+)"\s*\[label=', line)
            if not m:
                continue

            node_id = m.group(1)
            parts = node_id.split()
            # Expected: ['AU', 'ATM', 'AU', '15', '15', '87'] or ['PC','ATM','PC','23','23','9']
            if len(parts) >= 6 and parts[1] == prog_name:
                try:
                    s = int(parts[3])
                    e = int(parts[4])
                    starts.append(s)
                    ends.append(e)
                except Exception:
                    pass

            # Capture first textual label as a description
            if first_label is None:
                m2 = re.search(r'\[label="(.+)"', line)
                if m2:
                    first_label = m2.group(1).replace(r"\"", '"')

        if not starts or not ends:
            # Nothing useful in this rule file
            continue

        br_id = os.path.splitext(fname)[0]  # e.g. "rule_1"
        start_line = min(starts)
        end_line = max(ends)
        if not first_label:
            first_label = br_id

        business_rules.append({
            "id": br_id,
            "description": first_label,
            "start_line": start_line,
            "end_line": end_line,
        })

    return {
        "program": prog_name,
        "business_rules": business_rules,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Build A-COBREX business rule JSON from rule_*.dot files."
    )
    parser.add_argument(
        "--prog",
        required=True,
        help="Program name, e.g. ATM",
    )
    parser.add_argument(
        "--rules-dir",
        required=True,
        help="Directory containing rule_* DOT files.",
    )
    parser.add_argument(
        "--out-json",
        required=True,
        help="Output JSON path, e.g. output/COBOL_ATM/BR/BR_ATM.json",
    )
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    br_json = build_acobrex_br_from_dot(args.rules_dir, args.prog)

    with open(args.out_json, "w") as f:
        json.dump(br_json, f, indent=2)

    print(f"[build_br_json_from_dot] Wrote {args.out_json}")


if __name__ == "__main__":
    main()
