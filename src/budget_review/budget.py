import argparse
from datetime import date
from pathlib import Path
import json

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
from typing import TypedDict


@dataclass(slots=True)
class BudgetExpense:
    transaction: Transaction
    posting: Posting  # Original expense posting
    funding_account: str  # Single funding source
    allocated_amount: Decimal  # Portion allocated to this funding source


@dataclass(slots=True)
class BudgetResult:
    """Structured result from budget review."""
    min_budget_date: date
    expenses_in_range: int
    expenses_in_budget_period: int
    categorized: dict[str, list[BudgetExpense]]
    totals: dict[str, Decimal]


class AccountPeriod(TypedDict):
    """Budget period for a funding account."""
    start: date
    end: date


class EnvelopeConfig(TypedDict):
    """Configuration for a budget envelope."""
    tags: list[str]
    accounts: list[str]


class BudgetConfig(TypedDict):
    """Validated budget configuration."""
    envelopes: dict[str, EnvelopeConfig]
    accounts: dict[str, AccountPeriod]


def validate_budget_config(raw_config: dict) -> BudgetConfig:
    """Validate and parse budget configuration from JSON.

    Args:
        raw_config: Raw dictionary from JSON file

    Returns:
        Validated BudgetConfig with parsed dates

    Raises:
        ValueError: If configuration is invalid
        KeyError: If required fields are missing
    """
    # Validate top-level structure
    if 'envelopes' not in raw_config:
        raise KeyError("Missing required field: 'envelopes'")
    if 'accounts' not in raw_config:
        raise KeyError("Missing required field: 'accounts'")

    if not isinstance(raw_config['envelopes'], dict):
        raise ValueError("'envelopes' must be a dictionary")
    if not isinstance(raw_config['accounts'], dict):
        raise ValueError("'accounts' must be a dictionary")

    # Validate envelopes
    envelopes: dict[str, EnvelopeConfig] = {}
    for name, envelope in raw_config['envelopes'].items():
        if not isinstance(envelope, dict):
            raise ValueError(f"Envelope '{name}' must be a dictionary")

        tags = envelope.get('tags', [])
        accounts = envelope.get('accounts', [])

        if not isinstance(tags, list):
            raise ValueError(f"'tags' in envelope '{name}' must be a list")
        if not isinstance(accounts, list):
            raise ValueError(f"'accounts' in envelope '{name}' must be a list")

        # Validate tag and account types
        for tag in tags:
            if not isinstance(tag, str):
                raise ValueError(f"Tag in envelope '{name}' must be a string")
        for acc in accounts:
            if not isinstance(acc, str):
                raise ValueError(f"Account in envelope '{name}' must be a string")

        envelopes[name] = EnvelopeConfig(tags=tags, accounts=accounts)

    # Validate account periods
    validated_accounts: dict[str, AccountPeriod] = {}
    for account, period in raw_config['accounts'].items():
        if not isinstance(period, dict):
            raise ValueError(f"Period for account '{account}' must be a dictionary")

        if 'start' not in period:
            raise KeyError(f"Missing 'start' date for account '{account}'")
        if 'end' not in period:
            raise KeyError(f"Missing 'end' date for account '{account}'")

        # Parse dates
        try:
            start_date = date.fromisoformat(period['start'])
        except ValueError as e:
            raise ValueError(f"Invalid 'start' date for account '{account}': {e}")

        try:
            end_date = date.fromisoformat(period['end'])
        except ValueError as e:
            raise ValueError(f"Invalid 'end' date for account '{account}': {e}")

        if start_date > end_date:
            raise ValueError(
                f"Start date {start_date} is after end date {end_date} for account '{account}'"
            )

        validated_accounts[account] = AccountPeriod(start=start_date, end=end_date)

    # Validate envelope tag uniqueness
    validate_envelopes(envelopes)

    return BudgetConfig(envelopes=envelopes, accounts=validated_accounts)


