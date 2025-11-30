from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from summarizer.mocktail_config import DEFAULT_MOCKTAIL_MODES
from ollama_utils import generate_text


# ---------- discovery ----------

def find_cobol_program_dirs(output_root: Path) -> Iterable[Tuple[str, Path]]:
    """
    Yield (prog, base_dir) for each directory named COBOL_<PROG>.
    Works for both output/COBOL_ATM and output/ProjectX/COBOL_ATM.
    """
    for path in output_root.glob("**/COBOL_*"):
        if not path.is_dir():
            continue
        prog = path.name.replace("COBOL_", "", 1)
        yield prog, path


def iter_prompt_files(base_dir: Path, mode: str) -> Iterable[Tuple[str, Path]]:
    """
    Yield (rule_id, prompt_path) for PROMPT files for this mode.

    Expected filename pattern:
      PROMPT_{prog}_{sanitised_br_id}_{mode}.txt
    """
    prompts_dir = base_dir / "BR_PROMPTS" / mode
    if not prompts_dir.is_dir():
        return []

    files = sorted(prompts_dir.glob(f"PROMPT_*_{mode}.txt"))
    out: List[Tuple[str, Path]] = []

    for path in files:
        # recover something like a rule id from the middle
        stem = path.stem  # PROMPT_ATM_rule_1_C or PROMPT_ATM_ATM__1_C
        parts = stem.split("_")
        # best effort: everything between program (index 1) and mode (last) is "br_id"
        if len(parts) >= 4:
            rule_id = "_".join(parts[2:-1])
        else:
            rule_id = parts[-2]
        out.append((rule_id, path))

    return out


# ---------- rule-level summaries ----------

def generate_rule_level_summaries_for_program(
    prog: str,
    base_dir: Path,
    modes: List[str],
    model: str,
    overwrite: bool = False,
) -> None:
    for mode in modes:
        entries = list(iter_prompt_files(base_dir, mode))
        if not entries:
            print(f"[WARN] {prog}: no prompts for mode={mode} → skip rule-level")
            continue

        out_dir = base_dir / "LLM_Ollama" / mode / "rule_level"
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"[RULE] {prog} mode={mode}: {len(entries)} prompts")
        for rule_id, prompt_path in entries:
            out_path = out_dir / f"SUMMARY_{prog}_{rule_id}_{mode}.txt"
            if out_path.exists() and not overwrite:
                continue

            prompt_text = prompt_path.read_text(encoding="utf-8")
            try:
                ans = generate_text(model, prompt_text)
            except Exception as e:
                print(f"  [ERROR] Ollama failed for {prog} rule={rule_id} mode={mode}: {e}")
                continue

            out_path.write_text(ans, encoding="utf-8")

        print(f"  -> rule summaries in {out_dir}")


# ---------- file-level summaries ----------

def build_file_level_prompt(
    prog: str,
    mode: str,
    rule_summaries: List[Tuple[str, str]],
) -> str:
    blocks = []
    for rule_id, text in rule_summaries:
        blocks.append(f"<Rule id=\"{rule_id}\">\n{text.strip()}\n</Rule>")

    rules_str = "\n\n".join(blocks)

    return f"""You are a Text Processing Agent that merges COBOL business-rule
explanations into a single, coherent file-level explanation.

Program ID: {prog}
Configuration / mocktail: {mode}

You are given a list of rule-level explanations (one per business rule or
paragraph-level unit) enclosed in <Rule> tags.

Your task:
1. Produce ONE clear, human-readable explanation of the ENTIRE COBOL file.
2. Cover the overall business purpose of the file (what this program does).
3. Summarize the major responsibilities of each rule/paragraph and how they
   interact (e.g., control flow, data flow).
4. Highlight any important validation or error-handling logic.
5. Write 2–4 short paragraphs (150–250 words in total).

Do NOT repeat the <Rule> texts verbatim. Instead, synthesize them into a
higher-level explanation.

<Rules>
{rules_str}
</Rules>
"""


