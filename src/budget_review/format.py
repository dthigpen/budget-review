from decimal import Decimal
from tabulate import tabulate


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
