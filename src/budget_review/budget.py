import argparse
from datetime import date
from pathlib import Path
import json

from .format import print_table
from decimal import Decimal
from .beancount_util import (
    short_account,
    expense_postings,
    funding_postings,
    load_transactions,
)
from beancount.core.data import (
    Posting,
    Transaction,
)

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class BudgetExpense:
    transaction: Transaction
    posting: Posting  # Original expense posting
    funding_account: str  # Single funding source
    allocated_amount: Decimal  # Portion allocated to this funding source


from decimal import Decimal


def allocate_budget_expenses(txn: Transaction):
    expenses = expense_postings(txn)
    funding = funding_postings(txn)

    if not expenses or not funding:
        return

    #
    # Fast path (95% of transactions)
    #
    if len(expenses) == 1 and len(funding) == 1:
        yield BudgetExpense(
            transaction=txn,
            posting=expenses[0],
            funding_account=funding[0].account,
            allocated_amount=expenses[0].units.number,
        )
        return

    total_expenses = sum(p.units.number for p in expenses)

    for funding_posting in funding:
        fraction = abs(funding_posting.units.number) / total_expenses

        for expense_posting in expenses:
            yield BudgetExpense(
                transaction=txn,
                posting=expense_posting,
                funding_account=funding_posting.account,
                allocated_amount=expense_posting.units.number * fraction,
            )


def expense_in_budget_period(
    expense: BudgetExpense,
    budget,
):
    account_budget = budget['accounts'].get(expense.funding_account)

    if account_budget is None:
        print(f"Funding account '{expense.funding_account}' not in budget.")
        return False

    return account_budget['start'] <= expense.transaction.date <= account_budget['end']


def validate_envelopes(envelopes):

    seen_tags = {}

    for name, envelope in envelopes.items():
        for tag in envelope.get('tags', []):
            if tag in seen_tags:
                raise ValueError(
                    f"Tag '{tag}' used by both {seen_tags[tag]} and {name}"
                )

            seen_tags[tag] = name


def match_envelope(
    expense,
    envelopes: dict,
) -> tuple[str, str]:

    posting = expense.posting
    txn = expense.transaction

    #
    # 1. Explicit posting override
    #
    override = posting.meta.get('budget')

    if override:
        if override not in envelopes:
            raise ValueError(f'Unknown budget override: {override}')

        return override, 'metadata'

    #
    # 2. Tag matching
    #
    tags = txn.tags or set()

    tag_matches = [
        name
        for name, envelope in envelopes.items()
        if any(tag in tags for tag in envelope.get('tags', []))
    ]

    if len(tag_matches) == 1:
        return tag_matches[0], 'tag'

    if len(tag_matches) > 1:
        raise ValueError(f'Multiple tag matches: {tag_matches}')

    #
    # 3. Account matching
    #
    account = posting.account

    account_matches = [
        name
        for name, envelope in envelopes.items()
        if any(account.startswith(prefix) for prefix in envelope.get('accounts', []))
    ]

    if len(account_matches) == 1:
        return account_matches[0], 'account'

    if len(account_matches) > 1:
        raise ValueError(f'Multiple account matches: {account_matches}')

    #
    # 4. Fallback
    #
    return 'Uncategorized', 'uncategorized'


def categorize_expenses(
    expenses,
    envelopes: dict,
):
    categorized = {name: [] for name in envelopes}

    categorized['Uncategorized'] = []

    for expense in expenses:
        envelope, match_type = match_envelope(
            expense,
            envelopes,
        )

        categorized[envelope].append(expense)

    return categorized


def envelope_totals(categorized):
    totals = {}

    for name, expenses in categorized.items():
        totals[name] = sum(
            (expense.allocated_amount for expense in expenses),
            start=Decimal('0'),
        )

    return totals


def run_budget_report(
    categorized: dict,
    totals: dict,
):
    print()
    print('=== SUMMARY ===')
    print()

    summary_rows = [
        [
            envelope,
            total,
        ]
        for envelope, total in sorted(
            totals.items(),
            key=lambda e: e[1],
            reverse=True,
        )
    ]

    print_table(
        summary_rows,
        ['Envelope', 'Total'],
    )

    print()
    print('=== DETAILS ===')

    for envelope_name, expenses in sorted(
        categorized.items(),
        key=lambda e: totals[e[0]],
        reverse=True,
    ):
        total = totals[envelope_name]

        print()
        print('=' * 80)
        print(f'{envelope_name} (${total:.2f})')
        print('=' * 80)

        rows = []

        for expense in sorted(
            expenses,
            key=lambda e: e.transaction.date,
        ):
            rows.append(
                [
                    expense.transaction.date.isoformat(),
                    expense.transaction.narration[:10].strip(),
                    short_account(expense.funding_account),
                    short_account(expense.posting.account),
                    expense.allocated_amount,
                ]
            )

        if rows:
            print_table(
                rows,
                [
                    'Date',
                    'Description',
                    'Funding',
                    'Expense Account',
                    'Amount',
                ],
            )
        else:
            print('(no transactions)')


def existing_file(p):
    p = Path(p)
    if p.is_file():
        return p
    raise argparse.ArgumentTypeError(f'Path must be an existing file: {p}')


def run(budget_path: Path, ledger_path: Path):
    budget = json.loads(budget_path.read_text())
    validate_envelopes(budget['envelopes'])
    # min_budget_date = date.fromisoformat('2999-01-01')
    # Find the min date AND update the date strings to actual date types
    min_budget_date = None
    for acc, dates in budget.get('accounts', {}).items():
        start = date.fromisoformat(dates['start'])
        end = date.fromisoformat(dates['end'])
        dates['start'] = start
        dates['end'] = end
        if min_budget_date is None or start < min_budget_date:
            min_budget_date = start

    transactions = load_transactions(ledger_path)
    expenses = [
        expense
        for txn in transactions
        for expense in allocate_budget_expenses(txn)
        if expense.transaction.date >= min_budget_date
    ]

    budget_expenses = [
        expense
        for expense in expenses
        if expense_in_budget_period(
            expense,
            budget,
        )
    ]
    print(f'Min start date: {min_budget_date}')
    print(f'Expenses in range: {len(expenses)}')
    print(f'Expenses in budget period: {len(budget_expenses)}')

    categorized = categorize_expenses(
        budget_expenses,
        budget['envelopes'],
    )

    totals = envelope_totals(categorized)

    run_budget_report(categorized, totals)
