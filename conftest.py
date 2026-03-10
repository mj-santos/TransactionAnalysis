"""
Root conftest.py — adds src/ to sys.path so pytest can find finance_etl
without requiring `pip install -e .` first.
"""
import sys
from pathlib import Path

# Insert src/ at the front of the path
sys.path.insert(0, str(Path(__file__).parent / "src"))
