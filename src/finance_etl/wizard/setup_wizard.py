"""
Finance ETL — First-Run Setup Wizard  (importable module)
==========================================================

This module exposes the ``run_wizard()`` function used by both the
``finance_etl wizard`` CLI command and the standalone ``setup_wizard.py``
script at the repository root.

See ``setup_wizard.py`` (root) for full CLI usage documentation.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Optional

import yaml

from finance_etl.wizard.header_inference import infer_csv_headers
from finance_etl.wizard.category_suggestion import suggest_categories
from finance_etl.wizard.mapping_rules import generate_mapping_rules, read_descriptions


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_csv(raw_data_dir: Path) -> Path:
    """Return the first CSV file found under *raw_data_dir*."""
    csvs = sorted(raw_data_dir.glob("*.csv")) + sorted(raw_data_dir.glob("*.CSV"))
    if not csvs:
        raise FileNotFoundError(
            f"No CSV files found in '{raw_data_dir}'.\n"
            "Place your bank export CSV in that directory and re-run the wizard.\n"
            f"  mkdir -p {raw_data_dir} && cp <your_bank_export>.csv {raw_data_dir}/"
        )
    if len(csvs) > 1:
        print(f"[wizard] Multiple CSVs found — using the first: {csvs[0].name}")
    return csvs[0]


def _prompt_bank_info() -> dict[str, str]:
    """Interactively collect bank / account metadata from the user."""
    print("\n--- Bank / Account Information ---")
    print("(Press Enter to accept the default shown in brackets)\n")

    def ask(label: str, default: str) -> str:
        answer = input(f"  {label} [{default}]: ").strip()
        return answer if answer else default

    return {
        "bank_key":         ask("bank_key   (slug, e.g. chase_checking)", "my_bank"),
        "bank_name":        ask("bank_name  (e.g. Chase Bank)",           "My Bank"),
        "account_name":     ask("account_name (e.g. Personal Checking)",  "Primary Account"),
        "account_id":       ask("account_id (e.g. CHK-XXXX-1234)",        "ACCT-0000"),
        "currency_default": ask("currency  (e.g. USD)",                   "USD"),
    }


def _confirm(prompt: str, default: bool = True) -> bool:
    yn = "Y/n" if default else "y/N"
    answer = input(f"\n{prompt} [{yn}]: ").strip().lower()
    if not answer:
        return default
    return answer.startswith("y")


def _review_categories(
    clusters: dict[str, list[str]],
    auto_accept: bool,
) -> dict[str, list[str]]:
    """
    Let the user rename, skip, or accept each suggested category.

    When *auto_accept* is True all clusters are kept without prompting.
    """
    if auto_accept or not clusters:
        return clusters

    print("\n--- Category Review ---")
    print("For each suggestion, you can:")
    print("  • Press Enter          — accept with the suggested name")
    print("  • Type a new name      — rename the category")
    print("  • Type 'skip'          — exclude this category\n")

    accepted: dict[str, list[str]] = {}
    for idx, (name, keywords) in enumerate(clusters.items(), 1):
        kw_preview = ", ".join(keywords[:6])
        print(f"  [{idx:02d}] {name}")
        print(f"        Keywords: {kw_preview}")
        answer = input("        Accept / rename / skip? [Enter=accept]: ").strip()
        if answer.lower() == "skip":
            continue
        final_name = answer if answer and answer.lower() != "skip" else name
        accepted[final_name] = keywords

    return accepted


def _build_config(
    bank_info: dict[str, str],
    inference: dict,
    categories: dict[str, list[str]],
    mapping_rules: dict[str, str],
) -> dict:
    """
    Assemble the complete mapping config dict from all wizard outputs.

    The returned dict matches the structure expected by
    ``finance_etl.models.parse_mapping_config()``.
    """
    config: dict = {
        "bank_key":             bank_info["bank_key"],
        "bank_name":            bank_info["bank_name"],
        "account_name":         bank_info["account_name"],
        "account_id":           bank_info["account_id"],
        "amount_format_family": inference["amount_format_family"],
        "column_map":           inference["column_map"],
        "date":                 inference["date"],
        "amount":               inference["amount"],
        "currency_default":     bank_info["currency_default"],
        "locale": {
            "decimal_separator":    ".",
            "thousands_separator":  ",",
            "parentheses_negative": False,
            "date_locale":          "US",
        },
    }

    if inference.get("drop_columns"):
        config["drop_columns"] = inference["drop_columns"]

    if categories:
        config["suggested_categories"] = {
            name: keywords[:5]
            for name, keywords in categories.items()
        }

    if mapping_rules:
        config["keyword_rules"] = mapping_rules

    return config


def _yaml_dump(config: dict) -> str:
    """Render *config* as a well-formatted YAML string."""
    return yaml.dump(
        config,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=88,
    )


def _banner() -> str:
    return textwrap.dedent("""
    ╔══════════════════════════════════════════════╗
    ║   Finance ETL — First-Run Setup Wizard  v1   ║
    ╚══════════════════════════════════════════════╝
    Automated mode: you act as a reviewer, not a data engineer.
    """).strip()


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def run_wizard(
    raw_data_dir: str | Path = "raw_data",
    output_config: Optional[str | Path] = None,
    auto_yes: bool = False,
) -> Path:
    """
    Execute the full first-run setup wizard.

    Parameters
    ----------
    raw_data_dir : str | Path
        Directory to scan for the bank CSV export (default: ``raw_data/``).
    output_config : str | Path | None
        Where to write the generated YAML.
        Defaults to ``config/mappings/<bank_key>.yaml``.
    auto_yes : bool
        If True, accept every suggestion without interactive prompts.
        Useful in CI or batch-processing scenarios.

    Returns
    -------
    Path
        The resolved output path (whether or not the file was saved).
    """
    raw_data_dir = Path(raw_data_dir)
    print(_banner())

    # ------------------------------------------------------------------
    # Step 1 — Locate CSV
    # ------------------------------------------------------------------
    print("\n[1/5] Scanning for CSV file …")
    csv_path = _find_csv(raw_data_dir)
    print(f"      Found: {csv_path.name}")

    # ------------------------------------------------------------------
    # Step 2 — Header inference
    # ------------------------------------------------------------------
    print("\n[2/5] Inferring column headers …")
    inference = infer_csv_headers(str(csv_path))

    # ------------------------------------------------------------------
    # Step 3 — Category suggestion
    # ------------------------------------------------------------------
    print("\n[3/5] Generating category suggestions …")
    descriptions: list[str] = []
    try:
        descriptions = read_descriptions(csv_path)
    except ValueError as exc:
        print(f"      [warn] Could not read descriptions — skipping: {exc}")

    raw_clusters = suggest_categories(descriptions, n_clusters=8) if descriptions else {}
    categories = _review_categories(raw_clusters, auto_accept=auto_yes)

    # ------------------------------------------------------------------
    # Step 4 — Vendor mapping rules
    # ------------------------------------------------------------------
    print("\n[4/5] Generating vendor mapping rules …")
    mapping_rules: dict[str, str] = {}
    try:
        mapping_rules = generate_mapping_rules(str(csv_path), min_occurrences=3)
    except Exception as exc:
        print(f"      [warn] Could not generate mapping rules — skipping: {exc}")

    # ------------------------------------------------------------------
    # Step 5 — Collect bank metadata + assemble config
    # ------------------------------------------------------------------
    print("\n[5/5] Building config.yaml …")
    if auto_yes:
        bank_info: dict[str, str] = {
            "bank_key":         "my_bank",
            "bank_name":        "My Bank",
            "account_name":     "Primary Account",
            "account_id":       "ACCT-0000",
            "currency_default": "USD",
        }
    else:
        bank_info = _prompt_bank_info()

    config = _build_config(bank_info, inference, categories, mapping_rules)
    yaml_text = _yaml_dump(config)

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    sep = "=" * 60
    print(f"\n{sep}")
    print("  Generated config.yaml — PREVIEW")
    print(sep)
    print(yaml_text)
    print(sep)

    # ------------------------------------------------------------------
    # Resolve output path
    # ------------------------------------------------------------------
    if output_config is None:
        config_dir = Path("config/mappings")
        config_dir.mkdir(parents=True, exist_ok=True)
        output_path = config_dir / f"{bank_info['bank_key']}.yaml"
    else:
        output_path = Path(output_config)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Confirm + save
    # ------------------------------------------------------------------
    if auto_yes or _confirm(f"Save config to '{output_path}'?", default=True):
        output_path.write_text(yaml_text, encoding="utf-8")
        print(f"\n[wizard] Config saved → {output_path}")
        print("[wizard] You can now run the ETL pipeline with:")
        print(
            f"         finance_etl run --inputs {csv_path} "
            f"--bank-key {bank_info['bank_key']}"
        )
    else:
        print("\n[wizard] Save cancelled — the config was NOT written to disk.")

    return output_path
