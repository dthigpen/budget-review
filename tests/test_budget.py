"""Tests for budget review logic."""

import pytest
from decimal import Decimal
from datetime import date
from beancount.core.data import Transaction, Posting, TxnPosting
from beancount.core.amount import Amount
from beancount.core.number import MISSING

from budget_review.budget import (
    allocate_budget_expenses,
    BudgetExpense,
    expense_in_budget_period,
    validate_budget_config,
)


def make_transaction(date_str, narration, postings):
    """Helper to create a Transaction."""
    return Transaction(
        meta={},
        date=date.fromisoformat(date_str),
        flag='*',
        payee=None,
        narration=narration,
        tags=frozenset(),
        links=frozenset(),
        postings=postings,
    )


def make_posting(account, amount_str, currency='USD'):
    """Helper to create a Posting."""
    return Posting(
        account=account,
        units=Amount(Decimal(amount_str), currency) if amount_str else MISSING,
        cost=None,
        price=None,
        flag=None,
        meta={},
    )


class TestAllocateBudgetExpenses:
    """Tests for expense allocation logic."""

    def test_single_expense_single_funding(self):
        """Fast path: one expense, one funding source."""
        txn = make_transaction(
            '2024-01-01',
            'Test',
            [
                make_posting('Expenses:Food', '100.00'),
                make_posting('Assets:Checking', '-100.00'),
            ],
        )

        results = list(allocate_budget_expenses(txn))
        assert len(results) == 1

        expense = results[0]
        assert expense.funding_account == 'Assets:Checking'
        assert expense.allocated_amount == Decimal('100.00')
        assert expense.posting.account == 'Expenses:Food'

    def test_multiple_expenses_single_funding(self):
        """Multiple expenses from single funding source."""
        txn = make_transaction(
            '2024-01-01',
            'Test',
            [
                make_posting('Expenses:Food', '60.00'),
                make_posting('Expenses:Transport', '40.00'),
                make_posting('Assets:Checking', '-100.00'),
            ],
        )

        results = list(allocate_budget_expenses(txn))
        assert len(results) == 2

        # Each expense is fully allocated to the single funding source
        food_expense = next(e for e in results if e.posting.account == 'Expenses:Food')
        transport_expense = next(e for e in results if e.posting.account == 'Expenses:Transport')

        assert food_expense.funding_account == 'Assets:Checking'
        assert food_expense.allocated_amount == Decimal('60.00')
        assert transport_expense.funding_account == 'Assets:Checking'
        assert transport_expense.allocated_amount == Decimal('40.00')

    def test_single_expense_multiple_funding(self):
        """Single expense split across multiple funding sources."""
        txn = make_transaction(
            '2024-01-01',
            'Test',
            [
                make_posting('Expenses:Food', '100.00'),
                make_posting('Assets:Checking', '-60.00'),
                make_posting('Assets:Savings', '-40.00'),
            ],
        )

        results = list(allocate_budget_expenses(txn))
        assert len(results) == 2

        # Expense is split proportionally based on funding amounts
        # Total expenses = 100, Checking = 60 (60%), Savings = 40 (40%)
        checking_expense = next(e for e in results if e.funding_account == 'Assets:Checking')
        savings_expense = next(e for e in results if e.funding_account == 'Assets:Savings')

        assert checking_expense.allocated_amount == Decimal('60.00')
        assert savings_expense.allocated_amount == Decimal('40.00')

    def test_multiple_expenses_multiple_funding(self):
        """Multiple expenses split across multiple funding sources."""
        txn = make_transaction(
            '2024-01-01',
            'Test',
            [
                make_posting('Expenses:Food', '60.00'),
                make_posting('Expenses:Transport', '40.00'),
                make_posting('Assets:Checking', '-70.00'),
                make_posting('Assets:Savings', '-30.00'),
            ],
        )

        results = list(allocate_budget_expenses(txn))
        assert len(results) == 4  # 2 expenses × 2 funding sources

        # Total expenses = 100
        # Checking funds 70% (70/100), Savings funds 30% (30/100)
        # Food (60): 60 * 0.7 = 42 from Checking, 60 * 0.3 = 18 from Savings
        # Transport (40): 40 * 0.7 = 28 from Checking, 40 * 0.3 = 12 from Savings

        food_checking = next(
            e for e in results
            if e.posting.account == 'Expenses:Food' and e.funding_account == 'Assets:Checking'
        )
        food_savings = next(
            e for e in results
            if e.posting.account == 'Expenses:Food' and e.funding_account == 'Assets:Savings'
        )
        transport_checking = next(
            e for e in results
            if e.posting.account == 'Expenses:Transport' and e.funding_account == 'Assets:Checking'
        )
        transport_savings = next(
            e for e in results
            if e.posting.account == 'Expenses:Transport' and e.funding_account == 'Assets:Savings'
        )

        assert food_checking.allocated_amount == Decimal('42.00')
        assert food_savings.allocated_amount == Decimal('18.00')
        assert transport_checking.allocated_amount == Decimal('28.00')
        assert transport_savings.allocated_amount == Decimal('12.00')

    def test_no_expenses(self):
        """Transaction with no expense postings yields no allocations."""
        txn = make_transaction(
            '2024-01-01',
            'Transfer',
            [
                make_posting('Assets:Checking', '-100.00'),
                make_posting('Assets:Savings', '100.00'),
            ],
        )

        results = list(allocate_budget_expenses(txn))
        assert len(results) == 0

    def test_no_funding(self):
        """Transaction with no funding postings yields no allocations."""
        txn = make_transaction(
            '2024-01-01',
            'Test',
            [
                make_posting('Expenses:Food', '100.00'),
            ],
        )

        results = list(allocate_budget_expenses(txn))
        assert len(results) == 0

    def test_conserves_total_expense(self):
        """Verify that total allocated amount equals total expense amount."""
        txn = make_transaction(
            '2024-01-01',
            'Test',
            [
                make_posting('Expenses:Food', '60.00'),
                make_posting('Expenses:Transport', '40.00'),
                make_posting('Assets:Checking', '-70.00'),
                make_posting('Assets:Savings', '-30.00'),
            ],
        )

        results = list(allocate_budget_expenses(txn))
        total_allocated = sum(e.allocated_amount for e in results)
        total_expense = Decimal('60.00') + Decimal('40.00')

        assert total_allocated == total_expense


