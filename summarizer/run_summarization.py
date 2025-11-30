# summarizer/run_summarization.py

from __future__ import annotations

import argparse
import json
from pathlib import Path
from textwrap import dedent
from typing import Dict, List, Iterable

from .mocktail_config import MOCKTAIL_VIEWS, DEFAULT_MOCKTAIL_MODES


def load_br_reps(br_rep_dir: Path) -> List[Dict]:
    reps: List[Dict] = []
    if not br_rep_dir.is_dir():
        raise FileNotFoundError(f"BR_REP directory not found: {br_rep_dir}")
    for path in sorted(br_rep_dir.glob("BR_*.json")):
        with path.open("r", encoding="utf-8") as f:
            reps.append(json.load(f))
    return reps


def _safe_br_id(br_id: str) -> str:
    s = br_id.replace("::", "__")
    for ch in ["/", "\\", " ", ":", "\"", "'"]:
        s = s.replace(ch, "_")
    return s


# ---------- view formatters ----------

def _fmt_code(rep: Dict) -> str:
    lines = rep.get("raw_code", []) or []
    body = "\n".join(f"  {ln}" for ln in lines)
    return f"<CODE>\n{body}\n</CODE>"


def _fmt_br(rep: Dict) -> str:
    br_text = (rep.get("br_text") or "").strip()
    if not br_text:
        return ""
    return f"<BUSINESS_RULE>\n{br_text}\n</BUSINESS_RULE>"


def _fmt_brr(rep: Dict) -> str:
    # BR_REP currently does not store BRR; we add a placeholder so the
    # LLM knows there is an execution/realisation view.
    # If you later add BRR text into BR_REP (e.g. rep["brr_text"]), use that here.
    brr_text = (rep.get("brr_text") or "").strip()
    if not brr_text:
        brr_text = (
            "BR realisation (BRR) information is available in the underlying "
            "analysis (paragraphs, activation graph), but not fully included "
            "in this JSON view. Treat the rule code and control/data-flow "
            "facts as the practical realisation."
        )
    return f"<BR_REALISATION>\n{brr_text}\n</BR_REALISATION>"


def _fmt_dfg_pruned(rep: Dict) -> str:
    df = rep.get("data_flow_summary") or []
    if not df:
        return ""
    lines: List[str] = []
    for item in df:
        var = item.get("variable", "?")
        defs = item.get("definitions", []) or []
        uses = item.get("uses", []) or []
        lines.append(
            f"- variable {var}:\n"
            f"    defs: {defs}\n"
            f"    uses: {uses}"
        )
    body = "\n".join(lines)
    return f"<DFG_PRUNED>\n{body}\n</DFG_PRUNED>"


def _fmt_cfg(rep: Dict) -> str:
    facts = rep.get("control_flow_facts") or []
    if not facts:
        return ""
    body = "\n".join(f"- {f}" for f in facts)
    return f"<CFG_FACTS>\n{body}\n</CFG_FACTS>"


def _fmt_ast(rep: Dict) -> str:
    # We don’t have raw AST nodes here; we expose a high-level note
    # plus paragraph/line span from code_span.
    span = rep.get("code_span") or {}
    paras = span.get("paragraphs")
    lines = span.get("lines")
    return (
        "<AST_VIEW>\n"
        f"- Paragraphs covered: {paras}\n"
        f"- Line range: {lines}\n"
        "- Assume a COBOL AST has been constructed and used to derive the "
        "data-flow and control-flow summaries.\n"
        "</AST_VIEW>"
    )


def _fmt_pdg(rep: Dict) -> str:
    # PDG is implicitly reflected by control/data-flow categories; we annotate that.
    cats = rep.get("categories") or {}
    body = (
        "Program dependence (data + control) has been analysed. "
        f"High-level categories: {cats}"
    )
    return f"<PDG_VIEW>\n{body}\n</PDG_VIEW>"


def build_prompt_for_br(rep: Dict, mode: str) -> str:
    if mode not in MOCKTAIL_VIEWS:
        raise KeyError(f"Unknown mocktail mode: {mode}")
    views = MOCKTAIL_VIEWS[mode]

    prog = rep.get("program", "")
    br_id = rep.get("br_id", "")

    header = dedent(
        f"""
        You are an expert mainframe COBOL engineer.

        Program: {prog}
        Business-Rule Unit (BR-ID): {br_id}

        You will be given one or more *views* of this rule, such as:
        - COBOL source lines
        - business rule text
        - pruned data-flow facts
        - control-flow / structural information
        - program dependence / category tags

        Your job is to explain what THIS rule does, in business terms.
        Focus only on this rule, not the entire program.
        """
    ).strip()

    sections: List[str] = []

    for v in views:
        if v == "CODE":
            sections.append(_fmt_code(rep))
        elif v == "BR":
            block = _fmt_br(rep)
            if block:
                sections.append(block)
        elif v == "BRR":
            sections.append(_fmt_brr(rep))
        elif v == "DFG_PRUNED":
            block = _fmt_dfg_pruned(rep)
            if block:
                sections.append(block)
        elif v == "CFG":
            block = _fmt_cfg(rep)
            if block:
                sections.append(block)
        elif v == "AST":
            sections.append(_fmt_ast(rep))
        elif v == "PDG":
            sections.append(_fmt_pdg(rep))
        else:
            # Ignore unknown view labels so the config can evolve safely.
            continue

    context = "\n\n".join(sections)

    footer = dedent(
        """
        Write 3–7 sentences that:
        - Describe the purpose of this rule.
        - Mention key decisions, loops, validations and important fields.
        - Use clear English suitable for a human analyst.
        - Do NOT just restate the code line-by-line.
        - Do NOT include any XML or tags in your answer, only prose.
        """
    ).strip()

    return header + "\n\n" + context + "\n\n" + footer


# ---------- core entrypoint for other scripts ----------

def build_prompts_for_program(
    prog: str,
    base_dir: Path,
    modes: List[str],
) -> None:
    br_rep_dir = base_dir / "BR_REP"
    reps = load_br_reps(br_rep_dir)
    if not reps:
        print(f"[WARN] No BR_REP JSON files for program {prog} in {br_rep_dir}")
        return

    for mode in modes:
        if mode not in MOCKTAIL_VIEWS:
            raise KeyError(f"Unknown mocktail mode: {mode}")

        mode_out_dir = base_dir / "BR_PROMPTS" / mode
        mode_out_dir.mkdir(parents=True, exist_ok=True)

        for rep in reps:
            br_id = rep.get("br_id", "UNKNOWN")
            safe_id = _safe_br_id(br_id)
            prompt = build_prompt_for_br(rep, mode)

            out_name = f"PROMPT_{prog}_{safe_id}_{mode}.txt"
            out_path = mode_out_dir / out_name
            with out_path.open("w", encoding="utf-8") as f:
                f.write(prompt)

        print(f"[PROMPTS] {prog} mode={mode} -> {mode_out_dir}")


def _cli(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate mocktail prompts for a COBOL program from BR_REP."
    )
    parser.add_argument("--prog", required=True, help="Program name, e.g. ATM")
    parser.add_argument(
        "--base-dir",
        required=True,
        type=Path,
        help="Base output dir, e.g. output/COBOL_ATM",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        default=list(DEFAULT_MOCKTAIL_MODES),
        help=f"Mocktail modes (default: {list(DEFAULT_MOCKTAIL_MODES)})",
    )
    args = parser.parse_args(argv)
    build_prompts_for_program(args.prog, args.base_dir, args.modes)


if __name__ == "__main__":
    _cli()
