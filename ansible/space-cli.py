#!/usr/bin/env python3
"""Alias launcher for space-navigator."""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("space-navigator.py")), run_name="__main__")
