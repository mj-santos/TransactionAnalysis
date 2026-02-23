# First-run mapping review (LLM handoff chart)

This chart summarizes how `finance_etl` expects a bank CSV mapping to be defined for first-run setup, with a North America-focused handoff section for generating starter templates.

## 1) What first-run requires

`finance_etl` needs one YAML mapping per bank/export format so it can map CSV headers into canonical transaction fields (date, description, amount, etc.).

## 2) Core schema chart

| Section | Key | Required | Purpose | Notes |
|---|---|---:|---|---|
| root | `bank_key` | Yes | Stable identifier used by CLI/API | Use lowercase slug, unique per bank format |
| root | `bank_name` | Yes | Human display name | Can include bank + account/export label |
| root | `account_name` | No | Friendly account label | Useful for multi-account ingestion |
| root | `account_id` | No | Safe account token | Never use full account number |
| root | `amount_format_family` | Yes | Declares amount parsing strategy | One of: `signed`, `debit_credit`, `money_in_out`, `amount_plus_flag` |
| root | `column_map` | Yes | Maps raw CSV headers to canonical names | Example canonical fields: `transaction_date`, `posted_date`, `description`, `amount` |
| root | `drop_columns` | No | Columns to ignore | Common for `Category`, `Balance` |
| root | `currency_default` | No | Default ISO currency code | Defaults to `USD` |
| root | `locale` | No | Numeric/date locale hints | Includes separators, parentheses handling, date locale |
| `date` | `transaction_date` | Yes | Main transaction date source header | Must be present |
| `date` | `posted_date` | No | Posted/settled date source header | Optional |
| `date` | `date_format` | Cond. | Explicit parse format | Recommended to avoid ambiguous dates |
| `amount` | family-specific keys | Yes | Amount interpretation inputs | Depends on selected `amount_format_family` |

## 3) Amount-family decision chart

| Family | Required amount keys | Computation model | Typical NA fit |
|---|---|---|---|
| `signed` | `signed_amount` | Single signed number (`+` inflow, `-` outflow) | Most US credit card exports; many US checking exports |
| `debit_credit` | `debit_col`, `credit_col` | Net = `credit - debit` | Some Canadian bank and credit-union exports |
| `money_in_out` | `money_in_col`, `money_out_col` | Separate inflow/outflow columns | Less common but seen in some retail banking portals |
| `amount_plus_flag` | `amount_col`, `dc_flag_col`, `dc_flag_values.debit`, `dc_flag_values.credit` | Sign inferred from Dr/Cr-style flag | Legacy/enterprise-style CSV exports |

## 4) Validation/guardrail chart

| Guardrail | Rule |
|---|---|
| Required roots | `bank_key`, `bank_name`, `amount_format_family`, `column_map`, `date` must exist |
| Valid family | `amount_format_family` must be one of the 4 supported families |
| Date minimum | `date.transaction_date` is mandatory |
| Family enforcement | Amount keys must match chosen family |
| Flag families | In `amount_plus_flag`, debit/credit flag value sets must both be non-empty and non-overlapping |
| Ambiguous dates | Prefer explicit `date.date_format`; locale fallback exists but ambiguity is fail-fast |

## 5) First-run workflow chart

| Step | Action | Output |
|---|---|---|
| 1 | Copy closest example mapping | New bank mapping YAML file |
| 2 | Replace sample header names with exact CSV column headers | Valid header-to-canonical map |
| 3 | Choose amount family matching export layout | Correct signed/net direction |
| 4 | Set `date.date_format` and locale separators | Deterministic parsing |
| 5 | Run with `--mapping` (or by `--bank-key`) | Parsed/staged transactions |

## 6) North America starter-template matrix (for another LLM)

Use this matrix as prompt context to generate starter templates (not final production mappings) for NA institutions.

| Template ID | Target institution pattern | Recommended family | Expected date style | Currency default | Common header hints to map |
|---|---|---|---|---|---|
| `na_us_credit_card_signed` | US credit cards (monthly activity export) | `signed` | `%m/%d/%Y` | `USD` | `Transaction Date`, `Post Date`, `Description`, `Amount` |
| `na_us_checking_signed` | US checking/savings (single amount column) | `signed` | `%m/%d/%Y` | `USD` | `Date`, `Description`, `Amount`, optional `Type` |
| `na_ca_debit_credit` | Canada retail banking with split columns | `debit_credit` | `%m/%d/%Y` or `%Y-%m-%d` | `CAD` | `Transaction Date`, `Description`, `Debit`, `Credit` |
| `na_ca_money_in_out` | Canada portals with explicit inflow/outflow labels | `money_in_out` | `%Y-%m-%d` | `CAD` | `Date`, `Details`, `Money In`, `Money Out` |
| `na_legacy_drcr_flag` | Exports with amount + DR/CR flag | `amount_plus_flag` | `%m/%d/%Y` | `USD`/`CAD` | `Date`, `Description`, `Amount`, `DR/CR` |

## 7) Prompt-ready constraints for template generation

When passing to another LLM, enforce these constraints:

1. Generate one mapping per export shape (not just per institution name).
2. Preserve exact CSV header strings in mapping keys.
3. Always include explicit `date.date_format` when date strings are ambiguous.
4. Keep `account_id` masked/safe.
5. Set `currency_default` to `USD` or `CAD` for NA templates unless known otherwise.
6. For `amount_plus_flag`, include non-overlapping debit and credit flag lists.
7. Include a short "expected CSV headers" comment block for human editing.

