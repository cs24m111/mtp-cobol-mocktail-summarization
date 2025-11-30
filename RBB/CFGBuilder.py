# RBB/CFGBuilder.py

from pathlib import Path

def graphBuilder(ir_path: str, out_dir: str, prog_name: str) -> None:
    """
    Stub implementation of graphBuilder.

    Parameters
    ----------
    ir_path : str
        Path to the IR file produced by IRBuilder (usually .json or .txt).
    out_dir : str
        Directory where CFG/graph artifacts would normally be written.
    prog_name : str
        Program name (e.g., 'HCIVDB01') used for naming outputs.

    This stub just ensures the pipeline doesn't fail when CFGBuilder
    is imported and called.
    """
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    # Optional: create a small marker file so you can confirm it ran
    marker = out_dir_path / f"CFG_{prog_name}.stub"
    try:
        marker.write_text("CFGBuilder stub invoked for program: " + prog_name)
    except Exception:
        # Don't break the pipeline if writing fails
        pass

    print("[CFGBuilder] Stub graphBuilder called (no-op).")
