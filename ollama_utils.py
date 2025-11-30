# ollama_utils.py
"""
Small helper wrapper around the `ollama` CLI.

Usage:
    from ollama_utils import generate_text

    text = generate_text("llama3.1", "Your prompt here")
"""

from __future__ import annotations

import subprocess
from typing import Optional


def _run_ollama(model: str, prompt: str, timeout: Optional[int] = None) -> str:
    """
    Call `ollama run <model>` with the given prompt and return the
    concatenated text output.

    Assumes Ollama is installed locally and the model has been pulled.
    """
    proc = subprocess.Popen(
        ["ollama", "run", model],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = proc.communicate(prompt, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ollama run failed (code={proc.returncode}): {err.strip()}")
    return out.strip()


def generate_text(model: str, prompt: str, timeout: Optional[int] = None) -> str:
    """Return raw text from the Ollama model."""
    return _run_ollama(model, prompt, timeout=timeout)
