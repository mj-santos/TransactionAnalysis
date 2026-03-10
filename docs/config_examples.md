# Mapping Config Examples

This document explains each field in a mapping YAML and provides examples for all four amount format families.

---

## Required Fields

| Field | Type | Description |
|---|---|---|
| `bank_key` | string | Unique identifier for this bank config (used for auto-detection) |
| `bank_name` | string | Human-readable bank name (stored in transactions_norm) |
| `account_name` | string | Account name (overridable via CLI `--account-name`) |
| `account_id` | string | Safe token identifier — **never use a full account number** |
| `amount_format_family` | string | One of: `signed`, `debit_credit`, `money_in_out`, `amount_plus_flag` |
| `column_map` | dict | Maps source CSV column name → canonical field name |
| `drop_columns` | list | Columns to discard during staging |
| `date` | dict | Specifies which source column(s) contain dates |
| `amount` | dict | Specifies amount column(s) for the chosen family |

---

## Family A: `signed`

Single column containing a signed amount. Positive = inflow, negative = outflow.

```yaml
bank_key: chase_visa
bank_name: "Chase Visa"
account_name: "Freedom Card"
account_id: "VISA-1234"
amount_format_family: signed

column_map:
  "Transaction Date": transaction_date
  "Post Date": posted_date
  "Description": description
  "Amount": amount

drop_columns: ["Category", "Memo"]

date:
  transaction_date: "Transaction Date"
  posted_date: "Post Date"
  date_format: "%m/%d/%Y"

amount:
  signed_amount: "Amount"

currency_default: "USD"
locale:
  decimal_separator: "."
  thousands_separator: ","
  parentheses_negative: false
  date_locale: "US"
```

---

## Family B: `debit_credit`

Two separate columns — one for debits (outflows), one for credits (inflows). Usually only one is populated per row.

```yaml
bank_key: barclays_current
bank_name: "Barclays"
account_name: "Current Account"
account_id: "BARC-5678"
amount_format_family: debit_credit

column_map:
  "Transaction Date": transaction_date
  "Transaction Description": description

drop_columns: ["Balance", "Type"]

date:
  transaction_date: "Transaction Date"
  date_format: "%d/%m/%Y"

amount:
  debit_col: "Debit Amount"
  credit_col: "Credit Amount"

currency_default: "GBP"
locale:
  decimal_separator: "."
  thousands_separator: ","
  parentheses_negative: false
  date_locale: "EU"
```

---

## Family C: `money_in_out`

Two columns representing money received and money sent. Both may be populated simultaneously.

```yaml
bank_key: commonwealth_au
bank_name: "Commonwealth Bank"
account_name: "Everyday Account"
account_id: "CBA-9999"
amount_format_family: money_in_out

column_map:
  "Date": transaction_date
  "Narration": description

drop_columns: ["Balance"]

date:
  transaction_date: "Date"
  date_format: "%d/%m/%Y"

amount:
  money_in_col: "Credit"
  money_out_col: "Debit"

currency_default: "AUD"
locale:
  decimal_separator: "."
  thousands_separator: ","
  parentheses_negative: false
  date_locale: "EU"
```

---

## Family D: `amount_plus_flag`

A single amount column plus a flag column indicating whether the transaction is a debit or credit.

```yaml
bank_key: hsbc_export
bank_name: "HSBC"
account_name: "Premier Account"
account_id: "HSBC-4321"
amount_format_family: amount_plus_flag

column_map:
  "Txn Date": transaction_date
  "Description": description

drop_columns: ["Ref No"]

date:
  transaction_date: "Txn Date"
  date_format: "%Y-%m-%d"

amount:
  amount_col: "Amount"
  dc_flag_col: "DR/CR Indicator"
  dc_flag_values:
    debit:  ["DR", "D", "Debit"]
    credit: ["CR", "C", "Credit"]

currency_default: "USD"
locale:
  decimal_separator: "."
  thousands_separator: ","
  parentheses_negative: false
  date_locale: "US"
```

---

## Date Format Reference (strptime)

| Format String | Example Input |
|---|---|
| `%m/%d/%Y` | `03/15/2024` (US) |
| `%d/%m/%Y` | `15/03/2024` (EU) |
| `%Y-%m-%d` | `2024-03-15` (ISO) |
| `%b %d, %Y` | `Mar 15, 2024` |
| `%d %b %Y` | `15 Mar 2024` |

If you omit `date_format`, the parser will auto-detect ISO 8601 safely. Any ambiguous format (e.g. `01/02/2024`) **requires** either an explicit `date_format` or `locale.date_locale: US|EU` — otherwise the pipeline will fail with an actionable error message.

---

## CLI Override Examples

```bash
# Override account name and ID at runtime (useful if one mapping covers multiple accounts)
finance_etl run \
  --inputs statements/savings_jan.csv \
  --mapping config/mappings/my_bank.yaml \
  --account-name "High-Yield Savings" \
  --account-id "SAV-7777"
```
