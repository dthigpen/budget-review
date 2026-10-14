from dataclasses import dataclass

from beancount.loader import load_file
from beancount.core.data import (
    Posting,
    Transaction,
)

from decimal import Decimal, InvalidOperation


@dataclass(slots=True)
class PostingWithTransaction:
    transaction: Transaction
    posting: Posting


def as_postings(txn: Transaction, account_prefixes=None):
    for posting in txn.postings:
        if account_prefixes is None:
            yield PostingWithTransaction(transaction=txn, posting=posting)
        else:
            for prefix in account_prefixes:
                if posting.account.startswith(prefix):
                    yield PostingWithTransaction(transaction=txn, posting=posting)


def expense_postings(txn: Transaction) -> list[Posting]:
    return [p for p in txn.postings if p.account.startswith('Expenses:')]


def funding_postings(txn: Transaction) -> list[Posting]:
    return [
        p for p in txn.postings if not p.account.startswith(('Expenses:', 'Income:'))
    ]


def funding_accounts(txn: Transaction) -> list[str]:
    return [p.account for p in funding_postings(txn)]


def funding_account(txn):
    """Get the only funding account associated with this transaction.

    If there are more then an error is thrown.
    """
    accounts = funding_accounts(txn)
    if len(accounts) != 1:
        raise ValueError(f'Expected exactly one funding account: {txn}')
    return accounts[0]


def short_account(account: str, count=2) -> str:
    """Returns the tail end of an accounts sub accounts. Defaults to the last 2"""
    sub_accounts = account.split(':')
    return ':'.join(sub_accounts[-1 * count :])


def load_transactions(path: str) -> list[Transaction]:
    entries, errors, _ = load_file(path)

    if errors:
        print(errors)

    return [e for e in entries if isinstance(e, Transaction)]


def parse_decimal(value: str) -> Decimal:
    """Parse a human-entered decimal number."""

    negative = value.startswith('(') and value.endswith(')')

    value = (
        value.strip()
        .strip('()')
        .replace('$', '')
        .replace(',', '')
        .replace('_', '')  # optional, nice for 1_000_000
    )

    amount = Decimal(value)

    return -amount if negative else amount


def parse_money(value: str) -> Decimal:
    try:
        return parse_decimal(value)
    except InvalidOperation as e:
        raise ValueError(f'Invalid money value: {value}') from e
