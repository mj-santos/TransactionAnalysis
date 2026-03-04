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

## Optional fallback amount columns (amount_debit / amount_credit)

Two optional canonical fields can supplement **any** primary `amount_format_family`:

| Key | Purpose | Sign convention |
|-----|---------|----------------|
| `amount.amount_debit` | Outflow / withdrawal column | Positive number → stored negative |
| `amount.amount_credit` | Inflow / deposit column | Positive number → stored positive |

These are resolved by `resolve_amount()` only when the primary family field is absent or empty:

```
Step 1 — Parse via amount_format_family (backward-compatible)
Step 2 — Fall back to amount_debit / amount_credit if Step 1 yields nothing
            result = credit − debit  (positive = inflow, negative = outflow)
Step 3 — All fields empty → row skipped with a warning
```

They can also serve as the **sole** amount mapping (when no primary family columns are
present).  In that case the wizard sets `amount_format_family: signed` with an empty
`signed_amount`; Step 2 of the resolver handles the rest automatically.

Example YAML fragment:
```yaml
amount:
  amount_debit: "Debit"    # outflow column (positive numbers)
  amount_credit: "Credit"  # inflow column  (positive numbers)
```

## Canonical field reference

| Canonical field | Required | Description |
|----------------|---------|-------------|
| `transaction_date` | **Yes** | Transaction date column |
| `debit_amount` | Group | Withdrawal amount (pairs with `credit_amount`) |
| `credit_amount` | Group | Deposit amount (pairs with `debit_amount`) |
| `amount` | Group | Signed amount (positive=inflow, negative=outflow) |
| `money_in` | Group | Inflow column (pairs with `money_out`) |
| `money_out` | Group | Outflow column (pairs with `money_in`) |
| `dc_flag` | Group | Debit/Credit flag (pairs with `amount`) |
| `amount_debit` | Optional | Fallback outflow column (positive number) |
| `amount_credit` | Optional | Fallback inflow column (positive number) |
| `description` | Optional | Transaction description / narrative |
| `posted_date` | Optional | Settlement / posting date |
| `merchant` | Optional | Merchant / payee name |
| `category` | Optional | Transaction category |
| `account` | Optional | Account identifier |
| `notes` | Optional | Notes or memo |
| `currency` | Optional | Currency code |

"Group" means at least one complete group must be present for a valid mapping.

## Validation and guardrails

Mapping files are validated before staging starts.
Guardrails include:
- required key checks,
- family-specific amount-key checks,
- debit/credit flag sanity checks.
