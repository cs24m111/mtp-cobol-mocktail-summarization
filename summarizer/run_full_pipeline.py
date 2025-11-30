# summarizer/run_full_pipeline.py

import os
import subprocess
from typing import List


def run(cmd: List[str]):
    print("[RUN]", " ".join(cmd))
    subprocess.check_call(cmd)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run full COBOL → BR → ProgramIndex → BR_REP → prompts pipeline."
    )
    parser.add_argument("--prog", required=True, help="Program name, e.g. ATM")
    parser.add_argument(
        "--base-dir",
        required=True,
        help="Base output dir, e.g. output/COBOL_ATM",
    )
    parser.add_argument(
        "--rules-dir",
        required=True,
        help="Directory where rule_* DOT files are produced for this program.",
    )
    parser.add_argument(
        "--br-json",
        required=True,
        help="Where to store BR_<PROG>.json (A-COBREX rule JSON).",
    )
    parser.add_argument(
        "--prompts-dir",
        required=True,
        help="Where to store LLM prompts.",
    )
  

    parser.add_argument(
    "--modes",
    nargs="+",
    default=["C", "C_BR", "C_BR_BRR", "C_AST_DFGP", "C_AST_CFG_DFGP_PDG", "FULL"],
    help="Experiment modes to generate prompts for.",
)

    args = parser.parse_args()

    prog = args.prog
    base = args.base_dir

    # 1) Build BR JSON from rule_*.dot
    run([
        "python", "-m", "summarizer.build_br_json_from_dot",
        "--prog", prog,
        "--rules-dir", args.rules_dir,
        "--out-json", args.br_json,
    ])

    # 2) Build ProgramIndex
    run([
        "python", "-m", "summarizer.program_index",
        "--prog", prog,
        "--base-dir", base,
        "--br-json", args.br_json,
    ])

    # 3) Build BR representations
    run([
        "python", "-m", "summarizer.br_representation",
        "--prog", prog,
        "--base-dir", base,
    ])

    # 4) Generate prompts for each mode
    for mode in args.modes:
        mode_out_dir = os.path.join(args.prompts_dir, mode)
        run([
            "python", "-m", "summarizer.run_summarization",
            "--prog", prog,
            "--base-dir", base,
            "--out-dir", mode_out_dir,
            "--mode", mode,
        ])

    print("[run_full_pipeline] Done.")


if __name__ == "__main__":
    main()
