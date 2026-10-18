# budget-review

An opinionated tool for reviewing Beancount expenses against budget envelopes.

## Usage

### CLI

```bash
budget-review --budget budget.json --ledger ledger.bean
budget-review --budget budget.json --ledger ledger.bean --show-excluded
```

The `--show-excluded` flag displays transactions that fall outside the budget period.

## Budget Configuration

The budget JSON file defines envelope categories and budget periods. Two modes are supported:

### Calendar-Month Mode

For conventional calendar-month budgeting:

```json
{
  "period": "2026-01",
  "envelopes": {
    "Groceries": {
      "tags": ["groceries"],
      "accounts": ["Expenses:Food:Groceries"]
    },
    "Dining": {
      "tags": ["dining", "restaurant"],
      "accounts": ["Expenses:Food:Dining"]
    }
  }
}
```

The `period` can be specified as a year-month string (`"2026-01"`) or as a dictionary with start/end dates (`{"start": "2026-01-01", "end": "2026-01-31"}`). In this mode, all transactions within the overall period are included regardless of funding account.

### Account-Period Mode (Advanced)

For users with funding accounts that have different budget cycles:

```json
{
  "envelopes": {
    "Groceries": {
      "tags": ["groceries"],
      "accounts": ["Expenses:Food:Groceries"]
    },
    "Dining": {
      "tags": ["dining", "restaurant"],
      "accounts": ["Expenses:Food:Dining"]
    }
  },
  "accounts": {
    "Assets:Checking:Budget": {
      "start": "2024-01-01",
      "end": "2024-12-31"
    },
    "Assets:Savings:Emergency": {
      "start": "2024-06-01",
      "end": "2024-12-31"
    }
  }
}
```

In account-period mode, expenses are included based on their funding account's specific budget period. You must specify either `period` or `accounts`, but not both.

## Envelope Overrides

You can override automatic envelope matching by adding metadata to a Beancount posting:

```
2024-01-05 * "Weekly shop"
  Expenses:Food:Groceries  125.30 USD
    budget: "Groceries"
  Assets:Checking:Budget  -125.30 USD
```

The `budget` metadata key on the expense posting forces the expense into the specified envelope, taking priority over tag and account matching.

Expense matching priority:
1. Posting metadata (`budget: envelope-name`)
2. Transaction tags
3. Account prefix
4. Falls back to "Uncategorized"

### Python API

```python
from budget_review import review_budget, print_budget_report

result = review_budget(
    budget_path="budget.json",
    ledger_path="ledger.bean",
)

print_budget_report(result, show_excluded=True)
```

## Example Output

```
=== BUDGET PERIOD ===

Overall: 2024-01-01 to 2024-12-31

Account periods:
  Checking:Budget: 2024-01-01 to 2024-12-31

=== SUMMARY ===

Envelope      Total
-----------  -------
Groceries    850.42
Dining       423.15
Uncategorized  12.50

Expenses in date range: 142
Expenses in budget period: 138

=== DETAILS ===

================================================================================
Groceries ($850.42)
================================================================================

Date       Description      Funding      Expense Account    Amount
---------- --------------- ------------ ----------------- --------
2024-01-05 Weekly shop      Checking     Food:Groceries    125.30
2024-01-12 Weekend stock    Checking     Food:Groceries     87.45
```

## Beancount Transaction Format

Expenses are allocated from funding accounts (non-Expenses/Income postings):

```
2024-01-05 * "Weekly shop"
  Expenses:Food:Groceries  125.30 USD
  Assets:Checking:Budget  -125.30 USD
```

Add a posting metadata override to force envelope assignment:

```
2024-01-05 * "Weekly shop"
  Expenses:Food:Groceries  125.30 USD  ^budget:Groceries
  Assets:Checking:Budget  -125.30 USD
```