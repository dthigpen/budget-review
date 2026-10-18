# budget-review

An opinionated tool for reviewing Beancount expenses against budget envelopes.

## Usage

### CLI

```bash
budget-review --budget budget.json --ledger ledger.bean
```

### Python API

```python
from budget_review import review_budget, print_budget_report

result = review_budget(
    budget_path="budget.json",
    ledger_path="ledger.bean",
)

print_budget_report(result)
```

## Budget Configuration

The budget JSON file defines envelope categories and funding account periods:

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
    }
  }
}
```

Expense matching priority:
1. Posting metadata (`budget: envelope-name`)
2. Transaction tags
3. Account prefix
4. Falls back to "Uncategorized"

## Example Output

```
Min start date: 2024-01-01
Expenses in range: 142
Expenses in budget period: 138

=== SUMMARY ===

Envelope      Total
-----------  -------
Groceries    850.42
Dining       423.15
Uncategorized  12.50

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