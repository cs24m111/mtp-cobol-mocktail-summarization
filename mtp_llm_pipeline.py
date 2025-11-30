"""LLM pipeline for COBOL code summarization mocktail experiments (local LLM / Ollama).

This script assumes you already ran the summarizer pipeline and have
prompt files for each rule/business-rule unit under a structure like:

  output/COBOL_ATM/BR_PROMPTS/
    C/
      PROMPT_ATM_rule_1_C.txt
      PROMPT_ATM_rule_2_C.txt
    C_BR/
      PROMPT_ATM_rule_1_C_BR.txt
      ...
    FULL/
      PROMPT_ATM_rule_1_FULL.txt
      ...

It does three things:

1) Rule-level summaries
   For each prompt file, call a local LLM (Code Processing Agent) and store
   the answer under rule_level/<mode>/...

2) File-level summaries
   For each mode, merge all rule-level summaries for a program using a
   Text Processing Agent into a single file-level explanation.

3) LLM-as-a-Judge evaluation (file level)
   For each mode, ask a Judge LLM to score the file-level summary
   against a human reference explanation.

You can adapt model names and paths as needed.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from mocktail.mocktail_config import DEFAULT_MOCKTAIL_MODES
from local_llm_client import call_llm


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PromptEntry:
    mode: str
    unit_id: str
    path: Path


# ---------------------------------------------------------------------------
# Prompt discovery
# ---------------------------------------------------------------------------


def discover_prompts(
    prompt_root: Path,
    prog: str,
    modes: List[str],
) -> Dict[str, List[PromptEntry]]:
    """Discover all prompt files for the given program and modes.

    Expected filename pattern (from build_br_prompts_mocktail.py):

      PROMPT_{prog}_{unit_id}_{mode}.txt

    For example:
      PROMPT_ATM_rule_1_C.txt
      PROMPT_ATM_rule_1_C_BR.txt
      PROMPT_ATM_rule_2_FULL.txt

    Returns:
      dict: mode -> list[PromptEntry]
    """

    mapping: Dict[str, List[PromptEntry]] = {}

    for mode in modes:
        mode_dir = prompt_root / mode
        if not mode_dir.is_dir():
            print(f"[discover_prompts] WARNING: mode dir not found: {mode_dir}")
            mapping[mode] = []
            continue

        entries: List[PromptEntry] = []
        for path in sorted(mode_dir.glob(f"PROMPT_{prog}_*_{mode}.txt")):
            stem_parts = path.stem.split("_")
            # e.g. ["PROMPT", "ATM", "rule", "1", "C"]
            # program is at index 1, mode is last part
            # unit_id is everything from index 2 to -1
            if len(stem_parts) < 4:
                unit_id = "_".join(stem_parts[2:-1]) or stem_parts[-2]
            else:
                unit_id = "_".join(stem_parts[2:-1])

            entries.append(PromptEntry(mode=mode, unit_id=unit_id, path=path))

        if not entries:
            print(f"[discover_prompts] WARNING: no prompt files found for mode={mode}")
        mapping[mode] = entries

    return mapping


# ---------------------------------------------------------------------------
# 1) Rule-level summary generation
# ---------------------------------------------------------------------------


def generate_rule_level_summaries(
    prog: str,
    prompt_root: Path,
    out_root: Path,
    modes: List[str],
    code_model: str,
) -> None:
    """Generate rule-level summaries for all prompts.

    For each mode and each PROMPT file we create:
      out_root / "rule_level" / <mode> / SUMMARY_{prog}_{unit_id}_{mode}.txt
    """

    prompt_map = discover_prompts(prompt_root, prog, modes)
    base_out = out_root / "rule_level"

    for mode, entries in prompt_map.items():
        if not entries:
            continue
        mode_out = base_out / mode
        mode_out.mkdir(parents=True, exist_ok=True)

        print(f"[rule_summaries] Mode={mode}, {len(entries)} prompts")

        for entry in entries:
            prompt_text = entry.path.read_text(encoding="utf-8")
            out_path = mode_out / f"SUMMARY_{prog}_{entry.unit_id}_{mode}.txt"

            # Skip if already exists (useful if you re-run).
            if out_path.exists():
                print(f"  [skip] {out_path} (already exists)")
                continue

            print(f"  [LLM] {entry.path.name} -> {out_path.name}")
            summary = call_llm(code_model, prompt_text)
            out_path.write_text(summary, encoding="utf-8")


# ---------------------------------------------------------------------------
# 2) File-level summary generation (Text Processing Agent)
# ---------------------------------------------------------------------------


def build_file_level_prompt(
    prog: str,
    mode: str,
    rule_summaries: List[Tuple[str, str]],
) -> str:
    """Build a hierarchical prompt that merges rule-level explanations.

    `rule_summaries` is a list of (unit_id, summary_text).
    """

    rules_block = []
    for unit_id, text in rule_summaries:
        rules_block.append(f"<Rule id=\"{unit_id}\">\n{text.strip()}\n</Rule>")

    rules_str = "\n\n".join(rules_block)

    prompt = f"""You are a Text Processing Agent that merges COBOL business-rule
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
    return prompt


