#!/usr/bin/env python3
"""Run from the repository: uv run --extra eval --env-file .env python tools/run_evaluation.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.evaluation import main

if __name__ == '__main__':
    main()