class TestExpenseInBudgetPeriod:
    """Tests for budget period filtering."""

    def make_budget_expense(self, date_str, funding_account):
        """Helper to create a BudgetExpense."""
        txn = make_transaction(
            date_str,
            'Test',
            [
                make_posting('Expenses:Food', '100.00'),
                make_posting(funding_account, '-100.00'),
            ],
        )
        return BudgetExpense(
            transaction=txn,
            posting=txn.postings[0],
            funding_account=funding_account,
            allocated_amount=Decimal('100.00'),
        )

    def test_expense_in_period(self):
        """Expense date falls within budget period."""
        from budget_review.budget import BudgetConfig

        budget = BudgetConfig(
            envelopes={},
            accounts={
                'Assets:Checking': {
                    'start': date(2024, 1, 1),
                    'end': date(2024, 12, 31),
                }
            },
            period=None,
        )
        expense = self.make_budget_expense('2024-06-15', 'Assets:Checking')

        assert expense_in_budget_period(expense, budget) is True

    def test_expense_before_period(self):
        """Expense date before budget period."""
        from budget_review.budget import BudgetConfig

        budget = BudgetConfig(
            envelopes={},
            accounts={
                'Assets:Checking': {
                    'start': date(2024, 1, 1),
                    'end': date(2024, 12, 31),
                }
            },
            period=None,
        )
        expense = self.make_budget_expense('2023-12-31', 'Assets:Checking')

        assert expense_in_budget_period(expense, budget) is False

    def test_expense_after_period(self):
        """Expense date after budget period."""
        from budget_review.budget import BudgetConfig

        budget = BudgetConfig(
            envelopes={},
            accounts={
                'Assets:Checking': {
                    'start': date(2024, 1, 1),
                    'end': date(2024, 12, 31),
                }
            },
            period=None,
        )
        expense = self.make_budget_expense('2025-01-01', 'Assets:Checking')

        assert expense_in_budget_period(expense, budget) is False

    def test_expense_on_start_date(self):
        """Expense on the start date is included."""
        from budget_review.budget import BudgetConfig

        budget = BudgetConfig(
            envelopes={},
            accounts={
                'Assets:Checking': {
                    'start': date(2024, 1, 1),
                    'end': date(2024, 12, 31),
                }
            },
            period=None,
        )
        expense = self.make_budget_expense('2024-01-01', 'Assets:Checking')

        assert expense_in_budget_period(expense, budget) is True

    def test_expense_on_end_date(self):
        """Expense on the end date is included."""
        from budget_review.budget import BudgetConfig

        budget = BudgetConfig(
            envelopes={},
            accounts={
                'Assets:Checking': {
                    'start': date(2024, 1, 1),
                    'end': date(2024, 12, 31),
                }
            },
            period=None,
        )
        expense = self.make_budget_expense('2024-12-31', 'Assets:Checking')

        assert expense_in_budget_period(expense, budget) is True

    def test_funding_account_not_in_budget(self):
        """Funding account not defined in budget configuration."""
        from budget_review.budget import BudgetConfig

        budget = BudgetConfig(
            envelopes={},
            accounts={
                'Assets:Checking': {
                    'start': date(2024, 1, 1),
                    'end': date(2024, 12, 31),
                }
            },
            period=None,
        )
        expense = self.make_budget_expense('2024-06-15', 'Assets:Savings')

        assert expense_in_budget_period(expense, budget) is False

    def test_expense_in_budget_period_with_budget_config(self):
        """Test with BudgetConfig TypedDict structure."""
        from budget_review.budget import BudgetConfig

        budget = BudgetConfig(
            envelopes={},
            accounts={
                'Assets:Checking': {
                    'start': date(2024, 1, 1),
                    'end': date(2024, 12, 31),
                }
            },
            period=None,
        )
        expense = self.make_budget_expense('2024-06-15', 'Assets:Checking')

        assert expense_in_budget_period(expense, budget) is True

    def test_calendar_month_mode_expense_in_period(self):
        """Calendar-month mode includes expenses in overall period."""
        from budget_review.budget import BudgetConfig

        budget = BudgetConfig(
            envelopes={},
            accounts=None,
            period={
                'start': date(2024, 1, 1),
                'end': date(2024, 1, 31),
            },
        )
        expense = self.make_budget_expense('2024-01-15', 'Assets:Checking')

        assert expense_in_budget_period(expense, budget) is True

    def test_calendar_month_mode_expense_outside_period(self):
        """Calendar-month mode excludes expenses outside overall period."""
        from budget_review.budget import BudgetConfig

        budget = BudgetConfig(
            envelopes={},
            accounts=None,
            period={
                'start': date(2024, 1, 1),
                'end': date(2024, 1, 31),
            },
        )
        expense = self.make_budget_expense('2024-02-15', 'Assets:Checking')

        assert expense_in_budget_period(expense, budget) is False

    def test_multiple_accounts(self):
        """Correctly filters based on specific funding account."""
        from budget_review.budget import BudgetConfig

        budget = BudgetConfig(
            envelopes={},
            accounts={
                'Assets:Checking': {
                    'start': date(2024, 1, 1),
                    'end': date(2024, 12, 31),
                },
                'Assets:Savings': {
                    'start': date(2024, 6, 1),
                    'end': date(2024, 12, 31),
                }
            },
            period=None,
        )

        # Expense in May is only in Checking's period
        expense_may = self.make_budget_expense('2024-05-15', 'Assets:Checking')
        assert expense_in_budget_period(expense_may, budget) is True

        # Expense in May is not in Savings's period
        expense_may_savings = self.make_budget_expense('2024-05-15', 'Assets:Savings')
        assert expense_in_budget_period(expense_may_savings, budget) is False

        # Expense in July is in both periods
        expense_july = self.make_budget_expense('2024-07-15', 'Assets:Checking')
        assert expense_in_budget_period(expense_july, budget) is True

        expense_july_savings = self.make_budget_expense('2024-07-15', 'Assets:Savings')
        assert expense_in_budget_period(expense_july_savings, budget) is True


