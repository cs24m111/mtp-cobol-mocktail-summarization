#!/usr/bin/env python
import argparse
import csv
from pathlib import Path
import textwrap

import ollama  # make sure `pip install ollama` and Ollama is running


import itertools

def load_referenced_files(ref_csv: Path):
    """
    Returns a set of canonicalized file identifiers that already have references.

    We do NOT assume specific column names.
    Instead:
    - For each row, we search for any cell containing '.cbl'
    - Treat that as a COBOL file path
    - Derive project_name and file_name from that path.

    Key format: 'project_name/file_name'
    Example: 'IBM_example-health-apis/HCAPDB01.cbl'
    """
    referenced = set()

    with ref_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            print("[WARN] No header row found in reference CSV.")
            return referenced

        print(f"[DEBUG] CSV columns: {reader.fieldnames}")

        for row in reader:
            cobol_path_val = None

            # Look through all cell values to find something like "*.cbl"
            for v in row.values():
                if not v:
                    continue
                v_str = str(v).strip()
                if ".cbl" in v_str.lower():
                    cobol_path_val = v_str
                    break

            if not cobol_path_val:
                # This row doesn't contain a COBOL path
                continue

            p = Path(cobol_path_val)
            file_name = p.name
            project_name = p.parent.name  # parent folder name as project

            key = f"{project_name}/{file_name}"
            referenced.add(key)

    # Print a few example keys for sanity check
    print("[INFO] Example referenced keys (up to 10):")
    for k in itertools.islice(referenced, 10):
        print("   ", k)

    return referenced


def build_prompt(source_code: str) -> str:
    """
    Build the summarization prompt:
    - human annotator style
    - max 200 words
    - 2–3 paragraphs
    """
    instruction = textwrap.dedent(
        """
        You are a human annotator creating reference summaries for a COBOL-to-English dataset.

        Task:
        - Read the COBOL program below.
        - Write a natural-language summary as if you are a human annotator describing what this program does.
        - Describe its main purpose, important inputs/outputs, and key processing logic.
        - Do NOT explain COBOL syntax itself; focus on behaviour and intent.

        Output format:
        - 2 to 3 paragraphs.
        - Maximum 200 words in total.
        - No bullet points, no code, no headings. Only plain paragraphs.

        Now summarize the following COBOL program.
        """
    ).strip()

    return f"{instruction}\n\n<PROGRAM>\n{source_code}\n</PROGRAM>"


def generate_summary_for_file(
    model: str,
    cobol_path: Path,
) -> str:
    """
    Call Ollama to generate the human-like summary for a single COBOL file.
    """
    code = cobol_path.read_text(encoding="utf-8", errors="ignore")
    prompt = build_prompt(code)

    response = ollama.generate(
        model=model,
        prompt=prompt,
    )
    # `response` is a dict; the text is usually in the "response" key
    summary = response.get("response", "").strip()
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Generate human-annotator-like summaries for COBOL files "
                    "that do NOT have entries in the reference CSV."
    )

    parser.add_argument(
        "--projects-root",
        type=Path,
        required=True,
        help="Root directory containing project folders with .cbl files "
             "(e.g. data/project_clean).",
    )
    parser.add_argument(
        "--ref-csv",
        type=Path,
        required=True,
        help="Path to file_level_reference_dataset.csv (or similar).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Directory where generated summaries will be saved.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="llama3.1",
        help="Ollama model name to use (default: llama3.1).",
    )

    args = parser.parse_args()

    projects_root: Path = args.projects_root
    ref_csv: Path = args.ref_csv
    output_root: Path = args.output_root
    model: str = args.model

    if not projects_root.is_dir():
        raise SystemExit(f"projects-root does not exist or is not a directory: {projects_root}")

    if not ref_csv.is_file():
        raise SystemExit(f"ref-csv does not exist: {ref_csv}")

    output_root.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Loading referenced files from: {ref_csv}")
    referenced = load_referenced_files(ref_csv)
    print(f"[INFO] Found {len(referenced)} files already having references.")

    total = 0
    skipped = 0
    generated = 0

    # Walk all projects and .cbl files
    for proj_dir in sorted(projects_root.iterdir()):
        if not proj_dir.is_dir():
            continue

        project_name = proj_dir.name

        for cobol_path in sorted(proj_dir.rglob("*.cbl")):
            total += 1
            key = f"{project_name}/{cobol_path.name}"

            if key in referenced:
                skipped += 1
                # already has a human reference -> skip
                print(f"[SKIP] {key} (already in reference CSV)")
                continue

            # Generate summary for this file
            print(f"[GEN]  {key}")
            summary = generate_summary_for_file(model, cobol_path)

            # Save under: output_root/project_name/PROGRAM_human_ref.txt
            proj_out_dir = output_root / project_name
            proj_out_dir.mkdir(parents=True, exist_ok=True)
            out_path = proj_out_dir / f"{cobol_path.stem}_human_ref.txt"
            out_path.write_text(summary, encoding="utf-8")
            generated += 1

    print()
    print(f"[DONE] Total COBOL files scanned : {total}")
    print(f"[DONE] Skipped (already referenced): {skipped}")
    print(f"[DONE] Generated new summaries   : {generated}")
    print(f"[DONE] Saved under               : {output_root}")


if __name__ == "__main__":
    main()