def generate_file_level_summaries_for_program(
    prog: str,
    base_dir: Path,
    modes: List[str],
    model: str,
    overwrite: bool = False,
) -> None:
    for mode in modes:
        rule_dir = base_dir / "LLM_Ollama" / mode / "rule_level"
        if not rule_dir.is_dir():
            print(f"[WARN] {prog}: no rule summaries for mode={mode} → skip file-level")
            continue

        out_dir = base_dir / "LLM_Ollama" / mode / "file_level"
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / f"FILE_SUMMARY_{prog}_{mode}.txt"
        if out_path.exists() and not overwrite:
            continue

        rule_files = sorted(rule_dir.glob(f"SUMMARY_{prog}_*_{mode}.txt"))
        if not rule_files:
            print(f"[WARN] {prog}: empty rule dir for mode={mode}")
            continue

        collected: List[Tuple[str, str]] = []
        for path in rule_files:
            stem_parts = path.stem.split("_")
            # SUMMARY, prog, <rule_id...>, mode
            if len(stem_parts) < 4:
                rule_id = "_".join(stem_parts[2:-1]) or stem_parts[-2]
            else:
                rule_id = "_".join(stem_parts[2:-1])
            text = path.read_text(encoding="utf-8")
            collected.append((rule_id, text))

        prompt = build_file_level_prompt(prog, mode, collected)
        try:
            ans = generate_text(model, prompt)
        except Exception as e:
            print(f"[ERROR] Ollama file-level failed for {prog} mode={mode}: {e}")
            continue

        out_path.write_text(ans, encoding="utf-8")
        print(f"[FILE] {prog} mode={mode} -> {out_path}")


# ---------- evaluation: file-level ROUGE-1 F1 vs CSV ----------

def load_references(csv_path: Path, prog_col: str = "prog", text_col: str = "reference") -> Dict[str, str]:
    refs: Dict[str, str] = {}
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            prog = (row.get(prog_col) or "").strip()
            txt = (row.get(text_col) or "").strip()
            if prog and txt and prog not in refs:
                refs[prog] = txt
    return refs


def _tokens(s: str) -> List[str]:
    return [t for t in s.lower().split() if t]


def rouge1_f1(pred: str, ref: str) -> float:
    p = _tokens(pred)
    r = _tokens(ref)
    if not p or not r:
        return 0.0

    from collections import Counter
    cp, cr = Counter(p), Counter(r)
    overlap = sum(min(cp[w], cr[w]) for w in cp)

    prec = overlap / len(p)
    rec = overlap / len(r)
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


def evaluate_program(
    prog: str,
    base_dir: Path,
    modes: List[str],
    ref_text: str,
) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for mode in modes:
        path = base_dir / "LLM_Ollama" / mode / "file_level" / f"FILE_SUMMARY_{prog}_{mode}.txt"
        if not path.is_file():
            continue
        pred = path.read_text(encoding="utf-8")
        scores[mode] = rouge1_f1(pred, ref_text)
    return scores


# ---------- main ----------

def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run Ollama-based rule + file-level summarisation for ALL COBOL programs."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("output"),
        help="Root holding COBOL_* dirs (default: ./output)",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        default=list(DEFAULT_MOCKTAIL_MODES),
        help="Mocktail modes (default: all from mocktail_config)",
    )
    parser.add_argument(
        "--model",
        default="llama3",
        help="Ollama model name (default: llama3)",
    )
    parser.add_argument(
        "--ref-csv",
        type=Path,
        default=None,
        help="CSV with human file-level references (columns: prog, reference).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate summaries even if outputs exist.",
    )
    args = parser.parse_args(argv)

    refs: Dict[str, str] = {}
    if args.ref_csv is not None and args.ref_csv.is_file():
        refs = load_references(args.ref_csv)

    agg: Dict[str, Tuple[float, int]] = defaultdict(lambda: [0.0, 0])  # mode -> [sum, count]

    for prog, base_dir in find_cobol_program_dirs(args.output_root):
        print(f"\n========== PROGRAM {prog} ({base_dir}) ==========")

        generate_rule_level_summaries_for_program(
            prog=prog,
            base_dir=base_dir,
            modes=args.modes,
            model=args.model,
            overwrite=args.overwrite,
        )

        generate_file_level_summaries_for_program(
            prog=prog,
            base_dir=base_dir,
            modes=args.modes,
            model=args.model,
            overwrite=args.overwrite,
        )

        if prog in refs:
            scores = evaluate_program(
                prog=prog,
                base_dir=base_dir,
                modes=args.modes,
                ref_text=refs[prog],
            )
            print(f"[METRICS] {prog}: {json.dumps(scores, indent=2)}")
            for mode, s in scores.items():
                agg[mode][0] += s
                agg[mode][1] += 1
        elif refs:
            print(f"[WARN] no reference found in CSV for prog={prog}; skipping metric.")

    if agg:
        print("\n===== AGGREGATED AVERAGE ROUGE-1 F1 OVER ALL FILES =====")
        for mode in sorted(agg.keys()):
            total, count = agg[mode]
            avg = total / count if count else 0.0
            print(f"{mode:18s}: {avg:0.4f}  (n={count})")


if __name__ == "__main__":
    main()
