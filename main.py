#!/usr/bin/env python3
"""Backward-compatible entry point.

The implementation now lives in the ``custom_mcp_database`` package under ``src/``.
This shim keeps existing client configs that point at ``main.py`` working. Prefer
the ``custom-mcp-database`` console command (installed via ``pip``/``uv``/``uvx``).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from custom_mcp_database.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