def generate_file_level_summaries(
    prog: str,
    summaries_root: Path,
    out_root: Path,
    modes: List[str],
    text_model: str,
) -> None:
    """Merge rule-level summaries per mode into a single file-level summary.

    Inputs (produced by generate_rule_level_summaries):
      summaries_root / "rule_level" / <mode> / SUMMARY_{prog}_{unit_id}_{mode}.txt

    Output:
      out_root / "file_level" / FILE_SUMMARY_{prog}_{mode}.txt
    """

    base_in = summaries_root / "rule_level"
    base_out = out_root / "file_level"
    base_out.mkdir(parents=True, exist_ok=True)

    for mode in modes:
        mode_in = base_in / mode
        if not mode_in.is_dir():
            print(f"[file_summaries] WARNING: no rule summaries for mode={mode}")
            continue

        rule_files = sorted(mode_in.glob(f"SUMMARY_{prog}_*_{mode}.txt"))
        if not rule_files:
            print(f"[file_summaries] WARNING: empty mode dir: {mode_in}")
            continue

        rule_summaries: List[Tuple[str, str]] = []
        for path in rule_files:
            stem_parts = path.stem.split("_")
            # SUMMARY, prog, unit_id..., mode
            if len(stem_parts) < 4:
                unit_id = "_".join(stem_parts[2:-1]) or stem_parts[-2]
            else:
                unit_id = "_".join(stem_parts[2:-1])
            text = path.read_text(encoding="utf-8")
            rule_summaries.append((unit_id, text))

        prompt = build_file_level_prompt(prog, mode, rule_summaries)
        out_path = base_out / f"FILE_SUMMARY_{prog}_{mode}.txt"

        if out_path.exists():
            print(f"[file_summaries] [skip] {out_path} (already exists)")
            continue

        print(f"[file_summaries] Mode={mode}, {len(rule_summaries)} rules -> {out_path.name}")
        summary_text = call_llm(text_model, prompt)
        out_path.write_text(summary_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 3) LLM-as-a-Judge evaluation (file level)
# ---------------------------------------------------------------------------


def build_judge_prompt(reference: str, candidate: str, mode: str) -> str:
    """Build a prompt for the Judge LLM.

    We compare a candidate file-level explanation against a human-written
    reference explanation. The judge must output strict JSON so we can parse it.
    """

    return f"""You are an expert COBOL documentation reviewer.

You will be given two texts:
  1) A *reference* explanation for a COBOL program (written by a human).
  2) A *candidate* explanation generated by a model using configuration '{mode}'.

Your job is to evaluate how good the candidate explanation is compared to the
reference along the following dimensions (each 0–10, higher is better):

- purpose: does it clearly describe the overall purpose of the COBOL file?
- functionality: does it cover the key behaviors / main flows?
- clarity: is it easy to read and understand?
- overall: your overall judgment of quality, considering all the above.

Important:
- Only consider the *candidate* explanation. The reference is ground truth.
- Do NOT be overly strict about wording; focus on meaning.
- Return your answer as STRICT JSON on a single line, with this schema:
  {{"purpose": float, "functionality": float, "clarity": float, "overall": float}}

Reference explanation:
<Reference>
{reference.strip()}
</Reference>

Candidate explanation:
<Candidate>
{candidate.strip()}
</Candidate>
"""


