"""
finance_etl.wizard — Automated setup helpers for the first-run wizard.

Public API
----------
infer_csv_headers(file_path)        → header-inference dict  (header_inference.py)
suggest_categories(descriptions)    → {category: [keywords]} (category_suggestion.py)
generate_mapping_rules(csv_path)    → {vendor: category}     (mapping_rules.py)
run_wizard(raw_data_dir, ...)       → Path to saved config   (setup_wizard.py)
"""
from .header_inference import infer_csv_headers
from .category_suggestion import suggest_categories
from .mapping_rules import generate_mapping_rules
from .setup_wizard import run_wizard

__all__ = [
    "infer_csv_headers",
    "suggest_categories",
    "generate_mapping_rules",
    "run_wizard",
]
