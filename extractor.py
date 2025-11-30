"""
This module contains functions used by flask server to extract business rules,
convert json to dot format, and generating graph file
"""

"""
This module contains functions used by flask server to extract business rules,
convert json to dot format, and generating graph file
"""

import sys
from pathlib import Path

from preprocessor import preprocess
from ParsingUnit.main import extractor

# -------------------------------------------------------------------
# Ensure RBB modules (IRBuilder, CFGBuilder) are importable
# -------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
RBB_DIR = ROOT_DIR / "RBB"

# Add RBB directory to sys.path so we can import IRBuilder, CFGBuilder
if str(RBB_DIR) not in sys.path:
    sys.path.append(str(RBB_DIR))

from IRBuilder import runIR
from CFGBuilder import graphBuilder





def _fallback_make_clean_output(src_path: Path, clean_path: Path) -> None:
    """
    Fallback when GnuCOBOL/preprocessor fails (eg. missing SQLCA).
    We copy the original COBOL into `clean_output.cbl`, but:
      - drop lines containing SQLCA
      - drop EXEC SQL ... END-EXEC blocks
    so that the parser can still work on the remaining code.
    """
    skip_sql_block = False

    with src_path.open("r", errors="ignore") as fin, clean_path.open("w") as fout:
        for line in fin:
            u = line.upper()

            # detect EXEC SQL block
            if "EXEC SQL" in u:
                skip_sql_block = True
                continue

            if skip_sql_block:
                if "END-EXEC" in u:
                    skip_sql_block = False
                # do not write anything while skipping SQL block
                continue

            # drop SQLCA copy/include lines
            if "SQLCA" in u:
                continue

            fout.write(line)


def extract_business_rules(file_path: Path):
    """
    Main entry point: preprocess COBOL, run the parser/IR/CFG/BR extraction
    and print locations of generated artefacts.

    Returns a summary list:
      [cyclomatic_complexity, num_subrules, num_rules,
       constructs_addressed, total_constructs,
       indirectly_addressed, num_RBBs, total_lines]
    or None on hard failure.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        print("ERROR: File does not exists!")
        return None

    file_name = file_path.stem
    clean_output = Path("clean_output.cbl")

    print("STAGE: Parsing stage intialised.")

    # --------------------------
    # 1. Preprocess with fallback
    # --------------------------
    try:
        # Your existing preprocessor – may fail when SQLCA copybook is missing
        preprocess(str(file_path))
        if not clean_output.exists():
            # Some preprocessor versions write `output.i` then copy; be defensive
            raise FileNotFoundError("clean_output.cbl was not created by preprocess()")
    except Exception as e:
        # This is where your current run dies on SQLCA/output.i.
        print("WARNING: Preprocessing failed, using fallback sanitization.")
        print("Cause of error:", repr(e))

        try:
            _fallback_make_clean_output(file_path, clean_output)
            print("INFO: Fallback clean_output.cbl created (SQL/SQLCA stripped).")
        except Exception as inner:
            print("ERROR: Fallback preprocessing also failed.")
            print("Cause of error:", repr(inner))
            print("STAGE: Parsing stage Failed.")
            return None

    preprocessed_file_path = clean_output

    # --------------------------
    # 2. Run COBOL parser / extractor
    # --------------------------
    try:
        # This is directly from your existing code pattern:
        #   extractor(preprocessed_file_path, file_name, file_path, 'output')
        cfg_json, cyclomatic_complexity = extractor(
            str(preprocessed_file_path),  # preprocessed COBOL
            file_name,                    # program name
            str(file_path),               # original path
            "output",                     # root output folder
        )
    except Exception as e:
        print("ERROR: Parsing stage Failed.")
        print("Cause of error:", repr(e))
        # Optional: uncomment to debug deeply
        # traceback.print_exc()
        return None

    print("STAGE: Parsing stage successfully executed.")

    # --------------------------
    # 3. Run IR / BR / RBB builders
    # --------------------------
    total_lines = 0
    try:
        with preprocessed_file_path.open("r", errors="ignore") as f:
            total_lines = sum(1 for _ in f)
    except OSError:
        total_lines = 0

    try:
        (
            allConstructs,
            constructs_addressed,
            indirectly_addressed,
            num_subrules,
            num_rules,
            num_RBBs,
        ) = runIR(file_name)
    except Exception as e:
        # This is where you were seeing errors like 'A-GAIN' or 'WRITE-ERROR-MESSAGE'
        print("WARNING: IR / BR extraction failed; partial results only.")
        print("Cause of error:", repr(e))
        # traceback.print_exc()

        # degrade gracefully – no IR, but at least static structures may exist
        allConstructs = []
        constructs_addressed = []
        indirectly_addressed = []
        num_subrules = 0
        num_rules = 0
        num_RBBs = 0

    try:
        # If graphBuilder fails, we just log and move on.
        graphBuilder(file_name)
    except Exception as e:
        print("WARNING: CFG / graph building failed.")
        print("Cause of error:", repr(e))

    # --------------------------
    # 4. Print summary + paths
    # --------------------------
    print()
    print("===== COBREX Summary for program {} =====".format(file_name))
    print("Cyclomatic complexity      ::", cyclomatic_complexity)
    print("Total rules (incl. subrules)::", num_rules)
    print("Total subrules              ::", num_subrules)
    print("Total constructs            ::", len(allConstructs))
    print("Directly addressed constructs::", len(constructs_addressed))
    print("Indirectly addressed        ::", len(indirectly_addressed))
    print("RBBs                        ::", num_RBBs)
    print("Total preprocessed lines    ::", total_lines)
    print()

    print("CFG PDF          :: COBREX-CLI/output/COBOL_{}/CFG/CFG_{}.pdf"
          .format(file_name, file_name))
    print("RBBs directory   :: COBREX-CLI/output/COBOL_{}/RBBs"
          .format(file_name))
    print("Rules directory  :: COBREX-CLI/output/COBOL_{}/Rules"
          .format(file_name))
    print("Activation graph :: COBREX-CLI/output/COBOL_{}/BRR_{}.pdf"
          .format(file_name, file_name))

    return [
        cyclomatic_complexity,
        num_subrules,
        num_rules,
        constructs_addressed,
        len(allConstructs),
        indirectly_addressed,
        num_RBBs,
        total_lines,
    ]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("ERROR: File path not specified.")
        print("Supported Format :: python3 extractor.py <input-file-path>")
        sys.exit(1)

    file_path = Path(sys.argv[1])

    if not file_path.exists():
        print("ERROR: File does not exists!")
        sys.exit(1)

    extract_business_rules(file_path)
