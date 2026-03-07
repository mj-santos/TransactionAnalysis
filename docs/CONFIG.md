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

## Credit-card transaction model

Credit-card rows are classified into three subtypes using `transaction_subtype`:

| Subtype | Meaning | Effect on balance |
|---------|---------|-------------------|
| `spending` | Purchase/charge on card | Increases balance owed |
| `payment` | Payment toward card balance | Decreases balance owed |
| `adjustment` | Refund, chargeback, or credit | Decreases balance owed |
| `NULL` | Legacy row — no subtype | Excluded from balance |

**Card Balance formula:** `Card Balance = Total Spending − Total Payments − Total Adjustments`

A positive balance = amount still owed. Negative = card is in credit (overpaid).

### CC amount formats

**Format C (two-column):** `amount.debit_col` + `amount.credit_col` — charge/payment auto-split.

**Format A** (`cc_polarity: format_a`): positive = spending (most US cards).

**Format B** (`cc_polarity: format_b`): positive = payment (some EU/UK banks).

`resolved_amount` is always ≥ 0. Direction is encoded entirely in `transaction_subtype`.

## Canonical field reference

Canonical fields are **scoped by statement_type** in the wizard.

### Credit-card fields (statement_type = credit_card)

| Canonical field | Old name (retired) | Required | Description |
|----------------|-------------------|---------|-------------|
| `cc_amount` | `amount` | CC Group | Single signed/unsigned amount — polarity confirmed by user |
| `cc_charge` | `amount_debit` | CC Group | Money charged to card (Format C → spending) |
| `cc_payment` | `amount_credit` | CC Group | Money paid toward card (Format C → payment) |

CC Group: one of (`cc_charge` + `cc_payment`) or (`cc_amount`) must be mapped.

### Bank fields (statement_type = bank)

| Canonical field | Old name | Required | Description |
|----------------|---------|---------|-------------|
| `bank_amount` | `amount` | Bank Group | Single signed/unsigned amount |
| `bank_debit` | `amount_debit` | Bank Group | Money leaving the bank account |
| `bank_credit` | `amount_credit` | Bank Group | Money entering the bank account |
| `debit_amount` | — | Bank Group | Withdrawal (pairs with `credit_amount`) |
| `credit_amount` | — | Bank Group | Deposit (pairs with `debit_amount`) |
| `money_in` | — | Bank Group | Inflow (pairs with `money_out`) |
| `money_out` | — | Bank Group | Outflow (pairs with `money_in`) |
| `dc_flag` | — | Bank Group | Debit/Credit flag (pairs with `bank_amount`) |

Bank Group: at least one complete group must be present.

### Shared fields (both types)

| Canonical field | Required | Description |
|----------------|---------|-------------|
| `transaction_date` | **Yes** | Transaction date column |
| `description` | Optional | Transaction description / narrative |
| `posted_date` | Optional | Settlement / posting date |
| `merchant` | Optional | Merchant / payee name |
| `category` | Optional | Transaction category |
| `account` | Optional | Account identifier |
| `notes` | Optional | Notes or memo |
| `currency` | Optional | Currency code |

### Retired field names (rejected by the validator with a clear error)

| Retired name | Use instead (CC) | Use instead (bank) |
|-------------|-----------------|-------------------|
| `amount` | `cc_amount` | `bank_amount` |
| `amount_debit` | `cc_charge` | `bank_debit` |
| `amount_credit` | `cc_payment` | `bank_credit` |

## Validation and guardrails

Mapping files are validated before staging starts.
Guardrails include:
- required key checks,
- family-specific amount-key checks,
- debit/credit flag sanity checks.
