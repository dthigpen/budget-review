from decimal import Decimal
from tabulate import tabulate
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .budget import BudgetResult, BudgetExpense


def fmt_money(x, round_to_whole=False):
    from decimal import Decimal, ROUND_HALF_UP

    if not isinstance(x, Decimal):
        x = Decimal(str(x))

    if round_to_whole:
        x = x.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return f'{int(x):,}'

    # default: cents precision
    x = x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    if x == x.to_integral():
        return f'{int(x):,}'
    else:
        return f'{x:,.2f}'


def fmt_pct(x, round_to_whole=False):
    return fmt_money(x * Decimal('100'), round_to_whole=round_to_whole)


def table(rows, headers):

    return tabulate(rows, headers=headers, tablefmt='github')


def print_table(rows, headers):
    print(tabulate(rows, headers=headers, tablefmt='github'))
    print()


def print_budget_report(result: 'BudgetResult', show_excluded: bool = False):
    """Print a budget report from a BudgetResult.

    Args:
        result: BudgetResult with categorized expenses and totals
        show_excluded: If True, print excluded transactions section
    """
    from .beancount_util import short_account

    print()
    print('=== BUDGET PERIOD ===')
    print()
    print(f'Overall: {result.min_budget_date} to {result.max_budget_date}')
    print()

    if result.budget_config['accounts'] is not None:
        # Account-period mode
        print('Account periods:')
        for account, period in result.budget_config['accounts'].items():
            print(f'  {short_account(account)}: {period["start"]} to {period["end"]}')
    else:
        # Calendar-month mode
        print('Mode: Calendar-month (overall period)')
    print()

    print('=== SUMMARY ===')
    print()

    summary_rows = [
        [
            envelope,
            total,
        ]
        for envelope, total in sorted(
            result.totals.items(),
            key=lambda e: e[1],
            reverse=True,
        )
    ]

    print_table(
        summary_rows,
        ['Envelope', 'Total'],
    )

    print()
    print(f'Expenses in date range: {result.expenses_in_range}')
    print(f'Expenses in budget period: {result.expenses_in_budget_period}')

    if show_excluded:
        print()
        print('=== EXCLUDED TRANSACTIONS ===')
        print()
        print(f'Count: {len(result.excluded_expenses)}')
        print()

        if result.excluded_expenses:
            rows = []
            for expense in sorted(
                result.excluded_expenses,
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
            print('(no excluded transactions)')

    print()
    print('=== DETAILS ===')

    for envelope_name, expenses in sorted(
        result.categorized.items(),
        key=lambda e: result.totals[e[0]],
        reverse=True,
    ):
        total = result.totals[envelope_name]

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