def evaluate_file_level_summaries(
    prog: str,
    file_summaries_root: Path,
    reference_path: Path,
    modes: List[str],
    judge_model: str,
    out_json: Path,
) -> None:
    """Run LLM-as-a-Judge on each mode's file-level summary.

    Writes a JSON file like:
      {
        "ATM": {
          "C": {"purpose": 6.5, "functionality": 6.0, ...},
          "C_BR": {...},
          ...
        }
      }
    """

    reference = reference_path.read_text(encoding="utf-8")

    result: Dict[str, Dict[str, float]] = {}

    for mode in modes:
        path = file_summaries_root / "file_level" / f"FILE_SUMMARY_{prog}_{mode}.txt"
        if not path.is_file():
            print(f"[judge] WARNING: missing file-level summary for mode={mode}: {path}")
            continue

        candidate = path.read_text(encoding="utf-8")
        prompt = build_judge_prompt(reference, candidate, mode)

        print(f"[judge] Evaluating mode={mode}")
        raw = call_llm(judge_model, prompt)

        try:
            scores = json.loads(raw)
        except json.JSONDecodeError:
            # Try to recover if the model added text around JSON
            try:
                start = raw.index("{")
                end = raw.rindex("}") + 1
                scores = json.loads(raw[start:end])
            except Exception as e:
                raise RuntimeError(
                    f"Could not parse judge JSON for mode={mode}: {e}\nRaw: {raw}"
                )

        # Normalise to floats and keep only expected keys
        cleaned: Dict[str, float | None] = {}
        for key in ("purpose", "functionality", "clarity", "overall"):
            val = scores.get(key)
            try:
                cleaned[key] = float(val)
            except (TypeError, ValueError):
                cleaned[key] = None

        result[mode] = cleaned

    # Wrap under program ID so you can later aggregate multiple programs
    wrapped = {prog: result}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(wrapped, indent=2), encoding="utf-8")
    print(f"[judge] Results written to {out_json}")


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local LLM-based summarization + evaluation for COBOL mocktails.",
    )

    parser.add_argument("--prog", required=True, help="Program ID, e.g. ATM")
    parser.add_argument(
        "--base-dir",
        type=Path,
        required=True,
        help="Base output dir for this program, e.g. output/COBOL_ATM",
    )
    parser.add_argument(
        "--prompt-root",
        type=Path,
        default=None,
        help="Root directory of prompts (defaults to BASE/BR_PROMPTS)",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=None,
        help="Root directory for summaries and evaluation (defaults to BASE)",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        default=list(DEFAULT_MOCKTAIL_MODES),
        help="Mocktail modes to process (default: all defined in mocktail_config).",
    )

    sub = parser.add_subparsers(dest="stage", required=True)

    # Stage 1: rule-level summaries
    p_rule = sub.add_parser("rule", help="Generate rule-level summaries from prompts")
    p_rule.add_argument(
        "--code-model",
        default="codellama",
        help="Local model name for Code Processing Agent (e.g., codellama, llama3.1).",
    )

    # Stage 2: file-level summaries
    p_file = sub.add_parser("file", help="Merge rule summaries into file-level summary")
    p_file.add_argument(
        "--text-model",
        default="llama3.1",
        help="Local model name for Text Processing Agent (e.g., llama3.1).",
    )

    # Stage 3: judge
    p_judge = sub.add_parser("judge", help="Run LLM-as-a-Judge on file-level summaries")
    p_judge.add_argument(
        "--reference",
        type=Path,
        required=True,
        help="Path to human-written reference explanation for the COBOL file",
    )
    p_judge.add_argument(
        "--judge-model",
        default="llama3.1",
        help="Local model name for Judge LLM (e.g., llama3.1).",
    )
    p_judge.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="Where to store JSON results (defaults to BASE/eval_{prog}.json)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    prog: str = args.prog
    base_dir: Path = args.base_dir
    prompt_root: Path = args.prompt_root or (base_dir / "BR_PROMPTS")
    out_root: Path = args.out_root or base_dir

    if args.stage == "rule":
        generate_rule_level_summaries(
            prog=prog,
            prompt_root=prompt_root,
            out_root=out_root,
            modes=args.modes,
            code_model=args.code_model,
        )

    elif args.stage == "file":
        generate_file_level_summaries(
            prog=prog,
            summaries_root=out_root,
            out_root=out_root,
            modes=args.modes,
            text_model=args.text_model,
        )

    elif args.stage == "judge":
        out_json: Path = args.out_json or (out_root / f"eval_{prog}.json")
        evaluate_file_level_summaries(
            prog=prog,
            file_summaries_root=out_root,
            reference_path=args.reference,
            modes=args.modes,
            judge_model=args.judge_model,
            out_json=out_json,
        )


if __name__ == "__main__":
    main()