class TestValidateBudgetConfig:
    """Tests for budget configuration validation."""

    def test_valid_config(self):
        """Valid configuration passes validation."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
                'Dining': {
                    'tags': ['dining'],
                    'accounts': ['Expenses:Food:Dining'],
                },
            },
            'accounts': {
                'Assets:Checking': {
                    'start': '2024-01-01',
                    'end': '2024-12-31',
                },
            },
        }

        validated = validate_budget_config(config)
        assert 'envelopes' in validated
        assert 'accounts' in validated
        assert validated['accounts'] is not None
        assert validated['period'] is None
        assert validated['accounts']['Assets:Checking']['start'] == date(2024, 1, 1)
        assert validated['accounts']['Assets:Checking']['end'] == date(2024, 12, 31)

    def test_missing_envelopes(self):
        """Missing 'envelopes' field raises KeyError."""
        config = {
            'accounts': {
                'Assets:Checking': {
                    'start': '2024-01-01',
                    'end': '2024-12-31',
                },
            },
        }

        with pytest.raises(KeyError, match="Missing required field: 'envelopes'"):
            validate_budget_config(config)

    def test_missing_accounts_and_period(self):
        """Missing both 'accounts' and 'period' raises ValueError."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
        }

        with pytest.raises(ValueError, match="Must specify either 'accounts' or 'period'"):
            validate_budget_config(config)

    def test_both_accounts_and_period(self):
        """Specifying both 'accounts' and 'period' raises ValueError."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'accounts': {
                'Assets:Checking': {
                    'start': '2024-01-01',
                    'end': '2024-12-31',
                },
            },
            'period': {
                'start': '2024-01-01',
                'end': '2024-12-31',
            },
        }

        with pytest.raises(ValueError, match="Cannot specify both 'accounts' and 'period'"):
            validate_budget_config(config)

    def test_invalid_date_format(self):
        """Invalid date format raises ValueError."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'accounts': {
                'Assets:Checking': {
                    'start': '2024-13-01',  # Invalid month
                    'end': '2024-12-31',
                },
            },
        }

        with pytest.raises(ValueError, match="Invalid 'start' date"):
            validate_budget_config(config)

    def test_start_after_end(self):
        """Start date after end date raises ValueError."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'accounts': {
                'Assets:Checking': {
                    'start': '2024-12-31',
                    'end': '2024-01-01',
                },
            },
        }

        with pytest.raises(ValueError, match="Start date .* is after end date"):
            validate_budget_config(config)

    def test_duplicate_tags(self):
        """Duplicate tags across envelopes raises ValueError."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['food'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
                'Dining': {
                    'tags': ['food'],  # Duplicate tag
                    'accounts': ['Expenses:Food:Dining'],
                },
            },
            'accounts': {
                'Assets:Checking': {
                    'start': '2024-01-01',
                    'end': '2024-12-31',
                },
            },
        }

        with pytest.raises(ValueError, match="Tag 'food' used by both"):
            validate_budget_config(config)

    def test_empty_envelopes_allowed(self):
        """Empty envelopes dict is allowed."""
        config = {
            'envelopes': {},
            'accounts': {
                'Assets:Checking': {
                    'start': '2024-01-01',
                    'end': '2024-12-31',
                },
            },
        }

        validated = validate_budget_config(config)
        assert validated['envelopes'] == {}

    def test_envelope_without_tags_or_accounts(self):
        """Envelope can have empty tags and accounts lists."""
        config = {
            'envelopes': {
                'Misc': {
                    'tags': [],
                    'accounts': [],
                },
            },
            'accounts': {
                'Assets:Checking': {
                    'start': '2024-01-01',
                    'end': '2024-12-31',
                },
            },
        }

        validated = validate_budget_config(config)
        assert validated['envelopes']['Misc']['tags'] == []
        assert validated['envelopes']['Misc']['accounts'] == []

    def test_calendar_month_mode(self):
        """Valid calendar-month mode configuration with dict format."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'period': {
                'start': '2024-01-01',
                'end': '2024-01-31',
            },
        }

        validated = validate_budget_config(config)
        assert validated['accounts'] is None
        assert validated['period'] is not None
        assert validated['period']['start'] == date(2024, 1, 1)
        assert validated['period']['end'] == date(2024, 1, 31)

    def test_calendar_month_year_month_format(self):
        """Valid calendar-month mode with year-month string format."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'period': '2024-01',
        }

        validated = validate_budget_config(config)
        assert validated['accounts'] is None
        assert validated['period'] is not None
        assert validated['period']['start'] == date(2024, 1, 1)
        assert validated['period']['end'] == date(2024, 1, 31)

    def test_calendar_month_year_month_february(self):
        """Year-month format handles February correctly."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'period': '2024-02',
        }

        validated = validate_budget_config(config)
        assert validated['period']['start'] == date(2024, 2, 1)
        assert validated['period']['end'] == date(2024, 2, 29)  # 2024 is leap year

    def test_calendar_month_year_month_february_non_leap(self):
        """Year-month format handles non-leap year February."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'period': '2023-02',
        }

        validated = validate_budget_config(config)
        assert validated['period']['start'] == date(2023, 2, 1)
        assert validated['period']['end'] == date(2023, 2, 28)  # 2023 is not leap year

    def test_calendar_month_year_month_december(self):
        """Year-month format handles December correctly."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'period': '2024-12',
        }

        validated = validate_budget_config(config)
        assert validated['period']['start'] == date(2024, 12, 1)
        assert validated['period']['end'] == date(2024, 12, 31)

    def test_calendar_month_invalid_year_month_format(self):
        """Invalid year-month format raises ValueError."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'period': '2024/01',
        }

        with pytest.raises(ValueError, match="Invalid period format"):
            validate_budget_config(config)

    def test_calendar_month_invalid_month(self):
        """Invalid month in year-month format raises ValueError."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'period': '2024-13',
        }

        with pytest.raises(ValueError):
            validate_budget_config(config)

    def test_calendar_month_invalid_date(self):
        """Invalid date in calendar-month mode raises ValueError."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'period': {
                'start': '2024-13-01',
                'end': '2024-01-31',
            },
        }

        with pytest.raises(ValueError, match="Invalid 'start' date in 'period'"):
            validate_budget_config(config)

    def test_calendar_month_start_after_end(self):
        """Start after end in calendar-month mode raises ValueError."""
        config = {
            'envelopes': {
                'Groceries': {
                    'tags': ['groceries'],
                    'accounts': ['Expenses:Food:Groceries'],
                },
            },
            'period': {
                'start': '2024-01-31',
                'end': '2024-01-01',
            },
        }

        with pytest.raises(ValueError, match="Start date .* is after end date"):
            validate_budget_config(config)