def allocate_budget_expenses(txn: Transaction):
    """Allocate expense postings to funding accounts.

    Allocation rules:
    - Single expense + single funding: expense fully allocated to that funding
    - Multiple expenses and/or funding: expenses are split proportionally
      based on funding amounts
    - Uses absolute value of funding amounts for proportion calculation
    - Each expense is allocated to each funding source based on funding's share

    Note: This function does not handle currency conversion. All amounts are
    assumed to be in the same currency. If transactions span currencies,
    behavior is undefined.
    """
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
    """Check if expense falls within its funding account's budget period.

    The expense is included if the transaction date falls within the funding
    account's budget period (start <= date <= end). This means the funding
    account's period governs inclusion, not the expense account's period.

    Args:
        expense: The budget expense to check
        budget: Budget configuration with 'accounts' dict mapping account names
                to their budget periods

    Returns:
        True if expense date is within funding account's budget period,
        False otherwise. Returns False if funding account is not in budget.
    """
    account_budget = budget['accounts'].get(expense.funding_account)

    if account_budget is None:
        # Funding account not defined in budget configuration
        return False

    return account_budget['start'] <= expense.transaction.date <= account_budget['end']


def validate_envelopes(envelopes: dict[str, EnvelopeConfig]):
    """Validate that tags are unique across envelopes.

    Args:
        envelopes: Validated envelope configurations

    Raises:
        ValueError: If a tag is used by multiple envelopes
    """
    seen_tags = {}

    for name, envelope in envelopes.items():
        for tag in envelope['tags']:
            if tag in seen_tags:
                raise ValueError(
                    f"Tag '{tag}' used by both {seen_tags[tag]} and {name}"
                )

            seen_tags[tag] = name


def match_envelope(
    expense: BudgetExpense,
    envelopes: dict[str, EnvelopeConfig],
) -> tuple[str, str]:
    """Match an expense to a budget envelope.

    Matching priority:
    1. Posting metadata override (budget: envelope-name)
    2. Transaction tags
    3. Account prefix
    4. Fallback to 'Uncategorized'

    Args:
        expense: The budget expense to match
        envelopes: Validated envelope configurations

    Returns:
        Tuple of (envelope_name, match_method)

    Raises:
        ValueError: If multiple envelopes match or override references unknown envelope
    """
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
        if any(tag in tags for tag in envelope['tags'])
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
        if any(account.startswith(prefix) for prefix in envelope['accounts'])
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
    expenses: list[BudgetExpense],
    envelopes: dict[str, EnvelopeConfig],
) -> dict[str, list[BudgetExpense]]:
    """Categorize expenses into budget envelopes.

    Args:
        expenses: List of budget expenses to categorize
        envelopes: Validated envelope configurations

    Returns:
        Dictionary mapping envelope names to lists of expenses
    """
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
    """Legacy function - use format.print_budget_report instead."""
    from .format import print_budget_report

    # Create a temporary BudgetResult for backward compatibility
    result = BudgetResult(
        min_budget_date=date.min,
        expenses_in_range=0,
        expenses_in_budget_period=0,
        categorized=categorized,
        totals=totals,
    )
    print_budget_report(result)





def existing_file(p):
    p = Path(p)
    if p.is_file():
        return p
    raise argparse.ArgumentTypeError(f'Path must be an existing file: {p}')


def review_budget(budget_path: Path, ledger_path: Path) -> BudgetResult:
    """Review expenses against budget and return structured results.

    Args:
        budget_path: Path to budget JSON configuration file
        ledger_path: Path to Beancount ledger file

    Returns:
        BudgetResult with categorized expenses and totals

    Raises:
        ValueError: If budget configuration is invalid
        KeyError: If required configuration fields are missing
    """
    raw_config = json.loads(budget_path.read_text())
    budget = validate_budget_config(raw_config)

    # Find the minimum budget start date
    min_budget_date = min(
        period['start'] for period in budget['accounts'].values()
    )

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

    categorized = categorize_expenses(
        budget_expenses,
        budget['envelopes'],
    )

    totals = envelope_totals(categorized)

    return BudgetResult(
        min_budget_date=min_budget_date,
        expenses_in_range=len(expenses),
        expenses_in_budget_period=len(budget_expenses),
        categorized=categorized,
        totals=totals,
    )


def run(budget_path: Path, ledger_path: Path):
    """Run budget review and print report (CLI entry point)."""
    from .format import print_budget_report

    result = review_budget(budget_path, ledger_path)

    print(f'Min start date: {result.min_budget_date}')
    print(f'Expenses in range: {result.expenses_in_range}')
    print(f'Expenses in budget period: {result.expenses_in_budget_period}')

    print_budget_report(result)
