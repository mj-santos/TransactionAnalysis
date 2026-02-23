# CONFIG

Configuration guide for bank mappings and runtime behavior.

## Mapping files

Mapping YAMLs live in `config/mappings/`.

Examples:
- `config/mappings/example_signed_amount.yaml`
- `config/mappings/example_debit_credit.yaml`

Run with explicit mapping:

```bash
finance_etl run --inputs data/raw/transactions.csv --mapping config/mappings/my_bank.yaml
```

Or by bank key:

```bash
finance_etl run --inputs data/raw/transactions.csv --bank-key my_bank
```

## Required mapping keys

- `bank_key`
- `bank_name`
- `amount_format_family`
- `column_map`
- `date`

`amount_format_family` must be one of:
- `signed`
- `debit_credit`
- `money_in_out`
- `amount_plus_flag`

## Amount-family specific keys

### signed
- `amount.signed_amount`

### debit_credit
- `amount.debit_col`
- `amount.credit_col`

### money_in_out
- `amount.money_in_col`
- `amount.money_out_col`

### amount_plus_flag
- `amount.amount_col`
- `amount.dc_flag_col`
- `amount.dc_flag_values.debit` (non-empty)
- `amount.dc_flag_values.credit` (non-empty)
- debit/credit flag sets must not overlap

## Date parsing configuration

Date ambiguity is fail-fast.
Use either:
- `date.date_format` (recommended), or
- `locale.date_locale` (`US`/`EU`) when input format is ambiguous.

## Currency + locale options

Optional keys:
- `currency_default` (e.g. `USD`, `GBP`)
- `locale.decimal_separator`
- `locale.thousands_separator`
- `locale.parentheses_negative`
- `locale.date_locale`

## Other config assets

- `config/canonical_schema.yaml`: canonical field reference
- `config/categories/rules.yaml`: optional categorization rules

## Validation and guardrails

Mapping files are validated before staging starts.
Guardrails include:
- required key checks,
- family-specific amount-key checks,
- debit/credit flag sanity checks.
