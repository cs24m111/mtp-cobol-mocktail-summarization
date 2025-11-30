#!/usr/bin/env python3
"""
Run COBREX static extraction for all COBOL programs in one or more projects.

Usage examples:

  # run for all projects under data/project_clean
  python run_all_projects_static.py

  # run only for one project
  python run_all_projects_static.py --projects IBM_example-health-apis

Assumptions:
  - COBOL sources live under: data/project_clean/<project_name>/*.cbl
  - extractor.py will write static outputs to:
        output/<project_name>/COBOL_<PROGRAM>
"""

import argparse
import subprocess
import sys
from pathlib import Path


DEFAULT_PROJECTS_ROOT = Path("data") / "project_clean"
DEFAULT_OUTPUT_ROOT = Path("output")


def discover_projects(projects_root: Path) -> list[str]:
    """Return sorted list of project directory names under projects_root."""
    if not projects_root.exists():
        return []
    return sorted(
        p.name for p in projects_root.iterdir() if p.is_dir()
    )


def iter_cobol_files(projects_root: Path, project_name: str):
    """Yield all .cbl files for a given project."""
    proj_dir = projects_root / project_name
    if not proj_dir.exists():
        return

    for path in sorted(proj_dir.rglob("*.cbl")):
        # only regular files
        if path.is_file():
            yield path


def run_extractor_for_file(
    cobol_path: Path,
    project_name: str,
    output_root: Path,
) -> bool:
    """Call extractor.py for a single COBOL file, with SKIP logic."""
    prog_name = cobol_path.stem

    # expected output: output/<project>/COBOL_<prog>
    prog_out_dir = output_root / project_name / f"COBOL_{prog_name}"

    if prog_out_dir.exists():
        print(f"--- [{project_name}] {cobol_path.name} (program={prog_name}) ---")
        print(f"[SKIP] Already processed → {prog_out_dir}")
        return True

    print(f"--- [{project_name}] {cobol_path.name} (program={prog_name}) ---")
    print(f"[RUN] python extractor.py {cobol_path}")

    try:
        subprocess.run(
            [sys.executable, "extractor.py", str(cobol_path)],
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(
            f"[ERROR] Failure for {cobol_path}: "
            f"Command {e.cmd!r} returned non-zero exit status {e.returncode}."
        )
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run COBREX static extraction for COBOL projects."
    )

    parser.add_argument(
        "--projects-root",
        type=Path,
        default=DEFAULT_PROJECTS_ROOT,
        help="Root directory containing project folders "
             "(default: data/project_clean)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root directory where static outputs are written (default: output)",
    )
    parser.add_argument(
        "--projects",
        nargs="*",
        help=(
            "Specific project names to run. If omitted, all projects under "
            "projects-root are processed."
        ),
    )

    args = parser.parse_args(argv)

    projects_root: Path = args.projects_root
    output_root: Path = args.output_root

    if args.projects:
        projects = args.projects
    else:
        projects = discover_projects(projects_root)

    if not projects:
        print(f"[INFO] No projects found under {projects_root}")
        return 0

    print(f"[INFO] Projects: {projects!r}")
    print()

    any_failures = False

    for proj in projects:
        proj_dir = projects_root / proj
        if not proj_dir.exists():
            print(f"[WARN] Project {proj!r} does not exist under {projects_root}")
            continue

        cobol_files = list(iter_cobol_files(projects_root, proj))
        print(
            f"========== REPO: {proj} "
            f"({len(cobol_files)} COBOL files) =========="
        )
        print()

        for cobol_path in cobol_files:
            ok = run_extractor_for_file(cobol_path, proj, output_root)
            if not ok:
                any_failures = True
            print()  # blank line between files

    if any_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
